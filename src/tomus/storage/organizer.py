"""Materializador de diretórios e controle de deduplicação/obsolescência (Item 21).

Organiza arquivos aprovados em
<TARGET_DIR>/<Área Básica>/<Subárea>/<Tipo>/<nome_formatado>.pdf,
duplicatas da mesma edição em <TARGET_DIR>/duplicatas/,
edições superadas (mais antigas) em <TARGET_DIR>/obsoletos/, e
arquivos de baixa confiança/erro em <TARGET_DIR>/revisao_manual/.

Implementa a classe ``LibraryIndex`` com detecção em 3 camadas:
  1. SHA-256 global (entre todas as subáreas/pastas) -> duplicatas/
  2. DOI / ISBN-13 / ISSN normalizados + Guardas G1/G2/G3 -> duplicatas/ ou obsoletos/
  3. Impressão digital bibliográfica (work_fingerprint) + Guardas G1/G2/G3 -> duplicatas/ ou obsoletos/

Quando uma edição mais recente chega para uma obra já classificada, realiza
substituição reversa segura (validada por ``_is_within``), movendo a edição
antiga para ``obsoletos/`` e promovendo a nova para a árvore temática.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tomus.core.models import (
    ExecutionSummary,
    FileManifestEntry,
    ProcessStatus,
)
from tomus.core.periodicals import canonical_journal, journal_sort_key
from tomus.core.prompts import extract_first_author_key
from tomus.extractors.identifiers import (
    normalize_doi,
    normalize_isbn,
    normalize_issn,
)
from tomus.storage.companion import (
    generate_companion_markdown,
    generate_duplicate_companion_markdown,
    generate_obsolete_companion_markdown,
)
from tomus.storage.namer import MAX_BYTES, WIN_SAFE_FULL_PATH_CHARS
from tomus.storage.namer import _strip_trailing_punct as _strip_trailing_punct_organizer

REVISAO_DIR = "revisao_manual"
DUPLICATAS_DIR = "duplicatas"
OBSOLETOS_DIR = "obsoletos"
MANIFEST_FILENAME = "manifest.json"
RELATORIO_FILENAME = "relatorio_revisao.md"
COLLISION_SUFFIX = " (2)"

_NON_CANONICAL_DIRS = {REVISAO_DIR, DUPLICATAS_DIR, OBSOLETOS_DIR}
_FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)

# --------------------------------------------------------------------------- #
# Constantes e helpers para Guardas G1/G2/G3 e impressão digital (work_fingerprint)
# --------------------------------------------------------------------------- #
_STOPWORDS = set(
    "a o as os um uma uns umas de da do das dos d e em no na nos nas num numa "
    "para pra por pelo pela pelos pelas com sem sobre entre ao aos à às the of "
    "and in on for to an la le les el los las del des du un une und der die das ein eine y".split()
)

_GENERIC_SUBTITLE_WORDS = set(
    "obras escolhidas obras completas edicao revista ampliada atualizada "
    "introducao estudo estudos teoria pratica aplicacoes volume vol livro parte".split()
)

_ROMAN_NUMERALS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20, "xxi": 21,
    "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25, "xxvi": 26, "xxvii": 27,
}

_DISC_WORDS = {
    "vol": "vol", "volume": "vol", "v": "vol", "tomo": "vol", "t": "vol",
    "parte": "part", "part": "part", "pt": "part",
    "livro": "livro", "book": "livro", "seminario": "livro", "seminar": "livro", "libro": "livro",
    "caderno": "part", "modulo": "part",
}

_DISC_RE = re.compile(
    r"\b(" + "|".join(sorted(_DISC_WORDS, key=len, reverse=True))
    + r")(?:(?<=\w\w)\s*[:.-]?\s*|(?:\s*[:.-]\s*|\s+))0*(\d{1,3}|[ivxl]{1,6})\b"
)

_AUDIENCE_WORDS = {
    "paciente": "paciente", "pacientes": "paciente",
    "cliente": "paciente", "clientes": "paciente",
    "terapeuta": "terapeuta", "terapeutas": "terapeuta", "clinico": "terapeuta",
    "aluno": "aluno", "estudante": "aluno", "professor": "professor",
    "exercicios": "exercicios", "workbook": "exercicios",
    "instrutor": "professor", "facilitador": "professor", "cuidador": "cuidador",
}

_FILENAME_NOISE_RE = re.compile(
    r"\b(z library|zlibrary|pdfdrive|libgen|completo|www|pdf|ebook|scan|copia)\b"
)

_SERIES_PREFIX_RE = re.compile(
    r"^(obras?\s+completas?|obras?\s+psicologicas?\s+completas?|obras?\s+escolhidas?|"
    r"o\s+seminario|el\s+seminario|seminario|colecao\s+os\s+pensadores)\b"
)

_SYNTHETIC_TEST_TITLES = {
    "titulo de teste",
    "titulo teste",
    "livro de teste",
    "livro teste",
    "obra de teste",
    "obra teste",
}

MIN_PAGE_RATIO = 0.25


def _fold_text(value: Any) -> str:
    """Normalizar texto para comparação (sem acentos, minúsculas, alfanumérico)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " e ")
    text = re.sub(r"\(\s*(?:os?|as?)\s*\)", " ", text)
    text = re.sub(r"\bpsicologasos\b", "psicologas", text)
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(text.split())


def _is_within(child: Path, parent: Path) -> bool:
    """Validar que ``child`` está estritamente contido dentro de ``parent``."""
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except OSError:
        return False


def _parse_front_matter_safe(md_path: Path) -> dict[str, Any] | None:
    """Analisar front matter YAML de um .md companheiro sem usar eval()."""
    try:
        raw = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _FM_RE.match(raw)
    if not match:
        return None

    data: dict[str, Any] = {}
    current_key: str | None = None
    for line in match.group(1).splitlines():
        if line.startswith("  - ") and current_key:
            item_raw = line[4:].strip()
            try:
                item_val = ast.literal_eval(item_raw)
            except (ValueError, SyntaxError):
                item_val = item_raw.strip("'\"")
            existing = data.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(item_val)
            continue

        if ":" in line:
            k, _, v = line.partition(":")
            current_key = k.strip()
            val_raw = v.strip()
            if not val_raw:
                continue
            low = val_raw.lower()
            if low == "true":
                data[current_key] = True
            elif low == "false":
                data[current_key] = False
            elif low in ("null", "none"):
                data[current_key] = None
            else:
                try:
                    data[current_key] = ast.literal_eval(val_raw)
                except (ValueError, SyntaxError):
                    data[current_key] = val_raw.strip("'\"")
    return data


_ISSUE_RE = re.compile(
    r"\b("
    r"n\.|no\.|num|numero|nro|issue|iss\.|fasc|fasciculo|ed\.|edicao"
    r")"
    r"(?:(?<=\w\w)\s*[:.-]?\s*|(?:\s*[:.-]\s*|\s+))"
    r"0*(\d{1,4})\b"
)

# Mês / bimestre em periódicos (jan..dez ou MM/AAAA).
_PERIOD_M_RE = re.compile(
    r"\b(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"\d{1,2}/\d{4})\b"
)

# Número isolado no fim do título/filename para periódicos (ex.: 'Revista #12', 'Micro Sistemas 045').
_ISOLATED_NUM_RE = re.compile(r"(?:#|n(?:o|\.)?\s*)?0*(\d{1,4})\s*$")


