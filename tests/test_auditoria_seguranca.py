"""Testes de regressão de segurança (AppSec) — release 1.4.1.

Cobre os achados críticos/altos da seção SENTINELA da auditoria 2026-11-24:

- SEN-03 (alta): precedência de fontes de configuração ENV > TOML local > TOML global.
- SEN-04 (alta): nenhuma falha silenciosa na aplicação de ACL/permissão 0600.
- SEN-05 (alta): containment de source_dir/target_dir em startOrganize (bridge).
- SEN-06 (alta): remoção de Path.home() como raiz permitida em revealPath/openPdf.
- FORJA-01 (lado config, alta): tupla canônica de variáveis de ambiente do Gemini.

Não reescreve testes existentes; arquivo próprio do escopo SENTINELA.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tomus.core.config import _ENV_KEY_MAP, AppConfig
from tomus.core.file_security import set_restrictive_file_permissions
from tomus.gui.bridge import _USER_SAFE_DIRS, WebBridge, _is_safe_path

# --------------------------------------------------------------------------- #
# SEN-03 — Precedência ENV > TOML local > TOML global
# --------------------------------------------------------------------------- #

def test_sen03_env_prevalece_sobre_toml_local(tmp_path, monkeypatch):
    """ENV deve prevalecer sobre ./tomus.toml (SEN-03)."""
    toml_local = tmp_path / "tomus.toml"
    toml_local.write_text(
        '[api_keys]\ngemini_api_key = "CHAVE_DO_TOML_LOCAL"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TOMUS_GEMINI_API_KEY", "CHAVE_DA_ENV")
    monkeypatch.chdir(tmp_path)

    cfg = AppConfig()
    assert cfg.api_keys.gemini_api_key == "CHAVE_DA_ENV", (
        "SEN-03: a variável de ambiente deve prevalecer sobre o TOML local"
    )


def test_sen03_toml_local_prevalece_sobre_toml_global(tmp_path, monkeypatch):
    """TOML local deve prevalecer sobre TOML global (SEN-03)."""
    toml_local = tmp_path / "tomus.toml"
    toml_local.write_text(
        '[api_keys]\ngemini_api_key = "CHAVE_DO_TOML_LOCAL"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOMUS_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("BIBLIOTEC_GEMINI_API_KEY", raising=False)

    cfg = AppConfig()
    assert cfg.api_keys.gemini_api_key == "CHAVE_DO_TOML_LOCAL", (
        "SEN-03: o TOML local deve ser usado quando não há env var"
    )


# --------------------------------------------------------------------------- #
# SEN-04 — Nenhuma falha silenciosa na ACL do Windows
# --------------------------------------------------------------------------- #

def test_sen04_win32_acl_falha_nao_eh_silenciosa(caplog):
    """Falha ao aplicar ACL no Windows deve logar aviso e retornar False (SEN-04).

    Simula falha nas chamadas do icacls e confirma que o log registra o
    motivo e o caminho, e que a função retorna False (não silenciosa).
    """
    fake_path = Path("C:/Users/qualquer/config.toml")

    def falso_run(cmd, **kwargs):
        if "whoami" in cmd:
            class _Resultado:
                stdout = "usuario    S-1-5-21-1234567890-1234567890-1234567890-500\n"
            return _Resultado()
        raise subprocess.CalledProcessError(
            1, cmd, output="", stderr="Acesso negado."
        )

    with (
        patch("sys.platform", "win32"),
        patch(
            "tomus.core.file_security.subprocess.run",
            side_effect=falso_run,
        ),
        caplog.at_level(logging.WARNING, logger="tomus.core.file_security"),
    ):
        resultado = set_restrictive_file_permissions(fake_path)

    assert resultado is False, "SEN-04: deve retornar False em falha"
    assert "Não foi possível aplicar ACL restritiva no Windows" in caplog.text
    assert str(fake_path) in caplog.text


def test_sen04_set_restrictive_file_permissions_retorna_bool(tmp_path, caplog):
    """set_restrictive_file_permissions deve retornar bool e logar falha (SEN-04)."""
    alvo = tmp_path / "config.toml"
    alvo.write_text("# teste\n", encoding="utf-8")

    def falso_run(cmd, **kwargs):
        if "whoami" in cmd:
            class _Resultado:
                stdout = "usuario    S-1-5-21-1234567890-1234567890-1234567890-500\n"
            return _Resultado()
        raise subprocess.CalledProcessError(
            1, cmd, output="", stderr="Acesso negado."
        )

    with (
        patch("sys.platform", "win32"),
        patch(
            "tomus.core.file_security.subprocess.run",
            side_effect=falso_run,
        ),
        caplog.at_level(logging.WARNING, logger="tomus.core.file_security"),
    ):
        ok = set_restrictive_file_permissions(alvo)

    assert ok is False
    assert "Não foi possível aplicar ACL restritiva no Windows" in caplog.text


# --------------------------------------------------------------------------- #
# SEN-05 — Containment de source_dir/target_dir em startOrganize
# --------------------------------------------------------------------------- #

def _bridge_sem_parent() -> WebBridge:
    cfg = AppConfig()
    return WebBridge(cfg, parent_widget=None)


def test_sen05_startorganize_rejeita_origem_fora_das_raizes(tmp_path):
    """startOrganize deve rejeitar source_dir fora das raízes autorizadas (SEN-05)."""
    bridge = _bridge_sem_parent()
    origem_maliciosa = tmp_path / "origem"
    origem_maliciosa.mkdir()
    destino_seguro = tmp_path / "destino"
    destino_seguro.mkdir()

    params = {
        "source_dir": str(origem_maliciosa),
        "target_dir": str(destino_seguro),
        "provider": "gemini",
        "file_operation": "copy",
        "recursive": True,
        "dry_run": False,
    }

    with pytest.raises(ValueError, match="fora das raízes autorizadas"):
        bridge.startOrganize(json.dumps(params))


def test_sen05_startorganize_rejeita_destino_fora_das_raizes(tmp_path):
    """startOrganize deve rejeitar target_dir fora das raízes autorizadas (SEN-05)."""
    bridge = _bridge_sem_parent()
    origem_segura = tmp_path / "origem"
    origem_segura.mkdir()
    destino_malicioso = Path.home() / ".ssh"

    params = {
        "source_dir": str(origem_segura),
        "target_dir": str(destino_malicioso),
        "provider": "gemini",
        "file_operation": "copy",
        "recursive": True,
        "dry_run": False,
    }

    with pytest.raises(ValueError, match="fora das raízes autorizadas"):
        bridge.startOrganize(json.dumps(params))


def test_sen05_startorganize_aceita_caminhos_dentro_das_raizes(tmp_path):
    """startOrganize deve aceitar caminhos dentro de _USER_SAFE_DIRS (SEN-05).

    Mocka PipelineWorker para evitar iniciar threads reais do Qt (SIGABRT
    sem display/event loop).
    """
    bridge = _bridge_sem_parent()
    origem = tmp_path / "origem"
    origem.mkdir()
    destino = tmp_path / "destino"
    destino.mkdir()
    bridge.source_dir = str(origem)
    bridge.target_dir = str(destino)

    params = {
        "source_dir": str(origem),
        "target_dir": str(destino),
        "provider": "gemini",
        "file_operation": "copy",
        "recursive": True,
        "dry_run": True,
    }

    worker_mock = Mock()
    worker_mock.isRunning.return_value = False
    with patch("tomus.gui.bridge.PipelineWorker", return_value=worker_mock):
        try:
            bridge.startOrganize(json.dumps(params))
        except ValueError as exc:
            if "fora das raízes autorizadas" in str(exc):
                pytest.fail(
                    f"SEN-05: caminhos dentro das raízes não devem ser rejeitados: {exc}"
                )
            raise

    # Se chegou aqui, o containment não rejeitou os caminhos válidos.
    assert True


# --------------------------------------------------------------------------- #
# SEN-06 — remoção de Path.home() como raiz permitida
# --------------------------------------------------------------------------- #

def test_sen06_revealpath_nao_aceita_home_como_raiz(tmp_path):
    """revealPath não deve tratar Path.home() como raiz permitida (SEN-06).

    Um caminho dentro de Path.home() mas fora de _USER_SAFE_DIRS e das
    pastas do usuário deve ser rejeitado por _is_safe_path.
    """
    bridge = _bridge_sem_parent()
    bridge.source_dir = str(tmp_path / "origem")
    bridge.target_dir = str(tmp_path / "destino")

    caminho_ssh = Path.home() / ".ssh" / "id_rsa"

    roots = [
        Path(d) for d in (bridge.source_dir, bridge.target_dir) if d and str(d).strip()
    ] + list(_USER_SAFE_DIRS)
    assert _is_safe_path(caminho_ssh, roots) is False, (
        "SEN-06: ~/.ssh não deve ser acessível quando Path.home() não é raiz"
    )


def test_sen06_openpdf_nao_abre_fora_das_raizes(tmp_path):
    """openPdf não deve abrir arquivos fora das raízes autorizadas (SEN-06)."""
    bridge = _bridge_sem_parent()
    bridge.source_dir = str(tmp_path / "origem")
    bridge.target_dir = str(tmp_path / "destino")

    alvo = Path.home() / ".config" / "tomus" / "config.toml"

    chamado = []

    def falso_open_file_in_os(p):
        chamado.append(p)

    with patch("tomus.gui.bridge.open_file_in_os", falso_open_file_in_os):
        bridge.openPdf(str(alvo))

    assert chamado == [], (
        "SEN-06: openPdf não deve chamar open_file_in_os para caminhos fora das raízes"
    )


# --------------------------------------------------------------------------- #
# SEN-06 (Windows) — raízes do sistema e UNC bloqueadas
# --------------------------------------------------------------------------- #

def _windows_roots() -> list[str]:
    """Raízes permitidas simulando pastas do usuário no Windows."""
    return [
        r"C:\Users\Dario\Documents",
        r"C:\Users\Dario\Desktop",
        r"C:\Users\Dario\Downloads",
    ]


def test_sen06_windows_bloqueia_c_windows():
    """C:\\Windows deve ser bloqueado (raiz do sistema Windows)."""
    assert _is_safe_path(r"C:\Windows", _windows_roots()) is False


def test_sen06_windows_bloqueia_c_windows_subpasta():
    """C:\\Windows\\System32\\config\\SAM deve ser bloqueado (subpasta do sistema)."""
    assert (
        _is_safe_path(r"C:\Windows\System32\config\SAM", _windows_roots()) is False
    )


def test_sen06_windows_bloqueia_program_files():
    """C:\\Program Files\\Tomus\\app.exe deve ser bloqueado."""
    assert (
        _is_safe_path(r"C:\Program Files\Tomus\app.exe", _windows_roots()) is False
    )


def test_sen06_windows_bloqueia_program_files_x86():
    """C:\\Program Files (x86)\\qualquer deve ser bloqueado."""
    assert (
        _is_safe_path(
            r"C:\Program Files (x86)\qualquer\coisa.exe", _windows_roots()
        )
        is False
    )


def test_sen06_windows_bloqueia_program_data():
    """C:\\ProgramData\\malicious\\config deve ser bloqueado."""
    assert (
        _is_safe_path(r"C:\ProgramData\malicious\config", _windows_roots()) is False
    )


def test_sen06_windows_bloqueia_unc():
    """Caminhos UNC (\\\\servidor\\compartilhamento) devem ser sempre bloqueados."""
    assert (
        _is_safe_path(r"\\servidor\compartilhamento\arquivo.pdf", _windows_roots())
        is False
    )


def test_sen06_windows_bloqueia_unc_com_drive_vazio():
    """UNC com barra dupla no início deve ser bloqueado independentemente do drive."""
    assert _is_safe_path(r"\\outro_servidor\share\segredo.txt", _windows_roots()) is False


def test_sen06_windows_permite_pasta_usuario_com_espaco():
    """Pasta do usuário com espaço no nome deve ser permitida quando dentro da raiz."""
    assert (
        _is_safe_path(
            r"C:\Users\Dario\Documents\Minha Pasta com Espaço\livro.pdf",
            _windows_roots(),
        )
        is True
    )


def test_sen06_windows_permite_pasta_usuario_sem_espaco():
    """Pasta do usuário sem espaço deve ser permitida quando dentro da raiz."""
    assert (
        _is_safe_path(
            r"C:\Users\Dario\Documents\livro.pdf", _windows_roots()
        )
        is True
    )


def test_sen06_windows_rejeita_fora_das_raizes():
    """C:\\Temp\\arquivo.pdf (fora das raízes permitidas e não é raiz do sistema)
    deve ser rejeitado porque não está em nenhuma raiz permitida."""
    assert _is_safe_path(r"C:\Temp\arquivo.pdf", _windows_roots()) is False


def test_sen06_unix_ainda_funciona(tmp_path):
    """Caminhos Unix continuam funcionando (não regressão)."""
    origem = tmp_path / "origem"
    origem.mkdir()
    destino = tmp_path / "destino"
    destino.mkdir()

    roots = [
        Path(d) for d in (str(origem), str(destino)) if d and str(d).strip()
    ] + list(_USER_SAFE_DIRS)

    assert _is_safe_path(origem / "livro.pdf", roots) is True
    assert _is_safe_path(destino / "arquivo.pdf", roots) is True


# --------------------------------------------------------------------------- #
# FORJA-01 (lado config) — tupla canônica do Gemini
# --------------------------------------------------------------------------- #

def test_forja01_config_tupla_gemini_canonica():
    """Tupla de env do Gemini em config.py deve ser a canônica (FORJA-01 lado config).

    Ordem canônica: TOMUS_GEMINI_API_KEY, BIBLIOTEC_GEMINI_API_KEY (legado),
    GEMINI_API_KEY.
    """
    assert _ENV_KEY_MAP["gemini_api_key"] == (
        "TOMUS_GEMINI_API_KEY",
        "BIBLIOTEC_GEMINI_API_KEY",
        "GEMINI_API_KEY",
    ), "FORJA-01: tupla Gemini em config.py diverge da ordem canônica"
