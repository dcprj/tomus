"""Testes de seguranca da Fase 2 — endurecimento do WebBridge (bridge.py).

Cobre:
* Bloqueio de esquemas nao-HTTP(S) em openExternalUrl (file, smb, javascript, etc.).
* Escape seguro de payloads JS (_safe_js_json): escapamento de </, \\u2028, \\u2029.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from tomus.core.config import AppConfig
from tomus.gui.bridge import WebBridge

_QAPP = None


@pytest.fixture
def qapp():
    global _QAPP
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def test_openExternalUrl_bloqueia_esquemas_nao_http_https(qapp, monkeypatch):
    """openExternalUrl deve rejeitar esquemas nao-HTTP(S) sem abrir o navegador."""
    import tomus.gui.bridge as bridge_module

    cfg = AppConfig()
    bridge = WebBridge(cfg)

    chamados: list[str] = []

    def fake_open_url(url):
        chamados.append(str(url))

    monkeypatch.setattr(bridge_module.QDesktopServices, "openUrl", fake_open_url)
    mensagens_log: list[str] = []
    monkeypatch.setattr(
        bridge_module._logger,
        "warning",
        lambda msg, *args: mensagens_log.append(msg % args if args else msg),
    )

    urls_perigosas = [
        "file:///etc/passwd",
        "file:///caminho/local",
        "smb://servidor/compartilhamento",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://arquivos.example.com/x.bin",
        "about:blank",
        "chrome://settings",
        "qrc:///recurso",
    ]

    for url in urls_perigosas:
        bridge.openExternalUrl(url)

    assert chamados == [], f"QDesktopServices.openUrl nao deve ser chamado para: {chamados}"
    assert len(mensagens_log) == len(urls_perigosas), "Cada esquema perigoso deve ser logado"


def test_openExternalUrl_permite_http_https(qapp, monkeypatch):
    """openExternalUrl deve permitir esquemas http e https."""
    import tomus.gui.bridge as bridge_module

    cfg = AppConfig()
    bridge = WebBridge(cfg)

    chamados: list[str] = []

    def fake_open_url(url):
        if hasattr(url, "toString"):
            chamados.append(url.toString())
        else:
            chamados.append(str(url))

    monkeypatch.setattr(bridge_module.QDesktopServices, "openUrl", fake_open_url)

    for url in ["https://example.com", "http://localhost:8080", "HTTPS://EXEMPLO.COM"]:
        bridge.openExternalUrl(url)

    assert len(chamados) == 3
    for url in chamados:
        assert QUrl(url).scheme().lower() in ("http", "https")


def test_safe_js_json_escape_sequencias_proibidas():
    """_safe_js_json deve escapar </ para evitar quebra de contexto JS em script tags.

    \\u2028 e \\u2029 ja sao escapados nativamente pelo json.dumps; o helper
    garante que </ seja convertido para \\u003c/ e que o resultado seja JSON valido.
    """

    cfg = AppConfig()
    bridge = WebBridge(cfg)

    # Caso com </ dentro de string (tentativa de quebra de tag script)
    payload = {"mensagem": "fim </script><script>alert('xss')</script>"}
    resultado = bridge._safe_js_json(payload)
    assert "</script>" not in resultado
    assert "\\u003c/script>" in resultado

    # Caso com \\u2028 e \\u2029 (ja escapados pelo json.dumps, preservados pelo helper)
    payload2 = {"texto": "linha1\u2028linha2\u2029linha3"}
    resultado2 = bridge._safe_js_json(payload2)
    # O resultado deve ser JSON valido e conter os caracteres escapados
    dados2 = json.loads(resultado2)
    assert dados2["texto"] == "linha1\u2028linha2\u2029linha3"

    # Caso normal sem caracteres especiais
    payload3 = {"chave": "valor_normal", "numero": 42}
    resultado3 = bridge._safe_js_json(payload3)
    assert "valor_normal" in resultado3
    assert "42" in resultado3


def test_safe_js_json_e_uma_metodo_da_classe():
    """_safe_js_json deve ser metodo da classe WebBridge."""

    assert hasattr(WebBridge, "_safe_js_json")
    cfg = AppConfig()
    bridge = WebBridge(cfg)
    assert callable(bridge._safe_js_json)


def test_nao_existem_metodos_validate_mortos():
    """Os 5 metodos mortos _validate_* nao devem existir na classe WebBridge."""

    assert not hasattr(WebBridge, "_validate_gemini")
    assert not hasattr(WebBridge, "_validate_groq")
    assert not hasattr(WebBridge, "_validate_nvidia")
    assert not hasattr(WebBridge, "_validate_deepseek")
    assert not hasattr(WebBridge, "_validate_claude")


def test_key_validation_result_nao_eh_duplicado():
    """keyValidationResult deve ser declarada exatamente uma vez."""
    import inspect


    fontes = inspect.getsource(WebBridge)
    declaracoes = fontes.count("keyValidationResult = Signal(str)")
    assert declaracoes == 1, f"Esperava 1 declaracao, encontrou {declaracoes}"
