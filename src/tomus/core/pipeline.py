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
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

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
from tomus.core.periodicals import canonical_journal
from tomus.core.prompts import extract_first_author_key, normalize_authors
from tomus.core.scanner import ScannedFile, scan_directory
from tomus.core.taxonomy import (
    get_taxonomy_version,
    normalize_and_resolve_taxonomy,
)
from tomus.core.text_utils import normalize_tex_accents
from tomus.extractors import extract_document_content
from tomus.extractors.identifiers import normalize_doi, normalize_isbn
from tomus.storage.namer import format_periodical_filename
from tomus.storage.organizer import LibraryOrganizer

_logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz as _fuzz
except Exception:  # pragma: no cover
    _fuzz = None

# Tipos de documento considerados artigo (OpenAlex) para regras de bloqueio de merge.
_ARTICLE_DOCUMENT_TYPES = {
    "article", "journal-article", "editorial", "letter", "erratum",
    "paratext", "review",
}

try:
    from tomus.core.enrichers import (  # type: ignore
        enrich_document_metadata,
        select_best_external_metadata,
    )
except Exception:  # pragma: no cover

    def enrich_document_metadata(  # type: ignore[no-redef]
        doc: ExtractedDocument, config: AppConfig
    ) -> list:
        return []

    def select_best_external_metadata(  # type: ignore[no-redef]
        doc: ExtractedDocument, candidates: list
    ):
        return candidates[0] if candidates else None


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
    except Exception as exc:
        _logger.warning("Falha ao emitir evento de pipeline: %s", exc)


def _classification_to_dict(result: ClassificationResult) -> dict[str, Any]:
    subarea = (result.subarea or "").strip() or "Geral"
    especialidade = (result.especialidade or "").strip() or "Geral"
    tipo_str = str(result.tipo)
    d: dict[str, Any] = {
        "grande_area": result.grande_area,
        "area_basica": result.area_basica,
        "subarea": subarea,
        "especialidade": especialidade,
        "tipo": tipo_str,
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
        "provider_name": result.provider_name,
        "model_name": result.model_name,
    }
    # --- Campos seriais (PR #14) ---
    d["periodico"] = getattr(result, "journal_name", None)  # periódico é o journal_name para revistas
    d["publication_month"] = getattr(result, "publication_month", None)
    d["publication_month_end"] = getattr(result, "publication_month_end", None)
    d["publication_year_end"] = getattr(result, "publication_year_end", None)
    d["issn"] = getattr(result, "issn", None)
    d["journal_genre"] = getattr(result, "journal_genre", None)
    d["volume_label"] = getattr(result, "volume_label", None)
    d["issue_designation"] = getattr(result, "issue_designation", None)
    d["serial_evidence"] = getattr(result, "serial_evidence", None)
    # Periódico canônico para roteamento/índice.
    if tipo_str in ("Revista", "Revista Científica") and d.get("periodico"):
        d["_journal_canonical"] = canonical_journal(d["periodico"]) or ""
    return d


def _apply_canonical_normalization(classification: dict[str, Any]) -> dict[str, Any]:
    """Aplicar normalização de autores, identificadores e taxonomia controlada."""
    out = dict(classification)
    authors_norm = normalize_authors(list(out.get("authors") or []))
    if authors_norm:
        out["authors"] = authors_norm
    # Revista: não usar 'Autor Desconhecido' como prefixo/autor.
    if str(out.get("tipo") or "") in ("Revista", "Revista Científica"):
        out["authors"] = []

    # [BUG-TXT-01] Normalizar acentos TeX nos campos de texto antes da montagem
    # do nome de arquivo e da comparação taxonômica.
    for _field in ("title", "subtitle", "publisher", "journal_name"):
        val = out.get(_field)
        if isinstance(val, str) and val:
            out[_field] = normalize_tex_accents(val)

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


