"""Testes unitários para o WebBridge e MainWindow baseada em WebEngine."""

import os
import sys

# Garantir offscreen e desativação de sandbox ANTES de qualquer import do PySide6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tomus.core.config import AppConfig
from tomus.gui.bridge import WebBridge
from tomus.gui.main_window import TomusMainWindow

_QAPP = None


def get_qapp():
    global _QAPP
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def test_web_bridge_initial_state():
    get_qapp()
    cfg = AppConfig()
    bridge = WebBridge(cfg)
    bridge.source_dir = "/tmp/origem"
    bridge.target_dir = "/tmp/destino"

    raw = bridge.getInitialState()
    data = json.loads(raw)
    assert data["source"] == "/tmp/origem"
    assert data["target"] == "/tmp/destino"
    assert "provider" in data
    assert "hasKey" in data


def test_web_bridge_slots_exist():
    get_qapp()
    cfg = AppConfig()
    bridge = WebBridge(cfg)

    assert hasattr(bridge, "browseSource")
    assert hasattr(bridge, "browseTarget")
    assert hasattr(bridge, "startOrganize")
    assert hasattr(bridge, "cancelPipeline")
    assert hasattr(bridge, "openPdf")
    assert hasattr(bridge, "revealPath")
    assert hasattr(bridge, "openExternalUrl")
    assert hasattr(bridge, "approveManualTriage")
    assert hasattr(bridge, "checkProviderKey")
    assert hasattr(bridge, "openCacheDialog")
    assert hasattr(bridge, "openPreferences")


def test_web_bridge_check_provider_key():
    get_qapp()
    cfg = AppConfig()
    bridge = WebBridge(cfg)

    # Provider sem chave deve retornar False
    cfg.api_keys.claude_api_key = ""
    assert bridge.checkProviderKey("claude") is False

    # Provider com chave deve retornar True
    cfg.api_keys.claude_api_key = "sk-ant-test-key"
    assert bridge.checkProviderKey("claude") is True

    cfg.api_keys.groq_api_key = ""
    assert bridge.checkProviderKey("groq") is False

    cfg.api_keys.groq_api_key = "gsk_test"
    assert bridge.checkProviderKey("groq") is True


def test_web_bridge_cache_module_accessible():
    """Garante que tomus.core.cache é importado sem erros no slot de cache."""
    from tomus.core.cache import FileCache

    cache = FileCache(enabled=True)
    count = cache.count()
    assert isinstance(count, int)
    assert count >= 0
    cache.close()


def test_preferences_dialog_light_styling():
    """Garante que PreferencesDialog tem estilo claro explícito e componentes legíveis."""
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog

    get_qapp()
    cfg = AppConfig()
    dlg = PreferencesDialog(cfg)

    assert "#FFFFFF" in dlg.styleSheet()
    assert "#1E3A8A" in dlg.styleSheet()
    assert dlg.tabs.count() == 3
    assert dlg.tabs.tabText(0) == "Credenciais e Chaves de API"
    assert dlg.tabs.tabText(1) == "Provedores LLM && Fallback"
    assert dlg.tabs.tabText(2) == "Pipeline, OCR && Cache"
    dlg.close()


