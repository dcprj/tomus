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


def validate_or_repair_pair(
    grande_area: str,
    area_basica: str,
) -> Optional[tuple[str, str]]:
    """Validar ou reparar o par (grande_area, area_basica).

    Se a area_basica existir em outra Grande Área, corrige a grande_area pai.
    Retorna None caso nenhuma das duas exista no catálogo.
    """
    taxonomy = _load_taxonomy()
    areas = taxonomy.get("areas", {})
    area_to_grande = _build_area_to_grande_area()

    if grande_area in areas and area_basica in areas[grande_area]:
        return (grande_area, area_basica)

    if area_basica in area_to_grande:
        correta = area_to_grande[area_basica]
        return (correta, area_basica)

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