def _record_materialization_error(
    *,
    source_path: Path,
    sha256: str,
    organizer: LibraryOrganizer,
    finalize_lock: threading.RLock,
    used_ocr: bool,
    emit_terminal: Any,
    stage_label: str,
    exc: Exception,
) -> FileManifestEntry | None:
    """Registrar erro de materialização no manifest com fallback secundário.

    Usado tanto no bloco de Cache Hit quanto no Estágio 5. Se
    ``organizer.add_error`` falhar em disco, adiciona um
    ``FileManifestEntry(status=ProcessStatus.ERROR)`` diretamente à lista de
    entradas para nunca perder o registro do erro.
    """
    logger = logging.getLogger("tomus.pipeline")
    clean = _sanitize_error_message(str(exc))
    logger.error("Organizer falhou (%s): %s", stage_label, clean)
    entry: FileManifestEntry | None = None
    try:
        with finalize_lock:
            entry = organizer.add_error(
                source_path,
                sha256,
                f"Organizer falhou ({stage_label}): {clean}",
                used_ocr=used_ocr,
            )
    except Exception:
        # Fallback secundário: adicionar FileManifestEntry ERROR diretamente
        # se organizer.add_error falhar em disco.
        entry = FileManifestEntry(
            source_path=str(source_path),
            destination_path=None,
            sha256=sha256,
            status=ProcessStatus.ERROR,
            used_ocr=used_ocr,
            error_message=f"Organizer falhou ({stage_label}): {clean}",
        )
        organizer.entries.append(entry)
        organizer._error_count += 1  # type: ignore[attr-defined]
    if emit_terminal is not None:
        emit_terminal(
            "organizer",
            "error",
            f"Organizer falhou ({stage_label}): {clean}",
            destination_path=entry.destination_path if entry else None,
        )
    return entry


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
                subarea_clean = (classification.get("subarea") or "Geral").strip() or "Geral"
                tipo_cache = str(classification.get("tipo", "Outros"))
                if tipo_cache in ("Revista", "Revista Científica"):
                    jc = classification.get("_journal_canonical") or canonical_journal(
                        classification.get("periodico") or classification.get("journal_name") or ""
                    ) or ""
                    if not jc:
                        # Periódico não identificável no cache: enviar a revisão manual.
                        with finalize_lock:
                            entry = organizer.add_manual_review(
                                source_path=source_path,
                                sha256=sha256,
                                reason="Periódico não identificável no cache hit",
                                used_ocr=used_ocr,
                                classification=classification,
                            )
                        _emit_terminal(
                            "pipeline",
                            "manual_review",
                            "Periódico não identificável no cache hit",
                            classification=classification,
                            destination_path=entry.destination_path,
                        )
                        return organizer.entries[-1]
                    dest_dir = target_dir / classification.get("area_basica", "") / subarea_clean / "Revista" / jc
                else:
                    dest_dir = target_dir / classification.get("area_basica", "") / subarea_clean / tipo_cache
                try:
                    filename = _organizer_filename(classification, dest_dir=dest_dir)
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
                except Exception as exc:
                    entry = _record_materialization_error(
                        source_path=source_path,
                        sha256=sha256,
                        organizer=organizer,
                        finalize_lock=finalize_lock,
                        used_ocr=used_ocr,
                        emit_terminal=_emit_terminal,
                        stage_label="cache hit",
                        exc=exc,
                    )
                    return organizer.entries[-1]
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
    external_metadata = select_best_external_metadata(doc, external_list)
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

    # [BUG-ENRICH-01] Para fascículos de Revista, preencher periodico/journal_name
    # com o title quando não houver periódico identificado, e nunca injetar
    # DOI/ISBN detectados no conteúdo (evitar contaminação com artigo externo).
    is_rev = str(classification.get("tipo") or "") in ("Revista", "Revista Científica")
    if is_rev:
        if not classification.get("periodico") and not classification.get("journal_name"):
            if classification.get("title"):
                classification["periodico"] = classification["title"]
                classification["journal_name"] = classification["title"]

    if not classification.get("doi") and doc.detected_doi and not is_rev:
        classification["doi"] = normalize_doi(doc.detected_doi)
    if not classification.get("isbn") and doc.detected_isbn and not is_rev:
        classification["isbn"] = normalize_isbn(doc.detected_isbn)

    if external_metadata is not None:
        # [BUG-ENRICH-01] Validações de coerência antes do merge de metadados externos.
        match_origin = getattr(external_metadata, "match_origin", "text_search")
        doc_tipo = classification.get("tipo", "")
        ext_title = getattr(external_metadata, "title", "") or ""
        ext_source = getattr(external_metadata, "source", "")
        ext_doc_type = (getattr(external_metadata, "document_type_hint", None) or "").strip().lower()

        # 1. Busca textual: validar coerência entre o título da classificação
        #    e o título do metadado externo. Se divergir, pular TODO o merge externo.
        if match_origin == "text_search" and ext_title and classification.get("title"):
            q = str(classification["title"]).strip()
            a = ext_title.strip()
            len_ratio = min(len(q), len(a)) / max(1, max(len(q), len(a)))
            sort_ok = False
            if _fuzz is not None:
                sort_ok = _fuzz.token_sort_ratio(q, a) >= 72.0
            else:
                # Sem rapidfuzz: comparar títulos normalizados em lowercase
                # (igualdade ou subconjunto) em vez de falhar cegamente.
                qn = q.casefold()
                an = a.casefold()
                sort_ok = qn == an or qn in an or an in qn
            if len_ratio < 0.45 or not sort_ok:
                external_metadata = None  # pular merge externo inteiro

        # 2. Regras por tipo documental antes de herdarmos campos.
        block_journal = False
        block_number = False
        block_volume = False
        block_pages = False
        block_doi = False
        block_isbn = False

        if doc_tipo == "Livro":
            block_journal = True
            block_number = True
            if ext_source == "openalex" and ext_doc_type in _ARTICLE_DOCUMENT_TYPES:
                block_volume = True
                block_pages = True
                block_doi = True
            # Aceitar DOI em Livro apenas se doc.detected_doi existir OU
            # document_type_hint for monográfico com match validado.
            monografico = ext_doc_type in ("book", "monograph", "edited-book", "book-chapter")
            if not doc.detected_doi and not (monografico and match_origin != "text_search"):
                block_doi = True

        if doc_tipo in ("Tese_Dissertacao", "Outros"):
            if ext_source == "openalex" and match_origin == "text_search" and ext_doc_type in _ARTICLE_DOCUMENT_TYPES:
                block_journal = True
                block_number = True

        # Revista: não herdar DOI/ISBN/autor/journal de artigo externo.
        if doc_tipo in ("Revista", "Revista Científica"):
            block_journal = True
            block_number = True
            block_doi = True
            block_isbn = True

        if external_metadata is not None:
            if not classification.get("publisher") and getattr(external_metadata, "publisher", None):
                classification["publisher"] = external_metadata.publisher
            if not classification.get("city") and getattr(external_metadata, "city", None):
                classification["city"] = external_metadata.city
            if not classification.get("edition") and getattr(external_metadata, "edition", None):
                classification["edition"] = external_metadata.edition
            if not block_journal and not classification.get("journal_name") and getattr(external_metadata, "journal_name", None):
                classification["journal_name"] = external_metadata.journal_name
            if not block_volume and not classification.get("volume") and getattr(external_metadata, "volume", None):
                classification["volume"] = external_metadata.volume
            if not block_number and not classification.get("number") and getattr(external_metadata, "number", None):
                classification["number"] = external_metadata.number
            if not block_pages and not classification.get("pages") and getattr(external_metadata, "pages", None):
                classification["pages"] = external_metadata.pages
            if not block_doi and not classification.get("doi") and getattr(external_metadata, "doi", None):
                classification["doi"] = normalize_doi(external_metadata.doi)
            if not block_isbn and not classification.get("isbn") and getattr(external_metadata, "isbn", None):
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
    try:
        with finalize_lock:
            if confidence >= config.general.confidence_min:
                subarea_clean = (classification.get("subarea") or "Geral").strip() or "Geral"
                tipo_stage5 = str(result.tipo)
                if tipo_stage5 in ("Revista", "Revista Científica"):
                    jc = classification.get("_journal_canonical") or canonical_journal(
                        classification.get("periodico") or classification.get("journal_name") or ""
                    ) or ""
                    if not jc:
                        # Periódico não identificável: enviar a revisão manual.
                        with finalize_lock:
                            entry = organizer.add_manual_review(
                                source_path=source_path,
                                sha256=sha256,
                                reason="Periódico não identificável no Estágio 5",
                                used_ocr=doc.used_ocr,
                                classification=classification,
                            )
                        _emit_terminal(
                            "organizer",
                            "manual_review",
                            "Periódico não identificável no Estágio 5",
                            classification=classification,
                            destination_path=entry.destination_path,
                        )
                        return organizer.entries[-1]
                    dest_dir = target_dir / classification.get("area_basica", "") / subarea_clean / "Revista" / jc
                else:
                    dest_dir = target_dir / classification.get("area_basica", "") / subarea_clean / tipo_stage5
                filename = _organizer_filename(classification, dest_dir=dest_dir)
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
                    requested_model=model_name,
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
    except Exception as exc:
        entry = _record_materialization_error(
            source_path=source_path,
            sha256=sha256,
            organizer=organizer,
            finalize_lock=finalize_lock,
            used_ocr=doc.used_ocr,
            emit_terminal=_emit_terminal,
            stage_label="estagio 5",
            exc=exc,
        )
        return organizer.entries[-1]

    return organizer.entries[-1]