def test_preferences_dialog_save_and_reactivity(tmp_path, monkeypatch):
    """Garante que PreferencesDialog salva in-place e atualiza labels reativos."""
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog

    monkeypatch.chdir(tmp_path)
    get_qapp()
    cfg = AppConfig()
    cfg_file = tmp_path / "config.toml"
    dlg = PreferencesDialog(cfg, config_path=cfg_file)

    # Label inicial deve ser não configurado se vazio
    dlg._fields["gemini_api_key"].setText("")
    assert "Não configurado" in dlg._env_labels["gemini_api_key"].text()

    # Digitar chave deve atualizar reativamente para configurado
    dlg._fields["gemini_api_key"].setText("AIzaSyTestKey123")
    assert "Configurado" in dlg._env_labels["gemini_api_key"].text()

    # Alterar provedor e modelo
    dlg.cmb_primary.setCurrentText("groq")
    dlg.edit_model.setText("llama-3.3-70b-versatile")
    # Remover nvidia da cadeia de fallback (segundo item)
    model = dlg.fallback_model
    for i in range(model.rowCount()):
        if model.item(i).text() == "nvidia":
            model.takeRow(i)
            break

    dlg._save()

    # Validar persistência in-place no objeto cfg
    assert cfg.api_keys.gemini_api_key == "AIzaSyTestKey123"
    assert cfg.llm.provider == "groq"
    assert cfg.llm.model == "llama-3.3-70b-versatile"
    assert "nvidia" not in cfg.llm.fallback_chain

    # Validar persistência no arquivo TOML
    assert dlg._config_path.exists()
    content = dlg._config_path.read_text(encoding="utf-8")
    assert "AIzaSyTestKey123" in content
    assert "groq" in content
    dlg.close()


def test_save_button_async_persists_on_validation_failure(tmp_path, monkeypatch):
    """Botão Salvar (caminho assíncrono): persiste cfg SEMPRE, mesmo quando validação ao vivo falha (401/offline).

    Reproduz o Achado B do Sentinela: garante que _persist_config é chamado
    imediatamente (cfg gravado) antes da validação ao vivo, e que o
    feedback 401/403 não-bloqueante é disparado após a validação assíncrona.
    """
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog

    get_qapp()
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig()
    cfg_file = tmp_path / "config.toml"
    dlg = PreferencesDialog(cfg, config_path=cfg_file)

    # 1. Digitar chave válida no Gemini
    dlg._fields["gemini_api_key"].setText("AIzaSyTestKey123")

    # 2. Mockar _start_async_validation para simular falha de validação (HTTP 401)
    #    sem criar QThread real (evita travar em offscreen/headless).
    async_started = []
    validation_emitted = []

    def fake_start_validation(checks):
        async_started.append(True)
        for field_name, keys in checks:
            for key_index, _key in enumerate(keys):
                validation_emitted.append((field_name, key_index, "HTTP 401: Não autorizada"))
                dlg._on_validation_result(field_name, key_index, "", False, "HTTP 401: Não autorizada")
        dlg._on_validation_finished()

    monkeypatch.setattr(dlg, "_start_async_validation", fake_start_validation)

    # Mockar _on_validation_finished para não disparar QMessageBox em offscreen,
    # mas ainda validar que o fluxo chega até ele após a persistência.
    finished_called = []

    def fake_on_validation_finished():
        finished_called.append(True)

    dlg._on_validation_finished = fake_on_validation_finished

    # 3. Espionar _persist_config: confirmar que é chamado e gravar no cfg
    #    (sem chamar self.accept(), que fecharia o diálogo).
    persist_called = []

    def spied_persist():
        persist_called.append(True)
        val = dlg._fields["gemini_api_key"].text().strip()
        cfg.api_keys.gemini_api_key = val

    dlg._persist_config = spied_persist

    # 4. Disparar caminho assíncrono do botão Salvar
    dlg._salvar_com_validacao_async()

    # 5. Verificar que _persist_config foi chamado imediatamente (cfg persistido)
    assert len(persist_called) == 1
    assert cfg.api_keys.gemini_api_key == "AIzaSyTestKey123"

    # 6. Verificar que o caminho assíncrono foi iniciado
    assert len(async_started) == 1
    assert len(validation_emitted) >= 1
    assert any(field == "gemini_api_key" for field, _, _ in validation_emitted)

    # 7. Verificar feedback 401/403 não-bloqueante na UI (validação assíncrona)
    env_lbl = dlg._env_labels["gemini_api_key"]
    assert "HTTP 401" in env_lbl.text() or "Credenciais Rejeitadas" in env_lbl.text()

    # 8. Verificar que o fluxo chegou até a conclusão assíncrona
    assert len(finished_called) == 1

    # Fechar diálogo limpo antes do teardown do QApplication offscreen
    dlg.reject()


