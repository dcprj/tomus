"""Extração de identificadores (DOI, ISBN, ISSN) e detecção de Ficha Catalográfica (Item 13).

Localiza candidatos a DOI por expressão regular estrita (limpando pontuação
terminal) e candidatos a ISBN-10/ISBN-13 validando matematicamente o dígito
verificador via ``python-stdnum`` (``stdnum.isbn.is_valid``). Detecta também
páginas de Ficha Catalográfica CIP por marcadores ABNT.

Fornece funções de normalização canônica (Camada 2 do LibraryIndex):
``normalize_isbn``, ``normalize_issn`` e ``normalize_doi``, aplicando
filtros contra listas negras de identificadores contaminantes.
"""

from __future__ import annotations

import re

from stdnum import isbn as _isbn
from stdnum import issn as _issn

# Expressão regular estrita para DOI (Item 13).
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")

# Pontuação terminal que pode ser capturada indevidamente pela regex.
_TERMINAL_PUNCT = ".,;:!?)]}»’\"'"

# Identificadores contaminantes a serem filtrados (Camada 2 / Sanidade Bibliográfica).
ISBN_BLACKLIST = {
    "9786557826669",
    "9780123456786",
    "9780000000002",
    "9781234567897",
}
DOI_BLACKLIST = {"10.1590/1980-53148425", "10.56083/rcv5n6-015"}


def _clean_doi(candidate: str) -> str:
    """Remove pontuação terminal de um candidato a DOI."""
    cleaned = candidate
    while cleaned and cleaned[-1] in _TERMINAL_PUNCT:
        cleaned = cleaned[:-1]
    return cleaned


def extract_doi(text: str) -> str | None:
    """Extrair o primeiro DOI válido de ``text``, ou ``None``.

    Valida cada candidato com ``normalize_doi`` dentro do loop de extração:
    se o primeiro candidato estiver na blacklist ou for inválido, continua
    buscando os demais candidatos em vez de retornar um placeholder bloqueado.
    """
    for match in DOI_RE.finditer(text):
        candidate = _clean_doi(match.group(0))
        if candidate and normalize_doi(candidate) is not None:
            return candidate
    return None


def extract_isbn(text: str) -> str | None:
    """Extrair o primeiro ISBN-10/ISBN-13 válido de ``text``, ou ``None``.

    A validação do dígito verificador é feita por ``python-stdnum``
    (``stdnum.isbn.is_valid``), rejeitando números arbitrários. Retorna o
    ISBN-13 normalizado (via ``normalize_isbn``), nunca o formato bruto com
    hífens ou espaços.
    """
    # Candidatos a ISBN: sequências de dígitos, hífens e espaços, com opcional
    # sufixo 'X' (dígito verificador do ISBN-10).
    for match in re.finditer(r"\b[\d][\d\- ]{8,}[\dXx]\b", text):
        candidate = match.group(0).replace("-", "").replace(" ", "")
        normalized = normalize_isbn(candidate)
        if normalized is not None:
            return normalized
    return None


def extract_identifiers(text: str) -> tuple[str | None, str | None]:
    """Extrair DOI e ISBN de ``text``.

    Retorna uma tupla ``(detected_doi, detected_isbn)``.
    """
    return extract_doi(text), extract_isbn(text)


# Marcadores de Ficha Catalográfica CIP (Item 13).
CIP_MARKERS = (
    "Ficha catalográfica",
    "Dados Internacionais de Catalogação",
    "CDD",
    "CDU",
    "Bibliotecári",
)


def _is_trivial_isbn_body(s13: str) -> bool:
    """Rejeitar corpos triviais de ISBN-13.

    Retorna True quando os 9 dígitos do corpo (``s13[3:12]``) são compostos
    por um único dígito repetido (ex.: ``000000000``) ou pelas sequências
    exatas ``012345678`` / ``123456789``.
    """
    body = s13[3:12]
    if len(body) == 9 and len(set(body)) == 1:
        return True
    if body in ("012345678", "123456789"):
        return True
    return False


def normalize_isbn(raw: str | None) -> str | None:
    """Normalizar ISBN para ISBN-13 canônico.

    Remove caracteres fora de ``[0-9Xx]``, valida o dígito verificador com
    ``stdnum.isbn.is_valid``, converte ISBN-10 para ISBN-13 via
    ``stdnum.isbn.to_isbn13(stdnum.isbn.compact(s))`` e filtra
    ``ISBN_BLACKLIST``. Rejeita ainda corpos triviais (dígito repetido ou
    sequências exatas). Retorna ``None`` quando inválido ou listrado.
    """
    if not raw:
        return None
    s = re.sub(r"[^0-9Xx]", "", str(raw))
    if not s or not _isbn.is_valid(s):
        return None
    s13 = _isbn.to_isbn13(_isbn.compact(s))
    if s13 in ISBN_BLACKLIST:
        return None
    if _is_trivial_isbn_body(s13):
        return None
    return s13


def normalize_issn(raw: str | None) -> str | None:
    """Normalizar ISSN para forma compacta de 8 caracteres (``XXXXYYYY``).

    Valida com ``stdnum.issn.is_valid`` e compacta via
    ``stdnum.issn.compact``. Retorna ``None`` quando inválido.
    """
    if not raw:
        return None
    s = re.sub(r"[^0-9Xx]", "", str(raw))
    if not s or not _issn.is_valid(s):
        return None
    return _issn.compact(s)


def normalize_doi(raw: str | None) -> str | None:
    """Normalizar DOI para forma canônica em minúsculas.

    Extrai ``10\\.\\d{4,9}/\\S+`` em minúsculas, remove prefixo
    ``doi.org/`` e pontuação terminal, e filtra ``DOI_BLACKLIST``. Retorna
    ``None`` quando inválido ou listrado.
    """
    if not raw:
        return None
    s = str(raw).strip().lower()
    if "doi.org/" in s:
        s = s.split("doi.org/")[-1]
    s = s.strip(".,;:!?)]}»\"'")
    if not re.match(r"^10\.\d{4,9}/\S+$", s) or s in DOI_BLACKLIST:
        return None
    return s


def detect_cip_page(text: str) -> str:
    """Detectar o trecho de Ficha Catalográfica de ``text``.

    Retorna o conteúdo da página/trecho que contiver qualquer marcador CIP, ou
    uma string vazia quando não houver marcador.
    """
    if not text:
        return ""

    # Trabalha linha a linha para isolar o bloco da ficha catalográfica.
    lines = text.splitlines()
    cip_lines: list[str] = []
    in_cip = False

    for line in lines:
        stripped = line.strip()
        if any(marker.lower() in stripped.lower() for marker in CIP_MARKERS):
            in_cip = True
        if in_cip:
            cip_lines.append(line)
            # Encerra o bloco quando encontrar uma linha vazia dupla ou um
            # novo marcador de seção distante (heurística simples).
            if stripped == "" and cip_lines:
                break

    return "\n".join(cip_lines).strip()