def _organizer_filename(
    classification: dict[str, Any], dest_dir: Path | str | None = None
) -> str:
    """Montar o nome de arquivo a partir da classificação."""
    from tomus.storage.namer import format_academic_filename

    tipo = str(classification.get("tipo") or "")
    authors = classification.get("authors") or []
    title = classification.get("title") or ""
    subtitle = classification.get("subtitle") or ""
    year = classification.get("year")

    if tipo in ("Revista", "Revista Científica"):
        # Revista: usar nomeador dedicado de periódico (sem autor, sem subtítulo de capa).
        return format_periodical_filename(
            journal=classification.get("periodico") or classification.get("journal_name") or "",
            title=title,
            subtitle=subtitle,
            year=year,
            month=classification.get("publication_month"),
            month_end=classification.get("publication_month_end"),
            year_end=classification.get("publication_year_end"),
            volume=classification.get("volume"),
            volume_label=classification.get("volume_label"),
            number=classification.get("number") or classification.get("numero"),
            issue_designation=classification.get("issue_designation"),
            supplement=classification.get("supplement"),
            ext=".pdf",
            dest_dir=dest_dir,
            sha=classification.get("sha256"),
        )

    return format_academic_filename(
        authors=authors,
        title=title,
        subtitle=subtitle,
        year=year,
        dest_dir=dest_dir,
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
        try:
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
        except Exception as exc:  # defensivo: 1 arquivo com erro nunca aborta o lote
            logger = logging.getLogger("tomus.pipeline")
            logger.error(
                "Falha inesperada processando %s: %s",
                scanned.path,
                _sanitize_error_message(str(exc)),
            )
            try:
                with finalize_lock:
                    entry = organizer.add_error(
                        scanned.path, scanned.sha256,
                        f"Falha inesperada: {_sanitize_error_message(str(exc))}",
                    )
                # Atualizar completed_count sob lock e emitir evento terminal de erro.
                comp = None
                if completed_count is not None and completed_count_lock is not None:
                    with completed_count_lock:
                        completed_count[0] += 1
                        comp = completed_count[0]
                _emit(
                    emit,
                    "organizer",
                    scanned.path,
                    "error",
                    f"Falha inesperada: {_sanitize_error_message(str(exc))}",
                    completed_files=comp,
                    total_files=total_scanned,
                    sha256=scanned.sha256,
                    destination_path=entry.destination_path,
                )
                return organizer.entries[-1]
            except Exception:
                return None

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process_with_lock, s) for s in valid_pdfs]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    _logger.warning(
                        "Falha ao processar future do pool: %s", exc
                    )
                    # já tratado dentro de process_with_lock
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
