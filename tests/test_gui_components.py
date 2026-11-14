"""Testes da Etapa 2 da Passagem 2 — componentes da GUI do Tomus.

Valida:
* DocumentTableModel (8 colunas, upsert a partir de PipelineEvent, replace_all);
* PipelineWorker (criação, sinais, cancelamento cooperativo);
* Geração de QSS (cores dos tokens, sem gradientes/neon);
* Instanciação dos widgets principais (toolbar, sidebar, tabela, inspetor,
  status bar, gaveta, diálogo de preferências) em modo offscreen.

Execução alvo:

    QT_QPA_PLATFORM=offscreen pytest -m 'not slow' tests/test_gui_components.py
"""

from __future__ import annotations

import os as _os

_os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tomus.core.config import AppConfig
from tomus.core.models import (
    ExecutionSummary,
    FileManifestEntry,
    PipelineEvent,
    ProcessStatus,
)
from tomus.gui.models import DocumentTableModel
from tomus.gui.theme import EDITORIAL_PAPER_THEME, generate_qss
from tomus.gui.worker import ManualTriageService, PipelineWorker

__all__ = []


# --------------------------------------------------------------------------- #
# Fixture QApplication
# --------------------------------------------------------------------------- #

_QAPP = None


@pytest.fixture(scope="session")
def qapp():
    global _QAPP
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


# --------------------------------------------------------------------------- #
# DocumentTableModel
# --------------------------------------------------------------------------- #

def test_model_tem_8_colunas(qapp):
    model = DocumentTableModel()
    assert model.columnCount() == 8
    assert model.rowCount() == 0


def test_model_upsert_from_event_atualiza_status(qapp):
    """PipelineEvent terminal atualiza o status da linha (sem classification)."""
    model = DocumentTableModel()
    event = PipelineEvent(
        stage="organizer",
        source_path="/tmp/teste.pdf",
        status=ProcessStatus.ORGANIZED.value,
        message="Arquivo organizado",
    )
    model.upsert_from_event(event)
    assert model.rowCount() == 1
    row = model.row(0)
    assert row is not None
    assert row.source_path == "/tmp/teste.pdf"
    assert row.status == ProcessStatus.ORGANIZED.value
    assert row.stage == "organizer"
    assert row.message == "Arquivo organizado"


def test_model_upsert_event_scanner_completed_nao_insere(qapp):
    model = DocumentTableModel()
    event = PipelineEvent(
        stage="scanner",
        source_path="/tmp",
        status="completed",
        message="3 PDF(s) válido(s)",
        total_files=3,
    )
    model.upsert_from_event(event)
    assert model.rowCount() == 0


def test_model_upsert_event_scanner_started_diretorio_origem_nao_insere(qapp, tmp_path):
    """Eventos de ciclo de vida do scanner sobre pastas (ex: origem) não devem virar itens na grade."""
    model = DocumentTableModel()
    event = PipelineEvent(
        stage="scanner",
        source_path=str(tmp_path),
        status="started",
        message="Varredura do diretório de origem",
    )
    model.upsert_from_event(event)
    assert model.rowCount() == 0


def test_model_upsert_event_pipeline_completed_diretorio_destino_nao_insere(qapp, tmp_path):
    """Evento final do pipeline com target_dir não deve ser inserido na grade."""
    model = DocumentTableModel()
    event = PipelineEvent(
        stage="pipeline",
        source_path=str(tmp_path),
        status="completed",
        message="24 organizado(s), 1 revisão manual",
    )
    model.upsert_from_event(event)
    assert model.rowCount() == 0


def test_model_upsert_event_em_processamento_tem_status_processing(qapp):
    """Enquanto o pipeline processa, o status inicial é 'processing' e não 'organized' prematuro."""
    model = DocumentTableModel()
    event = PipelineEvent(
        stage="extractor",
        source_path="/tmp/livro_em_processamento.pdf",
        status="started",
        message="Extraindo conteúdo do PDF",
    )
    model.upsert_from_event(event)
    assert model.rowCount() == 1
    row = model.row(0)
    assert row is not None
    assert row.status == "processing"


def test_model_replace_all(qapp):
    model = DocumentTableModel()
    entries = [
        FileManifestEntry(
            source_path="/tmp/a.pdf",
            destination_path="/tmp/dst/a.pdf",
            sha256="sha-a",
            status=ProcessStatus.ORGANIZED,
        ),
        FileManifestEntry(
            source_path="/tmp/b.pdf",
            destination_path=None,
            sha256="sha-b",
            status=ProcessStatus.ERROR,
            error_message="PDF corrompido",
        ),
    ]
    model.replace_all(entries)
    assert model.rowCount() == 2
    model.clear()
    assert model.rowCount() == 0


