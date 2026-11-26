"""Enriquecimento acadêmico externo via OpenAlex e Google Books (Item 16).

Implementa consultas HTTP com ``httpx`` + ``tenacity`` (3 tentativas, backoff
exponencial, timeout de 8s) para:

* OpenAlex API: busca exata por DOI ou busca por título com similaridade
  ``rapidfuzz.fuzz.token_set_ratio >= 88.0``, incluindo ``mailto:`` no
  ``User-Agent`` quando ``openalex_polite_email`` estiver configurado.
* Google Books API: busca por ISBN validado ou título/autor com rapidfuzz >= 88.0
  e ``&key=`` opcional.

Retorna ``list[ExternalMetadata]`` e expõe
:func:`enrich_document_metadata`.
"""

from __future__ import annotations

import logging
import re
import unicodedata

import httpx
from rapidfuzz import fuzz
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from tomus import __version__
from tomus.core.config import AppConfig
from tomus.core.models import ExternalMetadata, ExtractedDocument
from tomus.core.prompts import is_generic_title
from tomus.extractors.identifiers import (
    normalize_doi,
    normalize_isbn,
)

_logger = logging.getLogger(__name__)

# Limiar de similaridade para buscas por título/autor (Item 16).
_SIMILARITY_THRESHOLD = 88.0

# Similaridade mínima de título para aceitar doi/isbn retornado por busca textual.
_TITLE_SIMILARITY_MIN_FOR_ID = 0.65

# Timeouts e retry (Item 16).
_REQUEST_TIMEOUT = 8.0
_RETRY_ATTEMPTS = 3

_USER_AGENT = f"Tomus/{__version__} (https://github.com/dcprj/tomus)"

__all__ = ["enrich_document_metadata", "select_best_external_metadata"]

# ---------------------------------------------------------------------------
# Normalização e helpers de correspondência textual (Item 16, BUG-ENRICH-01)
# ---------------------------------------------------------------------------

_TEXT_SEARCH_STOPWORDS = {
    "a", "o", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
    "das", "e", "em", "no", "na", "nos", "nas", "por", "para", "com", "sem",
    "sobre", "entre", "que", "ou", "mas", "se", "como", "mais", "menos",
    "the", "an", "and", "or", "of", "in", "on", "at", "to", "for",
    "with", "by", "from",
}

_TEXT_SEARCH_STRUCTURAL_LABELS = {
    "capitulo", "sumario", "prefacio", "introducao", "apresentacao",
    "indice", "anexo", "capa", "ebook", "livro",
}

_ARTICLE_DOCUMENT_TYPES = {
    "article", "journal-article", "editorial", "letter", "erratum",
    "paratext", "review",
}


