"""Orquestrador do pipeline de 5 estágios do Tomus (Item 22).

Conecta: Scanner -> FileCache -> Extrator -> Enriquecedor -> LLM -> Organizer.
Executa sequencialmente por padrão (workers=1) ou paraleliza apenas as etapas
de rede (enriquecimento e classificação LLM) quando workers>1, protegendo o OCR
e a finalização (cache + organizer) com um lock no orquestrador.

Emite PipelineEvent para a UI e calcula ExecutionSummary com verificação do
teto de 20% para revisao_manual/.
"""

from __future__ import annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from tomus.core.cache import FileCache
from tomus.core.config import AppConfig
from tomus.core.llm import (
    ClassificationResult,
    LLMProvider,
    MockLLMProvider,
    _sanitize_error_message,
    create_provider_chain,
)
from tomus.core.models import (
    ExecutionSummary,
    ExtractedDocument,
    FileManifestEntry,
    PipelineEvent,
    ProcessStatus,
)
from tomus.core.prompts import extract_first_author_key, normalize_authors
from tomus.core.scanner import ScannedFile, scan_directory
from tomus.core.taxonomy import (
    get_taxonomy_version,
    normalize_and_resolve_taxonomy,
)
from tomus.extractors.identifiers import normalize_doi, normalize_isbn
from tomus.storage.organizer import LibraryOrganizer

try:
    from tomus.core.enrichers import enrich_document_metadata  # type: ignore
except Exception:  # pragma: no cover

    def enrich_document_metadata(  # type: ignore[no-redef]
        doc: ExtractedDocument, config: AppConfig
    ) -> list:
        return []

from tomus.extractors import extract_document_content

EventCallback = Callable[[PipelineEvent], None]


def _emit(
    callback: EventCallback | None,
    stage: str,
    source_path: Path,
    status: str,
    message: str,
    total_files: int | None = None,
    completed_files: int | None = None,
    classification: dict[str, Any] | None = None,
    destination_path: Path | str | None = None,
    sha256: str | None = None,
) -> None:
    if callback is None:
        return
    try:
        callback(
            PipelineEvent(
                stage=stage,
                source_path=str(source_path),
                destination_path=str(destination_path) if destination_path else None,
                sha256=sha256,
                status=status,
                message=message,
                total_files=total_files,
                completed_files=completed_files,
                classification=classification,
            )
        )
    except Exception:
        pass


def _classification_to_dict(result: ClassificationResult) -> dict[str, Any]:
    subarea = (result.subarea or "").strip() or "Geral"
    especialidade = (result.especialidade or "").strip() or "Geral"
    return {
        "grande_area": result.grande_area,
        "area_basica": result.area_basica,
        "subarea": subarea,
        "especialidade": especialidade,
        "tipo": result.tipo,
        "authors": result.authors,
        "title": result.title,
        "subtitle": result.subtitle,
        "year": result.year,
        "publisher": getattr(result, "publisher", None),
        "city": getattr(result, "city", None),
        "edition": getattr(result, "edition", None),
        "journal_name": getattr(result, "journal_name", None),
        "volume": getattr(result, "volume", None),
        "number": getattr(result, "number", None),
        "pages": getattr(result, "pages", None),
        "doi": normalize_doi(getattr(result, "doi", None)),
        "isbn": normalize_isbn(getattr(result, "isbn", None)),
        "confidence_score": result.confidence_score,
        "reasoning": result.reasoning,
    }


def _apply_canonical_normalization(classification: dict[str, Any]) -> dict[str, Any]:
    """Aplicar normalização de autores, identificadores e taxonomia controlada."""
    out = dict(classification)
    authors_norm = normalize_authors(list(out.get("authors") or []))
    if authors_norm:
        out["authors"] = authors_norm

    resolved = normalize_and_resolve_taxonomy(
        out,
        first_author_key=extract_first_author_key(authors_norm),
    )
    if resolved.get("grande_area"):
        out["grande_area"] = resolved["grande_area"]
    if resolved.get("area_basica"):
        out["area_basica"] = resolved["area_basica"]
    if resolved.get("subarea"):
        out["subarea"] = resolved["subarea"]
    if resolved.get("especialidade"):
        out["especialidade"] = resolved["especialidade"]

    if "doi" in out:
        out["doi"] = normalize_doi(out.get("doi"))
    if "isbn" in out:
        out["isbn"] = normalize_isbn(out.get("isbn"))
    return out


