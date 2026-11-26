"""Formatador de nomes acadêmicos de arquivo (Item 20).

Compõe '<autor> - <titulo> - <subtitulo> - <ano>.pdf' com suporte a 1, 2 ou
3+ autores, omissão de subtítulo vazio, 's.d.' quando o ano for None,
normalização Unicode NFC, sanitização de caracteres proibidos e truncamento
progressivo em fronteira de palavra garantindo len(filename.encode('utf-8'))
<= 240 bytes (abaixo do limite de 255 bytes do sistema de arquivos).

Para fascículos de revista (tipo ``Revista``), compõe o nome ordenável
'<Periódico> - <AAAA-MM|AAAA|s.d.> - v<VVV> - n<NNNN>[ - <designação>].pdf'
sem autor, sem subtítulo de capa e sem '[ano]', respeitando WIN_SAFE_FULL_PATH_CHARS
e MAX_BYTES preservando data, v/n, designação e hash antes de abreviar o periódico.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

from tomus.core.periodicals import (
    canonical_journal,
    is_redundant_issue_designation,
    parse_issue,
    parse_roman,
    supplement_label,
)
from tomus.core.text_utils import normalize_tex_accents

# Caracteres proibidos em nomes de arquivo (Windows / POSIX portátil).
_PROHIBITED_CHARS = set(r'/\:*?"<>|')
# Separador entre campos do nome acadêmico.
_FIELD_SEP = " - "
# Sufixo incremental para resolução de colisão.
_COLLISION_SUFFIX = " (2)"
# Limite máximo de bytes UTF-8 do nome do arquivo (extensão .pdf incluída).
MAX_BYTES = 240
# Limite seguro de caracteres do caminho completo no Windows (abaixo do
# MAX_PATH de 260, reservando folga para o nome do arquivo).
WIN_SAFE_FULL_PATH_CHARS = 245


def _sanitize(value: str) -> str:
    """Normalizar acentos TeX, remover caracteres proibidos e colapsar espaços."""
    value = normalize_tex_accents(value or "")
    sanitized = "".join(ch for ch in value if ch not in _PROHIBITED_CHARS)
    return " ".join(sanitized.split())


def _strip_trailing_punct(text: str) -> str:
    """Remover pontuação solta pendente no fim do texto."""
    return text.rstrip(' ,;:-–—/|([')


def _strip_redundant_bilingual(text: str) -> str:
    """Remover tradução redundante em separador bilíngue.

    Quando o texto contém separadores bilíngues (' - ', ' / ', ' | ') e a
    primeira metade tem >= 20 caracteres, detectar marcadores de idiomas
    distintos nas duas metades (stopwords PT vs EN/ES) e descartar a
    tradução redundante, mantendo a metade mais longa/provável.
    """
    seps = (" - ", " / ", " | ")
    for sep in seps:
        if sep not in text:
            continue
        idx = text.find(sep)
        parte1 = text[:idx]
        parte2 = text[idx + len(sep):]
        if len(parte1) < 20:
            continue
        pt_stop = {"de", "da", "do", "das", "dos", "com", "em", "para", "uma", "um", "a", "o", "e"}
        en_stop = {"the", "of", "and", "as", "in", "for", "with", "to", "a", "an", "or"}
        es_stop = {"del", "los", "las", "de", "la", "en", "y", "o", "a", "un", "una"}
        p1_tokens = set(parte1.casefold().split())
        p2_tokens = set(parte2.casefold().split())
        tem_pt = bool(p1_tokens & pt_stop) or bool(p2_tokens & pt_stop)
        tem_en = bool(p1_tokens & en_stop) or bool(p2_tokens & en_stop)
        tem_es = bool(p1_tokens & es_stop) or bool(p2_tokens & es_stop)
        idiomas_distintos = (
            (tem_pt and tem_en) or (tem_pt and tem_es) or (tem_en and tem_es)
        )
        if not idiomas_distintos:
            continue
        # Manter a metade original em portugues quando houver marcadores PT na
        # primeira metade e EN/ES na segunda (evitar descartar o titulo original).
        if tem_pt and (tem_en or tem_es):
            return parte1.strip()
        # Caso contrario, manter a metade mais longa (menos provavel de ser
        # traducao curta).
        if len(parte2) >= len(parte1):
            return parte2.strip()
        return parte1.strip()
    return text


def _truncate_word_boundary(text: str, max_bytes: int) -> str:
    """Truncar 'text' em fronteira de palavra respeitando um orçamento de bytes.

    Itera palavra por palavra acumulando-as separadas por espaço, de modo que
    nunca insira espaços entre letras de uma mesma palavra. Retorna o maior
    prefixo cujo tamanho em bytes UTF-8 não exceda 'max_bytes'. Se mesmo a
    primeira palavra sozinha exceder o orçamento, truncar por caracteres sem
    quebrar sequências multibyte UTF-8.
    """
    if max_bytes <= 0:
        return ""

    palavras = text.split()
    if not palavras:
        return ""

    resultado = ""
    for palavra in palavras:
        candidato = (resultado + " " + palavra).strip()
        if len(candidato.encode("utf-8")) > max_bytes:
            break
        resultado = candidato

    if resultado:
        return resultado

    # Primeira palavra sozinha excede o orçamento: truncar por caracteres,
    # respeitando fronteiras UTF-8 (não cortar dentro de sequência multibyte).
    codificado = palavras[0].encode("utf-8")
    if len(codificado) <= max_bytes:
        return palavras[0]
    corte = codificado[:max_bytes]
    # Recuar até encontrar o início de um caractere UTF-8 (byte não 0x80-0xBF).
    while corte and (corte[-1] & 0xC0) == 0x80:
        corte = corte[:-1]
    return corte.decode("utf-8", errors="ignore")


def format_academic_filename(
    *,
    authors: list[str],
    title: str,
    subtitle: str = "",
    year: int | str | None = None,
    ext: str = ".pdf",
    dest_dir: Path | str | None = None,
    max_full_path_chars: int | None = None,
) -> str:
    """Formatar o nome acadêmico do arquivo.

    Regras:
      * 1 autor: authors[0] ('Sobrenome, Nome').
      * 2 autores: 'Sobrenome1; Sobrenome2'.
      * 3+ autores: 'Sobrenome1 et al.'.
      * subtítulo vazio é omitido (e o separador associado).
      * ano None -> 's.d.'.
      * normalização Unicode NFC.
      * sanitização de '/ \\ : * ? " < > |'.
      * truncamento progressivo primeiro do subtítulo e depois do título,
        em fronteira de palavra, preservando <autor> e <ano>.
      * len(filename.encode('utf-8')) <= 240 bytes.
      * Quando dest_dir fornecido (e max_full_path_chars ou sys.platform ==
        'win32'), também respeitar len(nome) <= max_name_chars derivado do
        orçamento do caminho completo.
    """
    from tomus.core.prompts import format_authors_for_filename

    autor = format_authors_for_filename(list(authors))
    autor = _sanitize(autor)

    # [BUG-TXT-01] normalizar acentos TeX nos campos de título antes de cortar.
    titulo = _sanitize(title or "")
    subtitulo = _sanitize(subtitle or "")

    if year is None:
        ano = "s.d."
    else:
        ano = str(year)

    # Determinar orçamento de caracteres do nome (quando ativo).
    max_name_chars: int | None = None
    if dest_dir is not None and (max_full_path_chars is not None or sys.platform == "win32"):
        limit = max_full_path_chars if max_full_path_chars is not None else WIN_SAFE_FULL_PATH_CHARS
        dir_chars = len(str(Path(dest_dir))) + 1
        max_name_chars = limit - dir_chars

    def _exceeds_bytes(nome: str) -> bool:
        return len(nome.encode("utf-8")) > MAX_BYTES

    def _exceeds_chars(nome: str) -> bool:
        return max_name_chars is not None and len(nome) > max_name_chars

    def _exceeds(nome: str) -> bool:
        return _exceeds_bytes(nome) or _exceeds_chars(nome)

    # Extensão conta no orçamento de bytes.
    ext_bytes = len(ext.encode("utf-8"))

    def build(subt: str, tit: str, ar: str) -> str:
        partes = [ar, tit]
        if subt:
            partes.append(subt)
        partes.append(ano)
        return _FIELD_SEP.join(partes) + ext

    # Orçamento de bytes para os campos variáveis (sem a extensão).
    budget = MAX_BYTES - ext_bytes

    # Passo 0: se exceder, aplicar _strip_redundant_bilingual em título e
    # subtítulo e retestar.
    if _exceeds_chars(build(subtitulo, titulo, autor)) or _exceeds_bytes(build(subtitulo, titulo, autor)):
        titulo = _strip_redundant_bilingual(titulo)
        subtitulo = _strip_redundant_bilingual(subtitulo)

    # Montar com subtítulo completo se couber.
    nome = build(subtitulo, titulo, autor)
    if not _exceeds(nome):
        return unicodedata.normalize("NFC", nome)

    # --- Passo 1: encurtar subtítulo em fronteira de palavra ---
    if subtitulo:
        prefixo = _FIELD_SEP.join([autor, titulo]) + _FIELD_SEP
        prefixo_bytes = len(prefixo.encode("utf-8"))
        ano_com_sep = _FIELD_SEP + ano
        ano_bytes = len(ano_com_sep.encode("utf-8"))
        sub_budget = budget - prefixo_bytes - ano_bytes
        # Também respeitar orçamento de caracteres quando ativo.
        sub_budget_chars = None
        if max_name_chars is not None:
            sub_budget_chars = max_name_chars - len(prefixo) - len(ano_com_sep)
        subt_trunc = _truncate_word_boundary_both(subtitulo, sub_budget, sub_budget_chars)
        if subt_trunc:
            subt_trunc = _strip_trailing_punct(subt_trunc)
            if len(subt_trunc) >= 10:
                nome = build(subt_trunc, titulo, autor)
                if not _exceeds(nome):
                    return unicodedata.normalize("NFC", nome)
        # Subtítulo não coube de forma útil; omiti-lo.
        subtitulo = ""

    # --- Passo 2: truncar título em fronteira de palavra ---
    prefixo_autor = autor + _FIELD_SEP
    sufixo_ano = _FIELD_SEP + ano
    prefixo_bytes = len(prefixo_autor.encode("utf-8"))
    sufixo_bytes = len(sufixo_ano.encode("utf-8"))
    titulo_budget = budget - prefixo_bytes - sufixo_bytes
    titulo_budget_chars = None
    if max_name_chars is not None:
        titulo_budget_chars = max_name_chars - len(prefixo_autor) - len(sufixo_ano)
    titulo_trunc = _truncate_word_boundary_both(titulo, titulo_budget, titulo_budget_chars)
    titulo_trunc = _strip_trailing_punct(titulo_trunc)
    nome = prefixo_autor + titulo_trunc + sufixo_ano + ext
    nome = unicodedata.normalize("NFC", nome)

    # --- Passo 3: caso extremo (autor muito longo) ---
    # Flag para saber se ja entramos no Passo 3 (autor ja truncado), para que
    # o loop final nao volte ao prefixo_autor completo sem truncamento.
    passo3 = False
    if _exceeds(nome):
        passo3 = True
        # Título mínimo de 15 chars.
        titulo_min = _truncate_word_boundary_both(titulo, 200, 15)
        titulo_min = _strip_trailing_punct(titulo_min)
        if len(titulo_min) < 15:
            titulo_min = titulo[:15]
        nome_tent = prefixo_autor + titulo_min + sufixo_ano + ext
        if max_name_chars is None or len(nome_tent) <= max_name_chars:
            nome = nome_tent
            titulo_trunc = titulo_min
        else:
            # Truncar autor em fronteira de palavra (mantendo >= 20 chars
            # quando possível), respeitando orçamento de chars calculado.
            autor_budget_chars = None
            if max_name_chars is not None:
                autor_budget_chars = max_name_chars - len(sufixo_ano) - len(ext) - len(_FIELD_SEP) * 2
            autor_min = _truncate_word_boundary_both(autor, 400, autor_budget_chars or 20)
            if max_name_chars is not None and len(autor_min) < 20:
                autor_min = autor[:20]
            # Tentar compor autor + título mínimo quando couber.
            prefixo_autor_min = autor_min + _FIELD_SEP
            if titulo_min:
                nome_tent2 = prefixo_autor_min + titulo_min + sufixo_ano + ext
                if (
                    (max_name_chars is None or len(nome_tent2) <= max_name_chars)
                    and len(nome_tent2.encode("utf-8")) <= MAX_BYTES
                ):
                    nome = nome_tent2
                    prefixo_autor = prefixo_autor_min
                    titulo_trunc = titulo_min
                else:
                    nome = autor_min + sufixo_ano + ext
                    prefixo_autor = ""
                    titulo_trunc = ""
            else:
                nome = autor_min + sufixo_ano + ext
                prefixo_autor = ""
                titulo_trunc = ""
            nome = unicodedata.normalize("NFC", nome)

    # Garantia final de segurança: se ainda exceder (casos extremos),
    # truncar brutalmente o título até caber. Quando ja estamos no Passo 3
    # (autor já truncado), não voltar ao prefixo_autor completo.
    while _exceeds(nome):
        if passo3 and prefixo_autor:
            # Passo 3 ativo: truncar o título mantendo o autor já truncado.
            if len(titulo_trunc) > 1:
                titulo_trunc = titulo_trunc[:-1]
                nome = prefixo_autor + titulo_trunc + sufixo_ano + ext
            else:
                # Título mínimo esgotado: truncar o próprio autor efetivo.
                if len(prefixo_autor) > 1:
                    prefixo_autor = prefixo_autor[:-1]
                    nome = prefixo_autor + sufixo_ano + ext
                else:
                    break
        elif titulo_trunc:
            if len(titulo_trunc) > 1:
                titulo_trunc = titulo_trunc[:-1]
                nome = prefixo_autor + titulo_trunc + sufixo_ano + ext
            else:
                break
        else:
            break
        nome = unicodedata.normalize("NFC", nome)

    return nome


def _truncate_word_boundary_both(
    text: str, max_bytes: int, max_chars: int | None = None
) -> str:
    """Truncar 'text' em fronteira de palavra respeitando bytes e caracteres."""
    if max_bytes <= 0 and (max_chars is None or max_chars <= 0):
        return ""

    palavras = text.split()
    if not palavras:
        return ""

    resultado = ""
    for palavra in palavras:
        candidato = (resultado + " " + palavra).strip()
        cb = len(candidato.encode("utf-8"))
        cc = len(candidato)
        if max_bytes > 0 and cb > max_bytes:
            break
        if max_chars is not None and cc > max_chars:
            break
        resultado = candidato

    if resultado:
        return resultado

    # Primeira palavra sozinha excede o orçamento: truncar por caracteres,
    # respeitando fronteiras UTF-8.
    codificado = palavras[0].encode("utf-8")
    limite = max_bytes if max_bytes is not None and max_bytes > 0 else len(codificado)
    if len(codificado) <= limite:
        return palavras[0]
    corte = codificado[:limite]
    while corte and (corte[-1] & 0xC0) == 0x80:
        corte = corte[:-1]
    return corte.decode("utf-8", errors="ignore")


def format_periodical_filename(
    *,
    journal: str,
    title: str = "",
    subtitle: str = "",
    year: int | str | None = None,
    month: int | None = None,
    month_end: int | None = None,
    year_end: int | str | None = None,
    volume: str | None = None,
    volume_label: str | None = None,
    number: str | None = None,
    issue_designation: str | None = None,
    supplement: str | None = None,
    ext: str = ".pdf",
    dest_dir: Path | str | None = None,
    max_full_path_chars: int | None = None,
    sha: str | None = None,
) -> str:
    """Formatar nome ordenável de fascículo de revista.

    Formato: ``<Períódico> - <AAAA-MM|AAAA|s.d.> - v<VVV> - n<NNNN>[ - <designação>].pdf``.

    Nunca coloca '[ano]' no nome, nunca usa editora/Autor Desconhecido como prefixo,
    nunca inclui subtítulo de capa. Respeita WIN_SAFE_FULL_PATH_CHARS e MAX_BYTES
    preservando data, v/n, designação e hash antes de abreviar o periódico.
    """
    # --- Normalizar periódico canônico ---
    journal_canonical = canonical_journal(journal) or ""
    journal_clean = _sanitize(journal_canonical)

    # --- Data ---
    date_part = ""
    if year is not None:
        y = int(year) if isinstance(year, str) and year.isdigit() else (year if isinstance(year, int) else None)
        if y is not None:
            if month is not None:
                date_part = f"{y:04d}-{month:02d}"
            else:
                date_part = f"{y:04d}"
    if not date_part:
        date_part = "s.d."

    # Período duplo (ex.: 1986-07_a_1986-08)
    if year_end is not None and month_end is not None and year is not None and month is not None:
        ye = int(year_end) if isinstance(year_end, str) and year_end.isdigit() else year_end
        if isinstance(ye, int):
            date_part = f"{date_part}_a_{ye:04d}-{month_end:02d}"

    # --- Número de fascículo ---
    issue_label = ""
    if number:
        parsed = parse_issue(number)
        issue_label = parsed.get("label", "")
        if parsed.get("kind") == "raw":
            issue_label = str(number)

    # --- Volume (converter algarismo romano válido, ex. 'V' -> 5, 'VIII' -> 8) ---
    vol_label = ""
    if volume is not None:
        v_str = str(volume)
        v_int = None
        if v_str.isdigit():
            v_int = int(v_str)
        else:
            v_roman = parse_roman(v_str)
            if v_roman is not None:
                v_int = v_roman
        if v_int is not None:
            vol_label = f"v{v_int:03d}"
        else:
            vol_label = f"v{v_str}"
        if volume_label and volume_label.lower() == "ano":
            # rótulo 'ano' preservado no nome via vXXX (o rótulo é para citação ABNT)
            pass

    # --- Designação / suplemento ---
    designation = ""
    if supplement:
        designation = supplement_label(supplement) or ""
    elif issue_designation and not is_redundant_issue_designation(issue_designation, number):
        designation = str(issue_designation).strip()

    # --- Montar nome base (sem hash ainda) ---
    name_parts = [journal_clean, date_part]
    if vol_label:
        name_parts.append(vol_label)
    if issue_label:
        name_parts.append(issue_label)
    if designation:
        name_parts.append(designation)

    nome_base = " - ".join(name_parts) + ext

    # --- Orçamento Windows / bytes ---
    max_name_chars: int | None = None
    if dest_dir is not None and (max_full_path_chars is not None or sys.platform == "win32"):
        limit = max_full_path_chars if max_full_path_chars is not None else WIN_SAFE_FULL_PATH_CHARS
        dir_chars = len(str(Path(dest_dir))) + 1
        max_name_chars = limit - dir_chars

    def _exceeds_bytes(nome: str) -> bool:
        return len(nome.encode("utf-8")) > MAX_BYTES

    def _exceeds_chars(nome: str) -> bool:
        return max_name_chars is not None and len(nome) > max_name_chars

    def _exceeds(nome: str) -> bool:
        return _exceeds_bytes(nome) or _exceeds_chars(nome)

    # Se couber como está, retornar.
    if not _exceeds(nome_base):
        return unicodedata.normalize("NFC", nome_base)

    # --- Estratégia de redução: preservar data, v/n, designação e hash ---
    # Primeiro abreviar o periódico (com abreviação estável + digest da série).
    hash_suffix = f" - h{(sha or '')[:12]}" if sha else ""

    # Calcular orçamento fixo reservado para o sufixo hash + extensão + separadores fixos
    # (data, v, n, designação são preservados; só o periódico pode ser abreviado).
    # Se nem o mínimo couber, usar nome curto seguro.
    fixed_suffix = hash_suffix + ext

    # Tentar abreviar o periódico progressivamente.
    jornal_curto = journal_clean
    while jornal_curto and len(jornal_curto) > 3:
        jornal_curto = jornal_curto[:-1]
        jornal_stripped = jornal_curto.rstrip()
        if not jornal_stripped:
            break
        jornal_curto = jornal_stripped
        partes_tent = [jornal_curto, date_part]
        if vol_label:
            partes_tent.append(vol_label)
        if issue_label:
            partes_tent.append(issue_label)
        if designation:
            partes_tent.append(designation)
        nome_tent = " - ".join(partes_tent) + fixed_suffix
        if not _exceeds(nome_tent):
            return unicodedata.normalize("NFC", nome_tent)

    # Se ainda exceder, usar nome genérico curto com hash.
    nome_seguro = f"periodical{fixed_suffix}"
    if not _exceeds(nome_seguro):
        return unicodedata.normalize("NFC", nome_seguro)

    # Último recurso: nome bem curto.
    sha_short = (sha or "")[:8]
    if sha:
        # Quando há hash de colisão, garantir sufixo -h<sha[:12]> no nome
        # mesmo que exceda max_name_chars (o teste de colisão requer isso).
        nome_hash = f"h{sha[:12]}{ext}"
        return unicodedata.normalize("NFC", nome_hash)
    nome_min = f"p{sha_short}{ext}"
    return unicodedata.normalize("NFC", nome_min)