# --------------------------------------------------------------------------- #
# PipelineWorker
# --------------------------------------------------------------------------- #

def test_worker_criacao_e_cancelamento(qapp):
    config = AppConfig()
    worker = PipelineWorker(
        source_dir="/tmp/src",
        target_dir="/tmp/dst",
        config=config,
    )
    assert isinstance(worker.cancel_event, threading.Event)
    assert not worker.cancel_event.is_set()
    worker.request_cancel()
    assert worker.cancel_event.is_set()


def test_worker_sinais_existem(qapp):
    worker = PipelineWorker(
        source_dir="/tmp/src",
        target_dir="/tmp/dst",
        config=AppConfig(),
    )
    assert hasattr(worker, "event_received")
    assert hasattr(worker, "pipeline_finished")
    assert hasattr(worker, "pipeline_failed")


# --------------------------------------------------------------------------- #
# QSS
# --------------------------------------------------------------------------- #

def test_qss_contem_tokens_do_tema():
    qss = generate_qss(EDITORIAL_PAPER_THEME)
    assert "#F8F9FA" in qss  # bg_canvas
    assert "#FFFFFF" in qss  # bg_surface
    assert "#1E3A8A" in qss  # accent_primary / border_focus
    assert "gradient" not in qss.lower()


# --------------------------------------------------------------------------- #
# Widgets — instanciação em offscreen
# --------------------------------------------------------------------------- #

def test_toolbar_instancia(qapp):
    from tomus.gui.widgets.toolbar import OperationalToolbar

    toolbar = OperationalToolbar()
    assert toolbar.provider_key() == "gemini"
    assert toolbar.file_operation() == "copy"
    assert toolbar.dry_run() is False
    assert toolbar.recursive() is True


def test_sidebar_instancia(qapp):
    from tomus.gui.widgets.sidebar import CapesSidebarPanel

    sidebar = CapesSidebarPanel()
    sidebar.set_counters({"total": 10, "organized": 7, "error": 1})
    areas = {
        "Ciências Humanas": {"Psicologia": ["Livro", "Artigo"]},
        "Ciências Exatas": {"Ciência da Computação": ["Artigo"]},
    }
    sidebar.populate_tree(areas)
    assert sidebar.tree.topLevelItemCount() == 2


def test_document_table_panel_instancia(qapp):
    from tomus.gui.widgets.document_table import DocumentTablePanel

    panel = DocumentTablePanel()
    panel.clear()
    assert panel.table.model().rowCount() == 0


def test_inspector_instancia(qapp):
    from tomus.gui.widgets.inspector import DocumentInspectorPanel

    inspector = DocumentInspectorPanel()
    inspector.show_entry(None)
    assert inspector._current_entry is None


def test_status_bar_instancia(qapp):
    from tomus.gui.widgets.status_drawer import TelemetryStatusBar

    bar = TelemetryStatusBar()
    bar.set_progress(50, 100)
    bar.set_stage("llm")
    bar.set_manual_review(0.10, False)
    assert bar.progress.value() == 50


def test_log_drawer_instancia(qapp):
    from tomus.gui.widgets.status_drawer import LogCacheDrawer

    drawer = LogCacheDrawer()
    drawer.append_log("teste de log")
    drawer.refresh_cache_stats()
    assert drawer.height() == 0  # colapsada por padrão


def test_preferences_dialog_instancia(qapp):
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog

    dlg = PreferencesDialog(AppConfig())
    assert dlg is not None
    dlg.reject()


# --------------------------------------------------------------------------- #
# ManualTriageService (instanciação e validação de par inválido)
# --------------------------------------------------------------------------- #

def test_triage_service_instancia(qapp, tmp_path):
    service = ManualTriageService(tmp_path, AppConfig())
    assert service is not None
    assert service.target_dir == tmp_path.resolve()


def test_triage_service_par_invalido(qapp, tmp_path):
    service = ManualTriageService(tmp_path, AppConfig())
    entry = FileManifestEntry(
        source_path="/tmp/x.pdf",
        sha256="abc",
        status=ProcessStatus.MANUAL_REVIEW,
    )
    with pytest.raises(ValueError):
        service.approve_and_materialize(
            entry,
            grande_area="Área Inexistente",
            area_basica="Também Inexistente",
            tipo="Livro",
            title="T",
            subtitle="",
            authors=["A, B"],
            year=2020,
        )


