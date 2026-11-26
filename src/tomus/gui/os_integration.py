"""Abstração multiplataforma de integração com o sistema operacional.

Implementa a seção 5.4 (item 2) da especificação ``docs/designs/gui_spec.md``:
``os_integration.py`` encapsula todas as interações dependentes de sistema
operacional usando ``sys.platform`` e ``pathlib.Path``, sem jamais concatenar
strings com ``/`` manualmente.

Suporta macOS (``darwin``), Windows (``win32``) e Linux (``linux`` /
Wayland/X11 — GNOME/KDE).
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import c_int, c_uint, c_uint32, c_void_p
from pathlib import Path

_logger = logging.getLogger("tomus.gui.os_integration")

__all__ = [
    "open_file_in_os",
    "reveal_in_file_manager",
    "secure_chmod_600",
]


def _resolve(path: Path | str) -> Path:
    """Resolver o caminho para um Path absoluto, levantando se não existir."""
    p = Path(path)
    return p.resolve(strict=False)


def open_file_in_os(path: Path | str) -> None:
    """Abrir um arquivo (PDF / Markdown / etc.) no aplicativo padrão do SO.

    * macOS: ``subprocess.Popen(["open", str(path)])``
    * Windows: ``os.startfile(str(path))``
    * Linux: ``subprocess.Popen(["xdg-open", str(path)])``

    :param path: caminho do arquivo a abrir.
    :raises FileNotFoundError: se o caminho não existir no disco.
    :raises OSError: se o comando do SO não estiver disponível.
    """
    p = _resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    elif sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(p)])


def _reveal_windows_shell(path: Path) -> bool:
    """Revelar (selecionar) arquivo no Explorer do Windows via Shell API nativa.

    Usa ``ole32.CoInitializeEx`` + ``shell32.ILCreateFromPathW`` (``restype=c_void_p``,
    tratando corretamente 64-bit) + ``shell32.SHOpenFolderAndSelectItems`` +
    ``shell32.ILFree`` (no ``finally``). Retorna ``True`` se a API da Shell foi
    invocada com sucesso, ``False`` em qualquer falha (caminho inválido, erro de
    COM, exceção inesperada, etc.).

    Essa abordagem evita o problema de ``explorer /select,<caminho>``, que gera
    aspas em torno de ``/select,`` junto com o caminho quando há espaços, fazendo
    o Explorer abrir a pasta padrão sem selecionar o arquivo.
    """
    _ole32 = ctypes.windll.ole32
    _shell32 = ctypes.windll.shell32

    _shell32.ILCreateFromPathW.restype = c_void_p
    _shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
    _shell32.ILFree.argtypes = [c_void_p]
    _shell32.SHOpenFolderAndSelectItems.restype = c_int  # HRESULT
    _shell32.SHOpenFolderAndSelectItems.argtypes = [c_void_p, c_uint, c_void_p, c_uint32]
    _ole32.CoInitializeEx.argtypes = [c_void_p, c_uint32]
    _ole32.CoInitializeEx.restype = c_int
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None

    pidl: c_void_p | None = None
    hr_co: int | None = None
    try:
        hr_co = _ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED = 0x2
        pidl = _shell32.ILCreateFromPathW(str(path))
        if not pidl:
            return False
        hr = _shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        return hr == 0  # S_OK
    except Exception:
        return False
    finally:
        if pidl:
            try:
                _shell32.ILFree(pidl)
            except Exception:
                _logger.warning("Falha ao liberar PIDL do Shell (ILFree)", exc_info=True)
        # CoUninitialize apenas se CoInitializeEx obteve S_OK (0) ou S_FALSE (1).
        # Nunca se retornar RPC_E_CHANGED_MODE (0x80010106): o Qt GUI thread pode
        # já ter COM inicializado e decrementar o refcount do Qt corromperia o COM.
        if hr_co in (0, 1):
            try:
                _ole32.CoUninitialize()
            except Exception:
                _logger.warning("Falha ao desinicializar COM (CoUninitialize)", exc_info=True)


def reveal_in_file_manager(path: Path | str) -> None:
    """Revelar (selecionar) um arquivo na pasta do gerenciador de arquivos.

    * macOS: ``subprocess.Popen(["open", "-R", str(path)])``
    * Windows: tenta a Shell API nativa (``_reveal_windows_shell``); em caso de
      falha, usa fallback ``explorer /select, <caminho>`` com ``/select,``
      separado do caminho (evita o problema de aspas em caminhos com espaços).
    * Linux: ``subprocess.Popen(["xdg-open", str(path.parent)])``

    :param path: caminho do arquivo a revelar.
    :raises FileNotFoundError: se o caminho não existir no disco.
    :raises OSError: se o comando do SO não estiver disponível.
    """
    p = _resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    elif sys.platform == "win32":
        # Shell API nativa primeiro (lida corretamente com espaços no caminho).
        if _reveal_windows_shell(p):
            return
        # Fallback: /select, separado do caminho, não colado nele.
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        # xdg-open abre o diretório pai quando o alvo não é um diretório.
        subprocess.Popen(["xdg-open", str(p.parent)])


def secure_chmod_600(path: Path | str) -> None:
    """Aplicar permissão restrita ``0600`` (apenas o dono lê/escreve).

    Usado para o arquivo de configuração ``config.toml`` (``CONFIG_FILE_MODE``
    do :mod:`tomus.core.config`). Em sistemas POSIX (macOS/Linux) aplica
    ``os.chmod(path, 0o600)``; no Windows a operação é ignorada com segurança
    via ``try/except OSError``, pois ACLs POSIX não se aplicam.

    :param path: caminho do arquivo a proteger.
    """
    if sys.platform == "win32":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Permissão não aplicável (sistema de arquivos sem suporte a ACL POSIX
        # ou usuário sem privilégios): ignorar com segurança.
        pass