def _extract_discriminators(
    title: str,
    subtitle: str,
    orig_filename: str,
    volume_field: str | None = None,
    number_field: str | None = None,
    tipo: str = "",
    year: int | None = None,
    is_serial: bool = False,
) -> dict[str, str]:
    """Extrair discriminadores estruturais (vol, part, livro, aud, issue, period_m) para Guarda G1."""
    out: dict[str, str] = {}
    for text in (title, subtitle):
        folded = _fold_text(text)
        for m in _DISC_RE.finditer(folded):
            kind, val = _DISC_WORDS[m.group(1)], m.group(2)
            if val.isdigit():
                if 1 <= int(val) <= 60:
                    out.setdefault(kind, str(int(val)))
            elif val in _ROMAN_NUMERALS:
                out.setdefault(kind, str(_ROMAN_NUMERALS[val]))
        for tok in folded.split():
            if tok in _AUDIENCE_WORDS:
                out.setdefault("aud", _AUDIENCE_WORDS[tok])

    # --- 'vol' para TODOS os tipos (não apenas Livro/Outros) ---
    if volume_field:
        vf = _fold_text(str(volume_field))
        m_num = re.search(r"\b(\d{1,2})\b", vf)
        if m_num:
            v_int = int(m_num.group(1))
            ctx = _fold_text(f"{title} {subtitle} {orig_filename}")
            if v_int in (1, 2, 3, 4) or any(
                w in ctx for w in ("vol", "volume", "tomo", "seminario", "obras completas", "oc ")
            ):
                out.setdefault("vol", str(v_int))
        elif vf in _ROMAN_NUMERALS:
            out.setdefault("vol", str(_ROMAN_NUMERALS[vf]))

    # --- 'issue' (número/fascículo) de número_field OU regex ---
    issue_val = None
    if number_field:
        nf = _fold_text(str(number_field))
        m = re.search(r"\b(\d{1,4})\b", nf)
        if m:
            n_int = int(m.group(1))
            # Ignorar anos 1900..2099.
            if not (1900 <= n_int <= 2099):
                issue_val = str(n_int)
    if issue_val is None:
        for text in (title, subtitle, orig_filename):
            folded = _fold_text(text)
            for m in _ISSUE_RE.finditer(folded):
                disc_word = m.group(1)
                # 'ed.' / 'edicao' indicam edicao de livro, nao fasciculo de
                # periodico: so usar como issue para seriais/revistas cientificas.
                if disc_word in ("ed.", "edicao") and not (
                    is_serial or tipo == "Revista Científica"
                ):
                    continue
                val = m.group(2)
                n_int = int(val)
                if 1900 <= n_int <= 2099:
                    continue
                issue_val = str(n_int)
                break
            if issue_val is not None:
                break
    if issue_val is not None:
        out["issue"] = issue_val

    # Número isolado no fim do título/filename para periódicos.
    if is_serial or tipo == "Revista Científica":
        for text in (title, orig_filename):
            m = _ISOLATED_NUM_RE.search(_fold_text(text))
            if m:
                n_int = int(m.group(1))
                if not (1900 <= n_int <= 2099):
                    out.setdefault("issue", str(n_int))
                    break

    # --- 'period_m' (mês/bimestre em periódicos) ---
    if is_serial or tipo == "Revista Científica":
        for text in (title, subtitle, orig_filename):
            folded = _fold_text(text)
            m = _PERIOD_M_RE.search(folded)
            if m:
                tok = m.group(1)
                if "/" in tok:
                    out.setdefault("period_m", tok)
                else:
                    mes_map = {
                        "jan": "01", "fev": "02", "mar": "03", "abr": "04",
                        "mai": "05", "jun": "06", "jul": "07", "ago": "08",
                        "set": "09", "out": "10", "nov": "11", "dez": "12",
                        "january": "01", "february": "02", "march": "03",
                        "april": "04", "may": "05", "june": "06",
                        "july": "07", "august": "08", "september": "09",
                        "october": "10", "november": "11", "december": "12",
                    }
                    out.setdefault("period_m", mes_map.get(tok, tok))
                break

    orig_stem = re.sub(r"\(\d+\)$", "", Path(orig_filename or "").stem.strip())
    f_orig = _FILENAME_NOISE_RE.sub(" ", _fold_text(orig_stem))
    for m in _DISC_RE.finditer(f_orig):
        kind, val = _DISC_WORDS[m.group(1)], m.group(2)
        if val.isdigit() and 1 <= int(val) <= 40:
            if kind == "livro" and "colecao" in f_orig and "seminario" not in f_orig:
                continue
            out.setdefault(kind, str(int(val)))
        elif val in _ROMAN_NUMERALS:
            out.setdefault(kind, str(_ROMAN_NUMERALS[val]))
    for tok in f_orig.split():
        if tok in _AUDIENCE_WORDS:
            out.setdefault("aud", _AUDIENCE_WORDS[tok])
    return out


def _build_title_fingerprint(title: str, subtitle: str) -> tuple[str, str, set[str], bool]:
    """Retornar (main_title_key, full_title_key, subtitle_distinct_tokens, is_weak)."""
    folded_title = _fold_text(title)
    if folded_title in _SYNTHETIC_TEST_TITLES:
        return folded_title, folded_title, set(), True

    t_clean = _DISC_RE.sub(" ", folded_title)
    t_clean = _SERIES_PREFIX_RE.sub(" ", t_clean).strip()
    t_tokens = [
        t for t in t_clean.split()
        if t not in _STOPWORDS and not re.fullmatch(r"(1[5-9]|20)\d\d", t)
    ]

    s_clean = _DISC_RE.sub(" ", _fold_text(subtitle))
    s_clean = _SERIES_PREFIX_RE.sub(" ", s_clean).strip()
    s_tokens = [
        t for t in s_clean.split()
        if t not in _STOPWORDS and not re.fullmatch(r"(1[5-9]|20)\d\d", t)
    ]

    if not t_tokens and s_tokens:
        t_tokens = s_tokens
        s_tokens = []

    main_key = " ".join(t_tokens)
    full_key = " ".join(t_tokens + [t for t in s_tokens if t not in t_tokens])
    sub_distinct = set(s_tokens) - set(t_tokens) - _GENERIC_SUBTITLE_WORDS
    is_weak = len(t_tokens) == 0 or (len(t_tokens) == 1 and len(t_tokens[0]) < 5)
    return main_key, full_key, sub_distinct, is_weak


def _parse_edition(
    ed_str: str | None,
    title: str = "",
    subtitle: str = "",
    orig_filename: str = "",
) -> tuple[int | None, int]:
    """Extrair ``(edition_number, revision_flag)``, ex.: DSM-5 -> (5, 0), DSM-5-TR -> (5, 1)."""
    combined = _fold_text(f"{title} {subtitle} {orig_filename}")
    rev = 1 if re.search(r"\bdsm\s*5\s*tr\b|\btexto\s+revisado\b|\brev\b", combined) else 0
    if ed_str:
        f_ed = _fold_text(str(ed_str))
        if f_ed not in ("nao especificada", "none", "null", ""):
            m = re.search(r"\b(\d{1,2})\b", f_ed)
            if m and 1 <= int(m.group(1)) <= 50:
                return int(m.group(1)), rev
    m_orig = re.search(r"\b(\d{1,2})\s*(?:a|o)?\s*ed(?:icao)?\b", _fold_text(orig_filename))
    if m_orig and 1 <= int(m_orig.group(1)) <= 50:
        return int(m_orig.group(1)), rev
    if re.search(r"\bdsm\s*5\b", combined):
        return 5, rev
    return None, rev


def _parse_year(y: int | str | None) -> int | None:
    if y is None:
        return None
    m = re.search(r"\b(1[5-9]\d\d|20[0-2]\d)\b", str(y))
    return int(m.group(1)) if m else None


