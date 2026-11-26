"""Testes de regressão dos achados da auditoria 1.4.1 — escopo ATLAS.

Cobre:
- ATL-01: DocumentType.TESE_DISSERTACAO aceita "Tese/Dissertacao" e
  "Tese_Dissertacao" via _missing_ (valor canônico inalterado).
- ATL-02: ProcessStatus.DUPLICATE e DUPLICATE_SKIPPED mantêm o mesmo valor
  persistido ("duplicate_skipped"); DUPLICATE é alias semântico documentado,
  sem migração de dados.
- ATL-05: checagem de mock no cache olha apenas _is_mock(classification);
  remove comparação de efetivo/solicitado com "mock".
- ATL-06: alias apontando para modelo ausente -> cache miss, sem fallback para
  o modelo solicitado; nunca devolve classificação de outro modelo.
"""

from __future__ import annotations

from pathlib import Path

from tomus.core.cache import FileCache
from tomus.core.models import DocumentType, LLMClassificationOutput, ProcessStatus


class _FakeClassification(dict):
    """Wrapper para facilitar construção de classificações de teste."""

    def __init__(self, confidence_score: float = 0.9, used_ocr: bool = False,
                 grande_area: str = "Ciências Humanas", reasoning: str = "normal",
                 **kwargs):
        super().__init__(
            confidence_score=confidence_score,
            used_ocr=used_ocr,
            grande_area=grande_area,
            reasoning=reasoning,
            **kwargs,
        )


# --------------------------------------------------------------------------- #
# ATL-01 — Coerção TESE_DISSERTACAO (_missing_)
# --------------------------------------------------------------------------- #
def test_document_type_tese_dissertacao_missing_atl01():
    """_missing_ deve aceitar as duas grafias sem alterar o valor canônico."""
    assert DocumentType._missing_("Tese/Dissertacao") == DocumentType.TESE_DISSERTACAO
    assert DocumentType._missing_("Tese_Dissertacao") == DocumentType.TESE_DISSERTACAO
    # Valor canônico persistido não muda.
    assert DocumentType.TESE_DISSERTACAO.value == "Tese_Dissertacao"


def test_llm_classificacao_tipo_tese_dissertacao_atl01():
    """LLMClassificationOutput deve normalizar "Tese/Dissertacao" para TESE_DISSERTACAO."""
    saida = LLMClassificationOutput(
        grande_area="Ciências Humanas",
        area_basica="Psicologia",
        tipo="Tese/Dissertacao",
        confidence_score=0.9,
        reasoning="ok",
    )
    assert saida.tipo == DocumentType.TESE_DISSERTACAO


# --------------------------------------------------------------------------- #
# ATL-02 — DUPLICATE e DUPLICATE_SKIPPED mesmo valor persistido
# --------------------------------------------------------------------------- #
def test_process_status_duplicate_mesmo_valor_persistido_atl02():
    """DUPLICATE e DUPLICATE_SKIPPED compartilham "duplicate_skipped" sem
    alterar valores persistidos (não há migração de dados/manifesto)."""
    assert ProcessStatus.DUPLICATE.value == "duplicate_skipped"
    assert ProcessStatus.DUPLICATE_SKIPPED.value == "duplicate_skipped"
    # Alias semântico: comparação por valor retorna True.
    assert ProcessStatus.DUPLICATE == ProcessStatus.DUPLICATE_SKIPPED
    # Leitura de "duplicate_skipped" mapeia para DUPLICATE_SKIPPED
    # (primeiro membro definido com esse valor).
    assert ProcessStatus("duplicate_skipped") == ProcessStatus.DUPLICATE_SKIPPED


# --------------------------------------------------------------------------- #
# ATL-05 — Checagem de mock olha apenas a classificação
# --------------------------------------------------------------------------- #
def test_cache_eh_mock_so_olha_classificacao_atl05(tmp_path: Path):
    """Quando a classificação NÃO é mock mas requested_model == "mock",
    o alias ainda deve ser gerenciado (antes de ATL-05, solicitado=="mock"
    forçava eh_mock=True e pulava a criação do alias)."""
    db_path = tmp_path / "state.db"
    cache = FileCache(enabled=True, db_path=db_path)
    cache._ensure_conn()

    classificacao = _FakeClassification(confidence_score=0.90, reasoning="normal")
    cache.put("sha-atl05", "capes-cnpq-v1", "modelo-real", classificacao, False,
              requested_model="mock")

    cur = cache._conn.execute(
        "SELECT requested_model, effective_model FROM model_aliases "
        "WHERE sha256 = ? AND taxonomy_version = ?",
        ("sha-atl05", "capes-cnpq-v1"),
    )
    alias = cur.fetchone()
    assert alias is not None
    assert alias[0] == "mock"
    assert alias[1] == "modelo-real"
    cache.close()


def test_cache_classificacao_mock_nao_cria_alias_atl05(tmp_path: Path):
    """Classificação com reasoning == "mock" não deve gerenciar alias
    (eh_mock True apenas pelo reasoning da classificação)."""
    db_path = tmp_path / "state.db"
    cache = FileCache(enabled=True, db_path=db_path)
    cache._ensure_conn()

    classificacao_mock = _FakeClassification(confidence_score=0.90, reasoning="mock")
    cache.put("sha-atl05b", "capes-cnpq-v1", "modelo-real", classificacao_mock, False,
              requested_model="modelo-real")

    cur = cache._conn.execute(
        "SELECT COUNT(*) FROM model_aliases "
        "WHERE sha256 = ? AND taxonomy_version = ?",
        ("sha-atl05b", "capes-cnpq-v1"),
    )
    assert cur.fetchone()[0] == 0
    cache.close()


# --------------------------------------------------------------------------- #
# ATL-06 — Alias para modelo ausente -> cache miss, sem fallback
# --------------------------------------------------------------------------- #
def test_cache_alias_aponta_modelo_ausente_cache_miss_atl06(tmp_path: Path):
    """Alias que aponta para modelo ausente deve retornar cache miss.
    Nunca cai para o modelo solicitado nem devolve classificação de outro
    modelo."""
    db_path = tmp_path / "state.db"
    cache = FileCache(enabled=True, db_path=db_path)
    cache._ensure_conn()

    classificacao_x = _FakeClassification(confidence_score=0.90, grande_area="Area X")
    # Cria alias "modelo-alias" -> "modelo-X" e linha em processed_files para modelo-X.
    cache.put("sha-atl06", "capes-cnpq-v1", "modelo-X", classificacao_x, False,
              requested_model="modelo-alias")

    # Remove a linha de processed_files do alvo (modelo-X), deixando o alias
    # apontando para um modelo ausente.
    cache._conn.execute(
        "DELETE FROM processed_files "
        "WHERE sha256 = ? AND taxonomy_version = ? AND model_name = ?",
        ("sha-atl06", "capes-cnpq-v1", "modelo-X"),
    )
    cache._conn.commit()

    # Grava uma classificação diferente sob o próprio nome "modelo-alias"
    # (sem requested_model, não toca no alias existente).
    classificacao_alias = _FakeClassification(confidence_score=0.80, grande_area="Area Alias")
    cache.put("sha-atl06", "capes-cnpq-v1", "modelo-alias", classificacao_alias, False)

    # get via alias deve retornar cache miss (None):
    # - não devolve a classificação de modelo-X (outro modelo),
    # - não faz fallback para "modelo-alias" (que tem dados gravados).
    resultado = cache.get("sha-atl06", "capes-cnpq-v1", "modelo-alias")
    assert resultado is None
    cache.close()