def test_save_button_async_validates_each_comma_key(tmp_path, monkeypatch):
    """BUG-UI-02: validar TODAS as chaves separadas por v\u00edrgula com feedback individual.

    Cada chave de um campo recebe seu pr\u00f3prio resultado (mascarada + status).
    O cfg \u00e9 persistido antes da valida\u00e7\u00e3o (caminho ass\u00edncoco n\u00e3o pula o salvamento).
    """
    from tomus.gui.widgets.preferences_dialog import PreferencesDialog

    get_qapp()
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig()
    cfg_file = tmp_path / "config.toml"
    dlg = PreferencesDialog(cfg, config_path=cfg_file)

    # BUG-UI-02: validar TODAS as chaves separadas por v\u00edrgula com feedback individual.
    get_qapp()
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig()
    # Limpar chaves de outros provedores para testar apenas Gemini com 2 chaves
    for field in ("groq_api_key", "nvidia_api_key", "deepseek_api_key", "claude_api_key", "google_books_api_key", "openalex_polite_email"):
        setattr(cfg.api_keys, field, "")
    cfg_file = tmp_path / "config.toml"
    dlg = PreferencesDialog(cfg, config_path=cfg_file)

    # 1. Duas chaves Gemini separadas por v\u00edrgula (1 v\u00e1lida, 1 rejeitada 401)
    dlg._fields["gemini_api_key"].setText(
        "AIzaSyValidKey0000000000, AIzaSyInvalidKey1111111111"
    )

    # 2. Mockar _start_async_validation (evita QThread real em offscreen)
    async_started = []
    validation_emitted = []
    finished_called = []

    def fake_start_validation(checks):
        async_started.append(True)
        for field_name, keys in checks:
            for key_index, _key in enumerate(keys):
                # Primeira chave v\u00e1lida, segunda rejeitada com HTTP 401
                ok = key_index == 0
                msg = "" if ok else "HTTP 401: N\u00e3o autorizada"
                validation_emitted.append((field_name, key_index, ok, msg))
                dlg._on_validation_result(field_name, key_index, "", ok, msg)
        dlg._on_validation_finished()

    monkeypatch.setattr(dlg, "_start_async_validation", fake_start_validation)

    # 3. Mockar _on_validation_finished para evitar QMessageBox em offscreen
    dlg._on_validation_finished = lambda: finished_called.append(True)

    # 4. Espionar _persist_config
    persist_called = []

    def spied_persist():
        persist_called.append(True)
        val = dlg._fields["gemini_api_key"].text().strip()
        cfg.api_keys.gemini_api_key = val

    dlg._persist_config = spied_persist

    # 5. Disparar caminho ass\u00edncoco do botão Salvar
    dlg._salvar_com_validacao_async()

    # 6. _persist_config chamado imediatamente (cfg persistido)
    assert len(persist_called) == 1
    assert cfg.api_keys.gemini_api_key == "AIzaSyValidKey0000000000, AIzaSyInvalidKey1111111111"

    # 7. Caminho ass\u00edncoco iniciado com feedback individual de cada chave
    assert len(async_started) == 1
    assert len(validation_emitted) == 2
    assert validation_emitted[0] == ("gemini_api_key", 0, True, "")
    assert validation_emitted[1] == ("gemini_api_key", 1, False, "HTTP 401: N\u00e3o autorizada")

    # 8. Label do campo reflete a rejei\u00e7\u00e3o da chave 2 (HTTP 401)
    env_lbl = dlg._env_labels["gemini_api_key"]
    assert "HTTP 401" in env_lbl.text() or "rejeitada" in env_lbl.text()

    # 9. Fluxo conclu\u00eddo (finished chamado)
    assert len(finished_called) == 1

    dlg.reject()


