"""Carrega e valida a taxonomia CAPES/CNPq (taxonomy_capes.json)."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional


def _find_taxonomy_file() -> Path:
    candidates = [
        Path(__file__).parent / "resources" / "taxonomy_capes.json",
    ]
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS)
            candidates.append(meipass / "tomus" / "core" / "resources" / "taxonomy_capes.json")
            candidates.append(meipass / "resources" / "taxonomy_capes.json")
        if hasattr(sys, "executable"):
            exe_dir = Path(sys.executable).parent
            candidates.append(exe_dir.parent / "Frameworks" / "tomus" / "core" / "resources" / "taxonomy_capes.json")
            candidates.append(exe_dir.parent / "Resources" / "taxonomy_capes.json")
            candidates.append(exe_dir / "resources" / "taxonomy_capes.json")
            candidates.append(exe_dir / "tomus" / "core" / "resources" / "taxonomy_capes.json")

    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]


_TAXONOMY_PATH = _find_taxonomy_file()

TAXONOMY_VERSION = "capes-cnpq-v1"

_taxonomy_cache: Optional[dict[str, Any]] = None


def _load_taxonomy() -> dict[str, Any]:
    global _taxonomy_cache
    if _taxonomy_cache is None:
        path = _find_taxonomy_file()
        with open(path, "r", encoding="utf-8") as fh:
            _taxonomy_cache = json.load(fh)
    return _taxonomy_cache


def _fold_tax(value: str | None) -> str:
    """Normalizar string para comparação taxonômica (sem acentos, minúsculas)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " e ")
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(text.split())


def get_taxonomy_version() -> str:
    """Retornar a versão do catálogo CAPES/CNPq."""
    return _load_taxonomy().get("version", TAXONOMY_VERSION)


def get_grandes_areas() -> list[str]:
    """Retornar a lista de Grandes Áreas oficiais."""
    return list(_load_taxonomy().get("areas", {}).keys())


def get_areas_basicas(grande_area: str) -> list[str]:
    """Retornar as Áreas Básicas de uma Grande Área específica."""
    return list(_load_taxonomy().get("areas", {}).get(grande_area, []))


def get_subareas(area_basica: str) -> list[str]:
    """Retornar as Subáreas controladas de uma Área Básica, se houver."""
    return list(_load_taxonomy().get("subareas", {}).get(area_basica, []))


def _build_area_to_grande_area() -> dict[str, str]:
    """Mapear cada Área Básica para sua Grande Área pai."""
    mapping: dict[str, str] = {}
    for grande_area, basicas in _load_taxonomy().get("areas", {}).items():
        if isinstance(basicas, dict):
            basicas = basicas.get("subareas", [])
        for area_basica in basicas:
            mapping[area_basica] = grande_area
    return mapping


# Tabela de aliases de Áreas Básicas (rótulo dobrado -> rótulo canônico).
# Permite resolver variações de acento, caixa e grafia informadas pelo LLM ou
# pelo usuário, ex.: "ciencia da computacao" -> "Computação".
AREA_BASICA_ALIASES: dict[str, str] = {
    "ciencia da computacao": "Computação",
    "ciencias da computacao": "Computação",
}