def is_structurally_compatible(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    via_identifier: bool = False,
) -> bool:
    """Aplicar Guardas G1 (discriminadores), G2 (proporção de páginas) e G3 (subtítulos)."""
    da, db = a["_disc"], b["_disc"]

    # NUNCA parear Artigo <-> Revista fora de L1.
    a_rev, b_rev = _tipo_eh_revista(a), _tipo_eh_revista(b)
    if a_rev != b_rev:
        return False

    for k in ("part", "aud", "livro"):
        if da.get(k) != db.get(k):
            return False

    # --- Guarda G4: discriminadores de periódico (issue/vol/period_m/ano/ed) ---
    # Sempre checar 'issue': se divergem, não são compatíveis.
    if da.get("issue") != db.get("issue"):
        return False

    if "vol" in da and "vol" in db and da["vol"] != db["vol"]:
        return False
    if ("vol" in da) != ("vol" in db):
        if any(w in _fold_text(a.get("titulo", "")) for w in ("seminario", "obras completas", "colecao")):
            return False

    a_serial = bool(a.get("_is_serial"))
    b_serial = bool(b.get("_is_serial"))
    if a_serial or b_serial:
        if da.get("vol") != db.get("vol"):
            return False
        if da.get("period_m") and db.get("period_m") and da["period_m"] != db["period_m"]:
            return False
        if a.get("_year") and b.get("_year") and a["_year"] != b["_year"]:
            return False
        if a.get("_ed") and b.get("_ed") and a["_ed"] != b["_ed"]:
            return False

    pa, pb = a.get("_pages"), b.get("_pages")
    if pa and pb:
        if min(pa, pb) / max(pa, pb) < MIN_PAGE_RATIO:
            return False

    sa, sb = a["_sub_tokens"], b["_sub_tokens"]
    if sa and sb and sa.isdisjoint(sb) and len(a["_tkey"].split()) <= 3:
        return False

    if via_identifier:
        ta = set(a["_tkey"].split())
        tb = set(b["_tkey"].split())
        jacc = len(ta & tb) / max(1, len(ta | tb))
        same_author = bool(a["_akey"] and a["_akey"] == b["_akey"])
        if jacc < 0.70 and not (same_author and jacc >= 0.50) and a["_fkey"] != b["_fkey"]:
            return False

    return True


def compare_editions(inc: dict[str, Any], can: dict[str, Any]) -> tuple[str, str]:
    """Comparar duas versões da mesma obra e decidir ``DUPLICATE`` vs ``OBSOLETE``.

    Retorna ``(verdict, winner)``:
      * ``('DUPLICATE', 'can')``: mesma edição e mesmo ano -> manter canônico, entrante vai para ``duplicatas/``.
      * ``('OBSOLETE', 'can')``: canônico é mais recente -> entrante vai para ``obsoletos/``.
      * ``('OBSOLETE', 'inc')``: entrante é mais recente -> substitui canônico e antigo vai para ``obsoletos/``.
    """
    yr_inc, yr_can = inc["_year"], can["_year"]
    ed_inc, rev_inc = inc["_ed"], inc["_rev"]
    ed_can, rev_can = can["_ed"], can["_rev"]

    if yr_inc is not None and yr_can is not None and yr_inc != yr_can:
        return ("OBSOLETE", "inc") if yr_inc > yr_can else ("OBSOLETE", "can")

    if ed_inc is not None and ed_can is not None and (ed_inc, rev_inc) != (ed_can, rev_can):
        return ("OBSOLETE", "inc") if (ed_inc, rev_inc) > (ed_can, rev_can) else ("OBSOLETE", "can")

    if (yr_inc is not None) != (yr_can is not None):
        return ("OBSOLETE", "inc") if yr_inc is not None else ("OBSOLETE", "can")

    return ("DUPLICATE", "can")


def _tipo_eh_revista(rec: dict[str, Any]) -> bool:
    return str(rec.get("tipo") or "") in ("Revista", "Revista Científica")


def _issn_issue_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Regra forte de exemplar para L2_ISSN de periódicos.

    Exigir número estruturado idêntico E volume ou ano civil compatível,
    designação compatível, ausência de conflito nos demais campos conhecidos.
    """
    da, db = a.get("_disc", {}), b.get("_disc", {})

    # Número estruturado idêntico.
    if da.get("issue") != db.get("issue"):
        return False

    # Volume ou ano civil compatível.
    vol_a, vol_b = da.get("vol"), db.get("vol")
    if vol_a is not None and vol_b is not None and vol_a != vol_b:
        return False
    yr_a, yr_b = a.get("_year"), b.get("_year")
    if yr_a is not None and yr_b is not None and yr_a != yr_b:
        return False

    # Designação compatível.
    des_a, des_b = a.get("_issue_designation"), b.get("_issue_designation")
    if des_a is not None and des_b is not None and str(des_a) != str(des_b):
        return False
    sup_a, sup_b = a.get("_supplement"), b.get("_supplement")
    if sup_a is not None and sup_b is not None and str(sup_a) != str(sup_b):
        return False

    # Periódico canônico igual (quando conhecido).
    ja, jb = a.get("_journal_canonical"), b.get("_journal_canonical")
    if ja and jb and ja != jb:
        return False

    return True


def _journal_serial_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Regra forte de exemplar para L3_FINGERPRINT de periódicos.

    Periódico canônico de série desambiguada + mesmo número, volume/ano e
    designação. Autor, editora, slogan e stem saneado não entram.
    """
    ja, jb = a.get("_journal_canonical"), b.get("_journal_canonical")
    if not ja or not jb or ja != jb:
        return False
    return _issn_issue_compatible(a, b)


def _read_pdf_page_count(pdf_path: Path) -> int | None:
    """Ler quantidade de páginas de um PDF de forma tolerante a falhas."""
    try:
        if not pdf_path.exists():
            return None
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            return int(doc.page_count)
    except Exception:
        return None