def _call_provider_classify(
    provider: LLMProvider,
    *,
    sampled_text: str,
    cip_text: str,
    external_metadata: Any,
    used_ocr: bool,
    source_path: Path,
) -> ClassificationResult:
    """Chamar provider.classify preservando compatibilidade com mocks legados."""
    try:
        sig = inspect.signature(provider.classify)
        accepts_source = (
            "source_path" in sig.parameters
            or any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
        )
    except (TypeError, ValueError):
        accepts_source = False

    if accepts_source:
        return provider.classify(
            sampled_text=sampled_text,
            cip_text=cip_text,
            external_metadata=external_metadata,
            used_ocr=used_ocr,
            source_path=source_path,
        )
    return provider.classify(
        sampled_text=sampled_text,
        cip_text=cip_text,
        external_metadata=external_metadata,
        used_ocr=used_ocr,
    )


def _process_one(
    scanned: ScannedFile,
    config: AppConfig,
    target_dir: Path,
    provider: LLMProvider,
    cache: FileCache,
    organizer: LibraryOrganizer,
    taxonomy_version: str,
    model_name: str,
    emit: EventCallback | None,
    finalize_lock: threading.RLock,
    completed_count: list[int] | None = None,
    completed_count_lock: threading.Lock | None = None,
    total_files: int | None = None,
) -> FileManifestEntry | None:
    """Processar um único PDF válido através dos 5 estágios."""
    source_path = scanned.path
    sha256 = scanned.sha256

    def _emit_terminal(
        stage: str,
        status: str,
        message: str,
        classification: dict[str, Any] | None = None,
        destination_path: Path | str | None = None,
    ) -> None:
        comp = None
        if completed_count is not None and completed_count_lock is not None:
            with completed_count_lock:
                completed_count[0] += 1
                comp = completed_count[0]
        _emit(
            emit,
            stage,
            source_path,
            status,
            message,
            completed_files=comp,
            total_files=total_files,
            classification=classification,
            destination_path=destination_path,
            sha256=sha256,
        )

    _emit(
        emit,
        "scanner",
        source_path,
        "started",
        "Iniciando processamento",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )

    if not scanned.is_valid_pdf:
        with finalize_lock:
            entry = organizer.add_error(
                source_path,
                sha256,
                "Assinatura %PDF- ausente ou arquivo corrompido",
            )
        _emit_terminal(
            "pipeline",
            "error",
            "PDF inválido -> revisao_manual",
            destination_path=entry.destination_path,
        )
        return organizer.entries[-1]

    # --- Cache hit ---
    with finalize_lock:
        cached = cache.get(sha256, taxonomy_version, model_name)
    if cached is not None:
        cached_subarea = (cached.get("subarea") or "").strip()
        if cached_subarea and cached_subarea.lower() not in (
            "não especificada",
            "nao especificada",
            "none",
            "null",
            "",
        ):
            _emit(
                emit,
                "cache",
                source_path,
                "hit",
                "Reutilizando classificação em cache",
                completed_files=completed_count[0] if completed_count else None,
                total_files=total_files,
            )
            classification = _apply_canonical_normalization(cached)
            used_ocr = bool(classification.get("used_ocr", False))
            confidence = float(classification.get("confidence_score", 0.0))
            if confidence >= config.general.confidence_min:
                filename = _organizer_filename(classification)
                with finalize_lock:
                    entry = organizer.add_organized(
                        source_path=source_path,
                        grande_area=classification.get("grande_area", ""),
                        area_basica=classification.get("area_basica", ""),
                        subarea=classification.get("subarea", ""),
                        especialidade=classification.get("especialidade", ""),
                        tipo=classification.get("tipo", "Outros"),
                        filename=filename,
                        sha256=sha256,
                        used_ocr=used_ocr,
                        classification=classification,
                    )
                _emit_terminal(
                    "pipeline",
                    entry.status.value,
                    "Cache hit aprovado",
                    classification=classification,
                    destination_path=entry.destination_path,
                )
                return organizer.entries[-1]

            with finalize_lock:
                entry = organizer.add_manual_review(
                    source_path=source_path,
                    sha256=sha256,
                    reason=f"Cache hit abaixo do limiar ({confidence:.2f})",
                    used_ocr=used_ocr,
                    classification=classification,
                )
            _emit_terminal(
                "pipeline",
                "manual_review",
                "Cache hit abaixo do limiar",
                classification=classification,
                destination_path=entry.destination_path,
            )
            return organizer.entries[-1]

    # --- Stage 2: Extração ---
    _emit(
        emit,
        "extractor",
        source_path,
        "started",
        "Extraindo conteúdo do PDF",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )
    try:
        with finalize_lock:
            doc: ExtractedDocument = extract_document_content(source_path, sha256)
    except Exception as exc:
        _emit(
            emit,
            "extractor",
            source_path,
            "error",
            f"Falha na extração: {exc}",
            completed_files=completed_count[0] if completed_count else None,
            total_files=total_files,
        )
        with finalize_lock:
            entry = organizer.add_error(
                source_path,
                sha256,
                f"Extração falhou: {_sanitize_error_message(str(exc))}",
            )
        _emit_terminal(
            "organizer",
            "error",
            f"Extração falhou: {exc}",
            destination_path=entry.destination_path,
        )
        return organizer.entries[-1]

    _emit(
        emit,
        "extractor",
        source_path,
        "completed",
        f"Texto extraído ({len(doc.sampled_text)} chars, OCR={doc.used_ocr})",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )

    # --- Stage 3: Enriquecimento acadêmico ---
    _emit(
        emit,
        "enricher",
        source_path,
        "started",
        "Enriquecendo metadados externos",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )
    try:
        external_list = enrich_document_metadata(doc, config)
    except Exception as exc:
        _emit(
            emit,
            "enricher",
            source_path,
            "error",
            f"Falha no enriquecimento: {exc}",
            completed_files=completed_count[0] if completed_count else None,
            total_files=total_files,
        )
        external_list = []
    external_metadata = external_list[0] if external_list else None
    _emit(
        emit,
        "enricher",
        source_path,
        "completed",
        f"{len(external_list)} metadado(s) externo(s)",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )

    # --- Stage 4: Classificação LLM ---
    _emit(
        emit,
        "llm",
        source_path,
        "started",
        "Classificando via LLM",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )
    try:
        result: ClassificationResult = _call_provider_classify(
            provider,
            sampled_text=doc.sampled_text,
            cip_text=doc.cip_text,
            external_metadata=external_metadata,
            used_ocr=doc.used_ocr,
            source_path=source_path,
        )
    except Exception as exc:
        _emit(
            emit,
            "llm",
            source_path,
            "error",
            f"Falha na classificação LLM: {exc}",
            completed_files=completed_count[0] if completed_count else None,
            total_files=total_files,
        )
        with finalize_lock:
            entry = organizer.add_error(
                source_path,
                sha256,
                f"LLM falhou: {_sanitize_error_message(str(exc))}",
                used_ocr=doc.used_ocr,
            )
        _emit_terminal(
            "organizer",
            "error",
            f"LLM falhou: {exc}",
            destination_path=entry.destination_path,
        )
        return organizer.entries[-1]

    classification = _classification_to_dict(result)
    classification["paginas_pdf"] = doc.total_pages

    if not classification.get("doi") and doc.detected_doi:
        classification["doi"] = normalize_doi(doc.detected_doi)
    if not classification.get("isbn") and doc.detected_isbn:
        classification["isbn"] = normalize_isbn(doc.detected_isbn)

    if external_metadata is not None:
        if not classification.get("publisher") and getattr(external_metadata, "publisher", None):
            classification["publisher"] = external_metadata.publisher
        if not classification.get("city") and getattr(external_metadata, "city", None):
            classification["city"] = external_metadata.city
        if not classification.get("edition") and getattr(external_metadata, "edition", None):
            classification["edition"] = external_metadata.edition
        if not classification.get("journal_name") and getattr(external_metadata, "journal_name", None):
            classification["journal_name"] = external_metadata.journal_name
        if not classification.get("volume") and getattr(external_metadata, "volume", None):
            classification["volume"] = external_metadata.volume
        if not classification.get("number") and getattr(external_metadata, "number", None):
            classification["number"] = external_metadata.number
        if not classification.get("pages") and getattr(external_metadata, "pages", None):
            classification["pages"] = external_metadata.pages
        if not classification.get("doi") and getattr(external_metadata, "doi", None):
            classification["doi"] = normalize_doi(external_metadata.doi)
        if not classification.get("isbn") and getattr(external_metadata, "isbn", None):
            classification["isbn"] = normalize_isbn(external_metadata.isbn)

    classification = _apply_canonical_normalization(classification)

    confidence = float(result.confidence_score)
    _emit(
        emit,
        "llm",
        source_path,
        "completed",
        f"confidence={confidence:.2f} tipo={result.tipo}",
        completed_files=completed_count[0] if completed_count else None,
        total_files=total_files,
    )

    # --- Stage 5: Materialização + cache ---
    with finalize_lock:
        if confidence >= config.general.confidence_min:
            filename = _organizer_filename(classification)
            entry = organizer.add_organized(
                source_path=source_path,
                grande_area=classification.get("grande_area", result.grande_area),
                area_basica=classification.get("area_basica", result.area_basica),
                subarea=classification.get("subarea", result.subarea),
                especialidade=classification.get("especialidade", result.especialidade),
                tipo=result.tipo,
                filename=filename,
                sha256=sha256,
                used_ocr=doc.used_ocr,
                classification=classification,
            )
            effective_model = result.model_name or model_name
            cache.put(
                sha256,
                taxonomy_version,
                effective_model,
                classification,
                doc.used_ocr,
                confidence_min=config.general.confidence_min,
            )
            if effective_model != model_name and effective_model != "mock":
                cache.put(
                    sha256,
                    taxonomy_version,
                    model_name,
                    classification,
                    doc.used_ocr,
                    confidence_min=config.general.confidence_min,
                )
            _emit_terminal(
                "organizer",
                entry.status.value,
                f"Arquivo organizado: {filename}",
                classification=classification,
                destination_path=entry.destination_path,
            )
        else:
            reason = result.reasoning or f"Confiança {confidence:.2f} abaixo do limiar"
            entry = organizer.add_manual_review(
                source_path=source_path,
                sha256=sha256,
                reason=reason,
                used_ocr=doc.used_ocr,
                classification=classification,
            )
            _emit_terminal(
                "organizer",
                "manual_review",
                f"Enviado para revisao_manual ({reason})",
                classification=classification,
                destination_path=entry.destination_path,
            )

    return organizer.entries[-1]


