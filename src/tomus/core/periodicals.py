"""Normalização de domínio para fascículos de revista (Item 4 do PR #14).

Módulo puro (sem dependência de rede ou de sistema de arquivos) que centraliza:
* normalização canônica do nome do periódico com aliases verificados;
* parse e validação estrita de algarismo romano -> decimal (preservando rótulo
  ``ano`` vs ``volume``);
* numeração simples/dupla/alfanumérica (``52/53``, ``52A``, zero apenas se
  expresso);
* datas PT/EN com virada de ano;
* formatadores de exibição e de nome ordenável;
* rótulo de suplemento (``supl-01``);
* chave serial para L3.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "JOURNAL_ALIASES",
    "canonical_journal",
    "journal_sort_key",
    "parse_roman",
    "parse_issue",
    "parse_date",
    "format_display_name",
    "format_sortable_name",
    "supplement_label",
    "is_redundant_issue_designation",
]

# ---------------------------------------------------------------------------
# Periódicos e aliases verificados
# ---------------------------------------------------------------------------

# Aliases verificados para o periódico da série piloto. Chave: rótulo dobrado
# (sem acento, minúsculo, pontuação normalizada). Valor: grafia canônica NFC.
JOURNAL_ALIASES: dict[str, str] = {
    "micro sistemas": "Micro Sistemas",
    "microsistemas": "Micro Sistemas",
}


def _fold_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^0-9a-z]+", " ", text.casefold())
    return " ".join(text.split())


def canonical_journal(name: str | None) -> str | None:
    """Retornar a grafia canônica NFC de um periódico, aplicando aliases verificados.

    Não realiza fusão aproximada de títulos diferentes. Retorna ``None`` para
    entrada vazia/ausente.
    """
    if not name:
        return None
    cleaned = " ".join(str(name).split())
    folded = _fold_text(cleaned)
    if not folded:
        return None
    if folded in JOURNAL_ALIASES:
        return JOURNAL_ALIASES[folded]
    # Preservar grafia editorial NFC quando não houver alias.
    return unicodedata.normalize("NFC", cleaned)


def journal_sort_key(name: str | None) -> str:
    """Chave comparativa para agrupamento por periódico (casefold + pontuação normalizada)."""
    canonical = canonical_journal(name) or ""
    return _fold_text(canonical)


# ---------------------------------------------------------------------------
# Algarismo romano estrito
# ---------------------------------------------------------------------------

_ROMAN_DIGITS = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

# Padrões de subtração válidos em numerais canônicos.
_ROMAN_SUBTRACTIVE = {
    "IV", "IX", "XL", "XC", "CD", "CM",
}

_ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)


def _is_canonical_roman(s: str) -> bool:
    """Verificar se ``s`` é um numeral romano em forma canônica (regras de posição)."""
    s = s.upper()
    if not _ROMAN_RE.match(s):
        return False
    # Valida ordem não crescente exceto subtrações válidas, e não repete V/L/D.
    prev_value = 10000
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        val = _ROMAN_DIGITS[ch]
        if ch in "VLD" and s.count(ch) > 1:
            return False
        if i + 1 < n:
            nxt = _ROMAN_DIGITS[s[i + 1]]
            if nxt > val:
                pair = s[i:i + 2]
                if pair not in _ROMAN_SUBTRACTIVE:
                    return False
                # Subtração não pode ser seguida de valor >= ao subtraído.
                combined = nxt - val
                if combined >= prev_value:
                    return False
                prev_value = combined
                i += 2
                continue
        if val > prev_value:
            return False
        prev_value = val
        i += 1
    return True


def parse_roman(value: str) -> int | None:
    """Converter numeral romano estrito para decimal.

    Retorna ``None`` quando a entrada não é um numeral romano válido/canônico.
    Preserva o rótulo 'ano' vs 'volume' a cargo do chamador (este valor é o
    ordinal; o rótulo é armazenado separadamente).
    """
    if not value:
        return None
    s = str(value).strip().upper()
    if not _is_canonical_roman(s):
        return None
    total = 0
    prev = 0
    for ch in reversed(s):
        val = _ROMAN_DIGITS[ch]
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total or None


# ---------------------------------------------------------------------------
# Numeração de fascículo
# ---------------------------------------------------------------------------

_ISSUE_SIMPLE_RE = re.compile(r"^(0*[1-9]\d*|0)$")
_ISSUE_DOUBLE_RE = re.compile(r"^(0*[1-9]\d*)\s*/\s*(0*[1-9]\d*)$")
_ISSUE_ALPHA_RE = re.compile(r"^(0*[1-9]\d*)([A-Za-z])$")


def _strip_leading_zeros(num: str) -> str:
    """Remover zeros à esquerda, preservando '0' quando expresso."""
    s = num.lstrip("0")
    return s if s else "0"


def parse_issue(value: str) -> dict[str, str]:
    """Parse de número de fascículo.

    Retorna dicionário com ``kind`` (``simple``, ``double``, ``alpha``, ``zero``,
    ``raw``), ``value`` (decimal sem padding, exceto ``raw``), ``label`` para
    exibição e ``primary`` (primeiro número em duplas).
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return {"kind": "raw", "value": "", "label": "", "primary": ""}

    m = _ISSUE_DOUBLE_RE.match(raw)
    if m:
        first = _strip_leading_zeros(m.group(1))
        second = _strip_leading_zeros(m.group(2))
        return {
            "kind": "double",
            "value": f"{first}-{second}",
            "label": f"n{first.zfill(4)}-{second.zfill(4)}",
            "primary": first,
        }

    m = _ISSUE_ALPHA_RE.match(raw)
    if m:
        num = _strip_leading_zeros(m.group(1))
        letter = m.group(2).upper()
        return {
            "kind": "alpha",
            "value": f"{num}{letter}",
            "label": f"n{num.zfill(4)}{letter}",
            "primary": num,
        }

    m = _ISSUE_SIMPLE_RE.match(raw)
    if m:
        num = _strip_leading_zeros(m.group(1))
        return {
            "kind": "zero" if num == "0" else "simple",
            "value": num,
            "label": f"n{num.zfill(4)}",
            "primary": num,
        }

    # Gramática não reconhecida: reverter ao bruto e sinalizar revisão.
    return {"kind": "raw", "value": raw, "label": raw, "primary": raw}