class LibraryIndex:
    """Índice em memória da biblioteca para deduplicação e controle de obsolescência."""

    def __init__(self) -> None:
        self.seen_by_sha: dict[str, dict[str, Any]] = {}
        self.canon_by_sha: dict[str, dict[str, Any]] = {}
        self.by_doi: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_isbn: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_issn: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_journal: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)

    @staticmethod
    def build_record(
        *,
        sha256: str,
        classification: dict[str, Any] | None,
        source_path: Path,
        pdf_path: Path,
        pages: int | None = None,
        from_same_run: bool = False,
    ) -> dict[str, Any]:
        """Construir o registro indexável normalizado de um documento."""
        cls = classification or {}
        # Chaves de classificação são lidas em português (padrão do projeto),
        # com fallback para chaves em inglês provenientes do classificador LLM
        # ou de registros em cache gravados em versões anteriores.
        authors = list(cls.get("autores") or cls.get("authors") or [])
        title = str(cls.get("titulo") or cls.get("title") or "")
        subtitle = str(cls.get("subtitulo") or cls.get("subtitle") or "")
        orig_filename = str(cls.get("arquivo_origem") or source_path.name)
        edition_raw = cls.get("edicao") or cls.get("edition")
        year_raw = cls.get("ano") if cls.get("ano") is not None else cls.get("year")
        tipo = str(cls.get("tipo") or "")
        volume_field = cls.get("volume_label") or cls.get("volume")
        number_field = cls.get("numero") or cls.get("number")
        issn = normalize_issn(cls.get("issn"))
        _is_serial = (tipo in ("Revista", "Revista Científica")) or bool(issn)
        year = _parse_year(year_raw)

        # --- Campos seriais (PR #14) ---
        journal_name = str(cls.get("periodico") or cls.get("journal_name") or "")
        journal_canonical = canonical_journal(journal_name) or ""
        journal_key = journal_sort_key(journal_name) or ""

        publication_month = cls.get("mes") or cls.get("publication_month")
        publication_month_end = cls.get("mes_final") or cls.get("publication_month_end")
        publication_year_end = cls.get("ano_final") or cls.get("publication_year_end")
        issue_designation = cls.get("designacao_fasciculo") or cls.get("issue_designation")
        supplement = cls.get("suplemento") or cls.get("supplement")
        serial_evidence = cls.get("evidencia_serial") or cls.get("serial_evidence")
        natureza_editorial = cls.get("natureza_editorial") or cls.get("journal_genre")
        volume_label = cls.get("rotulo_volume") or cls.get("volume_label")

        akey = extract_first_author_key(authors)
        tkey, fkey, sub_tokens, is_weak = _build_title_fingerprint(title, subtitle)
        if not akey and len(tkey.split()) < 3:
            is_weak = True
        disc = _extract_discriminators(
            title=title,
            subtitle=subtitle,
            orig_filename=orig_filename,
            volume_field=str(volume_field) if volume_field is not None else None,
            number_field=str(number_field) if number_field is not None else None,
            tipo=tipo,
            year=year,
            is_serial=_is_serial,
        )
        ed_num, rev_flag = _parse_edition(edition_raw, title, subtitle, orig_filename)

        if pages is None and cls.get("paginas_pdf") is not None:
            try:
                pages = int(cls["paginas_pdf"])
            except (TypeError, ValueError):
                pages = None

        return {
            "sha256": str(sha256),
            "titulo": title,
            "subtitulo": subtitle,
            "autores": authors,
            "ano": year,
            "edicao": edition_raw,
            "tipo": tipo,
            "_source_path": str(source_path),
            "_pdf_path": str(pdf_path),
            "_md_path": str(pdf_path.with_suffix(".md")),
            "_akey": akey,
            "_tkey": tkey,
            "_fkey": fkey,
            "_sub_tokens": sub_tokens,
            "_weak": is_weak,
            "_disc": disc,
            "_base_wkey": f"{akey}|{tkey}",
            "_full_wkey": f"{akey}|{fkey}",
            "_isbn": normalize_isbn(cls.get("isbn")),
            "_doi": normalize_doi(cls.get("doi")),
            "_issn": normalize_issn(cls.get("issn")),
            "_ed": ed_num,
            "_rev": rev_flag,
            "_year": year,
            "_pages": pages,
            "_from_same_run": from_same_run,
            "_is_serial": _is_serial,
            # --- Campos seriais (PR #14) ---
            "_journal": journal_name,
            "_journal_canonical": journal_canonical,
            "_journal_key": journal_key,
            "_publication_month": publication_month,
            "_publication_month_end": publication_month_end,
            "_publication_year_end": publication_year_end,
            "_issue_designation": issue_designation,
            "_supplement": supplement,
            "_serial_evidence": serial_evidence,
            "_natureza_editorial": natureza_editorial,
            "_volume_label": volume_label,
        }

    def register_canonical(self, rec: dict[str, Any]) -> None:
        """Registrar obra como canônica ativa nas 3 camadas do índice."""
        sha = rec["sha256"]
        self.seen_by_sha[sha] = rec
        self.canon_by_sha[sha] = rec
        if rec["_doi"] and rec not in self.by_doi[rec["_doi"]]:
            self.by_doi[rec["_doi"]].append(rec)
        if rec["_isbn"] and rec not in self.by_isbn[rec["_isbn"]]:
            self.by_isbn[rec["_isbn"]].append(rec)
        if rec["_issn"] and rec not in self.by_issn[rec["_issn"]]:
            self.by_issn[rec["_issn"]].append(rec)
        jkey = rec.get("_journal_key")
        if jkey and rec not in self.by_journal[jkey]:
            self.by_journal[jkey].append(rec)
        if not rec["_weak"]:
            if rec not in self.by_work[rec["_base_wkey"]]:
                self.by_work[rec["_base_wkey"]].append(rec)
            if rec["_full_wkey"] != rec["_base_wkey"] and rec not in self.by_work[rec["_full_wkey"]]:
                self.by_work[rec["_full_wkey"]].append(rec)

    def unregister_canonical(self, rec: dict[str, Any]) -> None:
        """Remover obra substituída das camadas canônicas (mantém em seen_by_sha)."""
        self.canon_by_sha.pop(rec["sha256"], None)
        if rec["_doi"] and rec in self.by_doi[rec["_doi"]]:
            self.by_doi[rec["_doi"]].remove(rec)
        if rec["_isbn"] and rec in self.by_isbn[rec["_isbn"]]:
            self.by_isbn[rec["_isbn"]].remove(rec)
        if rec["_issn"] and rec in self.by_issn[rec["_issn"]]:
            self.by_issn[rec["_issn"]].remove(rec)
        jkey = rec.get("_journal_key")
        if jkey and rec in self.by_journal[jkey]:
            self.by_journal[jkey].remove(rec)
        if not rec["_weak"]:
            if rec in self.by_work[rec["_base_wkey"]]:
                self.by_work[rec["_base_wkey"]].remove(rec)
            if rec["_full_wkey"] != rec["_base_wkey"] and rec in self.by_work[rec["_full_wkey"]]:
                self.by_work[rec["_full_wkey"]].remove(rec)

    def check(
        self,
        rec: dict[str, Any],
    ) -> tuple[str, str | None, dict[str, Any] | None, str | None]:
        """Avaliar um documento entrante contra o índice nas 3 camadas.

        Retorna ``(verdict, match_layer, matched_canon, winner)`` onde ``verdict`` é
        ``'CANONICAL'``, ``'DUPLICATE'`` ou ``'OBSOLETE'``.
        """
        sha = rec["sha256"]
        if sha and sha in self.seen_by_sha:
            matched = self.seen_by_sha[sha]
            src_raw = rec.get("_source_path") or ""
            dst_raw = matched.get("_pdf_path") or ""
            if not (src_raw and dst_raw and _destinations_equal(Path(src_raw), Path(dst_raw))):
                return "DUPLICATE", "L1_SHA256", matched, "can"
            return "CANONICAL", None, None, None

        matched_layer: str | None = None
        matched_canon: dict[str, Any] | None = None

        # Camada 2: DOI / ISBN / ISSN
        if rec["_doi"] and rec["_doi"] in self.by_doi:
            for cand in self.by_doi[rec["_doi"]]:
                if is_structurally_compatible(rec, cand, via_identifier=True):
                    matched_layer, matched_canon = "L2_DOI", cand
                    break

        if matched_canon is None and rec["_isbn"] and rec["_isbn"] in self.by_isbn:
            for cand in self.by_isbn[rec["_isbn"]]:
                if is_structurally_compatible(rec, cand, via_identifier=True):
                    matched_layer, matched_canon = "L2_ISBN", cand
                    break

        if matched_canon is None and rec["_issn"] and rec["_issn"] in self.by_issn:
            for cand in self.by_issn[rec["_issn"]]:
                if is_structurally_compatible(rec, cand, via_identifier=True):
                    # L2_ISSN estrita para periódicos: ISSN identifica a série, não o fascículo.
                    # Exigir número estruturado idêntico E volume ou ano civil compatível,
                    # designação compatível, ausência de conflito nos demais campos conhecidos.
                    if not _issn_issue_compatible(rec, cand):
                        continue
                    matched_layer, matched_canon = "L2_ISSN", cand
                    break

        # Camada 3: Impressão digital bibliográfica (work_fingerprint)
        if matched_canon is None and not rec["_weak"]:
            candidates = list(self.by_work.get(rec["_base_wkey"], []))
            if rec["_full_wkey"] != rec["_base_wkey"]:
                for cand in self.by_work.get(rec["_full_wkey"], []):
                    if cand not in candidates:
                        candidates.append(cand)
            for cand in candidates:
                if is_structurally_compatible(rec, cand, via_identifier=False):
                    # L3_FINGERPRINT para periódicos: periódico canônico de série
                    # desambiguada + mesma regra forte de exemplar (número, volume/ano, designação).
                    if rec.get("tipo") in ("Revista", "Revista Científica") or cand.get("tipo") in ("Revista", "Revista Científica"):
                        if not _journal_serial_compatible(rec, cand):
                            continue
                    matched_layer, matched_canon = "L3_FINGERPRINT", cand
                    break

        # Camada 3b: índice por periódico (mesmo para registros fracos/_weak,
        # ex. "Micro Sistemas" com 2 palavras). Exigir compatibilidade de
        # número/volume/ano/designação para não casar n. 59 com n. 58.
        if matched_canon is None and _tipo_eh_revista(rec):
            jkey = rec.get("_journal_key") or ""
            for cand in self.by_journal.get(jkey, []):
                if cand.get("sha256") == rec.get("sha256"):
                    continue
                if rec.get("_issn") and cand.get("_issn") and rec["_issn"] != cand["_issn"]:
                    continue
                if not is_structurally_compatible(rec, cand, via_identifier=False):
                    continue
                if not _journal_serial_compatible(rec, cand):
                    continue
                matched_layer, matched_canon = "L3_FINGERPRINT", cand
                break

        if matched_canon is not None:
            # Para fascículos de revista, NUNCA chamar compare_editions nem
            # rebaixar exemplares anteriores para obsoletos/: saída de match
            # positivo é sempre duplicata do mesmo exemplar bibliográfico.
            if rec.get("tipo") in ("Revista", "Revista Científica") or matched_canon.get("tipo") in ("Revista", "Revista Científica"):
                return "DUPLICATE", matched_layer, matched_canon, "can"
            verdict, winner = compare_editions(rec, matched_canon)
            return verdict, matched_layer, matched_canon, winner

        return "CANONICAL", None, None, None

    @classmethod
    def from_target_dir(cls, target_dir: Path) -> LibraryIndex:
        """Inicializar o índice lendo os .md companheiros existentes na árvore temática."""
        index = cls()
        if not target_dir.exists():
            return index

        for md_path in sorted(target_dir.rglob("*.md")):
            try:
                rel_parts = md_path.relative_to(target_dir).parts
            except ValueError:
                continue
            if not rel_parts or rel_parts[0] in _NON_CANONICAL_DIRS:
                continue

            fm = _parse_front_matter_safe(md_path)
            if not fm or not fm.get("sha256"):
                continue

            pdf_path = md_path.with_suffix(".pdf")
            if not pdf_path.exists():
                continue
            pages = fm.get("paginas_pdf")
            if pages is None and pdf_path.exists():
                pages = _read_pdf_page_count(pdf_path)

            # Mapear campos seriais legacy do front matter para build_record.
            fm.setdefault("publication_month", fm.get("mes"))
            fm.setdefault("publication_month_end", fm.get("mes_final"))
            fm.setdefault("publication_year_end", fm.get("ano_final"))
            fm.setdefault("volume_label", fm.get("rotulo_volume"))
            fm.setdefault("issue_designation", fm.get("designacao_fasciculo"))
            fm.setdefault("journal_genre", fm.get("natureza_editorial"))

            rec = cls.build_record(
                sha256=str(fm["sha256"]),
                classification=fm,
                source_path=pdf_path,
                pdf_path=pdf_path,
                pages=int(pages) if pages is not None else None,
                from_same_run=False,
            )
            index.register_canonical(rec)
        return index