def _organizer_filename(classification: dict[str, Any]) -> str:
    """Montar o nome de arquivo a partir da classificação."""
    from tomus.storage.namer import format_academic_filename

    authors = classification.get("authors") or []
    title = classification.get("title") or ""
    subtitle = classification.get("subtitle") or ""
    year = classification.get("year")
    return format_academic_filename(
        authors=authors,
        title=title,
        subtitle=subtitle,
        year=year,
    )


def run_pipeline(
    source_dir: Path,
    target_dir: Path,
    config: AppConfig,
    *,
    provider: LLMProvider | None = None,
    cache: FileCache | None = None,
    organizer: LibraryOrganizer | None = None,
    workers: int = 1,
    event_callback: EventCallback | None = None,
    use_cache: bool = True,
    dry_run: bool = False,
    cancel_event: threading.Event | None = None,
) -> ExecutionSummary:
    """Executar o pipeline completo de 5 estágios."""
    emit = event_callback
    source_dir = Path(source_dir)
    target_dir = Path(target_dir)

    taxonomy_version = get_taxonomy_version()
    model_name = config.llm.model

    if organizer is None:
        organizer = LibraryOrganizer(
            target_dir,
            file_operation=config.general.file_operation,
            dry_run=dry_run,
        )

    # --- Stage 1: Scanner ---
    _emit(emit, "scanner", source_dir, "started", "Varredura do diretório de origem")
    try:
        scan_result = scan_directory(
            source_dir,
            target_dir,
            recursive=config.general.recursive,
        )
    except Exception as exc:
        _emit(emit, "scanner", source_dir, "error", str(exc))
        return ExecutionSummary(
            total_scanned=0,
            error_count=1,
            entries=[
                FileManifestEntry(
                    source_path=str(source_dir),
                    destination_path=None,
                    sha256="",
                    status=ProcessStatus.ERROR,
                    error_message=_sanitize_error_message(str(exc)),
                )
            ],
        )

    for ignored in scan_result.ignored_non_pdf:
        organizer.add_ignored_non_pdf(ignored.path)
        _emit(
            emit,
            "scanner",
            ignored.path,
            ProcessStatus.IGNORED_NON_PDF.value,
            "Não é um PDF válido",
        )

    valid_pdfs = scan_result.valid_pdfs
    _emit(
        emit,
        "scanner",
        source_dir,
        "completed",
        f"{len(valid_pdfs)} PDF(s) válido(s), {len(scan_result.ignored_non_pdf)} ignorado(s)",
        total_files=len(valid_pdfs),
    )

    if not valid_pdfs:
        return organizer.finalize(total_scanned=len(scan_result.ignored_non_pdf))

    if cache is None:
        cache = FileCache(enabled=use_cache)

    if provider is None:
        has_configured_key = any(
            [
                config.api_keys.gemini_api_key,
                config.api_keys.groq_api_key,
                config.api_keys.nvidia_api_key,
                config.api_keys.deepseek_api_key,
                config.api_keys.claude_api_key,
            ]
        )
        if has_configured_key:
            try:
                provider = create_provider_chain(config)
            except ValueError:
                provider = MockLLMProvider()
        else:
            provider = MockLLMProvider()

    total_scanned = len(valid_pdfs)
    finalize_lock = threading.RLock()
    completed_count = [0]
    completed_count_lock = threading.Lock()

    def process_with_lock(scanned: ScannedFile) -> FileManifestEntry | None:
        if cancel_event is not None and cancel_event.is_set():
            return None
        return _process_one(
            scanned=scanned,
            config=config,
            target_dir=target_dir,
            provider=provider,
            cache=cache,
            organizer=organizer,
            taxonomy_version=taxonomy_version,
            model_name=model_name,
            emit=emit,
            finalize_lock=finalize_lock,
            completed_count=completed_count,
            completed_count_lock=completed_count_lock,
            total_files=total_scanned,
        )

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process_with_lock, s) for s in valid_pdfs]
            for _ in as_completed(futures):
                if cancel_event is not None and cancel_event.is_set():
                    break
    else:
        for scanned in valid_pdfs:
            if cancel_event is not None and cancel_event.is_set():
                break
            process_with_lock(scanned)

    for err in scan_result.errors:
        organizer.entries.append(
            FileManifestEntry(
                source_path="",
                destination_path=None,
                sha256="",
                status=ProcessStatus.ERROR,
                error_message=err,
            )
        )
        organizer._error_count += 1  # type: ignore[attr-defined]

    summary = organizer.finalize(total_scanned=total_scanned)
    _emit(
        emit,
        "pipeline",
        target_dir,
        "completed",
        f"{summary.organized_count} organizado(s), {summary.manual_review_count} revisão manual",
        total_files=total_scanned,
    )
    return summary