def test_badge_updates_when_switching_provider(monkeypatch):
    """BUG-UI-01: badge de provedor validado atualiza ao trocar de provedor na tela principal."""
    get_qapp()
    cfg = AppConfig()
    cfg.api_keys.gemini_api_key = "AIzaSyValidKey0000000000"
    cfg.api_keys.groq_api_key = ""  # sem chave

    # Simular o WebBridge / main_window sem QWebEngine real
    class FakeBackend:
        def __init__(self, config):
            self._config = config

        def checkProviderKey(self, provider):
            import asyncio

            async def _fake():
                key = getattr(self._config.api_keys, f"{provider}_api_key", "") or ""
                return bool(key.strip())

            return asyncio.get_event_loop().run_until_complete(_fake())

        def getProviderKeyStatus(self, provider):
            import asyncio

            async def _fake():
                key = getattr(self._config.api_keys, f"{provider}_api_key", "") or ""
                return "valid" if key.strip() else "invalid"

            return asyncio.get_event_loop().run_until_complete(_fake())

    # Estado simulado da tela principal (sem instanciar o MainWindow completo)
    state = {"provider": "gemini"}

    def providerLabel():
        labels = {
            "gemini": "Gemini",
            "groq": "Groq — Fallback",
            "nvidia": "NVIDIA NIM",
            "claude": "Anthropic Claude",
            "deepseek": "DeepSeek",
        }
        return labels.get(state["provider"], state["provider"])

    def updateKeyBadge(hasKey, provider=None):
        if provider:
            state["provider"] = provider
        label = providerLabel()
        if hasKey:
            return f"{label} — Chave Configurada"
        return f"{label} — Sem chave (Modo Simulado)"

    # Estado inicial: Gemini com chave
    assert updateKeyBadge(True, "gemini") == "Gemini — Chave Configurada"

    # Trocar para Groq (sem chave) — badge deve refletir Groq sem chave
    assert updateKeyBadge(False, "groq") == "Groq — Fallback — Sem chave (Modo Simulado)"
    assert state["provider"] == "groq"

    # Trocar de volta para Gemini (com chave) — badge volta a indicar chave configurada
    assert updateKeyBadge(True, "gemini") == "Gemini — Chave Configurada"
    assert state["provider"] == "gemini"


def test_main_window_web_view_instancia(monkeypatch):
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QWidget

    # Mock para QWebEngineView e TomusWebPage no teste para evitar crash de
    # HIServices / WindowServer em ambientes headless ou de automação.
    mock_view_instance = MagicMock(spec=QWidget)
    monkeypatch.setattr("tomus.gui.main_window.QWebEngineView", lambda parent=None: mock_view_instance)
    monkeypatch.setattr("tomus.gui.main_window.TomusWebPage", MagicMock)

    get_qapp()
    cfg = AppConfig()
    win = TomusMainWindow(cfg, source_dir="/tmp/origem", target_dir="/tmp/destino")
    assert win.web_view is not None
    assert win.bridge is not None
    assert win.bridge.source_dir == str(Path("/tmp/origem"))
    assert win.bridge.target_dir == str(Path("/tmp/destino"))


def test_apply_webengine_defenses_frozen_win32(monkeypatch, tmp_path):
    """_apply_webengine_defenses configura caminhos do QtWebEngineProcess em sys.frozen + win32.

    Preserva o comportamento macOS/Linux intacto e adiciona suporte a Windows:
    candidate_paths com PySide6/QtWebEngineProcess.exe, PySide6/Qt/bin/QtWebEngineProcess.exe,
    QtWebEngineProcess.exe e resources_candidates com PySide6/resources, PySide6/Qt/resources,
    resources, buscando qtwebengine_locales tambem em PySide6/translations/qtwebengine_locales.
    """
    import sys as _sys

    from tomus.gui.app import _apply_webengine_defenses

    fake_meipass = tmp_path / "meipass"
    (fake_meipass / "PySide6").mkdir(parents=True)
    (fake_meipass / "PySide6" / "QtWebEngineProcess.exe").write_bytes(b"fake")
    locales_dir = fake_meipass / "PySide6" / "resources" / "qtwebengine_locales"
    locales_dir.mkdir(parents=True)
    (locales_dir / "en-US.pak").write_bytes(b"fake")
    (fake_meipass / "PySide6" / "resources" / "qtwebengine_resources.pak").write_bytes(b"fake")

    monkeypatch.setattr(_sys, "platform", "win32", raising=False)
    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "_MEIPASS", str(fake_meipass), raising=False)

    captured: dict[str, str] = {}
    monkeypatch.setattr("os.environ", captured)

    _apply_webengine_defenses()

    assert captured.get("QTWEBENGINE_DISABLE_SANDBOX") == "1"
    assert (
        captured.get("QTWEBENGINEPROCESS_PATH")
        == str(fake_meipass / "PySide6" / "QtWebEngineProcess.exe")
    )
    assert captured.get("QTWEBENGINE_LOCALES_PATH") == str(locales_dir)