def _index_areas_basicas() -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Retornar (grande_por_dobra, basica_por_dobra).

    grande_por_dobra: rótulo de Grande Área dobrado -> rótulo canônico.
    basica_por_dobra: rótulo de Área Básica dobrado -> (Grande Área mãe, canônico).
    """
    taxonomy = _load_taxonomy()
    areas = taxonomy.get("areas", {})
    grande_por_dobra: dict[str, str] = {}
    basica_por_dobra: dict[str, tuple[str, str]] = {}
    for grande_area, basicas in areas.items():
        grande_por_dobra.setdefault(_fold_tax(grande_area), grande_area)
        if isinstance(basicas, dict):
            basicas = basicas.get("subareas", [])
        for area_basica in basicas:
            basica_por_dobra.setdefault(_fold_tax(area_basica), (grande_area, area_basica))
    return grande_por_dobra, basica_por_dobra


def validate_or_repair_pair(
    grande_area: str,
    area_basica: str,
) -> Optional[tuple[str, str]]:
    """Validar ou reparar o par (grande_area, area_basica).

    Resolve acento/caixa via ``_fold_tax`` e a tabela ``AREA_BASICA_ALIASES``.
    Se a area_basica existir em outra Grande Área, corrige a grande_area pai.
    Retorna None caso nenhuma das duas exista no catálogo.
    """
    grande_por_dobra, basica_por_dobra = _index_areas_basicas()
    area_to_grande = _build_area_to_grande_area()

    ga_fold = _fold_tax(grande_area)
    ab_fold = _fold_tax(area_basica)

    # Resolver o canônico da Área Básica: direto no catálogo ou por alias.
    ab_canonical: Optional[str] = None
    if ab_fold in basica_por_dobra:
        ab_canonical = basica_por_dobra[ab_fold][1]
    elif ab_fold in AREA_BASICA_ALIASES:
        ab_canonical = AREA_BASICA_ALIASES[ab_fold]
        ab_fold = _fold_tax(ab_canonical)

    if ab_canonical is None:
        return None

    mother_ga = area_to_grande.get(ab_canonical)
    ga_canonical = grande_por_dobra.get(ga_fold) if ga_fold else None

    if ga_canonical is not None:
        if mother_ga == ga_canonical:
            return (ga_canonical, ab_canonical)
        if mother_ga:
            return (mother_ga, ab_canonical)
        return None

    if mother_ga:
        return (mother_ga, ab_canonical)
    return None


def repair_taxonomy_levels(
    grande_area: str,
    area_basica: str,
    subarea: str = "",
    especialidade: str = "",
) -> Optional[tuple[str, str, str, str]]:
    """Reparar os quatro níveis taxonômicos.

    Primeiro tenta ``validate_or_repair_pair(grande_area, area_basica)``.
    Se retornar None, verifica se ``subarea`` (ou alias) corresponde via
    ``_fold_tax`` a uma Área Básica oficial quando ``area_basica`` for uma
    Grande Área oficial (ex.: ``Letras`` ou ``Linguística, Letras e Artes``)
    — nesse caso promove ``subarea`` para a Área Básica canônica, corrige
    ``grande_area`` para a Grande Área oficial mãe e rebaixa ``subarea`` para
    ``"Geral"`` (ou promove ``especialidade`` se não for ``Geral`` e zera
    ``especialidade`` para ``"Geral"``).

    Retorna uma tupla ``(grande_area, area_basica, subarea, especialidade)``
    ou ``None`` quando não houver reparo possível.
    """
    reparado = validate_or_repair_pair(grande_area, area_basica)
    if reparado is not None:
        ga, ab = reparado
        return (
            ga,
            ab,
            subarea or "Geral",
            especialidade or "Geral",
        )

    grande_por_dobra, basica_por_dobra = _index_areas_basicas()
    areas = _load_taxonomy().get("areas", {})

    ab_fold = _fold_tax(area_basica)
    sub_fold = _fold_tax(subarea)

    # area_basica é na verdade uma Grande Área oficial (rótulo deslocado)?
    mother_ga = grande_por_dobra.get(ab_fold) if ab_fold else None
    if mother_ga is None or not sub_fold:
        return None

    # A subarea corresponde a uma Área Básica oficial dessa Grande Área?
    if sub_fold in basica_por_dobra:
        sub_ga, sub_ab_canonical = basica_por_dobra[sub_fold]
        if sub_ga != mother_ga:
            return None

        nova_area_basica = sub_ab_canonical
        esp = (especialidade or "").strip()
        esp_fold = _fold_tax(esp)
        if esp and esp_fold not in (
            "geral",
            "nao especificada",
            "nao especificado",
            "none",
            "null",
            "",
        ):
            # Promove a especialidade para subarea e zera a especialidade.
            nova_subarea = esp
            nova_especialidade = "Geral"
        else:
            nova_subarea = "Geral"
            nova_especialidade = "Geral"

        return (mother_ga, nova_area_basica, nova_subarea, nova_especialidade)

    return None


# ---------------------------------------------------------------------------
# Vocabulário controlado de Subáreas, Sinônimos e Regras de Desambiguação
# ---------------------------------------------------------------------------
SUBAREA_SYNONYMS: dict[str, str] = {
    "psicanalise": "Psicanálise",
    "teoria psicanalitica": "Psicanálise",
    "psicologia psicanalitica": "Psicanálise",
    "clinica psicanalitica": "Psicanálise",
    "psicanalise lacaniana": "Psicanálise",
    "psicologia analitica": "Psicologia Analítica",
    "psicologia junguiana": "Psicologia Analítica",
    "avaliacao psicologica": "Avaliação Psicológica",
    "psicodiagnostico": "Avaliação Psicológica",
    "psicometria": "Avaliação Psicológica",
    "fundamentos e medidas da psicologia": "Avaliação Psicológica",
    "construcao e validade de testes escalas e outras medidas psicologicas": "Avaliação Psicológica",
    "neuropsicologia": "Neuropsicologia",
    "avaliacao neuropsicologica": "Neuropsicologia",
    "psicologia hospitalar": "Psicologia Hospitalar e da Saúde",
    "psicologia hospitalar e da saude": "Psicologia Hospitalar e da Saúde",
    "psicologia da saude": "Psicologia Hospitalar e da Saúde",
    "psicossomatica": "Psicologia Hospitalar e da Saúde",
    "psicologia juridica": "Psicologia Jurídica",
    "psicologia forense": "Psicologia Jurídica",
    "psicologia social": "Psicologia Social",
    "psicologia social comunitaria": "Psicologia Social",
    "psicologia e politicas publicas": "Psicologia Social",
    "psicologia organizacional e do trabalho": "Psicologia Organizacional e do Trabalho",
    "psicologia do trabalho e organizacional": "Psicologia Organizacional e do Trabalho",
    "psicologia do trabalho e das organizacoes": "Psicologia Organizacional e do Trabalho",
    "psicologia do trabalho": "Psicologia Organizacional e do Trabalho",
    "psicologia escolar": "Psicologia Escolar e Educacional",
    "psicologia educacional": "Psicologia Escolar e Educacional",
    "psicologia escolar e educacional": "Psicologia Escolar e Educacional",
    "psicologia do ensino e da aprendizagem": "Psicologia Escolar e Educacional",
    "psicologia do desenvolvimento": "Psicologia do Desenvolvimento",
    "psicologia do desenvolvimento humano": "Psicologia do Desenvolvimento",
    "psicologia infantil": "Psicologia do Desenvolvimento",
    "psicologia cognitiva": "Psicologia Cognitiva",
    "psicologia experimental": "Psicologia Experimental e Análise do Comportamento",
    "analise do comportamento": "Psicologia Experimental e Análise do Comportamento",
    "psicologia experimental e analise do comportamento": "Psicologia Experimental e Análise do Comportamento",
    "psicobiologia": "Psicobiologia e Psicofarmacologia",
    "psicobiologia e psicofarmacologia": "Psicobiologia e Psicofarmacologia",
    "psicologia fisiologica": "Psicobiologia e Psicofarmacologia",
    "psicofarmacologia": "Psicobiologia e Psicofarmacologia",
    "psicologia da personalidade": "Psicologia da Personalidade",
    "fundamentos e historia da psicologia": "Fundamentos e História da Psicologia",
    "historia da psicologia": "Fundamentos e História da Psicologia",
    "metodologia de pesquisa em psicologia": "Fundamentos e História da Psicologia",
    "psicologia do esporte": "Psicologia do Esporte",
    "psicologia do transito": "Psicologia do Trânsito",
    "psicologia geral": "Geral",
    "tratamento e prevencao psicologica": "Psicologia Clínica",
    "psicologia clinica": "Psicologia Clínica",
    "neurociencias": "Neurociências",
    "neurociencia": "Neurociências",
    "neurofisiologia": "Neurociências",
    "neuroanatomia": "Neurociências",
    "anatomia humana": "Neurociências",
    "anatomia": "Neurociências",
    "psiquiatria": "Psiquiatria",
    "neurologia": "Neurologia",
    "pediatria": "Pediatria",
    "farmacologia": "Farmacologia",
    "clinica medica": "Clínica Médica",
    "psicologia medica": "Psiquiatria",
}

SPECIFICITY_RANK: dict[str, int] = defaultdict(
    lambda: 2,
    {
        "Geral": 0,
        "Psicologia Clínica": 1,
        "Psicologia Social": 1,
        "Fundamentos e História da Psicologia": 1,
        "Psicologia Cognitiva": 1,
    },
)

AUTHOR_SUBAREA_ANCHORS: dict[str, str] = {
    "freud": "Psicanálise",
    "lacan": "Psicanálise",
    "winnicott": "Psicanálise",
    "klein": "Psicanálise",
    "bion": "Psicanálise",
    "ferenczi": "Psicanálise",
    "laplanche": "Psicanálise",
    "zimerman": "Psicanálise",
    "roudinesco": "Psicanálise",
    "chemama": "Psicanálise",
    "nasio": "Psicanálise",
    "dolto": "Psicanálise",
    "fink": "Psicanálise",
    "etchegoyen": "Psicanálise",
    "jung": "Psicologia Analítica",
    "hillman": "Psicologia Analítica",
    "franz": "Psicologia Analítica",
}

CROSS_AREA_CANONICAL: dict[str, tuple[str, str]] = {
    "Psicologia Jurídica": ("Ciências Humanas", "Psicologia"),
    "Neuropsicologia": ("Ciências Humanas", "Psicologia"),
    "Neurociências": ("Ciências da Saúde", "Medicina"),
}


def canon_label(label: str | None) -> str:
    """Converter um rótulo de subárea/especialidade usando a tabela de sinônimos."""
    raw = str(label or "").strip()
    folded = _fold_tax(raw)
    if not folded or folded in ("nao especificada", "nao especificado", "none", "null", "geral"):
        return "Geral"
    if folded in SUBAREA_SYNONYMS:
        return SUBAREA_SYNONYMS[folded]
    return raw


def _extract_surname_key(authors: list[str] | None) -> str:
    """Extrair chave do sobrenome do primeiro autor para comparação com âncoras."""
    if not authors:
        return ""
    first = str(authors[0] or "").strip()
    if not first:
        return ""
    if "," in first:
        surname = first.split(",", 1)[0].strip()
    else:
        parts = first.split()
        surname = parts[-1] if parts else ""
    return _fold_tax(surname).replace(" ", "")


def normalize_and_resolve_taxonomy(
    classification: dict[str, Any],
    first_author_key: str = "",
) -> dict[str, str]:
    """Normalizar sinônimos e aplicar regras determinísticas de desambiguação.

    Retorna um dicionário contendo ``grande_area``, ``area_basica``,
    ``subarea`` e ``especialidade`` consistentes com ``taxonomy_capes.json``.
    """
    grande_area = str(classification.get("grande_area") or "").strip()
    area_basica = str(classification.get("area_basica") or "").strip()
    reparado = validate_or_repair_pair(grande_area, area_basica)
    if reparado is not None:
        grande_area, area_basica = reparado

    raw_subarea = str(classification.get("subarea") or "")
    raw_especialidade = str(classification.get("especialidade") or "")
    subarea = canon_label(raw_subarea)
    especialidade = canon_label(raw_especialidade)

    # 1. Alinhamento interdisciplinar entre Grandes Áreas/Áreas Básicas.
    if subarea in CROSS_AREA_CANONICAL and (grande_area, area_basica) != CROSS_AREA_CANONICAL[subarea]:
        if not (subarea == "Neurociências" and area_basica == "Psicologia"):
            grande_area, area_basica = CROSS_AREA_CANONICAL[subarea]

    titulo = str(classification.get("titulo") or classification.get("title") or "")
    if (
        area_basica == "Medicina"
        and subarea == "Neurociências"
        and "neuro" not in _fold_tax(titulo)
        and _fold_tax(raw_subarea) in ("anatomia", "anatomia humana")
    ):
        subarea = "Geral"

    if area_basica == "Fisiologia" and subarea == "Neurociências":
        grande_area, area_basica = CROSS_AREA_CANONICAL["Neurociências"]

    # 2. Promoção de especialidade controlada mais específica em Psicologia.
    psicologia_vocab = get_subareas("Psicologia")
    if (
        area_basica == "Psicologia"
        and especialidade in psicologia_vocab
        and SPECIFICITY_RANK[especialidade] > SPECIFICITY_RANK[subarea]
    ):
        subarea, especialidade = especialidade, "Geral"

    # 3. Âncora determinística por autor canônico (apenas em subáreas amplas).
    author_key = first_author_key or _extract_surname_key(classification.get("authors"))
    if (
        author_key in AUTHOR_SUBAREA_ANCHORS
        and area_basica in ("Psicologia", "Medicina")
        and SPECIFICITY_RANK[subarea] <= 1
    ):
        grande_area = "Ciências Humanas"
        area_basica = "Psicologia"
        subarea = AUTHOR_SUBAREA_ANCHORS[author_key]

    # 4. Vocabulário controlado para Áreas Básicas mapeadas em taxonomy_capes.json.
    vocab = get_subareas(area_basica)
    if vocab and subarea not in vocab:
        subarea = "Geral"

    return {
        "grande_area": grande_area,
        "area_basica": area_basica,
        "subarea": subarea,
        "especialidade": especialidade,
    }


def normalize_and_repair_taxonomy(
    grande_area: str | None,
    area_basica: str | None,
    especialidade: str | None = None,
    authors: list[str] | None = None,
    subarea: str | None = None,
) -> dict[str, str]:
    """Interface de compatibilidade para normalização e reparo taxonômico."""
    return normalize_and_resolve_taxonomy(
        {
            "grande_area": grande_area or "",
            "area_basica": area_basica or "",
            "subarea": subarea or "",
            "especialidade": especialidade or "",
            "authors": authors or [],
        }
    )


def validate_or_repair_subarea_especialidade(
    subarea: str,
    especialidade: str,
) -> Optional[tuple[str, str]]:
    """Validar ou reparar o par (subarea, especialidade)."""
    subarea = (subarea or "").strip()
    especialidade = (especialidade or "").strip()

    if not subarea and not especialidade:
        return None

    if not subarea:
        subarea = "Não especificada"
    if not especialidade:
        especialidade = "Não especificada"

    return (subarea, especialidade)


def format_taxonomy_for_prompt() -> str:
    """Formatar o catálogo CAPES/CNPq e vocabulário controlado para o prompt do LLM."""
    taxonomy = _load_taxonomy()
    lines = ["Catálogo CAPES/CNPq (Grandes Áreas e Áreas Básicas válidas):"]
    for grande_area, areas_basicas in taxonomy.get("areas", {}).items():
        if isinstance(areas_basicas, dict):
            areas_basicas = areas_basicas.get("subareas", [])
        lines.append(f"- {grande_area}: {'; '.join(areas_basicas)}")

    subareas = taxonomy.get("subareas", {})
    if subareas:
        lines.append("")
        lines.append("Vocabulário controlado de Subáreas (use exatamente um destes valores quando aplicável):")
        for area_basica, lista in subareas.items():
            lines.append(f"- {area_basica}: {'; '.join(lista)}")
    return "\n".join(lines)