def _strip_accents(text: str) -> str:
    """Remover acentos via NFKD (decompõe e descarta marcas combinantes)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _normalize_title_for_match(title: str) -> str:
    """Normalizar título para comparação (NFKD sem acentos, minúsculas, alfanumérico/espaços)."""
    if not title:
        return ""
    stripped = _strip_accents(title)
    lowered = stripped.lower()
    alnum = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    return re.sub(r"\s+", " ", alnum).strip()


def _author_surnames(authors: list[str] | None) -> set[str]:
    """Extrair sobrenomes de uma lista de autores.

    Suporta ``'Nome Sobrenome'`` (ultimo token) e ``'Sobrenome, Nome'``
    (ultimo token ANTES da virgula), normalizado sem acento (NFKD) em
    lowercase. Assim ``'Cohen, Rodrigo'`` do PDF casa com
    ``'Rodrigo Cohen'`` das APIs externas.
    """
    surnames: set[str] = set()
    for author in (authors or []):
        raw = str(author).strip()
        if not raw:
            continue
        if "," in raw:
            surname_part = raw.split(",", 1)[0].strip()
        else:
            surname_part = raw.split()[-1]
        surname = _strip_accents(surname_part).lower()
        if surname:
            surnames.add(surname)
    return surnames


def _is_valid_text_search_title(title: str) -> bool:
    """Validar se um título é adequado para busca textual na OpenAlex/Google Books.

    Rejeita títulos normalizados com menos de 12 caracteres alfanuméricos,
    menos de 2 tokens relevantes (ignorando stopwords curtas) ou rótulos
    estruturais genéricos (capítulo, sumário, prefácio, introdução, etc.).
    """
    if not title or not title.strip():
        return False
    normalized = _normalize_title_for_match(title)
    if not normalized:
        return False
    alnum_count = sum(1 for ch in normalized if ch.isalnum())
    if alnum_count < 12:
        return False
    tokens = [t for t in normalized.split() if t and t not in _TEXT_SEARCH_STOPWORDS]
    if len(tokens) < 2:
        return False
    if normalized.strip().lower() in _TEXT_SEARCH_STRUCTURAL_LABELS:
        return False
    return True


def _compute_text_match_score(
    query_title: str,
    api_title: str,
    query_author: str | None = None,
    api_authors: list[str] | None = None,
) -> tuple[bool, float]:
    """Calcular métrica composta de correspondência de título/autor.

    Retorna (accepted, score_0_to_1) onde o score é baseado em sort_score/100.0.
    """
    q = _normalize_title_for_match(query_title)
    a = _normalize_title_for_match(api_title)
    if not q or not a:
        return False, 0.0

    len_ratio = min(len(q), len(a)) / max(1, max(len(q), len(a)))
    if len_ratio < 0.45:
        return False, 0.0

    sort_score = fuzz.token_sort_ratio(q, a)
    set_score = fuzz.token_set_ratio(q, a)

    author_match: bool | None = None
    if query_author and api_authors:
        query_surnames = _author_surnames([query_author])
        api_surnames = _author_surnames(api_authors)
        author_match = bool(query_surnames & api_surnames)

    accepted = (
        (sort_score >= 86.0 and not (author_match is False and sort_score < 92.0))
        or (set_score >= 92.0 and len_ratio >= 0.65 and author_match is True)
    )

    score = min(1.0, max(0.0, sort_score / 100.0))
    return accepted, score


# ---------------------------------------------------------------------------
# Cliente HTTP com retry (tenacity)
# ---------------------------------------------------------------------------


def _is_enricher_retryable(exc: BaseException) -> bool:
    """Retornar True para erros transitórios (429, 5xx ou falha de transporte/timeout)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def _retryable() -> httpx.Client:
    """Criar um cliente httpx com timeout de 8s."""
    return httpx.Client(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT})


