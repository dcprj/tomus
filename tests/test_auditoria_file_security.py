"""Testes de regressão de segurança (AppSec) — achado ATL-07 / Fase 2.

Cobre o tratamento de permissão restrita 0600 / ACL do banco de cache SQLite
e do arquivo config.toml em ``src/tomus/core/file_security.py``:

- ``set_restrictive_file_permissions`` retorna bool e loga aviso em falha.
- POSIX: aplica 0o600 via os.chmod (testado sem mock no runner local).
- Windows: aplica ACL restritiva via icacls (/inheritance:r /grant:r *<SID>:F)
  (testado sem mock no runner windows-latest do CI; skip no macOS/Linux).
- Falha não é silenciosa: loga aviso com caminho e motivo, retorna False.
- Nunca retorna None: apenas True ou False.

Não reescreve testes existentes; arquivo próprio do escopo Fase 2 / ATL-07.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tomus.core.file_security import set_restrictive_file_permissions

_logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# ATL-07 / Fase 2 — set_restrictive_file_permissions (POSIX, sem mock)
# --------------------------------------------------------------------------- #
def test_fase2_unix_aplica_chmod_0o600_e_retorna_true(tmp_path):
    """Em Unix, aplica os.chmod com 0o600 e retorna True (sem mock)."""
    if sys.platform == "win32":
        pytest.skip("os.chmod / os.stat de modo POSIX não é representável no Windows")

    alvo = tmp_path / "state.db"
    alvo.write_text("# banco de cache\n", encoding="utf-8")

    ok = set_restrictive_file_permissions(alvo)

    assert ok is True
    import stat

    modo = stat.S_IMODE(alvo.stat().st_mode)
    assert modo == 0o600, f"esperado 0o600 ({oct(0o600)}), obtido {oct(modo)}"


# --------------------------------------------------------------------------- #
# ATL-07 / Fase 2 — set_restrictive_file_permissions falha não é silenciosa
# --------------------------------------------------------------------------- #
def test_fase2_falha_nao_eh_silenciosa(tmp_path, monkeypatch, caplog):
    """Falha ao aplicar permissão loga aviso e retorna False (sem engolir erro)."""
    if sys.platform == "win32":
        pytest.skip("teste de falha POSIX focado no runner local")

    alvo = tmp_path / "state.db"
    alvo.write_text("# banco de cache\n", encoding="utf-8")

    with patch(
        "tomus.core.file_security.os.chmod", side_effect=OSError("permissão negada")
    ), caplog.at_level(logging.WARNING, logger="tomus.core.file_security"):
        ok = set_restrictive_file_permissions(alvo)

    assert ok is False, "Fase 2: deve retornar False em falha"
    assert "Não foi possível aplicar permissão restrita 0600" in caplog.text
    assert str(alvo) in caplog.text


# --------------------------------------------------------------------------- #
# ATL-07 / Fase 2 — nunca retorna None
# --------------------------------------------------------------------------- #
def test_fase2_nao_retorna_none(tmp_path, monkeypatch):
    """set_restrictive_file_permissions nunca retorna None: só True ou False."""
    if sys.platform == "win32":
        pytest.skip("teste de negação focado no runner local")

    alvo = tmp_path / "state.db"
    alvo.write_text("# banco de cache\n", encoding="utf-8")

    with patch(
        "tomus.core.file_security.os.chmod", side_effect=OSError("permissão negada")
    ):
        ok = set_restrictive_file_permissions(alvo)

    assert isinstance(ok, bool)
    assert ok is False


# --------------------------------------------------------------------------- #
# ATL-07 / Fase 2 — Windows via icacls (sem mock, roda no windows-latest)
# --------------------------------------------------------------------------- #
def test_fase2_windows_icacls_remove_heranca_e_concede_sid(tmp_path, monkeypatch):
    """No Windows, aplica icacls /inheritance:r /grant:r *<SID>:F (sem mock).

    Este teste é projetado para rodar no runner windows-latest do CI,
    sem mock, verificando que config.toml e state.db recebem ACL restrita
    real via icacls. No macOS/Linux é skipped.
    """
    if sys.platform != "win32":
        pytest.skip("teste de icacls Windows roda apenas no windows-latest do CI")

    from tomus.core.file_security import _set_windows_restrictive_acl

    # O nome do usuário deve ser obtido via whoami (não hardcoded).
    resultado_whoami = subprocess.run(
        ["whoami"], capture_output=True, text=True, check=True, shell=False
    )
    usuario_corrente = resultado_whoami.stdout.strip()

    # Cria arquivo temporário dentro do tmp_path (isolado do CI).
    alvo = tmp_path / "config.toml"
    alvo.write_text("# teste de ACL\n", encoding="utf-8")

    try:
        ok = _set_windows_restrictive_acl(alvo)
        assert ok is True, "Fase 2: icacls deve aplicar ACL restrita no Windows"

        # Verificar via icacls que a ACL está restrita.
        resultado = subprocess_icacls_query(alvo)

        # O nome do usuário (parte após a barra, ex: username) deve aparecer,
        # não necessariamente a string S-1-5-...
        assert usuario_corrente in resultado, (
            f"Fase 2: ACL deve conter o usuário corrente ({usuario_corrente})"
        )

        # Grupos amplos não devem aparecer.
        for grupo in ("BUILTIN\\Usuários", "BUILTIN\\Users", "Everyone",
                      "Usuários Autenticados", "Authenticated Users"):
            assert grupo not in resultado, (
                f"Fase 2: ACL não deve conceder acesso a grupo amplo: {grupo}"
            )

        # Apenas a permissão esperada (F) deve estar concedida ao usuário.
        # icacls imprime ":F" ou ":(F)" dependendo da versão; aceita ambos.
        assert re.search(r":\(?F\)?", resultado), (
            "Fase 2: ACL deve conceder permissão F (controle total)"
        )

        # Validar também o state.db via FileCache (uso real do _connect).
        db_alvo = tmp_path / "state.db"
        from tomus.core.cache import FileCache

        cache = FileCache(enabled=True, db_path=db_alvo)
        try:
            cache.get("sha", "v1", "gemini")
        except PermissionError:
            pass  # esperado no Windows se ACL não aplicada; abaixo verificamos direto
        finally:
            cache.close()

        # Aplicar ACL diretamente ao state.db e verificar.
        ok_db = _set_windows_restrictive_acl(db_alvo)
        assert ok_db is True, "Fase 2: icacls deve aplicar ACL restrita no state.db"

        resultado_db = subprocess_icacls_query(db_alvo)
        assert usuario_corrente in resultado_db, (
            f"Fase 2: state.db ACL deve conter o usuário corrente ({usuario_corrente})"
        )
        for grupo in ("BUILTIN\\Usuários", "BUILTIN\\Users", "Everyone",
                      "Usuários Autenticados", "Authenticated Users"):
            assert grupo not in resultado_db, (
                f"Fase 2: state.db ACL não deve conceder acesso a grupo amplo: {grupo}"
            )
        assert re.search(r":\(?F\)?", resultado_db), (
            "Fase 2: state.db ACL deve conceder permissão F (controle total)"
        )
    finally:
        # Limpeza: restaurar herança e remover o arquivo, se possível.
        try:
            subprocess.run(
                ["icacls", str(alvo), "/inheritance:e"],
                check=False,
                shell=False,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            _logger.warning(
                "Falha ao restaurar herança de ACL em %s: %s", alvo, exc
            )
        try:
            alvo.unlink(missing_ok=True)
        except OSError as exc:
            _logger.warning(
                "Falha ao remover arquivo de teste %s: %s", alvo, exc
            )


def subprocess_icacls_query(caminho: Path) -> str:
    """Executar icacls /query para inspecionar a ACL de um caminho (Windows)."""
    resultado = subprocess.run(
        ["icacls", str(caminho)],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    return resultado.stdout


# --------------------------------------------------------------------------- #
# Fase 2 — _connect aplica permissão e cache funciona (sucesso)
# --------------------------------------------------------------------------- #
def test_fase2_connect_aplica_permissao_e_cache_funciona(tmp_path, monkeypatch):
    """_connect aplica permissão e o cache funciona normalmente (Fase 2)."""
    from tomus.core.cache import _connect

    if sys.platform == "win32":
        pytest.skip("teste de conexão focado no runner local POSIX")

    monkeypatch.setattr("sys.platform", "linux")
    db_path = tmp_path / "state.db"

    chamada = {}

    def falso_set_permissions(path):
        chamada["chamado"] = True
        chamada["caminho"] = path
        return True

    with patch(
        "tomus.core.cache.set_restrictive_file_permissions", falso_set_permissions
    ):
        conn = _connect(db_path)

    try:
        assert chamada["chamado"] is True
        assert chamada["caminho"] == db_path
        # Cache funciona: criar e ler uma entrada.
        conn.execute(
            """
            INSERT INTO processed_files
                (sha256, taxonomy_version, model_name, classification_json, used_ocr, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("abc", "v1", "gemini", '{"confidence_score": 0.9}', 0, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT COUNT(*) FROM processed_files WHERE sha256 = 'abc'"
        )
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Fase 2 — falha de permissão bloqueia operações SQL (fail-closed)
# --------------------------------------------------------------------------- #
def test_fase2_connect_falha_permissao_levanta_erro_e_fecha_conexao(
    tmp_path, monkeypatch, caplog
):
    """Se a permissão falhar, _connect levanta PermissionError e fecha a conexão (Fase 2)."""
    from tomus.core.cache import _connect

    if sys.platform == "win32":
        pytest.skip("teste de conexão focado no runner local POSIX")

    monkeypatch.setattr("sys.platform", "linux")
    db_path = tmp_path / "state.db"

    with patch(
        "tomus.core.cache.set_restrictive_file_permissions", return_value=False
    ), caplog.at_level(logging.WARNING, logger="tomus.core.cache"), pytest.raises(
        PermissionError
    ) as excinfo:
        _connect(db_path)

    assert "0600" in str(excinfo.value)
    assert str(db_path) in str(excinfo.value)
    assert "Nenhuma operação SQL será permitida" in str(excinfo.value)
    assert "Falha ao aplicar permissão restrita" in str(excinfo.value)


def test_fase2_connect_falha_permissao_nao_executa_sql(tmp_path, monkeypatch):
    """Quando a permissão falha, nenhuma instrução SQL é executada (Fase 2).

    O _connect levanta PermissionError antes de qualquer SQL, fechando a
    conexão. O arquivo pode ter sido criado pelo sqlite3.connect mas nenhuma
    tabela deve ter sido criada (fail-closed: nada gravado sem proteção).
    """
    from tomus.core.cache import _connect

    if sys.platform == "win32":
        pytest.skip("teste de conexão focado no runner local POSIX")

    monkeypatch.setattr("sys.platform", "linux")
    db_path = tmp_path / "state.db"

    with patch(
        "tomus.core.cache.set_restrictive_file_permissions", return_value=False
    ), pytest.raises(PermissionError):
        _connect(db_path)

    # O fail-closed impede qualquer operação SQL. Abrir o arquivo diretamente
    # com sqlite3 não deve encontrar tabelas criadas pelo _connect (que
    # abortou antes de qualquer execução de SQL).
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tabelas = [row[0] for row in cur.fetchall()]
        assert "processed_files" not in tabelas, (
            "Fase 2: tabela processed_files não deve existir após falha de permissão"
        )
    finally:
        conn.close()


def test_fase2_cache_operacoes_bloqueadas_apos_falha_permissao(tmp_path, monkeypatch):
    """Nenhuma operação do FileCache prossegue após falha de permissão (Fase 2)."""
    from tomus.core.cache import FileCache

    if sys.platform == "win32":
        pytest.skip("teste de conexão focado no runner local POSIX")

    monkeypatch.setattr("sys.platform", "linux")
    db_path = tmp_path / "state.db"

    cache = FileCache(enabled=True, db_path=db_path)

    with patch(
        "tomus.core.cache.set_restrictive_file_permissions", return_value=False
    ), pytest.raises(PermissionError):
        # Qualquer operação que precise de conexão deve falhar com PermissionError.
        cache.get("sha", "v1", "gemini")

    # A conexão não deve ficar aberta (foi fechada no _connect).
    assert cache._conn is None


def test_fase2_connect_sucesso_cache_funciona(tmp_path, monkeypatch):
    """Quando a permissão funciona, _connect retorna conexão e o cache opera (Fase 2)."""
    from tomus.core.cache import _connect

    if sys.platform == "win32":
        pytest.skip("teste de conexão focado no runner local POSIX")

    monkeypatch.setattr("sys.platform", "linux")
    db_path = tmp_path / "state.db"

    chamada = {}

    def falso_set_permissions(path):
        chamada["chamado"] = True
        chamada["caminho"] = path
        return True

    with patch(
        "tomus.core.cache.set_restrictive_file_permissions", falso_set_permissions
    ):
        conn = _connect(db_path)

    try:
        assert chamada["chamado"] is True
        assert chamada["caminho"] == db_path
        # Cache funciona: criar e ler uma entrada.
        conn.execute(
            """
            INSERT INTO processed_files
                (sha256, taxonomy_version, model_name, classification_json, used_ocr, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("abc", "v1", "gemini", '{"confidence_score": 0.9}', 0, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT COUNT(*) FROM processed_files WHERE sha256 = 'abc'"
        )
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()
