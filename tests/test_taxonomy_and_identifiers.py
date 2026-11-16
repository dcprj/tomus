"""Testes de taxonomia e identificadores (Item 26).

Validam a integridade de taxonomy_capes.json, o reparo automático de
Grande Área, a extração de DOI por regex, a validação de ISBN via
stdnum.isbn.is_valid (rejeitando falsos números como 531581939) e a
detecção de Ficha Catalográfica.
"""

from __future__ import annotations

from tomus.core.taxonomy import (
    get_taxonomy_version,
    get_grandes_areas,
    get_areas_basicas,
    validate_or_repair_pair,
    repair_taxonomy_levels,
)
from tomus.core.llm import _finalize_classification
from tomus.core.models import LLMClassificationOutput, DocumentType
from tomus.extractors.identifiers import (
    extract_doi,
    extract_isbn,
    detect_cip_page,
)


def test_taxonomy_version():
    assert get_taxonomy_version() == "capes-cnpq-v1"


def test_taxonomy_has_nove_grandes_areas():
    grandes = get_grandes_areas()
    assert len(grandes) == 9
    assert "Ciências Humanas" in grandes
    assert "Ciências Exatas e da Terra" in grandes


def test_cada_grande_area_tem_areas_basicas_nao_vazias():
    for grande in get_grandes_areas():
        basicas = get_areas_basicas(grande)
        assert len(basicas) > 0, f"{grande} sem áreas básicas"
        for basica in basicas:
            assert "/" not in basica


def test_validate_or_repair_pair_consistente():
    assert validate_or_repair_pair("Ciências Humanas", "Psicologia") == (
        "Ciências Humanas",
        "Psicologia",
    )
    assert validate_or_repair_pair("Engenharias", "Engenharia Civil") == (
        "Engenharias",
        "Engenharia Civil",
    )


def test_validate_or_repair_pair_repara_grande_area():
    # Psicologia pertence a Ciências Humanas; grande_area informada errada.
    assert validate_or_repair_pair("Ciências Exatas e da Terra", "Psicologia") == (
        "Ciências Humanas",
        "Psicologia",
    )


def test_validate_or_repair_pair_ambos_invalidos_retorna_none():
    assert validate_or_repair_pair("Não Existe", "Também Não Existe") is None


def test_extract_doi_valido():
    texto = "DOI: 10.1037/arc0000014 e mais texto"
    assert extract_doi(texto) == "10.1037/arc0000014"


def test_extract_doi_limpa_pontuacao_terminal():
    texto = "https://doi.org/10.1000/xyz123."
    assert extract_doi(texto) == "10.1000/xyz123"


def test_extract_doi_nao_encontrado():
    assert extract_doi("não há doi aqui") is None


def test_extract_isbn_valido_isbn13():
    texto = "ISBN 978-85-363-1234-7"
    # 9788536312347 é um ISBN-13 válido (dígito verificador = 7).
    assert extract_isbn(texto) == "9788536312347"


def test_extract_isbn_rejeita_numero_arbitrario():
    # 531581939 é um número arbitrário (não ISBN válido).
    assert extract_isbn("531581939") is None


def test_extract_isbn_nao_encontrado():
    assert extract_isbn("não há isbn aqui") is None


def test_detect_cip_page():
    texto = """
    Sumário
    ...
    Ficha catalográfica
    Silva, João.
    Título da obra / João Silva. -- São Paulo : Editora, 2021.
    CDD 150.19
    """
    cip = detect_cip_page(texto)
    assert "Ficha catalográfica" in cip
    assert "CDD" in cip


def test_detect_cip_page_sem_marcador():
    assert detect_cip_page("apenas texto comum sem ficha") == ""


# --------------------------------------------------------------------------- #
# validate_or_repair_pair — acento, caixa e aliases
# --------------------------------------------------------------------------- #

def test_validate_or_repair_pair_case_insensitive():
    assert validate_or_repair_pair("ciências humanas", "psicologia") == (
        "Ciências Humanas",
        "Psicologia",
    )


