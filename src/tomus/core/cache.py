"""Cache SQLite local do Tomus (Stage 1 / idempotência).

Banco em ~/.cache/tomus/state.db em modo WAL com a tabela
processed_files indexada por (sha256, taxonomy_version, model_name),
persistindo apenas resultados com confidence_score >= confidence_min
e suportando invalidação via --no-cache.

Nunca lê nem grava resultados de provedores mock (reasoning == 'mock')
no cache real (~/.cache/tomus/state.db), a menos que um db_path
explícito de teste seja injetado.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tomus.core.file_security import set_restrictive_file_permissions

CACHE_DIR = Path.home() / ".cache" / "tomus"
CACHE_DB_PATH = CACHE_DIR / "state.db"

# Permissão restrita para o banco de cache (apenas o dono lê/escreve),
# equivalente a chmod 0600 POSIX. No Windows, aplicada via icacls.
CACHE_FILE_MODE = 0o600

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_files (
    sha256 TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    classification_json TEXT NOT NULL,
    used_ocr INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sha256, taxonomy_version, model_name)
);

CREATE TABLE IF NOT EXISTS model_aliases (
    sha256 TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    effective_model TEXT NOT NULL,
    PRIMARY KEY (sha256, taxonomy_version, requested_model)
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    """Abrir conexão SQLite em modo WAL, criando diretório e tabela se necessário.

    Semântica fail-closed (ATL-07 / Fase 2): a permissão restrita 0600 / ACL
    é aplicada ANTES de qualquer instrução SQL, para evitar uso do arquivo
    sem proteção. Se a proteção não puder ser aplicada, a conexão é fechada
    e um PermissionError é levantado, impedindo qualquer operação de
    leitura/escrita no banco sem proteção de ACL.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False permite uso da mesma conexão em worker threads
    # (acesso serializado pelo finalize_lock em pipeline.py).
    conn = sqlite3.connect(str(db_path), check_same_thread=False)

    # Aplicar permissão restrita ANTES de qualquer SQL (fail-closed).
    if not set_restrictive_file_permissions(db_path):
        conn.close()
        raise PermissionError(
            "Falha ao aplicar permissão restrita 0600 no cache SQLite "
            f"{db_path}: o arquivo pode ficar acessível a outros "
            "usuários do sistema. Nenhuma operação SQL será permitida "
            "sem proteção de ACL. Corrija as permissões do diretório ou "
            "do arquivo e tente novamente."
        )

    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()

    return conn


def _is_mock(classification: dict[str, Any]) -> bool:
    """Verificar se uma classificação veio de um provedor mock."""
    return str(classification.get("reasoning", "")) == "mock"