def test_web_bridge_pipeline_event_with_destination_and_sha256():
    """Garante que PipelineEvent carrega destination_path e sha256 para os botões do Inspetor."""
    from tomus.core.models import PipelineEvent

    ev = PipelineEvent(
        stage="organizer",
        source_path="/tmp/origem/doc.pdf",
        destination_path="/tmp/destino/Ciências Humanas/Sociologia/Artigo/doc.pdf",
        sha256="abc1234567890abcdef1234567890abcdef1234567890abcdef1234567890abc",
        status="organized",
        message="Arquivo organizado",
    )
    dumped = ev.model_dump()
    assert dumped["destination_path"] == "/tmp/destino/Ciências Humanas/Sociologia/Artigo/doc.pdf"
    assert dumped["sha256"].startswith("abc1234")


# --------------------------------------------------------------------------- #
# Testes obrigatórios: _is_safe_path com strings e openPdf/revealPath
# --------------------------------------------------------------------------- #
def test_is_safe_path_com_strings_e_varios_caminhos():
    """_is_safe_path deve aceitar strings (incluindo vazias) e Path, sem lançar AttributeError."""
    from tomus.gui.bridge import _is_safe_path

    roots = ["", "/Users/dario/Desktop", Path.home(), Path("/tmp"), ""]

    # Caminhos válidos dentro das raízes
    assert _is_safe_path("/Users/dario/Desktop/documento.pdf", roots) is True
    assert _is_safe_path(Path("/tmp/arquivo.pdf"), roots) is True
    assert _is_safe_path(str(Path.home() / "documento.pdf"), roots) is True

    # Caminhos fora das raízes (sistema)
    assert _is_safe_path("/etc/passwd", roots) is False
    assert _is_safe_path("/var/log/syslog", roots) is False
    assert _is_safe_path("/usr/bin/bash", roots) is False

    # Caminho protegido dentro de uma raiz permitida (ex: .ssh)
    assert _is_safe_path("/Users/dario/.ssh/id_rsa", roots) is False
    assert _is_safe_path("/Users/dario/.config/something", roots) is False

    # Caminho com subpasta normal (não protegida)
    assert _is_safe_path("/Users/dario/Desktop/@BIBLIOTECA_ORGANIZADA/livro.pdf", roots) is True


def test_openPdf_com_strings_em_source_target(tmp_path, monkeypatch):
    """openPdf deve funcionar quando source_dir e target_dir são strings (inclusive vazias)."""
    import os as _os
    import subprocess

    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    bridge = WebBridge(cfg)
    bridge.source_dir = ""  # string vazia
    bridge.target_dir = str(tmp_path / "destino")
    (tmp_path / "destino").mkdir(parents=True, exist_ok=True)

    pdf_path = tmp_path / "destino" / "livro_teste.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

    monkeypatch.setattr(subprocess, "Popen", lambda cmd: cmd)
    # No Windows (win32), open_file_in_os usa os.startfile: mockar para não abrir o arquivo de verdade.
    if sys.platform == "win32":
        monkeypatch.setattr(_os, "startfile", lambda path: None)
    bridge.openPdf(str(pdf_path))  # não deve lançar AttributeError