_ISSUE_PREFIX_RE = re.compile(
    r"^(?:n[°º]?\.?|no\.?|numero|numero\.?|#)\s*", re.IGNORECASE
)


def _strip_issue_prefix(value: str) -> str:
    """Remover prefixo opcional de número de fascículo (n., n°, nº, no., numero, #)."""
    return _ISSUE_PREFIX_RE.sub("", value or "").strip()


def is_redundant_issue_designation(
    designation: str | None, number: str | None
) -> bool:
    """Retornar True se a designação for redundante com o número do fascículo.

    Uma designação é considerada redundante quando, após remover prefixos
    comuns (``n.``, ``n°``, ``nº``, ``no.``, ``numero``, ``#``), ela faz parse
    via :func:`parse_issue` para ``kind`` em (``simple``, ``alpha``,
    ``double``) com o mesmo ``value`` de ``parse_issue(number)`` e esse valor
    não for ``'0'``.

    Retorna ``False`` para designações como ``'Edição Especial'``,
    ``'Suplemento'``, ``'N° 0'`` ou quando ``number`` estiver vazio.
    """
    if not number:
        return False
    number_parsed = parse_issue(number)
    number_value = number_parsed.get("value", "")
    if not number_value or number_value == "0":
        return False
    if not designation:
        return False
    cleaned = _strip_issue_prefix(designation)
    if not cleaned:
        return False
    designation_parsed = parse_issue(cleaned)
    designation_kind = designation_parsed.get("kind", "")
    designation_value = designation_parsed.get("value", "")
    if designation_kind not in ("simple", "alpha", "double"):
        return False
    if designation_value == "0":
        return False
    return designation_value == number_value


# ---------------------------------------------------------------------------
# Datas (PT/EN + virada de ano)
# ---------------------------------------------------------------------------

_MONTHS_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11,
    "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

_MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,  # noqa: F601
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_NUM_RE = re.compile(r"\b(0?[1-9]|1[0-2])[./-](19|20)\d{2}\b")
_MONTH_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted({*_MONTHS_PT, *_MONTHS_EN}, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def parse_date(value: str) -> dict[str, int | None]:
    """Extrair mês e ano de data PT/EN.

    Retorna dicionário com ``year``, ``month`` (1-12 ou None), ``raw``. Nunca
    promove um componente isolado de ``07/1986`` a número de fascículo. Suporta
    virada de ano (dezembro/janeiro) quando houver intervalo explícito.
    """
    text = (value or "").strip()
    result: dict[str, int | None] = {"year": None, "month": None, "raw": text}
    if not text:
        return result

    # Ano explícito.
    year_match = _YEAR_RE.search(text)
    if year_match:
        result["year"] = int(year_match.group(0))

    # Mês numérico no contexto MM/AAAA ou M/AAAA.
    mnum = _MONTH_NUM_RE.search(text)
    if mnum:
        result["month"] = int(mnum.group(1))
        if result["year"] is None:
            result["year"] = int(mnum.group(2))
        return result

    # Mês por extenso (PT ou EN).
    mname = _MONTH_NAME_RE.search(text)
    if mname:
        key = mname.group(1).lower()
        result["month"] = _MONTHS_PT.get(key) or _MONTHS_EN.get(key)

    return result


# ---------------------------------------------------------------------------
# Suplemento
# ---------


def supplement_label(value: str | None) -> str | None:
    """Normalizar rótulo de suplemento (ex.: 'supl-01').

    Retorna o rótulo normalizado ou None quando não houver suplemento identificado.
    """
    if not value:
        return None
    s = str(value).strip().lower()
    m = re.search(r"supl\.?\s*-?\s*(\d+)", s)
    if m:
        return f"supl-{m.group(1)}"
    if s in ("suplemento", "supl", "supl."):
        return "supl-00"
    return None


# ---------------------------------------------------------------------------
# Formatadores de exibição e nome ordenável
# ---------------------------------------------------------------------------


def _zero_pad(value: str | None, width: int) -> str:
    if value is None:
        return ""
    s = str(value)
    if s.isdigit():
        return s.zfill(width)
    return s


def format_display_name(
    journal: str,
    year: int | None = None,
    month: int | None = None,
    volume: str | None = None,
    volume_label: str | None = None,
    issue: str | None = None,
    designation: str | None = None,
) -> str:
    """Formatar nome de exibição do fascículo.

    Formato base: ``<Periódico> - <AAAA-MM|AAAA|s.d.> - v<VVV> - n<NNNN>[ - <designação>]``.
    Nunca fabrica mês 01. Volume e número omitidos quando não informados.
    """
    parts: list[str] = [journal or ""]

    if year is not None:
        if month is not None:
            parts.append(f"{year:04d}-{month:02d}")
        else:
            parts.append(f"{year:04d}")
    else:
        parts.append("s.d.")

    if volume is not None:
        vol_str = _zero_pad(volume, 3)
        label = volume_label or "volume"
        parts.append(f"v{vol_str} [{label}]" if label != "volume" else f"v{vol_str}")
    if issue is not None:
        parts.append(f"n{_zero_pad(issue, 4)}")
    if designation:
        parts.append(designation)

    return " - ".join(parts)


def format_sortable_name(
    journal: str,
    year: int | None = None,
    month: int | None = None,
    volume: str | None = None,
    issue: str | None = None,
    designation: str | None = None,
) -> str:
    """Formatar nome ordenável (data primeiro, depois volume e número numéricos)."""
    journal_part = journal or ""
    if year is not None:
        date_part = f"{year:04d}-{month:02d}" if month is not None else f"{year:04d}"
    else:
        date_part = "9999-99"  # datas ausentes vão para o fim

    vol_part = f"v{int(volume):03d}" if volume and volume.isdigit() else "v999"
    iss_part = f"n{int(issue):04d}" if issue and issue.isdigit() else "n9999"
    des_part = designation or ""

    return f"{journal_part} - {date_part} - {vol_part} - {iss_part}{' - ' + des_part if des_part else ''}"


# ---------------------------------------------------------------------------
# Chave serial para L3
# ---------------------------------------------------------------------------


@dataclass
class SerialIdentity:
    """Identidade serial de um fascículo para dedup L3."""

    journal_canonical: str
    journal_sort_key: str
    year: int | None = None
    month: int | None = None
    volume: str | None = None
    volume_label: str | None = None
    issue: str | None = None
    issue_kind: str = ""
    designation: str | None = None
    supplement: str | None = None
    issn: str | None = None

    def key(self) -> str:
        """Chave estável de identidade de série (sem autor, editora ou slogan)."""
        parts = [
            self.journal_sort_key,
            f"y{self.year}" if self.year is not None else "y?",
            f"m{self.month:02d}" if self.month is not None else "m?",
            f"v{self.volume}" if self.volume else "v?",
            f"i{self.issue}" if self.issue else "i?",
            f"s{self.supplement}" if self.supplement else "s?",
            f"issn{self.issn}" if self.issn else "issn?",
        ]
        return "|".join(parts)