# --------------------------------------------------------------------------- #
# Helpers de filesystem
# --------------------------------------------------------------------------- #
def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _destinations_equal(src: Path, dst: Path) -> bool:
    """Verificar se dois caminhos apontam para o mesmo arquivo."""
    try:
        return src.resolve() == dst.resolve()
    except OSError:
        return False


def _resolve_collision(
    dest_dir: Path,
    filename: str,
    src_path: Path,
    planned_destinations: dict[Path, str] | None = None,
    src_sha256: str | None = None,
    serial_mode: bool = False,
) -> tuple[str, str]:
    """Resolver colisão de nome no destino (disco + execuções em dry-run).

    Quando ``serial_mode=True`` (fascículos de revista) e há colisão física de
    caminho com SHA distinto, usa sufixo `` - h<12 hex>`` em vez de contador
    `` (2)``.
    """
    dest_path = dest_dir / filename
    src_hash = src_sha256 if src_sha256 else _compute_sha256(src_path)

    if planned_destinations is not None and dest_path in planned_destinations:
        planned_hash = planned_destinations[dest_path]
        if planned_hash == src_hash:
            return filename, ProcessStatus.DUPLICATE_SKIPPED.value

    if not dest_path.exists() and (planned_destinations is None or dest_path not in planned_destinations):
        # [BUG-WIN-PATH] no Windows, garantir que o caminho completo não estoure WIN_SAFE_FULL_PATH_CHARS
        if sys.platform == "win32":
            full = str(dest_dir / filename)
            if len(full) > WIN_SAFE_FULL_PATH_CHARS or len(filename.encode("utf-8")) > MAX_BYTES:
                return _shorten_name_for_win(dest_dir, filename, src_path, planned_destinations, src_hash)
        return filename, ""

    if dest_path.exists():
        try:
            dst_hash = _compute_sha256(dest_path)
        except OSError:
            dst_hash = ""
        if dst_hash and dst_hash == src_hash:
            return filename, ProcessStatus.DUPLICATE_SKIPPED.value

    stem = Path(filename).stem
    suffix = Path(filename).suffix

    # Para revistas em colisão com SHA distinto, usar hash discriminador.
    if serial_mode and src_hash:
        sha_disc = f"{stem} - h{src_hash[:12]}{suffix}"
        sha_disc_path = dest_dir / sha_disc
        planned_has = planned_destinations is not None and sha_disc_path in planned_destinations
        if not sha_disc_path.exists() and not planned_has:
            return sha_disc, ""
        if planned_has and planned_destinations.get(sha_disc_path) == src_hash:
            return sha_disc, ProcessStatus.DUPLICATE_SKIPPED.value
        if sha_disc_path.exists():
            try:
                if _compute_sha256(sha_disc_path) == src_hash:
                    return sha_disc, ProcessStatus.DUPLICATE_SKIPPED.value
            except OSError:
                pass

    counter = 2
    while True:
        candidate = f"{stem} ({counter}){suffix}"
        candidate_path = dest_dir / candidate
        planned_has = planned_destinations is not None and candidate_path in planned_destinations
        if not candidate_path.exists() and not planned_has:
            # [BUG-WIN-PATH] encurtar se estourar o limite do Windows.
            if sys.platform == "win32":
                full = str(candidate_path)
                if len(full) > WIN_SAFE_FULL_PATH_CHARS or len(candidate.encode("utf-8")) > MAX_BYTES:
                    return _shorten_name_for_win(dest_dir, filename, src_path, planned_destinations, src_hash, counter=counter)
            return candidate, ""
        if planned_has and planned_destinations is not None and planned_destinations[candidate_path] == src_hash:
            return candidate, ProcessStatus.DUPLICATE_SKIPPED.value
        if candidate_path.exists():
            try:
                candidate_hash = _compute_sha256(candidate_path)
            except OSError:
                candidate_hash = ""
            if candidate_hash == src_hash:
                return candidate, ProcessStatus.DUPLICATE_SKIPPED.value
        counter += 1


def _shorten_name_for_win(
    dest_dir: Path,
    filename: str,
    src_path: Path,
    planned_destinations: dict[Path, str] | None = None,
    src_hash: str | None = None,
    counter: int | None = None,
) -> tuple[str, str]:
    """Encurtar o stem do nome (com sufixo curto _{sha[:6]}) para respeitar WIN_SAFE_FULL_PATH_CHARS e MAX_BYTES no Windows."""
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    sha_suffix = f"_{str(src_hash or '')[:6]}" if src_hash else ""

    # Tentar stem curto + sufixo de colisão + sha curto.
    base_stem = _strip_trailing_punct_organizer(stem)
    if counter is not None:
        candidato = f"{base_stem} ({counter}){sha_suffix}{suffix}"
    else:
        candidato = f"{base_stem}{sha_suffix}{suffix}"

    # Se ainda estourar, truncar o stem agressivamente.
    while len(candidato.encode("utf-8")) > MAX_BYTES or len(str(dest_dir / candidato)) > WIN_SAFE_FULL_PATH_CHARS:
        if len(base_stem) <= 5:
            # Último recurso: nome genérico curto.
            candidato = f"file{sha_suffix}{suffix}"
            break
        base_stem = base_stem[:-1]
        if counter is not None:
            candidato = f"{base_stem} ({counter}){sha_suffix}{suffix}"
        else:
            candidato = f"{base_stem}{sha_suffix}{suffix}"

    # Verificar colisão com o nome encurtado.
    candidate_path = dest_dir / candidato
    planned_has = planned_destinations is not None and candidate_path in planned_destinations
    if not candidate_path.exists() and not planned_has:
        return candidato, ""
    if planned_has and planned_destinations[candidate_path] == src_hash:
        return candidato, ProcessStatus.DUPLICATE_SKIPPED.value
    if candidate_path.exists():
        try:
            if _compute_sha256(candidate_path) == src_hash:
                return candidato, ProcessStatus.DUPLICATE_SKIPPED.value
        except OSError:
            pass
    # Se ainda houver colisão, adicionar contador incremental curto.
    c = 2
    while True:
        cand2 = f"{base_stem} ({c}){sha_suffix}{suffix}"
        p2 = dest_dir / cand2
        ph = planned_destinations is not None and p2 in planned_destinations
        if not p2.exists() and not ph:
            return cand2, ""
        if ph and planned_destinations[p2] == src_hash:
            return cand2, ProcessStatus.DUPLICATE_SKIPPED.value
        c += 1
        if c > 99:
            return cand2, ""