@retry(
    retry=retry_if_exception(_is_enricher_retryable),
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _get_json(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    """GET JSON com retry de 3 tentativas e backoff exponencial."""
    resp = client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def _openalex_user_agent(email: str | None) -> str:
    """Montar o User-Agent com mailto quando o e-mail polite estiver configurado."""
    if email:
        return f"{_USER_AGENT} (mailto:{email})"
    return _USER_AGENT


def _query_openalex_by_doi(client: httpx.Client, doi: str, email: str | None) -> list[ExternalMetadata]:
    """Busca exata por DOI na OpenAlex com retry para erros transitórios."""
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    headers = {"User-Agent": _openalex_user_agent(email)}
    try:
        data = _get_json(client, url, params=None, headers=headers)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return []
        raise
    return [_openalex_to_metadata(data, score=1.0, match_origin="exact_doi")]


def _query_openalex_by_title(client: httpx.Client, title: str, email: str | None) -> list[ExternalMetadata]:
    """Busca por título na OpenAlex, aplicando filtro pré-consulta e métrica composta."""
    if not _is_valid_text_search_title(title):
        return []
    url = "https://api.openalex.org/works"
    headers = {"User-Agent": _openalex_user_agent(email)}
    params = {"search": title, "per-page": 10}
    data = _get_json(client, url, params=params, headers=headers)
    results = data.get("results", []) or []
    metadata: list[ExternalMetadata] = []
    for item in results:
        api_title = item.get("title") or ""
        accepted, score = _compute_text_match_score(title, api_title)
        if accepted:
            metadata.append(
                _openalex_to_metadata(item, score=score, match_origin="text_search")
            )
    return metadata


def _openalex_to_metadata(
    item: dict, score: float, match_origin: str = "text_search"
) -> ExternalMetadata:
    """Converter um item da OpenAlex em :class:`ExternalMetadata`."""
    authors = []
    for authorship in (item.get("authorships") or []):
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(name)
    publication_year = item.get("publication_year")
    concepts = []
    for concept in (item.get("concepts") or []):
        name = concept.get("display_name")
        if name:
            concepts.append(name)

    primary_loc = item.get("primary_location") or {}
    source_obj = primary_loc.get("source") or {}
    journal_name = source_obj.get("display_name")

    biblio = item.get("biblio") or {}
    volume = biblio.get("volume")
    number = biblio.get("issue")
    first_page = biblio.get("first_page")
    last_page = biblio.get("last_page")
    pages = f"{first_page}-{last_page}" if first_page and last_page else (str(first_page) if first_page else None)

    doi_raw = item.get("doi")
    doi = doi_raw.split("doi.org/")[-1] if doi_raw and "doi.org/" in str(doi_raw) else doi_raw
    doi = normalize_doi(doi) or None

    return ExternalMetadata(
        source="openalex",
        title=item.get("title") or "",
        subtitle="",
        authors=authors,
        publication_year=publication_year,
        journal_name=journal_name,
        volume=str(volume) if volume is not None else None,
        number=str(number) if number is not None else None,
        pages=pages,
        doi=doi,
        document_type_hint=item.get("type"),
        concepts=concepts,
        match_score=score,
        match_origin=match_origin,
    )


# ---------------------------------------------------------------------------
# Google Books
# ---------------------------------------------------------------------------


def _query_google_books_by_isbn(client: httpx.Client, isbn: str, api_key: str | None) -> list[ExternalMetadata]:
    """Busca exata por ISBN na Google Books."""
    url = "https://www.googleapis.com/books/v1/volumes"
    params: dict = {"q": f"isbn:{isbn}"}
    if api_key:
        params["key"] = api_key
    data = _get_json(client, url, params)
    items = data.get("items") or []
    return [
        _google_books_to_metadata(item, score=1.0, match_origin="exact_isbn")
        for item in items
    ]


def _query_google_books_by_title_author(
    client: httpx.Client, title: str, author: str | None, api_key: str | None
) -> list[ExternalMetadata]:
    """Busca por título/autor na Google Books, aplicando filtro pré-consulta e métrica composta."""
    if not _is_valid_text_search_title(title):
        return []
    url = "https://www.googleapis.com/books/v1/volumes"
    query = title if not author else f"{title} {author}"
    params: dict = {"q": query, "maxResults": 10}
    if api_key:
        params["key"] = api_key
    data = _get_json(client, url, params)
    items = data.get("items") or []
    metadata: list[ExternalMetadata] = []
    for item in items:
        volume_info = item.get("volumeInfo") or {}
        api_title = volume_info.get("title") or ""
        api_authors = list(volume_info.get("authors") or [])
        accepted, score = _compute_text_match_score(
            title, api_title, query_author=author, api_authors=api_authors
        )
        if accepted:
            metadata.append(
                _google_books_to_metadata(
                    item, score=score, match_origin="text_search"
                )
            )
    return metadata


def _google_books_to_metadata(
    item: dict, score: float, match_origin: str = "text_search"
) -> ExternalMetadata:
    """Converter um item da Google Books em :class:`ExternalMetadata`."""
    volume_info = item.get("volumeInfo") or {}
    authors = list(volume_info.get("authors") or [])
    pub_date = volume_info.get("publishedDate")
    publication_year: int | None = None
    if pub_date:
        try:
            publication_year = int(str(pub_date)[:4])
        except ValueError:
            publication_year = None

    publisher = volume_info.get("publisher")
    page_count = volume_info.get("pageCount")
    pages = f"{page_count} p." if page_count else None

    industry_ids = volume_info.get("industryIdentifiers") or []
    isbn: str | None = None
    for id_entry in industry_ids:
        t = id_entry.get("type")
        val = id_entry.get("identifier")
        if t in ("ISBN_13", "ISBN_10") and val:
            isbn = normalize_isbn(val)
            if isbn:
                break

    return ExternalMetadata(
        source="google_books",
        title=volume_info.get("title") or "",
        subtitle=volume_info.get("subtitle") or "",
        authors=authors,
        publication_year=publication_year,
        publisher=publisher,
        pages=pages,
        isbn=isbn,
        document_type_hint=volume_info.get("printType"),
        concepts=list(volume_info.get("categories") or []),
        match_score=score,
        match_origin=match_origin,
    )


# ---------------------------------------------------------------------------
# Orquestrador de enriquecimento
# ---------------------------------------------------------------------------


def _extract_title_author_candidates(doc: ExtractedDocument) -> tuple[str, str | None]:
    """Extrair candidatos distintos de título e autor a partir de metadados nativos ou linhas do texto."""
    native = doc.native_metadata or {}
    native_title = str(native.get("title") or "").strip()
    native_author = str(native.get("author") or "").strip()

    non_empty_lines = [
        line.strip() for line in (doc.sampled_text or "").splitlines() if line.strip()
    ]
    title_candidate = (
        native_title
        if native_title and not is_generic_title(native_title)
        else (non_empty_lines[0] if non_empty_lines else "")
    )
    author_candidate: str | None = None
    if native_author:
        author_candidate = native_author
    elif len(non_empty_lines) >= 2 and non_empty_lines[1] != title_candidate:
        author_candidate = non_empty_lines[1]

    return title_candidate, author_candidate


def enrich_document_metadata(
    doc: ExtractedDocument, config: AppConfig
) -> list[ExternalMetadata]:
    """Enriquecer um :class:`ExtractedDocument` com metadados externos.

    Consulta OpenAlex por DOI (exato) ou título, e Google Books por ISBN
    (exato) ou título/autor, retornando uma lista de
    :class:`ExternalMetadata` válidos (similaridade >= 88.0 para buscas
    textuais).

    Regras de sanidade (Camada 2 / anti-contaminação cruzada):
      - Resultados de busca textual com match_score < 0.65 e que carreguem
        doi/isbn são descartados.
      - doi/isbn presentes em ISBN_BLACKLIST / DOI_BLACKLIST são anulados
        (já normalizados em ``_openalex_to_metadata`` / ``_google_books_to_metadata``
        e descartados quando listrados).
    """
    email = config.api_keys.openalex_polite_email or None
    google_key = config.api_keys.google_books_api_key or None

    results: list[ExternalMetadata] = []
    title_candidate, author_candidate = _extract_title_author_candidates(doc)

    with _retryable() as client:
        # OpenAlex: busca exata por DOI, senão por título.
        if doc.detected_doi:
            try:
                results.extend(_query_openalex_by_doi(client, doc.detected_doi, email))
            except Exception as exc:  # falha transitória na OpenAlex por DOI
                _logger.warning("OpenAlex por DOI falhou: %s", exc)
        elif title_candidate and _is_valid_text_search_title(title_candidate):
            try:
                results.extend(
                    _query_openalex_by_title(client, title_candidate, email)
                )
            except Exception as exc:  # falha transitória na OpenAlex por título
                _logger.warning("OpenAlex por título falhou: %s", exc)

        # Google Books: busca exata por ISBN, senão por título/autor.
        if doc.detected_isbn:
            try:
                results.extend(_query_google_books_by_isbn(client, doc.detected_isbn, google_key))
            except Exception as exc:  # falha transitória na Google Books por ISBN
                _logger.warning("Google Books por ISBN falhou: %s", exc)
        elif title_candidate and _is_valid_text_search_title(title_candidate):
            try:
                results.extend(
                    _query_google_books_by_title_author(
                        client, title_candidate, author_candidate, google_key
                    )
                )
            except Exception as exc:  # falha transitória na Google Books por título/autor
                _logger.warning("Google Books por título/autor falhou: %s", exc)

    # Filtro de sanidade: descartar resultados de busca textual com
    # similaridade baixa que carreguem identificadores (evita contaminação cruzada).
    filtered: list[ExternalMetadata] = []
    for m in results:
        has_identifier = bool(m.doi or m.isbn)
        if has_identifier and m.match_score < _TITLE_SIMILARITY_MIN_FOR_ID:
            continue
        filtered.append(m)

    # Filtro estrutural anti-artigo em livros (OpenAlex textual):
    # se o documento parece um livro (muitas páginas, ISBN ou CIP), descarta
    # resultados de busca textual da OpenAlex cujo tipo seja artigo/paratexto.
    is_book_like = (
        doc.total_pages >= 80 or bool(doc.detected_isbn) or bool(doc.cip_text)
    )
    if is_book_like:
        structurally_filtered: list[ExternalMetadata] = []
        for m in filtered:
            if (
                m.source == "openalex"
                and m.match_origin == "text_search"
                and (m.document_type_hint or "").strip().lower()
                in _ARTICLE_DOCUMENT_TYPES
            ):
                continue
            structurally_filtered.append(m)
        filtered = structurally_filtered

    return filtered


def select_best_external_metadata(
    doc: ExtractedDocument, candidates: list[ExternalMetadata]
) -> ExternalMetadata | None:
    """Selecionar o melhor metadado externo por pontuação determinística.

    Perfil do documento:
      - looks_like_book: ISBN, CIP ou >= 60 páginas.
      - looks_like_article: DOI, ou <= 45 páginas sem ISBN/CIP.

    Pontuação:
      - exact_doi / exact_isbn: base 1000 (+100 se fonte alinhada ao perfil:
        google_books para livro, openalex para artigo).
      - text_search: base match_score * 100, mais bônus/penalidades por tipo
        de fonte e confirmação de sobrenome de autor.

    Retorna o candidato de maior pontuação, ou None quando a lista está vazia.
    """
    if not candidates:
        return None

    looks_like_book = (
        bool(doc.detected_isbn)
        or bool(doc.cip_text)
        or (doc.total_pages or 0) >= 60
    )
    looks_like_article = bool(doc.detected_doi) or (
        (doc.total_pages or 0) <= 45
        and not doc.detected_isbn
        and not doc.cip_text
    )

    _title_candidate, author_candidate = _extract_title_author_candidates(doc)

    def _score(m: ExternalMetadata) -> float:
        base = 0.0
        if m.match_origin in ("exact_doi", "exact_isbn"):
            base = 1000.0
            if looks_like_book and m.source == "google_books":
                base += 100.0
            if looks_like_article and m.source == "openalex":
                base += 100.0
        elif m.match_origin == "text_search":
            base = m.match_score * 100.0
            dt = (m.document_type_hint or "").strip().lower()
            if looks_like_book:
                if m.source == "google_books" or dt in (
                    "book",
                    "monograph",
                    "edited-book",
                    "reference-book",
                ):
                    base += 25.0
                if m.source == "openalex" and dt in _ARTICLE_DOCUMENT_TYPES:
                    base -= 40.0
            if looks_like_article and m.source == "openalex":
                base += 25.0
        if author_candidate and _author_surnames(
            [author_candidate]
        ) & _author_surnames(m.authors):
            base += 15.0
        return base

    return max(candidates, key=_score)
