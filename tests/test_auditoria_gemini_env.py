"""Testes de regressão — precedência de variáveis de ambiente Gemini (Fase 3).

Cobre a validação da ordem canônica:
    TOMUS_GEMINI_API_KEY > BIBLIOTEC_GEMINI_API_KEY > GEMINI_API_KEY

O helper resolve_gemini_api_key em src/tomus/core/config.py deve retornar o
valor da primeira variável definida nessa ordem.
"""

from __future__ import annotations

from tomus.core.config import GEMINI_ENV_KEYS, resolve_gemini_api_key


# --------------------------------------------------------------------------- #
# Precedência de variáveis de ambiente Gemini
# --------------------------------------------------------------------------- #
def test_gemini_env_keys_ordem_canonica():
    """A constante GEMINI_ENV_KEYS deve ter a ordem canônica."""
    assert GEMINI_ENV_KEYS == (
        "TOMUS_GEMINI_API_KEY",
        "BIBLIOTEC_GEMINI_API_KEY",
        "GEMINI_API_KEY",
    )


def test_resolve_gemini_api_key_precedencia_tomus_vence_bibliotec(monkeypatch):
    """TOMUS_GEMINI_API_KEY prevalece sobre BIBLIOTEC_GEMINI_API_KEY."""
    monkeypatch.setenv("TOMUS_GEMINI_API_KEY", "chave_tomus")
    monkeypatch.setenv("BIBLIOTEC_GEMINI_API_KEY", "chave_bibliotec")
    monkeypatch.setenv("GEMINI_API_KEY", "chave_gemini")

    assert resolve_gemini_api_key() == "chave_tomus"


def test_resolve_gemini_api_key_precedencia_bibliotec_vence_gemini(monkeypatch):
    """BIBLIOTEC_GEMINI_API_KEY prevalece sobre GEMINI_API_KEY."""
    monkeypatch.delenv("TOMUS_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BIBLIOTEC_GEMINI_API_KEY", "chave_bibliotec")
    monkeypatch.setenv("GEMINI_API_KEY", "chave_gemini")

    assert resolve_gemini_api_key() == "chave_bibliotec"


def test_resolve_gemini_api_key_apenas_gemini(monkeypatch):
    """Apenas GEMINI_API_KEY definida."""
    monkeypatch.delenv("TOMUS_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("BIBLIOTEC_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "chave_gemini")

    assert resolve_gemini_api_key() == "chave_gemini"


def test_resolve_gemini_api_key_nenhuma_definida(monkeypatch):
    """Nenhuma variável definida -> retorna string vazia."""
    monkeypatch.delenv("TOMUS_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("BIBLIOTEC_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert resolve_gemini_api_key() == ""


def test_resolve_gemini_api_key_valor_vazio_nao_vence(monkeypatch):
    """Variável definida como vazia não vence; próxima na ordem é usada."""
    monkeypatch.setenv("TOMUS_GEMINI_API_KEY", "")
    monkeypatch.setenv("BIBLIOTEC_GEMINI_API_KEY", "chave_bibliotec")
    monkeypatch.setenv("GEMINI_API_KEY", "chave_gemini")

    assert resolve_gemini_api_key() == "chave_bibliotec"


def test_resolve_gemini_api_key_espacos_brancos_sao_ignorados(monkeypatch):
    """Espaços em branco na variável são removidos."""
    monkeypatch.setenv("TOMUS_GEMINI_API_KEY", "  chave_tomus  ")
    monkeypatch.delenv("BIBLIOTEC_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert resolve_gemini_api_key() == "chave_tomus"


def test_git_grep_bibliotec_gemini_apenas_config():
    """git grep BIBLIOTEC_GEMINI_API_KEY deve apontar apenas para config.py."""
    import subprocess

    resultado = subprocess.run(
        ["git", "grep", "-n", "BIBLIOTEC_GEMINI_API_KEY", "src/"],
        capture_output=True,
        text=True,
        check=False,
    )
    saida = resultado.stdout
    # Todas as linhas devem conter src/tomus/core/config.py
    for linha in saida.splitlines():
        if linha.strip():
            assert "src/tomus/core/config.py" in linha, (
                f"BIBLIOTEC_GEMINI_API_KEY encontrada fora de config.py: {linha}"
            )