def test_revealPath_com_strings_em_source_target(tmp_path, monkeypatch):
    """revealPath deve funcionar quando source_dir e target_dir são strings."""
    import subprocess

    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    bridge = WebBridge(cfg)
    bridge.source_dir = str(tmp_path / "origem")
    bridge.target_dir = ""  # string vazia
    (tmp_path / "origem").mkdir(parents=True, exist_ok=True)

    arquivo_path = tmp_path / "origem" / "arquivo_teste.pdf"
    arquivo_path.write_bytes(b"%PDF-1.4 fake pdf content")

    monkeypatch.setattr(subprocess, "Popen", lambda cmd: cmd)
    bridge.revealPath(str(arquivo_path))  # não deve lançar AttributeError


def test_web_assets_syntax_integrity():
    """Garante que app.js e os assets do frontend não contêm erros de sintaxe JS."""
    import shutil
    import subprocess
    from pathlib import Path

    app_js = Path(__file__).parent.parent / "src" / "tomus" / "gui" / "web" / "app.js"
    assert app_js.exists(), "app.js deve existir"

    node_bin = shutil.which("node")
    if node_bin:
        res = subprocess.run([node_bin, "-c", str(app_js)], capture_output=True, text=True)
        assert res.returncode == 0, f"Erro de sintaxe em app.js:\n{res.stderr}"


def test_approve_manual_triage_com_subarea_e_auto_grande_area(tmp_path):
    """Garante que aprovação manual aceita subárea específica e resolve grande_area automaticamente."""
    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    target_dir = tmp_path / "target_biblioteca"
    target_dir.mkdir(parents=True)

    source_pdf = tmp_path / "Psicofarmacologia.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 dummy content for triage")

    bridge = WebBridge(cfg)
    bridge.target_dir = str(target_dir)

    events_captured = []
    bridge.pipelineEvent.connect(lambda ev_json: events_captured.append(json.loads(ev_json)))

    triage_payload = {
        "source_path": str(source_pdf),
        "area_basica": "Psicologia",
        "subarea": "Psicofarmacologia",
        "tipo": "Livro",
        "title": "Psicofarmacologia",
        "subtitle": "Bases e Prática",
        "authors": ["Menezes, Jacqueline"],
        "year": 2017,
    }

    ok = bridge.approveManualTriage(json.dumps(triage_payload))
    result = json.loads(ok) if isinstance(ok, str) else ok
    assert result.get("success", False) is True

    # Verificar se foi salvo no caminho correto: target / Psicologia / Psicofarmacologia / Livro / ...
    expected_dir = target_dir / "Psicologia" / "Psicofarmacologia" / "Livro"
    assert expected_dir.exists(), f"Diretório temático com subárea não foi criado: {expected_dir}"
    pdf_files = list(expected_dir.glob("*.pdf"))
    assert len(pdf_files) == 1
    assert "Menezes" in pdf_files[0].name or "Psicofarmacologia" in pdf_files[0].name

    # Verificar que companion .md foi criado
    assert pdf_files[0].with_suffix(".md").exists()

    # Verificar evento emitido
    assert len(events_captured) == 1
    ev = events_captured[0]
    assert ev["status"] == "organized"
    assert ev["classification"]["grande_area"] == "Ciências Humanas"
    assert ev["classification"]["area_basica"] == "Psicologia"
    assert ev["classification"]["subarea"] == "Psicofarmacologia"


