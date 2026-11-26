"""Aplicação de permissões restritas de arquivo (multiplataforma).

Fornece uma única função de aplicação de permissão 0600-equivalente que
funciona em POSIX (``os.chmod``) e Windows NTFS (``icacls`` via
``subprocess``), garantindo que apenas o usuário corrente tenha
leitura/escrita no arquivo, sem falhas silenciosas.

Este módulo centraliza a lógica antes duplicada em
``src/tomus/core/config.py`` e ``src/tomus/core/cache.py``, que usavam
uma implementação Win32 via ctypes quebrada (tipo ``LPTSTR`` inexistente
no Python 3.12, ``SetEntriesInAclW`` invertido, flag 1 em
``SetFileSecurityW`` e ``except Exception: pass`` engolindo erros).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from subprocess import CalledProcessError

_logger = logging.getLogger(__name__)


def _get_current_user_sid() -> str | None:
    """Obter o SID do usuário corrente no Windows.

    Usa ``whoami /user``, que funciona independentemente do idioma do
    Windows, e retorna o SID no formato ``S-1-5-...``. Retorna
    ``None`` se não for possível obtê-lo.
    """
    try:
        resultado = subprocess.run(
            ["whoami", "/user"],
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        # Saída esperada: "NOME_USUARIO    SID"
        # Ex.: "TOMUS\Dario    S-1-5-21-..."
        for linha in resultado.stdout.splitlines():
            linha = linha.strip()
            if linha and "S-1-" in linha:
                partes = linha.split()
                # O SID é o último token da linha.
                return partes[-1]
    except (CalledProcessError, FileNotFoundError, OSError) as exc:
        _logger.warning("Falha ao obter SID via whoami /user: %s", exc)
    return None


def set_restrictive_file_permissions(path: Path) -> bool:
    """Aplicar permissão restrita equivalente a chmod 0600 POSIX.

    Em POSIX (Linux/macOS) usa ``os.chmod(0o600)`` para permitir
    leitura/escrita apenas ao dono.

    No Windows (NTFS) usa ``icacls`` via ``subprocess`` para remover a
    herança de ACL do pai e conceder acesso total apenas ao SID do
    usuário corrente (``*<SID>:F``), equivalente ao chmod 0600 POSIX.
    Funciona independentemente do idioma do Windows porque obtém o SID
    via ``whoami /user``.

    Retorna ``True`` quando a permissão foi aplicada com sucesso,
    ``False`` caso contrário. Nenhuma falha é silenciosa: avisos são
    logados com o caminho e o motivo.
    """
    try:
        if sys.platform == "win32":
            return _set_windows_restrictive_acl(path)
        os.chmod(path, 0o600)
        return True
    except OSError as exc:
        _logger.warning(
            "Não foi possível aplicar permissão restrita 0600 em %s: %s",
            path,
            exc,
        )
        return False


def _set_windows_restrictive_acl(path: Path) -> bool:
    """Definir ACL restritiva no Windows via icacls.

    Aplica, em uma única chamada atômica, a remoção da herança de ACL
    do pai (``/inheritance:r``) e a substituição de quaisquer permissões
    explícitas residuais pela concessão de acesso total apenas ao SID
    do usuário corrente (``*<SID>:F``), equivalente ao chmod 0600 POSIX
    em sistemas de arquivos NTFS.

    Retorna ``True`` quando a ACL foi aplicada com sucesso,
    ``False`` caso contrário. Nenhuma falha é silenciosa: avisos são
    logados com o caminho e o motivo.
    """
    sid = _get_current_user_sid()
    if not sid:
        _logger.warning(
            "Não foi possível obter o SID do usuário corrente em %s; "
            "ACL restritiva não pôde ser aplicada.",
            path,
        )
        return False

    caminho = str(path)
    try:
        # Chamada atômica: remove herança do pai E substitui permissões
        # explícitas residuais, concedendo acesso total apenas ao usuário
        # corrente. Não deixa o arquivo momentaneamente sem ACE.
        subprocess.run(
            [
                "icacls",
                caminho,
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:F",
            ],
            check=True,
            shell=False,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        _logger.warning(
            "Não foi possível aplicar ACL restritiva no Windows em %s: %s",
            caminho,
            exc.stderr or str(exc),
        )
        return False
    except (FileNotFoundError, OSError) as exc:
        _logger.warning(
            "Não foi possível aplicar ACL restritiva no Windows em %s: %s",
            caminho,
            exc,
        )
        return False