def test_validate_or_repair_pair_alias_computacao():
    # Variações sem acento da Área Básica "Computação".
    assert validate_or_repair_pair(
        "Ciências Exatas e da Terra", "ciencia da computacao"
    ) == ("Ciências Exatas e da Terra", "Computação")
    assert validate_or_repair_pair(
        "Ciências Exatas e da Terra", "ciencias da computacao"
    ) == ("Ciências Exatas e da Terra", "Computação")


def test_validate_or_repair_pair_repara_grande_area_pelo_alias():
    # Grande área informada errada + alias da área básica.
    assert validate_or_repair_pair(
        "Ciências da Saúde", "ciencia da computacao"
    ) == ("Ciências Exatas e da Terra", "Computação")


def test_validate_or_repair_pair_ambos_invalidos_retorna_none():
    assert validate_or_repair_pair("Não Existe", "Também Não Existe") is None


# --------------------------------------------------------------------------- #
# repair_taxonomy_levels
# --------------------------------------------------------------------------- #

def test_repair_taxonomy_levels_ficcao_letras_literatura():
    # Produção: LLM devolveu Ciências Humanas / Letras / Literatura.
    # Letras é Grande Área; Literatura é Área Básica dela.
    reparado = repair_taxonomy_levels("Ciências Humanas", "Letras", "Literatura", "")
    assert reparado == ("Letras", "Literatura", "Geral", "Geral")


def test_repair_taxonomy_levels_promove_especialidade_nao_geral():
    # Especialidade não-Geral é promovida para subarea; especialidade zera.
    reparado = repair_taxonomy_levels("Ciências Humanas", "Letras", "Literatura", "Teoria Literária")
    assert reparado == ("Letras", "Literatura", "Teoria Literária", "Geral")


def test_repair_taxonomy_levels_par_valido_mantido():
    reparado = repair_taxonomy_levels("Ciências Humanas", "Psicologia", "Psicanálise", "")
    assert reparado == ("Ciências Humanas", "Psicologia", "Psicanálise", "Geral")


def test_repair_taxonomy_levels_subarea_vazia_sem_reparo():
    # Sem subarea não há o que promover para Área Básica: sem reparo.
    assert repair_taxonomy_levels("Ciências Humanas", "Letras", "", "") is None


def test_repair_taxonomy_levels_par_realmente_invalido_retorna_none():
    assert repair_taxonomy_levels("Não Existe", "Também Não Existe", "X", "Y") is None
    assert repair_taxonomy_levels("Ciências Humanas", "Não Existe", "Literatura", "") is None


# --------------------------------------------------------------------------- #
# _finalize_classification — confiança preservada ao reparar
# --------------------------------------------------------------------------- #

def _output(grande_area, area_basica, subarea="", especialidade="", conf=0.85):
    return LLMClassificationOutput(
        grande_area=grande_area,
        area_basica=area_basica,
        subarea=subarea,
        especialidade=especialidade,
        tipo=DocumentType.LIVRO,
        authors=["Machado de Assis"],
        title="O festim dos corvos",
        subtitle="",
        year=2020,
        confidence_score=conf,
        reasoning="llm",
    )


def test_finalize_classification_repara_e_nao_zera_confianca():
    # Caso de produção: não deve zerar a confiança ao reparar Letras/Literatura.
    res = _finalize_classification(
        _output("Ciências Humanas", "Letras", "Literatura", ""), used_ocr=False
    )
    assert res.grande_area == "Letras"
    assert res.area_basica == "Literatura"
    assert res.subarea == "Geral"
    assert res.confidence_score == 0.85  # confiança preservada


def test_finalize_classification_alias_computacao_preserva_confianca():
    res = _finalize_classification(
        _output("Ciências Exatas e da Terra", "ciencia da computacao", "", ""),
        used_ocr=False,
    )
    assert res.area_basica == "Computação"
    assert res.confidence_score == 0.85


def test_finalize_classification_par_invalido_zera_confianca():
    # Par realmente invocado não tem reparo possível: confiança vira 0.0.
    res = _finalize_classification(
        _output("Não Existe", "Também Não Existe", "", ""), used_ocr=False
    )
    assert res.confidence_score == 0.0
    assert "irreparável" in res.reasoning
