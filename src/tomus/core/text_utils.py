"""Utilitários de normalização de texto (Item 3 do design).

Fornece ``normalize_tex_accents`` para converter marcações de acento típicas de
PDFs gerados por dvips/LaTeX Type1 (acentos espacadores precedentes e ligaduras
tipográficas Unicode) em caracteres Unicode compostos, preservando caminhos de
arquivo (ex.: ``~/path``) e fórmulas (ex.: ``x^2``).
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_tex_accents"]

# Ligaduras tipográficas Unicode -> representação ASCII equivalente.
_LIGATURES: dict[str, str] = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

# Cedilha (espacador \u00b8) seguida, opcionalmente por espaço espurio, de c/C.
_CEDILLA_RE = re.compile(r"\u00b8\s*([cC])")

# Til (espacador \u02dc) seguido, opcionalmente por espaço espurio, de vogal/n.
_TILDE_SMALL_RE = re.compile(r"\u02dc\s*([aAoOnN])")
# Til ASCII '~' precedido por letra e seguido por vogal/n (letra, para não
# tocar em fórmulas como x^2 nem caminhos como ~/path).
_TILDE_RE = re.compile(r"(?<=[A-Za-z])~([aAoOnN])")

# Agudo: acento agudo (\u00b4) ou modificador (\u02ca) seguido de vogal (y
# incluída) ou i sem ponto (\u0131).
_ACUTE_RE = re.compile(r"[\u00b4\u02ca]([aAeEiIoOuUyY\u0131])")

# Circunflexo: modificador \u02c6 seguido de vogal, ou '^' entre letras.
_CIRCUMFLEX_SMALL_RE = re.compile(r"\u02c6([aAeEiIoOuU])")
_CIRCUMFLEX_RE = re.compile(r"(?<=[A-Za-z])\^([aAeEiIoOuU])(?=[A-Za-z])")

# Trema: \u00a8 seguido de vogal (y incluída).
_DIAERESIS_RE = re.compile(r"\u00a8([aAeEiIoOuUyY])")

# Crase: \u02cb seguido de vogal.
_GRAVE_RE = re.compile(r"\u02cb([aAeEiIoOuU])")

_ACUTE_MAP: dict[str, str] = {
    "a": "á",
    "e": "é",
    "i": "í",
    "o": "ó",
    "u": "ú",
    "y": "ý",
    "A": "Á",
    "E": "É",
    "I": "Í",
    "O": "Ó",
    "U": "Ú",
    "Y": "Ý",
    "\u0131": "í",  # i sem ponto -> í
}

_CIRCUMFLEX_MAP: dict[str, str] = {
    "a": "â",
    "e": "ê",
    "i": "î",
    "o": "ô",
    "u": "û",
    "A": "Â",
    "E": "Ê",
    "I": "Î",
    "O": "Ô",
    "U": "Û",
}

_TILDE_MAP: dict[str, str] = {
    "a": "ã",
    "o": "õ",
    "n": "ñ",
    "A": "Ã",
    "O": "Õ",
    "N": "Ñ",
}

_DIAERESIS_MAP: dict[str, str] = {
    "a": "ä",
    "e": "ë",
    "i": "ï",
    "o": "ö",
    "u": "ü",
    "y": "ÿ",
    "A": "Ä",
    "E": "Ë",
    "I": "Ï",
    "O": "Ö",
    "U": "Ü",
    "Y": "Ÿ",
}

_GRAVE_MAP: dict[str, str] = {
    "a": "à",
    "e": "è",
    "i": "ì",
    "o": "ò",
    "u": "ù",
    "A": "À",
    "E": "È",
    "I": "Ì",
    "O": "Ò",
    "U": "Ù",
}


def _replacer(mapping: dict[str, str]):
    """Retornar função de substituição que preserva maiúsculas via mapping direto."""

    def repl(match: re.Match[str]) -> str:
        return mapping.get(match.group(1), match.group(1))

    return repl


def normalize_tex_accents(text: str) -> str:
    """Normalizar acentos espacadores e ligaduras de texto LaTeX/dvips/PDF Type1.

    * Retorna ``''`` para ``None`` ou string vazia.
    * Expande ligaduras tipográficas Unicode (``\ufb00``..``\ufb04``).
    * Compõe acentos espacadores precedentes (cedilha, til, agudo, circunflexo,
      trema, crase) em caracteres Unicode compostos, preservando ``~/path`` e
      fórmulas como ``x^2``.
    * Finaliza com ``unicodedata.normalize('NFC', ...)``.
    """
    if text is None:
        return ""
    text = str(text)
    if not text:
        return ""

    # 1. Ligaduras tipográficas Unicode.
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)

    # 2. Cedilha: \u00b8 seguido (opcionalmente por espaço espurio) de c/C.
    text = _CEDILLA_RE.sub(
        lambda m: "ç" if m.group(1) == "c" else "Ç", text
    )

    # 3. Til: \u02dc e '~' entre letras.
    text = _TILDE_SMALL_RE.sub(_replacer(_TILDE_MAP), text)
    text = _TILDE_RE.sub(_replacer(_TILDE_MAP), text)

    # 4. Agudo (inclui i sem ponto \u0131 -> í).
    def _acute_repl(match: re.Match[str]) -> str:
        ch = match.group(1)
        if ch == "\u0131":
            return "í"
        return _ACUTE_MAP.get(ch, ch)

    text = _ACUTE_RE.sub(_acute_repl, text)

    # 5. Circunflexo: \u02c6 e '^' entre letras (não mexe em x^2 nem ~/path).
    text = _CIRCUMFLEX_SMALL_RE.sub(_replacer(_CIRCUMFLEX_MAP), text)
    text = _CIRCUMFLEX_RE.sub(_replacer(_CIRCUMFLEX_MAP), text)

    # 6. Trema.
    text = _DIAERESIS_RE.sub(_replacer(_DIAERESIS_MAP), text)

    # 7. Crase.
    text = _GRAVE_RE.sub(_replacer(_GRAVE_MAP), text)

    # 8. Composição canônica final.
    return unicodedata.normalize("NFC", text)