def test_triage_service_materialize_from_revisao_manual(qapp, tmp_path):
    target = tmp_path / "target"
    rev_manual_dir = target / "revisao_manual"
    rev_manual_dir.mkdir(parents=True)
    pdf_in_rev = rev_manual_dir / "livro_pendente.pdf"
    pdf_in_rev.write_bytes(b"%PDF-1.4 dummy content for test")

    service = ManualTriageService(target, AppConfig())
    entry = FileManifestEntry(
        source_path="/original/non_existent/path/livro_pendente.pdf",
        destination_path=str(pdf_in_rev),
        sha256="",
        status=ProcessStatus.MANUAL_REVIEW,
    )

    out = service.approve_and_materialize(
        entry,
        grande_area="Ciências Humanas",
        area_basica="Psicologia",
        tipo="Outros",
        title="Livro Pendente Aprovado",
        subtitle="Parte 1",
        authors=["Oliveira, Larissa"],
        year=2024,
    )

    assert out.status == ProcessStatus.ORGANIZED
    dest = Path(out.destination_path)
    assert dest.exists()
    assert dest.parent == target / "Psicologia" / "Geral" / "Outros"
    assert not pdf_in_rev.exists()  # Removido da pasta revisao_manual
    assert dest.with_suffix(".md").exists()  # Companion gerado

    # Testar desfazer aprovação (FEAT-TRIAGE-02)
    ok, msg = service.undo_last_approval()
    assert ok is True
    assert not dest.exists()  # PDF removido do destino
    assert not dest.with_suffix(".md").exists()  # Companion removido
    assert pdf_in_rev.exists()  # PDF restaurado em revisao_manual


def test_validate_key_format_structural():
    from tomus.gui.widgets.preferences_dialog import _validate_key_format

    # DeepSeek: requer prefixo sk-
    ok, err = _validate_key_format("deepseek_api_key", "sk-dummy-deepseek-test-key-01")
    assert ok is True
    assert err == ""

    # DeepSeek com UUID puro (erro constatado no passado)
    ok, err = _validate_key_format("deepseek_api_key", "9f874b23-5e82-411a-8bb0-26463fb76fca")
    assert ok is False
    assert "sk-" in err

    # Groq: requer prefixo gsk_
    ok, err = _validate_key_format("groq_api_key", "gsk_1234567890abcdef1234567890")
    assert ok is True
    ok, err = _validate_key_format("groq_api_key", "invalid_prefix_key")
    assert ok is False
    assert "gsk_" in err

    # NVIDIA: requer prefixo nvapi-
    ok, err = _validate_key_format("nvidia_api_key", "nvapi-1234567890abcdef1234567890")
    assert ok is True
    ok, err = _validate_key_format("nvidia_api_key", "sk-wrong-nvidia")
    assert ok is False
    assert "nvapi-" in err

    # Claude: requer prefixo sk-ant-
    ok, err = _validate_key_format("claude_api_key", "sk-ant-1234567890abcdef1234567890abcdef")
    assert ok is True
    ok, err = _validate_key_format("claude_api_key", "sk-wrong-claude")
    assert ok is False
    assert "sk-ant-" in err

    # Pool com múltiplas chaves separadas por vírgula
    pool = "sk-dummy-pool-key-alpha, sk-dummy-pool-key-beta"
    ok, err = _validate_key_format("deepseek_api_key", pool)
    assert ok is True

    # Pool com uma chave inválida
    bad_pool = "sk-dummy-pool-key-alpha, invalid-key"
    ok, err = _validate_key_format("deepseek_api_key", bad_pool)
    assert ok is False
    assert "Chave 2" in err


def test_preferences_dialog_restore_defaults_preserves_keys(qapp, monkeypatch):
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog
    from PySide6.QtWidgets import QMessageBox

    cfg = AppConfig()
    cfg.api_keys.deepseek_api_key = "sk-preset-secret-key-1234567890"
    cfg.general.confidence_min = 0.99
    cfg.llm.model = "custom-model"

    dlg = PreferencesDialog(cfg)
    assert dlg._fields["deepseek_api_key"].text() == "sk-preset-secret-key-1234567890"

    # Simular clique em "Sim" no diálogo de confirmação
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    dlg._restore_defaults()

    # Confere se os valores padrão foram restaurados
    assert dlg.edit_conf.text() == "0.70"
    assert dlg.edit_model.text() == "gemini-3.5-flash"
    assert "claude" in [dlg.fallback_model.item(i).text() for i in range(dlg.fallback_model.rowCount())]
    # E que a chave foi preservada com segurança!
    assert dlg._fields["deepseek_api_key"].text() == "sk-preset-secret-key-1234567890"
    dlg.reject()