class LibraryOrganizer:
    """Materializar a organização física dos arquivos classificados."""

    def __init__(
        self,
        target_dir: Path,
        *,
        file_operation: str = "copy",
        dry_run: bool = False,
        index: LibraryIndex | None = None,
    ) -> None:
        self.target_dir = Path(target_dir).resolve()
        self.file_operation = file_operation
        self.dry_run = dry_run
        self.entries: list[FileManifestEntry] = []
        self._organized_count = 0
        self._manual_review_count = 0
        self._duplicate_skipped_count = 0
        self._obsolete_count = 0
        self._ignored_non_pdf_count = 0
        self._error_count = 0
        self._planned_destinations: dict[Path, str] = {}
        self.index = index if index is not None else LibraryIndex.from_target_dir(self.target_dir)

    def _materialize(
        self,
        source_path: Path,
        destination_path: Path,
        sha256: str,
        status: ProcessStatus,
    ) -> bool:
        """Copiar/mover o arquivo para o destino (ou apenas simular no dry-run).

        AppSec A-02: validar source_path (exists/is_file) e _is_within antes
        de copiar/mover.
        """
        if self.dry_run:
            return True

        # AppSec A-02: source_path deve existir e ser um arquivo regular.
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Arquivo de origem não encontrado ou não é um arquivo: {source_path}")

        # AppSec A-02: destino deve estar dentro de target_dir.
        if not _is_within(destination_path, self.target_dir):
            raise ValueError(f"Caminho de destino fora do diretório alvo bloqueado: {destination_path}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if _destinations_equal(source_path, destination_path):
            return True

        shutil.copy2(source_path, destination_path)
        if self.file_operation == "move":
            try:
                source_path.unlink()
            except OSError:
                pass
        return True

    def _archive_to_special_dir(
        self,
        source_path: Path,
        subdir_name: str,
        desired_name: str,
        sha256: str,
    ) -> Path:
        """Copiar ou mover um arquivo para ``duplicatas/`` ou ``obsoletos/``."""
        special_dir = self.target_dir / subdir_name
        # [BUG-WIN-PATH] respeitar WIN_SAFE_FULL_PATH_CHARS antes de criar o Path/copiar.
        if sys.platform == "win32":
            if (
                len(str(special_dir / desired_name)) > WIN_SAFE_FULL_PATH_CHARS
                or len(desired_name.encode("utf-8")) > MAX_BYTES
            ):
                shortened, _ = _shorten_name_for_win(
                    special_dir,
                    desired_name,
                    source_path,
                    self._planned_destinations,
                    src_sha256=sha256,
                )
                desired_name = shortened
        resolved_name, _ = _resolve_collision(
            special_dir,
            desired_name,
            source_path,
            self._planned_destinations,
            src_sha256=sha256,
        )
        dest_path = special_dir / resolved_name
        self._planned_destinations[dest_path] = sha256

        if not self.dry_run:
            special_dir.mkdir(parents=True, exist_ok=True)
            if not _destinations_equal(source_path, dest_path):
                shutil.copy2(source_path, dest_path)
                if self.file_operation == "move":
                    try:
                        source_path.unlink()
                    except OSError:
                        pass
        return dest_path

    def _demote_canonical_to_obsolete(
        self,
        matched_canon: dict[str, Any],
        new_canonical_dest: Path,
        new_canon_record: dict[str, Any],
        match_layer: str,
    ) -> None:
        """Mover exemplar canônico antigo da árvore temática para ``obsoletos/``."""
        old_pdf_path = Path(matched_canon["_pdf_path"])
        old_md_path = Path(matched_canon["_md_path"])
        old_sha = matched_canon["sha256"]

        self.index.unregister_canonical(matched_canon)
        self.index.register_canonical(new_canon_record)

        obs_dir = self.target_dir / OBSOLETOS_DIR
        if self.dry_run:
            obs_dest = obs_dir / old_pdf_path.name
            self._planned_destinations[obs_dest] = old_sha
        else:
            if not _is_within(old_pdf_path, self.target_dir):
                raise ValueError(f"Caminho fora do diretório alvo bloqueado: {old_pdf_path}")

            obs_dir.mkdir(parents=True, exist_ok=True)
            obs_name, _ = _resolve_collision(
                obs_dir,
                old_pdf_path.name,
                old_pdf_path if old_pdf_path.exists() else new_canonical_dest,
                self._planned_destinations,
                src_sha256=old_sha,
            )
            obs_dest = obs_dir / obs_name
            self._planned_destinations[obs_dest] = old_sha

            if old_pdf_path.exists():
                shutil.move(str(old_pdf_path), str(obs_dest))

            if old_md_path.exists() and _is_within(old_md_path, self.target_dir):
                try:
                    old_md_path.unlink()
                except OSError:
                    pass

            # Limpar diretório pai caso tenha ficado vazio (mantendo self.target_dir).
            parent = old_pdf_path.parent
            while parent != self.target_dir and _is_within(parent, self.target_dir):
                try:
                    if not any(parent.iterdir()):
                        parent.rmdir()
                        parent = parent.parent
                    else:
                        break
                except OSError:
                    break

            md_content = generate_obsolete_companion_markdown(
                obsolete_source=old_pdf_path,
                canonical_dest=new_canonical_dest,
                sha256=old_sha,
                match_layer=match_layer,
                obsolete_info=matched_canon,
                canonical_info=new_canon_record,
                replaced_existing=True,
                target_dir=self.target_dir,
            )
            obs_dest.with_suffix(".md").write_text(md_content, encoding="utf-8")

        self._obsolete_count += 1
        # Se o canônico antigo foi registrado nesta mesma execução, atualizar sua entrada no manifesto.
        if matched_canon.get("_from_same_run"):
            for prev_entry in self.entries:
                if prev_entry.sha256 == old_sha and prev_entry.status == ProcessStatus.ORGANIZED:
                    prev_entry.status = ProcessStatus.OBSOLETE
                    prev_entry.destination_path = str(obs_dest)
                    self._organized_count = max(0, self._organized_count - 1)
                    break

    def add_organized(
        self,
        source_path: Path,
        grande_area: str,
        area_basica: str,
        subarea: str,
        especialidade: str,
        tipo: str,
        filename: str,
        sha256: str,
        used_ocr: bool = False,
        classification: dict[str, Any] | None = None,
        duplicate: bool = False,
    ) -> FileManifestEntry:
        """Classificar destino e materializar obra, duplicata ou edição obsoleta."""
        # [BUG-WIN-PATH] Proteção Windows MAX_PATH: pasta destino muito profunda.
        tipo_eh_revista_probe = str(tipo or "") in ("Revista", "Revista Científica")
        journal_canonical_probe = ""
        if tipo_eh_revista_probe and classification:
            journal_canonical_probe = str(
                classification.get("periodico")
                or classification.get("journal_name")
                or ""
            ).strip()
            journal_canonical_probe = canonical_journal(journal_canonical_probe) or ""
        if tipo_eh_revista_probe and journal_canonical_probe:
            dest_dir_probe = (
                self.target_dir
                / area_basica
                / ((subarea or "").strip() or "Geral")
                / "Revista"
                / journal_canonical_probe
            )
        else:
            dest_dir_probe = self.target_dir / area_basica / ((subarea or "").strip() or "Geral") / tipo
        if sys.platform == "win32":
            if len(str(dest_dir_probe)) > WIN_SAFE_FULL_PATH_CHARS - 40:
                return self.add_manual_review(
                    source_path=source_path,
                    sha256=sha256,
                    reason=(
                        f"Caminho de destino excessivamente profundo no Windows "
                        f"({len(str(dest_dir_probe))} chars > {WIN_SAFE_FULL_PATH_CHARS - 40}); "
                        f"sugerir pasta de destino mais curta."
                    ),
                    used_ocr=used_ocr,
                    classification=classification,
                )

        subarea_clean = (subarea or "").strip() or "Geral"

        # --- Roteador de periódicos (PR #14) ---
        tipo_eh_revista = str(tipo or "") in ("Revista", "Revista Científica")
        journal_canonical = ""
        if tipo_eh_revista and classification:
            journal_canonical = str(
                classification.get("periodico")
                or classification.get("journal_name")
                or ""
            ).strip()
            journal_canonical = canonical_journal(journal_canonical) or ""
            if not journal_canonical:
                # Periódico não identificável: encaminhar a revisão manual.
                return self.add_manual_review(
                    source_path=source_path,
                    sha256=sha256,
                    reason=(
                        "Periódico não identificado para fascículo de revista; "
                        "encaminhar a revisao_manual com motivo observável."
                    ),
                    used_ocr=used_ocr,
                    classification=classification,
                )
            dest_dir = self.target_dir / area_basica / subarea_clean / "Revista" / journal_canonical
        else:
            dest_dir = self.target_dir / area_basica / subarea_clean / tipo

        planned_dest = dest_dir / filename

        cls_enriched = dict(classification or {})
        cls_enriched.setdefault("grande_area", grande_area)
        cls_enriched.setdefault("area_basica", area_basica)
        cls_enriched.setdefault("subarea", subarea_clean)
        cls_enriched.setdefault("especialidade", especialidade)
        cls_enriched.setdefault("tipo", tipo)
        cls_enriched.setdefault("arquivo_origem", source_path.name)

        pages = cls_enriched.get("paginas_pdf")
        if pages is None and source_path.exists():
            pages = _read_pdf_page_count(source_path)
            if pages is not None:
                cls_enriched["paginas_pdf"] = pages

        rec = LibraryIndex.build_record(
            sha256=sha256,
            classification=cls_enriched,
            source_path=source_path,
            pdf_path=planned_dest,
            pages=int(pages) if pages is not None else None,
            from_same_run=True,
        )

        verdict, match_layer, matched_canon, winner = self.index.check(rec)

        # Fallback por colisão física exata de caminho mesmo para registros fracos
        if verdict == "CANONICAL":
            nome_final, colisao_status = _resolve_collision(
                dest_dir,
                filename,
                source_path,
                self._planned_destinations,
                src_sha256=sha256,
                serial_mode=tipo_eh_revista,
            )
            destination_path = dest_dir / nome_final
            rec["_pdf_path"] = str(destination_path)
            rec["_md_path"] = str(destination_path.with_suffix(".md"))
            if colisao_status == ProcessStatus.DUPLICATE_SKIPPED.value:
                verdict = "DUPLICATE"
                match_layer = "L1_SHA256"
                matched_canon = {"_pdf_path": str(destination_path), "sha256": sha256}
                winner = "can"
        else:
            destination_path = planned_dest

        if verdict == "DUPLICATE" and matched_canon is not None:
            status = ProcessStatus.DUPLICATE_SKIPPED
            self._duplicate_skipped_count += 1
            dup_dest_path = self._archive_to_special_dir(
                source_path, DUPLICATAS_DIR, source_path.name, sha256
            )
            if not self.dry_run:
                md_content = generate_duplicate_companion_markdown(
                    duplicate_source=source_path,
                    canonical_dest=Path(matched_canon["_pdf_path"]),
                    sha256=sha256,
                    match_layer=match_layer or "L1_SHA256",
                    target_dir=self.target_dir,
                )
                dup_dest_path.with_suffix(".md").write_text(md_content, encoding="utf-8")

            entry = FileManifestEntry(
                source_path=str(source_path),
                destination_path=str(dup_dest_path),
                sha256=sha256,
                status=status,
                used_ocr=used_ocr,
                classification=cls_enriched,
            )
            self.entries.append(entry)
            return entry

        if verdict == "OBSOLETE" and matched_canon is not None and winner == "can":
            status = ProcessStatus.OBSOLETE
            self._obsolete_count += 1
            obs_dest_path = self._archive_to_special_dir(
                source_path, OBSOLETOS_DIR, filename or source_path.name, sha256
            )
            if not self.dry_run:
                md_content = generate_obsolete_companion_markdown(
                    obsolete_source=source_path,
                    canonical_dest=Path(matched_canon["_pdf_path"]),
                    sha256=sha256,
                    match_layer=match_layer or "L2_IDENTIFIER",
                    obsolete_info=rec,
                    canonical_info=matched_canon,
                    replaced_existing=False,
                    target_dir=self.target_dir,
                )
                obs_dest_path.with_suffix(".md").write_text(md_content, encoding="utf-8")

            entry = FileManifestEntry(
                source_path=str(source_path),
                destination_path=str(obs_dest_path),
                sha256=sha256,
                status=status,
                used_ocr=used_ocr,
                classification=cls_enriched,
            )
            self.entries.append(entry)
            return entry

        if verdict == "OBSOLETE" and matched_canon is not None and winner == "inc":
            nome_final, _ = _resolve_collision(
                dest_dir,
                filename,
                source_path,
                self._planned_destinations,
                src_sha256=sha256,
            )
            destination_path = dest_dir / nome_final
            rec["_pdf_path"] = str(destination_path)
            rec["_md_path"] = str(destination_path.with_suffix(".md"))
            self._planned_destinations[destination_path] = sha256

            status = ProcessStatus.ORGANIZED
            self._organized_count += 1
            self._materialize(source_path, destination_path, sha256, status)
            if not self.dry_run and cls_enriched:
                companion_path = destination_path.with_suffix(".md")
                companion_content = generate_companion_markdown(
                    destination_path=companion_path,
                    source_path=source_path,
                    sha256=sha256,
                    classification=cls_enriched,
                    used_ocr=used_ocr,
                )
                companion_path.write_text(companion_content, encoding="utf-8")

            self._demote_canonical_to_obsolete(
                matched_canon=matched_canon,
                new_canonical_dest=destination_path,
                new_canon_record=rec,
                match_layer=match_layer or "L2_IDENTIFIER",
            )

            entry = FileManifestEntry(
                source_path=str(source_path),
                destination_path=str(destination_path),
                sha256=sha256,
                status=status,
                used_ocr=used_ocr,
                classification=cls_enriched,
            )
            self.entries.append(entry)
            return entry

        # CANONICAL
        self._planned_destinations[destination_path] = sha256
        status = ProcessStatus.ORGANIZED
        self._organized_count += 1
        self._materialize(source_path, destination_path, sha256, status)
        if not self.dry_run and cls_enriched:
            companion_path = destination_path.with_suffix(".md")
            companion_content = generate_companion_markdown(
                destination_path=companion_path,
                source_path=source_path,
                sha256=sha256,
                classification=cls_enriched,
                used_ocr=used_ocr,
            )
            companion_path.write_text(companion_content, encoding="utf-8")

        self.index.register_canonical(rec)

        entry = FileManifestEntry(
            source_path=str(source_path),
            destination_path=str(destination_path),
            sha256=sha256,
            status=status,
            used_ocr=used_ocr,
            classification=cls_enriched,
        )
        self.entries.append(entry)
        return entry

    def add_manual_review(
        self,
        source_path: Path,
        sha256: str,
        reason: str,
        used_ocr: bool = False,
        classification: dict[str, Any] | None = None,
    ) -> FileManifestEntry:
        """Registrar arquivo enviado para revisao_manual preservando o nome original."""
        revisao_dir = self.target_dir / REVISAO_DIR
        # [BUG-WIN-PATH] respeitar WIN_SAFE_FULL_PATH_CHARS antes de criar o Path/copiar.
        if sys.platform == "win32":
            if (
                len(str(revisao_dir / source_path.name)) > WIN_SAFE_FULL_PATH_CHARS
                or len(source_path.name.encode("utf-8")) > MAX_BYTES
            ):
                shortened, _ = _shorten_name_for_win(
                    revisao_dir,
                    source_path.name,
                    source_path,
                    self._planned_destinations,
                    src_sha256=sha256,
                )
                source_path_name_for_collision = shortened
            else:
                source_path_name_for_collision = source_path.name
        else:
            source_path_name_for_collision = source_path.name
        nome_final, _ = _resolve_collision(
            revisao_dir,
            source_path_name_for_collision,
            source_path,
            self._planned_destinations,
            src_sha256=sha256,
        )
        destination_path = revisao_dir / nome_final
        self._planned_destinations[destination_path] = sha256
        entry = FileManifestEntry(
            source_path=str(source_path),
            destination_path=str(destination_path),
            sha256=sha256,
            status=ProcessStatus.MANUAL_REVIEW,
            used_ocr=used_ocr,
            classification=classification,
            error_message=reason,
        )
        self.entries.append(entry)
        self._manual_review_count += 1
        self._materialize(source_path, destination_path, sha256, ProcessStatus.MANUAL_REVIEW)
        return entry

    def add_error(
        self,
        source_path: Path,
        sha256: str,
        error_message: str,
        used_ocr: bool = False,
    ) -> FileManifestEntry:
        """Registrar um erro (arquivo corrompido etc.) em revisao_manual."""
        revisao_dir = self.target_dir / REVISAO_DIR
        # [BUG-WIN-PATH] respeitar WIN_SAFE_FULL_PATH_CHARS antes de criar o Path/copiar.
        if sys.platform == "win32":
            if (
                len(str(revisao_dir / source_path.name)) > WIN_SAFE_FULL_PATH_CHARS
                or len(source_path.name.encode("utf-8")) > MAX_BYTES
            ):
                shortened, _ = _shorten_name_for_win(
                    revisao_dir,
                    source_path.name,
                    source_path,
                    self._planned_destinations,
                    src_sha256=sha256,
                )
                source_path_name_for_collision = shortened
            else:
                source_path_name_for_collision = source_path.name
        else:
            source_path_name_for_collision = source_path.name
        nome_final, _ = _resolve_collision(
            revisao_dir,
            source_path_name_for_collision,
            source_path,
            self._planned_destinations,
            src_sha256=sha256,
        )
        destination_path = revisao_dir / nome_final
        self._planned_destinations[destination_path] = sha256
        entry = FileManifestEntry(
            source_path=str(source_path),
            destination_path=str(destination_path),
            sha256=sha256,
            status=ProcessStatus.ERROR,
            used_ocr=used_ocr,
            error_message=error_message,
        )
        self.entries.append(entry)
        self._error_count += 1
        self._materialize(source_path, destination_path, sha256, ProcessStatus.ERROR)
        return entry

    def add_ignored_non_pdf(
        self, source_path: Path, reason: str = ""
    ) -> FileManifestEntry:
        """Registrar arquivo não-PDF ignorado com diagnóstico detalhado."""
        if not reason:
            suffix = source_path.suffix.lower()
            if suffix == ".webloc":
                reason = "Atalho de internet macOS (.webloc)"
            elif suffix == ".url":
                reason = "Atalho de internet Windows (.url)"
            elif suffix == ".desktop":
                reason = "Atalho de aplicativo Linux (.desktop)"
            elif suffix in (".epub", ".mobi", ".azw", ".azw3"):
                reason = f"E-book não-PDF ({suffix})"
            elif suffix in (".doc", ".docx", ".odt", ".rtf", ".txt"):
                reason = f"Documento de texto não-PDF ({suffix})"
            elif suffix in (".ppt", ".pptx", ".odp", ".key"):
                reason = f"Apresentação não-PDF ({suffix})"
            elif suffix in (".xls", ".xlsx", ".ods", ".csv"):
                reason = f"Planilha/dados ({suffix})"
            elif suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff"):
                reason = f"Imagem avulsa ({suffix})"
            elif suffix:
                reason = f"Arquivo com extensão não suportada ({suffix})"
            else:
                reason = "Arquivo sem extensão (não-PDF)"

        entry = FileManifestEntry(
            source_path=str(source_path),
            destination_path=None,
            sha256="",
            status=ProcessStatus.IGNORED_NON_PDF,
            error_message=reason,
        )
        self.entries.append(entry)
        self._ignored_non_pdf_count += 1
        return entry

    def build_summary(self, total_scanned: int) -> ExecutionSummary:
        manual_review_ratio = (
            self._manual_review_count / total_scanned if total_scanned else 0.0
        )
        return ExecutionSummary(
            total_scanned=total_scanned,
            organized_count=self._organized_count,
            manual_review_count=self._manual_review_count,
            duplicate_skipped_count=self._duplicate_skipped_count,
            obsolete_count=self._obsolete_count,
            ignored_non_pdf_count=self._ignored_non_pdf_count,
            error_count=self._error_count,
            manual_review_ratio=manual_review_ratio,
            exceeded_manual_review_ceiling=manual_review_ratio > 0.20,
            entries=list(self.entries),
        )

    def write_manifest(self, summary: ExecutionSummary) -> Path:
        """Gravar manifest.json no diretório de destino."""
        manifest_path = self.target_dir / MANIFEST_FILENAME
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_scanned": summary.total_scanned,
            "organized_count": summary.organized_count,
            "manual_review_count": summary.manual_review_count,
            "duplicate_skipped_count": summary.duplicate_skipped_count,
            "obsolete_count": summary.obsolete_count,
            "ignored_non_pdf_count": summary.ignored_non_pdf_count,
            "error_count": summary.error_count,
            "manual_review_ratio": round(summary.manual_review_ratio, 4),
            "exceeded_manual_review_ceiling": summary.exceeded_manual_review_ceiling,
            "entries": [
                entry.model_dump(mode="json") for entry in summary.entries
            ],
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest_path

    def write_relatorio_revisao(self, summary: ExecutionSummary) -> Path:
        """Gravar revisao_manual/relatorio_revisao.md com as pendências."""
        relatorio_dir = self.target_dir / REVISAO_DIR
        relatorio_path = relatorio_dir / RELATORIO_FILENAME
        relatorio_dir.mkdir(parents=True, exist_ok=True)

        pendentes = [
            e
            for e in summary.entries
            if e.status
            in (ProcessStatus.MANUAL_REVIEW, ProcessStatus.ERROR)
        ]

        lines: list[str] = []
        lines.append("# Relatório de Revisão Manual")
        lines.append("")
        lines.append(
            f"Gerado em: {datetime.now(UTC).isoformat()}\n"
        )
        lines.append(f"Total de arquivos pendentes: {len(pendentes)}\n")
        if summary.exceeded_manual_review_ceiling:
            lines.append(
                f"⚠️  ATENÇÃO: taxa de revisão manual "
                f"({summary.manual_review_ratio:.1%}) excede o teto de 20%."
            )
        lines.append("")

        if not pendentes:
            lines.append("Nenhum arquivo requer revisão manual.\n")
        else:
            lines.append("## Arquivos para revisão\n")
            for entry in pendentes:
                motivo = entry.error_message or "confiança abaixo do limiar"
                lines.append(f"- `{entry.source_path}` → `{entry.destination_path}`")
                lines.append(f"  - Status: {entry.status.value}")
                lines.append(f"  - Motivo: {motivo}")
                lines.append("")

        ignorados = [
            e for e in summary.entries if e.status == ProcessStatus.IGNORED_NON_PDF
        ]
        if ignorados:
            lines.append("## Arquivos Não-PDF e Atalhos Ignorados\n")
            lines.append(
                f"Total de itens ignorados na varredura: {len(ignorados)}\n"
            )
            for entry in ignorados:
                motivo = entry.error_message or "Não-PDF ignorado"
                lines.append(f"- `{entry.source_path}`")
                lines.append(f"  - Diagnóstico: {motivo}")
            lines.append("")

        relatorio_path.write_text("\n".join(lines), encoding="utf-8")
        return relatorio_path

    def finalize(self, total_scanned: int) -> ExecutionSummary:
        """Montar o resumo e gravar manifest.json e relatório de revisão."""
        summary = self.build_summary(total_scanned)
        self.write_manifest(summary)
        self.write_relatorio_revisao(summary)
        return summary
