"""Execução assíncrona do pipeline e serviço de triagem manual (Seção 5.4 item 1).

Implementa:
* ``PipelineWorker(QThread)`` — executa ``run_pipeline`` em background sem
  bloquear a Event Loop do Qt, comunicando-se via sinais Qt thread-safe
  (``event_received``, ``pipeline_finished``, ``pipeline_failed``) com
  cancelamento cooperativo seguro via ``cancel_event.set()``.
* ``ManualTriageService`` — aprova e materializa um item de revisão manual na
  árvore temática CAPES/CNPq, gera o ``.md`` companheiro ABNT, persiste no
  cache SQLite (confidence 1.0, modelo ``manual_human_review``) e atualiza
  ``manifest.json`` + ``relatorio_revisao.md``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from tomus.core.cache import FileCache
from tomus.core.config import AppConfig
from tomus.core.models import (
    FileManifestEntry,
    PipelineEvent,
    ProcessStatus,
)
from tomus.core.periodicals import canonical_journal
from tomus.core.pipeline import run_pipeline
from tomus.core.taxonomy import (
    get_taxonomy_version,
    repair_taxonomy_levels,
    validate_or_repair_pair,
)
from tomus.storage.companion import generate_companion_markdown
from tomus.storage.namer import format_academic_filename
from tomus.storage.organizer import (
    MANIFEST_FILENAME,
    RELATORIO_FILENAME,
    REVISAO_DIR,
    _is_within,
    _resolve_collision,
)

_logger = logging.getLogger("tomus.gui.worker")

__all__ = ["PipelineWorker", "ManualTriageService"]


# --------------------------------------------------------------------------- #
# PipelineWorker — execução assíncrona do pipeline de 5 estágios
# --------------------------------------------------------------------------- #


class PipelineWorker(QThread):
    """Executa ``run_pipeline`` em background sem bloquear a UI.

    Os sinais são emitidos com ``Qt.ConnectionType.QueuedConnection``
    (padrão para sinais entre threads no PySide6), garantindo comunicação
    thread-safe entre a worker thread e a thread principal da GUI.
    """

    event_received = Signal(object)          # PipelineEvent
    pipeline_finished = Signal(object, bool)  # (ExecutionSummary, was_cancelled)
    pipeline_failed = Signal(str)            # mensagem de erro inesperado

    def __init__(
        self,
        source_dir: Path | str,
        target_dir: Path | str,
        config: AppConfig,
        *,
        dry_run: bool = False,
        use_cache: bool = True,
        workers: int = 1,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.config = config
        self.dry_run = dry_run
        self.use_cache = use_cache
        self.workers = workers
        self.cancel_event = threading.Event()

    def request_cancel(self) -> None:
        """Acionar cancelamento cooperativo seguro no orquestrador."""
        self.cancel_event.set()

    def run(self) -> None:
        try:
            summary = run_pipeline(
                source_dir=self.source_dir,
                target_dir=self.target_dir,
                config=self.config,
                workers=self.workers,
                event_callback=self._handle_pipeline_event,
                use_cache=self.use_cache,
                dry_run=self.dry_run,
                cancel_event=self.cancel_event,
            )
            self.pipeline_finished.emit(summary, self.cancel_event.is_set())
        except Exception as exc:  # pragma: no cover - erro inesperado do orquestrador
            self.pipeline_failed.emit(str(exc))

    def _handle_pipeline_event(self, event: PipelineEvent) -> None:
        self.event_received.emit(event)


# --------------------------------------------------------------------------- #
# ManualTriageService — triagem manual assistida
# --------------------------------------------------------------------------- #


class ManualTriageService(QObject):
    """Aprovar e materializar um item de revisão manual na biblioteca temática.

    O serviço move/copia o arquivo de ``revisao_manual/`` para a pasta temática
    correta ``<Grande Área>/<Área Básica>/<Tipo>/``, gera o ``.md`` companheiro
    ABNT NBR 6023, grava a classificação revisada no cache SQLite
    (``confidence_score = 1.0``, ``model_name = "manual_human_review"``) e
    atualiza ``manifest.json`` e ``relatorio_revisao.md``.
    """

    triage_completed = Signal(object)  # FileManifestEntry atualizado (organizado)

    def __init__(
        self,
        target_dir: Path | str,
        config: AppConfig,
        cache: FileCache | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.target_dir = Path(target_dir).resolve()
        self.config = config
        self.cache = cache or FileCache(enabled=True)
        self._history: list[tuple[FileManifestEntry, Path, Path]] = []

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def approve_and_materialize(
        self,
        entry: FileManifestEntry,
        grande_area: str,
        area_basica: str,
        tipo: str,
        title: str,
        subtitle: str,
        authors: list[str],
        year: int | None,
        subarea: str = "Geral",
        *,
        publication_month: int | None = None,
        publication_month_end: int | None = None,
        publication_year_end: int | str | None = None,
        volume: str | None = None,
        volume_label: str | None = None,
        number: str | None = None,
        issue_designation: str | None = None,
        supplement: str | None = None,
        issn: str | None = None,
        journal_genre: str | None = None,
        serial_evidence: str | None = None,
    ) -> FileManifestEntry:
        """Aprovar classificação manual e materializar o item na biblioteca."""
        # Validar/reparar o par CAPES/CNPq (incluindo deslocamento de níveis
        # quando area_basica é, na verdade, uma Grande Área, ex.: Letras).
        par = validate_or_repair_pair(grande_area, area_basica)
        if par is None:
            reparado_niveis = repair_taxonomy_levels(
                grande_area, area_basica, subarea
            )
            if reparado_niveis is None:
                raise ValueError(
                    f"Par CAPES/CNPq inválido: {grande_area} / {area_basica}"
                )
            grande_area, area_basica, subarea, _especialidade = reparado_niveis
        else:
            grande_area, area_basica = par

        # Revista: não usar 'Autor Desconhecido' como prefixo.
        if str(tipo) in ("Revista", "Revista Científica"):
            authors = []

        # Roteador de periódicos (PR #14).
        tipo_eh_revista = str(tipo) in ("Revista", "Revista Científica")
        subarea_clean = (subarea or "").strip() or "Geral"
        journal_canonical = ""
        if tipo_eh_revista:
            journal_canonical = canonical_journal(title) or ""
            if not journal_canonical:
                raise ValueError(
                    "Periódico não identificado para fascículo de revista."
                )
            dest_dir = self.target_dir / area_basica / subarea_clean / "Revista" / journal_canonical
        else:
            dest_dir = self.target_dir / area_basica / subarea_clean / tipo

        # Nome padronizado do arquivo de destino.
        if tipo_eh_revista:
            from tomus.storage.namer import format_periodical_filename

            filename = format_periodical_filename(
                journal=title,
                year=year,
                month=publication_month,
                month_end=publication_month_end,
                year_end=publication_year_end,
                volume=volume,
                volume_label=volume_label,
                number=number,
                issue_designation=issue_designation,
                supplement=supplement,
                dest_dir=dest_dir,
            )
        else:
            filename = format_academic_filename(
                authors=authors,
                title=title,
                subtitle=subtitle,
                year=year,
                dest_dir=dest_dir,
            )

        # Localizar o arquivo físico existente (seja na origem ou já em revisao_manual)
        source_path = Path(entry.source_path)
        actual_file_path: Path | None = None
        if source_path.exists():
            actual_file_path = source_path
        elif entry.destination_path and Path(entry.destination_path).exists():
            actual_file_path = Path(entry.destination_path)
        else:
            candidate = self.target_dir / "revisao_manual" / source_path.name
            if candidate.exists():
                actual_file_path = candidate

        if actual_file_path is None or not actual_file_path.exists():
            raise FileNotFoundError(
                f"Arquivo PDF não encontrado na origem ({source_path}) nem em revisao_manual."
            )

        sha256 = entry.sha256 or self._compute_sha256(actual_file_path)

        classification: dict[str, Any] = {
            "grande_area": grande_area,
            "area_basica": area_basica,
            "subarea": subarea_clean,
            "especialidade": "Geral",
            "tipo": tipo,
            "authors": authors,
            "title": title,
            "subtitle": subtitle,
            "year": year,
            "confidence_score": 1.0,
            "reasoning": "manual_human_review",
        }
        # Campos seriais (PR #14).
        if tipo_eh_revista:
            classification["periodico"] = title
            classification["_journal_canonical"] = journal_canonical
            if publication_month is not None:
                classification["publication_month"] = publication_month
            if publication_month_end is not None:
                classification["publication_month_end"] = publication_month_end
            if publication_year_end is not None:
                classification["publication_year_end"] = publication_year_end
            if volume is not None:
                classification["volume"] = volume
            if volume_label is not None:
                classification["volume_label"] = volume_label
            if number is not None:
                classification["number"] = number
            if issue_designation is not None:
                classification["issue_designation"] = issue_designation
            if supplement is not None:
                classification["supplement"] = supplement
            if issn is not None:
                classification["issn"] = issn
            if journal_genre is not None:
                classification["journal_genre"] = journal_genre
            if serial_evidence is not None:
                classification["serial_evidence"] = serial_evidence

        # Destino na árvore temática com resolução de colisão.
        dest_dir.mkdir(parents=True, exist_ok=True)
        nome_final, _colisao = _resolve_collision(
            dest_dir, filename, actual_file_path, src_sha256=sha256
        )
        dest_path = dest_dir / nome_final

        # AppSec A-02: validar source_path e _is_within antes de copiar/mover.
        if not actual_file_path.exists() or not actual_file_path.is_file():
            raise FileNotFoundError(
                f"Arquivo de origem não encontrado ou não é um arquivo: {actual_file_path}"
            )
        if not _is_within(dest_path, self.target_dir):
            raise ValueError(
                f"Caminho de destino fora do diretório alvo bloqueado: {dest_path}"
            )

        # Copiar o PDF para o destino temático
        shutil.copy2(actual_file_path, dest_path)

        # Se o arquivo já estava em revisao_manual, limpar o arquivo obsoleto de lá
        if actual_file_path.parent == (self.target_dir / "revisao_manual") and actual_file_path != dest_path:
            try:
                actual_file_path.unlink()
                old_companion = actual_file_path.with_suffix(".md")
                if old_companion.exists():
                    old_companion.unlink()
            except Exception:
                _logger.warning("Falha ao remover companheiro .md antigo", exc_info=True)

        # Arquivo companheiro .md ABNT NBR 6023.
        companion_path = dest_path.with_suffix(".md")
        companion_path.write_text(
            generate_companion_markdown(
                destination_path=companion_path,
                source_path=actual_file_path,
                sha256=sha256,
                classification=classification,
                used_ocr=bool(entry.used_ocr),
            ),
            encoding="utf-8",
        )

        # Persistir no cache SQLite (confidence 1.0, revisão humana).
        taxonomy_version = get_taxonomy_version()
        self.cache.put(
            sha256,
            taxonomy_version,
            "manual_human_review",
            classification,
            bool(entry.used_ocr),
            confidence_min=0.0,
        )

        # Atualizar manifest.json e relatorio_revisao.md.
        self._update_manifest_and_relatorio(
            source_path=source_path,
            dest_path=dest_path,
            sha256=sha256,
            classification=classification,
            used_ocr=bool(entry.used_ocr),
        )

        entry_out = FileManifestEntry(
            source_path=str(source_path),
            destination_path=str(dest_path),
            sha256=sha256,
            status=ProcessStatus.ORGANIZED,
            used_ocr=bool(entry.used_ocr),
            classification=classification,
        )
        self._history.append((entry, dest_path, companion_path))
        self.triage_completed.emit(entry_out)
        return entry_out

    def undo_last_approval(self) -> tuple[bool, str]:
        """Desfazer a última aprovação de triagem manual e restaurar o estado."""
        if not self._history:
            return False, "Nenhuma aprovação de triagem registrada para desfazer."

        orig_entry, dest_pdf, companion_md = self._history.pop()
        try:
            # 1. Restaurar em revisao_manual antes de remover do destino
            revisao_dir = self.target_dir / REVISAO_DIR
            revisao_dir.mkdir(parents=True, exist_ok=True)
            revisao_pdf = revisao_dir / Path(orig_entry.source_path).name
            if not revisao_pdf.exists() and dest_pdf.exists():
                shutil.copy2(dest_pdf, revisao_pdf)
            elif not revisao_pdf.exists() and Path(orig_entry.source_path).exists():
                shutil.copy2(orig_entry.source_path, revisao_pdf)

            # 2. Remover PDF e .md materializados do destino temático
            if dest_pdf.exists():
                dest_pdf.unlink()
            if companion_md.exists():
                companion_md.unlink()

            # 3. Remover do cache
            if orig_entry.sha256:
                self.cache.delete(orig_entry.sha256)

            return True, f"Aprovação de {Path(orig_entry.source_path).name} desfeita com sucesso."
        except Exception as exc:
            return False, f"Falha ao desfazer aprovação: {exc}"

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _update_manifest_and_relatorio(
        self,
        *,
        source_path: Path,
        dest_path: Path,
        sha256: str,
        classification: dict[str, Any],
        used_ocr: bool,
    ) -> None:
        """Atualizar manifest.json e relatorio_revisao.md após triagem manual."""
        manifest_path = self.target_dir / MANIFEST_FILENAME

        # Carregar entradas existentes (se houver).
        entries: list[dict[str, Any]] = []
        generated_at = ""
        totals = {
            "total_scanned": 0,
            "organized_count": 0,
            "manual_review_count": 0,
            "duplicate_skipped_count": 0,
            "ignored_non_pdf_count": 0,
            "error_count": 0,
        }
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                entries = data.get("entries", [])
                generated_at = data.get("generated_at", "")
                for key in totals:
                    totals[key] = data.get(key, 0)
            except (json.JSONDecodeError, OSError):
                entries = []

        # Remover entrada antiga deste source_path (se já estava listada).
        entries = [e for e in entries if e.get("source_path") != str(source_path)]

        # Adicionar a nova entrada organizada.
        new_entry: dict[str, Any] = {
            "source_path": str(source_path),
            "destination_path": str(dest_path),
            "sha256": sha256,
            "status": ProcessStatus.ORGANIZED.value,
            "used_ocr": used_ocr,
            "classification": classification,
        }
        entries.append(new_entry)

        # Recalcular contadores.
        organized = sum(1 for e in entries if e.get("status") == ProcessStatus.ORGANIZED.value)
        manual = sum(1 for e in entries if e.get("status") == ProcessStatus.MANUAL_REVIEW.value)
        duplicate = sum(1 for e in entries if e.get("status") == ProcessStatus.DUPLICATE_SKIPPED.value)
        ignored = sum(1 for e in entries if e.get("status") == ProcessStatus.IGNORED_NON_PDF.value)
        errors = sum(1 for e in entries if e.get("status") == ProcessStatus.ERROR.value)
        total = len(entries)
        manual_ratio = (manual / total) if total else 0.0

        payload = {
            "generated_at": generated_at or datetime.now(UTC).isoformat(),
            "total_scanned": total,
            "organized_count": organized,
            "manual_review_count": manual,
            "duplicate_skipped_count": duplicate,
            "ignored_non_pdf_count": ignored,
            "error_count": errors,
            "manual_review_ratio": round(manual_ratio, 4),
            "exceeded_manual_review_ceiling": manual_ratio > 0.20,
            "entries": entries,
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Atualizar relatorio_revisao.md (remover este item dos pendentes).
        relatorio_path = self.target_dir / REVISAO_DIR / RELATORIO_FILENAME
        if relatorio_path.exists():
            lines = relatorio_path.read_text(encoding="utf-8").splitlines()
            # Manter apenas linhas que não referenciam este source_path como pendente.
            filtered: list[str] = []
            skip_next = False
            for line in lines:
                if skip_next:
                    skip_next = False
                    continue
                if str(source_path) in line and "→" in line:
                    # Esta linha é uma entrada pendente; pular ela e a linha de motivo.
                    skip_next = True
                    continue
                filtered.append(line)
            relatorio_path.write_text("\n".join(filtered), encoding="utf-8")

    def _resolve_collision(
        self,
        dest_dir: Path,
        filename: str,
        src_path: Path,
        *,
        src_sha256: str | None = None,
    ) -> tuple[str, str]:
        """Resolver colisão de nome no destino (mesma lógica do organizer)."""
        from tomus.storage.organizer import _resolve_collision

        return _resolve_collision(
            dest_dir, filename, src_path, None, src_sha256=src_sha256
        )