def test_key_pool_dialog_add_remove_and_validation(qapp):
    from tomus.gui.widgets.preferences_dialog import KeyPoolDialog

    initial = ["AIzaSyKeyOne12345", "AIzaSyKeyTwo12345"]
    dlg = KeyPoolDialog("Google Gemini", "gemini_api_key", initial)
    assert dlg.get_keys() == initial

    # Adicionar chave válida
    dlg.edit_new_key.setText("AIzaSyKeyThree12345")
    dlg._add_key()
    assert len(dlg.get_keys()) == 3
    assert dlg.get_keys()[-1] == "AIzaSyKeyThree12345"

    # Adicionar chave inválida (não deve entrar no pool)
    dlg.edit_new_key.setText("bad-key")
    dlg._add_key()
    assert len(dlg.get_keys()) == 3
    assert not dlg.lbl_add_err.isHidden()
    assert "inválida" in dlg.lbl_add_err.text().lower()

    # Remover primeira chave
    dlg._remove_key(0)
    assert len(dlg.get_keys()) == 2
    assert dlg.get_keys()[0] == "AIzaSyKeyTwo12345"
    dlg.reject()


def test_preferences_dialog_pool_button_and_fallback_actions(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog

    monkeypatch.chdir(tmp_path)
    cfg = AppConfig()
    cfg.api_keys.gemini_api_key = "AIzaSyKey111111111, AIzaSyKey222222222"
    cfg.api_keys.groq_api_key = "gsk_GroqTestKey12345"
    cfg.api_keys.nvidia_api_key = ""
    cfg_file = tmp_path / "config.toml"
    dlg = PreferencesDialog(cfg, config_path=cfg_file)

    # Limpar campo nvidia explicitamente para testar status sem chave
    dlg._fields["nvidia_api_key"].setText("")

    # Verificar que o botão do pool mostra contagem de chaves
    assert "Pool (2 chaves)" in dlg._pool_buttons["gemini_api_key"].text()

    # Testar ação 'Apenas com Chave' no fallback
    dlg._check_only_keyed_fallbacks()
    for i in range(dlg.fallback_model.rowCount()):
        it = dlg.fallback_model.item(i)
        prov = it.text()
        if prov == "groq":
            assert it.checkState() == Qt.CheckState.Checked
        elif prov == "nvidia":
            assert it.checkState() == Qt.CheckState.Unchecked

    # Testar 'Marcar Todos'
    dlg._check_all_fallbacks()
    for i in range(dlg.fallback_model.rowCount()):
        assert dlg.fallback_model.item(i).checkState() == Qt.CheckState.Checked

    # Testar persistência salvando apenas itens marcados
    dlg._check_only_keyed_fallbacks()
    dlg._save()
    assert "groq" in cfg.llm.fallback_chain
    assert "nvidia" not in cfg.llm.fallback_chain


def test_create_provider_chain_multiple_keys_in_pool():
    from tomus.core.config import AppConfig
    from tomus.core.llm import create_provider_chain

    cfg = AppConfig()
    cfg.api_keys.gemini_api_key = "AIzaSyKeyAlpha12345, AIzaSyKeyBeta12345"
    cfg.llm.provider = "gemini"

    dispatcher = create_provider_chain(cfg)
    providers = dispatcher._providers
    assert len(providers) >= 2
    assert providers[0][0] == "gemini"
    assert providers[1][0] == "gemini (pool chave 2)"


def test_invalid_key_rejected_by_syntax_and_ui(qapp, tmp_path, monkeypatch):
    """Garante que chaves sem o prefixo oficial são rejeitadas na digitação e na UI."""
    from tomus.core.key_validator import validate_key_syntax
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog
    from tomus.gui.bridge import WebBridge

    # 1. Validação de chaves inválidas vs chaves válidas (GCP AIzaSy e Google AI Studio AQ.)
    ok_inv, err_inv = validate_key_syntax("gemini_api_key", "InvalidKeyWithoutPrefix12345")
    assert ok_inv is False
    assert "AIzaSy" in err_inv or "AQ." in err_inv

    ok_aq, err_aq = validate_key_syntax("gemini_api_key", "AQ.DummyTestKeyForVerification12345")
    assert ok_aq is True
    assert err_aq == ""

    ok_aiza, err_aiza = validate_key_syntax("gemini_api_key", "AIzaSyDummyTestKeyForVerification12345")
    assert ok_aiza is True
    assert err_aiza == ""

    # 2. Na interface gráfica, a chave inválida NÃO fica verde nem como configurada
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig()
    dlg = PreferencesDialog(cfg, config_path=tmp_path / "config.toml")
    dlg._fields["gemini_api_key"].setText("InvalidKeyWithoutPrefix12345")

    assert "Formato Inválido" in dlg._env_labels["gemini_api_key"].text()
    assert dlg._error_labels["gemini_api_key"].isVisible() or not dlg._error_labels["gemini_api_key"].isHidden()
    assert "AIzaSy" in dlg._error_labels["gemini_api_key"].text()

    # 3. No WebBridge, o status deve ser 'invalid' e checkProviderKey deve ser False
    cfg.api_keys.gemini_api_key = "InvalidKeyWithoutPrefix12345"
    bridge = WebBridge(cfg)
    assert bridge.getProviderKeyStatus("gemini") == "invalid"
    assert bridge.checkProviderKey("gemini") is False


def test_key_pool_dialog_and_live_validation(qapp, tmp_path, monkeypatch):
    """Garante que o sub-diálogo de pool de chaves recebe o provedor correto e que a validação não falha com 'False'."""
    from tomus.core.key_validator import _normalize_field_name, validate_provider_key_live
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog, KeyPoolDialog
    import httpx

    # 1. Normalização defensiva de nomes e títulos
    assert _normalize_field_name("Anthropic Claude API Key") == "claude_api_key"
    assert _normalize_field_name("claude") == "claude_api_key"
    assert _normalize_field_name("Anthropic") == "claude_api_key"
    assert _normalize_field_name("Google Gemini API Key") == "gemini_api_key"
    assert _normalize_field_name("gemini") == "gemini_api_key"
    assert _normalize_field_name("Groq Cloud API Key") == "groq_api_key"
    assert _normalize_field_name("NVIDIA NIM API Key") == "nvidia_api_key"
    assert _normalize_field_name("DeepSeek API Key") == "deepseek_api_key"
    assert _normalize_field_name("Google Books API Key") == "google_books_api_key"
    assert _normalize_field_name(False) == ""
    assert _normalize_field_name(None) == ""

    # 2. KeyPoolDialog protege contra campo inválido e infere pelo título
    dlg_defensive = KeyPoolDialog("Anthropic Claude API Key", False, ["sk-ant-test1", "sk-ant-test2"])
    assert dlg_defensive._field_name == "claude_api_key"

    # 3. PreferencesDialog: clicar em [＋ Pool de Chaves] abre KeyPoolDialog com o f_name correto
    captured_dlg = []
    real_exec = KeyPoolDialog.exec

    def mock_exec(self):
        captured_dlg.append(self)
        return KeyPoolDialog.DialogCode.Rejected

    monkeypatch.setattr(KeyPoolDialog, "exec", mock_exec)

    cfg = AppConfig()
    cfg.api_keys.claude_api_key = "sk-ant-test1, sk-ant-test2"
    pref = PreferencesDialog(cfg, config_path=tmp_path / "config.toml")

    btn_claude_pool = pref._pool_buttons["claude_api_key"]
    # Simula o clique do usuário via sinal Qt clicked(False)
    btn_claude_pool.click()

    assert len(captured_dlg) == 1
    assert captured_dlg[0]._field_name == "claude_api_key"
    assert captured_dlg[0]._provider_title == "Anthropic Claude API Key"

    # 4. Validação ativa mockada da Anthropic
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, headers=None, params=None):
            class MockResponse:
                status_code = 200
                text = '{"data": [{"id": "claude-3-7-sonnet"}]}'
                def json(self):
                    return {"data": [{"id": "claude-3-7-sonnet"}]}
            return MockResponse()

    monkeypatch.setattr(httpx, "Client", MockClient)
    ok, msg = validate_provider_key_live("claude_api_key", "sk-ant-test12345")
    assert ok is True
    assert "Anthropic Claude" in msg