class FileCache:
    """Gerenciar cache local de classificações já aprovadas.

    Quando ``db_path`` não é fornecido, usa o cache real
    (~/.cache/tomus/state.db). Nesse caso, nunca lê nem grava resultados
    com ``reasoning == 'mock'`` (provedor MockLLMProvider), evitando poluir o
    cache real com dados de teste.
    """

    def __init__(self, enabled: bool = True, db_path: Path | None = None) -> None:
        self.enabled = enabled
        self.db_path = db_path or CACHE_DB_PATH
        self._conn: sqlite3.Connection | None = None
        # Indica se este é o cache real (sem db_path explícito de teste).
        self._is_real_cache = db_path is None

    def _ensure_conn(self) -> None:
        if self._conn is None and self.enabled:
            self._conn = _connect(self.db_path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> FileCache:
        self._ensure_conn()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get(
        self,
        sha256: str,
        taxonomy_version: str,
        model_name: str,
    ) -> dict[str, Any] | None:
        """Buscar classificação em cache pela chave composta.

        Resolve primeiro o alias vigente (requested_model -> effective_model),
        depois faz busca direta pela PK antiga.
        No cache real, ignora entradas com reasoning == 'mock'.
        """
        if not self.enabled:
            return None
        self._ensure_conn()
        if self._conn is None:
            return None
        # Resolver alias: requested_model -> effective_model.
        modelo_para_busca = model_name
        cur = self._conn.execute(
            """
            SELECT effective_model
            FROM model_aliases
            WHERE sha256 = ? AND taxonomy_version = ? AND requested_model = ?
            """,
            (sha256, taxonomy_version, model_name),
        )
        row_alias = cur.fetchone()
        if row_alias is not None:
            modelo_para_busca = row_alias[0]
        cur = self._conn.execute(
            """
            SELECT classification_json, used_ocr
            FROM processed_files
            WHERE sha256 = ? AND taxonomy_version = ? AND model_name = ?
            """,
            (sha256, taxonomy_version, modelo_para_busca),
        )
        row = cur.fetchone()
        if row is None:
            # Alias apontou para modelo ausente: cache miss.
            # Não cai para o modelo solicitado, para nunca devolver
            # uma classificação de outro modelo.
            return None
        classification_json, used_ocr = row
        try:
            data = json.loads(classification_json)
        except json.JSONDecodeError:
            return None
        data["used_ocr"] = bool(used_ocr)
        # No cache real, nunca retornar dados de mock.
        if self._is_real_cache and _is_mock(data):
            return None
        return data

    def put(
        self,
        sha256: str,
        taxonomy_version: str,
        model_name: str,
        classification: dict[str, Any],
        used_ocr: bool,
        confidence_min: float = 0.70,
        *,
        requested_model: str | None = None,
    ) -> None:
        """Persistir classificação apenas se confidence_score >= confidence_min.

        Grava resultado canônico e atualiza/remove o alias na mesma transação.
        Se o solicitado coincidir com o vencedor, remove eventual alias antigo
        desse solicitado. No cache real, nunca grava resultados com
        reasoning == 'mock' nem grava alias para mock.
        """
        if not self.enabled:
            return
        confidence = float(classification.get("confidence_score", 0.0))
        if confidence < confidence_min:
            return
        # No cache real, nunca gravar dados de mock.
        if self._is_real_cache and _is_mock(classification):
            return
        self._ensure_conn()
        if self._conn is None:
            return
        now = datetime.now(UTC).isoformat()
        efetivo = model_name
        solicitado = requested_model
        # Nunca criar alias para mock: a decisão baseia-se apenas na
        # classificacao (reasoning == 'mock'), nunca no nome do modelo.
        eh_mock = _is_mock(classification)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO processed_files
                    (sha256, taxonomy_version, model_name, classification_json, used_ocr, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256, taxonomy_version, model_name) DO UPDATE SET
                    classification_json = excluded.classification_json,
                    used_ocr = excluded.used_ocr,
                    updated_at = excluded.updated_at
                """,
                (
                    sha256,
                    taxonomy_version,
                    efetivo,
                    json.dumps(classification, ensure_ascii=False),
                    int(used_ocr),
                    now,
                ),
            )
            # Gerenciar alias na mesma transação.
            if not eh_mock and solicitado is not None and solicitado != efetivo:
                self._conn.execute(
                    """
                    INSERT INTO model_aliases
                        (sha256, taxonomy_version, requested_model, effective_model)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(sha256, taxonomy_version, requested_model) DO UPDATE SET
                        effective_model = excluded.effective_model
                    """,
                    (sha256, taxonomy_version, solicitado, efetivo),
                )
            elif not eh_mock and solicitado is not None and solicitado == efetivo:
                # Remover eventual alias antigo desse solicitado.
                self._conn.execute(
                    """
                    DELETE FROM model_aliases
                    WHERE sha256 = ? AND taxonomy_version = ? AND requested_model = ?
                    """,
                    (sha256, taxonomy_version, solicitado),
                )

    def clear(self) -> None:
        """Limpar todas as entradas do cache (suporte a --no-cache invalidação)."""
        if not self.enabled:
            return
        self._ensure_conn()
        if self._conn is None:
            return
        with self._conn:
            self._conn.execute("DELETE FROM processed_files")
            self._conn.execute("DELETE FROM model_aliases")

    def delete(self, sha256: str) -> None:
        """Remover uma entrada específica do cache pelo hash SHA-256."""
        if not self.enabled:
            return
        self._ensure_conn()
        if self._conn is None:
            return
        with self._conn:
            self._conn.execute("DELETE FROM processed_files WHERE sha256 = ?", (sha256,))
            self._conn.execute(
                "DELETE FROM model_aliases WHERE sha256 = ?", (sha256,)
            )

    def count(self) -> int:
        """Retorna o número total de entradas registradas no cache SQLite."""
        if not self.enabled or not self.db_path.exists():
            return 0
        try:
            self._ensure_conn()
            if self._conn is not None:
                cursor = self._conn.execute("SELECT COUNT(*) FROM processed_files")
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0
        return 0
