"""Testes do auto-teste headless de OCR (--self-test-ocr) sem abrir QApplication."""

import os
import sys
from unittest.mock import patch

# Garantir offscreen ANTES de qualquer import que possa tocar Qt.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from tomus.gui.app import run_self_test_ocr  # noqa: E402


def test_run_self_test_ocr_sem_argumento_sucesso(tmp_path, monkeypatch):
    """run_self_test_ocr() sem argumento gera PDF temporario e retorna 0 quando OCR reconhece TOMUS e 2026."""
    with patch(
        "tomus.extractors.ocr.ocr_scanned_pages",
        return_value="TOMUS OCR SMOKE CHECK 2026 reconhecido",
    ):
        codigo = run_self_test_ocr(None)
    assert codigo == 0


def test_run_self_test_ocr_sem_argumento_ocr_vazio_retorna_1(monkeypatch):
    """run_self_test_ocr() sem argumento retorna 1 quando OCR retorna vazio."""
    with patch("tomus.extractors.ocr.ocr_scanned_pages", return_value=""):
        codigo = run_self_test_ocr(None)
    assert codigo == 1


def test_run_self_test_ocr_sem_argumento_palavras_chave_faltando_retorna_1(monkeypatch):
    """run_self_test_ocr() sem argumento retorna 1 quando falta TOMUS ou 2026."""
    with patch(
        "tomus.extractors.ocr.ocr_scanned_pages", return_value="somente texto generico"
    ):
        codigo = run_self_test_ocr(None)
    assert codigo == 1


def test_run_self_test_ocr_pdf_inexistente_retorna_diferente_de_zero():
    """run_self_test_ocr com caminho de PDF inexistente retorna != 0."""
    codigo = run_self_test_ocr("/caminho/inexistente/nao_existe.pdf")
    assert codigo != 0


def test_run_self_test_ocr_caminho_valido_retorno_nao_vazio_retorna_0(tmp_path, monkeypatch):
    """run_self_test_ocr com caminho valido e retorno nao vazio retorna 0."""
    pdf_falso = tmp_path / "falso.pdf"
    pdf_falso.write_bytes(b"%PDF-1.4 fake")
    with patch("tomus.extractors.ocr.ocr_scanned_pages", return_value="texto qualquer"):
        codigo = run_self_test_ocr(str(pdf_falso))
    assert codigo == 0


def test_main_intercepta_self_test_ocr_sem_abrir_qapplication(monkeypatch):
    """main() com --self-test-ocr chama run_self_test_ocr e NAO chama launch_gui (sem QApplication)."""
    from tomus.gui import app as app_module

    chamado_run = []
    chamado_launch = []

    def fake_run(pdf_path=None):
        chamado_run.append(pdf_path)
        return 0

    def fake_launch():
        chamado_launch.append(True)
        return 0

    monkeypatch.setattr(app_module, "run_self_test_ocr", fake_run)
    monkeypatch.setattr(app_module, "launch_gui", fake_launch)

    argv_backup = sys.argv[:]
    sys.argv = ["tomus-gui", "--self-test-ocr", "/tmp/qualquer.pdf"]
    try:
        with pytest.raises(SystemExit) as excinfo:
            app_module.main()
        assert excinfo.value.code == 0
    finally:
        sys.argv = argv_backup

    assert chamado_run == ["/tmp/qualquer.pdf"]
    assert chamado_launch == [], "launch_gui nao deve ser chamado no modo --self-test-ocr"


def test_main_sem_argumento_chama_launch_gui(monkeypatch):
    """main() sem --self-test-ocr chama launch_gui (caminho normal da GUI)."""
    from tomus.gui import app as app_module

    chamado_run = []
    chamado_launch = []

    def fake_run(pdf_path=None):
        chamado_run.append(pdf_path)
        return 0

    def fake_launch():
        chamado_launch.append(True)
        return 0

    monkeypatch.setattr(app_module, "run_self_test_ocr", fake_run)
    monkeypatch.setattr(app_module, "launch_gui", fake_launch)

    argv_backup = sys.argv[:]
    sys.argv = ["tomus-gui"]
    try:
        with pytest.raises(SystemExit) as excinfo:
            app_module.main()
        assert excinfo.value.code == 0
    finally:
        sys.argv = argv_backup

    assert chamado_run == []
    assert chamado_launch == [True]