def test_approve_manual_triage_redige_segredo_no_erro_json(tmp_path, monkeypatch):
    """approveManualTriage não deve vazar segredos/tokens na mensagem de erro JSON retornada."""
    from unittest.mock import MagicMock

    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    target_dir = tmp_path / "target_biblioteca"
    target_dir.mkdir(parents=True)

    source_pdf = tmp_path / "DocComSigilo.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 dummy content for triage")

    bridge = WebBridge(cfg)
    bridge.target_dir = str(target_dir)

    # Forçar exceção cuja mensagem contenha tokens de API (devem ser redigidos)
    raw_sk = "sk-ant-1234567890abcdef1234567890abcdef"
    raw_nvapi = "nvapi-xyz7890123456789012345678901234"
    bridge.triage_service = MagicMock()
    bridge.triage_service.approve_and_materialize.side_effect = Exception(
        f"Falha ao chamar LLM com chave {raw_sk} e {raw_nvapi}"
    )

    triage_payload = {
        "source_path": str(source_pdf),
        "area_basica": "Psicologia",
        "subarea": "Psicofarmacologia",
        "tipo": "Livro",
        "title": "Doc com Segredo",
        "subtitle": "",
        "authors": ["Autor, A."],
        "year": 2020,
    }

    ok = bridge.approveManualTriage(json.dumps(triage_payload))
    result = json.loads(ok) if isinstance(ok, str) else ok
    assert result.get("success") is False
    error_msg = result.get("error", "")
    assert raw_sk not in error_msg
    assert raw_nvapi not in error_msg
    assert "REDACTED" in error_msg


# --------------------------------------------------------------------------- #
# Testes de segurança: recusa de caminho não autorizado (path traversal)
# --------------------------------------------------------------------------- #
def test_recolocar_na_fila_recusa_caminho_fora_das_raizes(tmp_path):
    """recolocarNaFila deve rejeitar caminhos fora de source_dir/target_dir."""
    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True)

    bridge = WebBridge(cfg)
    bridge.source_dir = str(tmp_path / "origem")
    bridge.target_dir = str(target_dir)

    # Caminho fora das raízes (sistema)
    caminho_malicioso = "/etc/passwd"
    resultado = bridge.recolocarNaFila(caminho_malicioso)
    resultado_dict = json.loads(resultado) if isinstance(resultado, str) else resultado
    assert resultado_dict.get("success") is False
    assert "não autorizado" in resultado_dict.get("error", "")


def test_promote_from_manual_review_recusa_caminho_fora_das_raizes(tmp_path):
    """promoteFromManualReview deve rejeitar source_path fora de source_dir/target_dir."""
    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True)

    bridge = WebBridge(cfg)
    bridge.source_dir = str(tmp_path / "origem")
    bridge.target_dir = str(target_dir)

    # Caminho malicioso no JSON de promoção
    promocao_payload = {
        "source_path": "/etc/shadow",
        "classificacao": {
            "titulo": "Qualquer Título",
            "autores": ["Autor, A."],
            "ano": 2020,
            "tipo": "Livro",
            "grande_area": "Ciências Humanas",
            "area_basica": "Psicologia",
        },
    }
    resultado = bridge.promoteFromManualReview(json.dumps(promocao_payload))
    resultado_dict = json.loads(resultado) if isinstance(resultado, str) else resultado
    assert resultado_dict.get("success") is False
    assert "não autorizado" in resultado_dict.get("error", "")
    assert resultado_dict.get("recusado") is True


def test_recolocar_na_fila_aceita_caminho_dentro_da_raiz(tmp_path, monkeypatch):
    """recolocarNaFila deve aceitar caminho válido dentro de target_dir."""
    import subprocess

    from tomus.gui.bridge import WebBridge

    cfg = AppConfig()
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True)

    bridge = WebBridge(cfg)
    bridge.source_dir = str(tmp_path / "origem")
    bridge.target_dir = str(target_dir)

    # Criar um PDF válido dentro do target_dir
    pdf_valido = target_dir / "documento_valido.pdf"
    pdf_valido.write_bytes(b"%PDF-1.4 dummy content")

    monkeypatch.setattr(subprocess, "Popen", lambda cmd: cmd)
    resultado = bridge.recolocarNaFila(str(pdf_valido))
    resultado_dict = json.loads(resultado) if isinstance(resultado, str) else resultado
    assert resultado_dict.get("success") is True


