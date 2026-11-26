"""Teste de integração validando propagação ponta a ponta dos eventos de pipeline com total_files.

Garante que o NameError em _emit foi resolvido e que a barra de progresso
não fica congelada em '0/?' ao usar múltiplos workers.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from tomus.core.cache import FileCache
from tomus.core.config import AppConfig
from tomus.core.llm import ClassificationResult, MockLLMProvider
from tomus.core.models import PipelineEvent, ProcessStatus
from tomus.core.pipeline import run_pipeline


def _criar_pdf(caminho: Path, texto: str = "Título de teste Autor Silva, João 2020") -> str:
    """Criar um PDF sintético de uma página e retornar seu SHA-256."""
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 72), texto)
    doc.save(str(caminho))
    doc.close()
    import hashlib
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def test_pipeline_events_propagation_with_total_files(tmp_path: Path):
    """Validar que eventos de pipeline incluem total_files e não travam em 0/?."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    for i in range(5):
        _criar_pdf(source / f"doc_{i}.pdf")

    cfg = AppConfig()
    events: list[PipelineEvent] = []

    def callback(event: PipelineEvent) -> None:
        events.append(event)

    summary = run_pipeline(
        source_dir=source,
        target_dir=target,
        config=cfg,
        provider=MockLLMProvider(),
        workers=4,
        cache=FileCache(enabled=True, db_path=tmp_path / "state.db"),
        event_callback=callback,
    )

    # Todos os PDFs processados sem erro.
    assert summary.total_scanned == 5
    assert summary.error_count == 0
    assert summary.organized_count + summary.manual_review_count == 5

    # Eventos de scanner devem incluir total_files.
    scanner_events = [e for e in events if e.stage == "scanner"]
    assert len(scanner_events) > 0
    completed_events = [e for e in scanner_events if e.status == "completed"]
    assert len(completed_events) == 1
    assert completed_events[0].total_files == 5, (
        f"Esperado total_files=5, obtido {completed_events[0].total_files}"
    )

    # Eventos de pipeline/organizer terminal devem ter completed_files preenchido.
    terminal_events = [
        e for e in events
        if e.stage in ("pipeline", "organizer")
        and e.status in ("organized", "manual_review", "error")
    ]
    if terminal_events:
        for ev in terminal_events:
            assert ev.completed_files is not None, (
                f"Evento {ev.stage}/{ev.status} não tem completed_files preenchido"
            )
            assert ev.total_files == 5, (
                f"Evento {ev.stage}/{ev.status} tem total_files={ev.total_files}, esperado 5"
            )

    # Verificar que o progresso avançou (completed_files > 0 em algum evento terminal).
    assert any(ev.completed_files and ev.completed_files > 0 for ev in terminal_events), (
        "Nenhum evento terminal reportou progresso (completed_files > 0)"
    )


def _criar_pdf_simples(caminho: Path, texto: str = "conteudo") -> None:
    """Criar um PDF sintético de uma página."""
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 72), texto)
    doc.save(str(caminho))
    doc.close()


class _ProviderQueFalhaEmUmArquivo:
    """Provider que levanta excecao inesperada so para um arquivo alvo."""

    def __init__(self, alvo: str) -> None:
        self.alvo = alvo
        self.chamadas: list[str] = []

    def classify(self, sampled_text, cip_text, external_metadata=None, used_ocr=False):
        self.chamadas.append(sampled_text[:30])
        return ClassificationResult(
            grande_area="Ciências Humanas",
            area_basica="Psicologia",
            tipo="Livro",
            authors=["Silva, João"],
            title="Doc",
            subtitle="",
            year=2020,
            confidence_score=0.90,
            reasoning="ok",
        )


def test_pipeline_continua_pos_excecao_inesperada_em_process_one(tmp_path: Path):
    """Excecao inesperada em _process_one nao aborta o lote.

    Valida:
    (a) o lote continua processando os demais arquivos;
    (b) completed_files e incrementado corretamente nos eventos terminais;
    (c) o evento terminal de erro e emitido para o arquivo falho.
    """
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    # Três PDFs; o meio (doc2) vai disparar excecao inesperada via provider.
    _criar_pdf_simples(source / "doc1.pdf", "documento um")
    _criar_pdf_simples(source / "doc2.pdf", "documento dois")
    _criar_pdf_simples(source / "doc3.pdf", "documento tres")

    cfg = AppConfig()
    events: list[PipelineEvent] = []

    def callback(event: PipelineEvent) -> None:
        events.append(event)

    # Provider que levanta excecao inesperada quando o nome do arquivo
    # amostrado contem o alvo (doc2). Para doc1 e doc3 retorna sucesso.
    provider = _ProviderQueFalhaEmUmArquivo(alvo="doc2")

    # Monkeypatch: injetar excecao inesperada dentro de _process_one apenas
    # para doc2, simulando falha nao tratada pelo provider.
    import tomus.core.pipeline as pipeline_mod

    _process_one_original = pipeline_mod._process_one

    def _process_one_com_falha(scanned, **kwargs):
        if scanned.path.name == "doc2.pdf":
            raise RuntimeError("erro inesperado simulado em doc2")
        return _process_one_original(scanned, **kwargs)

    pipeline_mod._process_one = _process_one_com_falha
    try:
        summary = run_pipeline(
            source_dir=source,
            target_dir=target,
            config=cfg,
            provider=provider,
            workers=1,
            cache=FileCache(enabled=True, db_path=tmp_path / "state.db"),
            event_callback=callback,
        )
    finally:
        pipeline_mod._process_one = _process_one_original

    # (a) O lote nao aborta: 3 itens processados (2 organizados + 1 erro).
    assert summary.total_scanned == 3
    assert summary.error_count == 1
    assert summary.organized_count == 2

    # (b) completed_files incrementado corretamente nos eventos terminais.
    terminal_events = [
        e for e in events
        if e.stage in ("organizer", "pipeline")
        and e.status in ("organized", "error")
    ]
    assert len(terminal_events) == 3, f"esperado 3 eventos terminais, obteve {len(terminal_events)}"
    for ev in terminal_events:
        assert ev.completed_files is not None, (
            f"evento {ev.stage}/{ev.status} sem completed_files"
        )
        assert ev.completed_files > 0, (
            f"evento {ev.stage}/{ev.status} com completed_files zerado"
        )
    # completed_files deve avançar 1, 2, 3 (ordem sequencial com workers=1).
    vals = sorted(ev.completed_files for ev in terminal_events)
    assert vals == [1, 2, 3], f"completed_files esperado [1,2,3], obteve {vals}"

    # (c) Evento terminal de erro emitido para o arquivo falho.
    error_events = [
        e for e in terminal_events
        if e.status == "error" and "doc2" in (e.source_path or "")
    ]
    assert len(error_events) == 1, "esperado exatamente 1 evento terminal de erro para doc2"

    # Nenhum arquivo ficou sem ser processado.
    statuses = {e.status.value for e in summary.entries if e.sha256}
    assert ProcessStatus.ORGANIZED.value in statuses
    assert ProcessStatus.ERROR.value in statuses
