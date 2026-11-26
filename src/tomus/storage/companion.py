"""Gerador de arquivo companheiro (.md) para cada PDF organizado.

Conforme a especificação, gera um arquivo Markdown com front matter YAML e
referência bibliográfica no estilo ABNT NBR 6023 ao lado de cada PDF
organizado na árvore temática, além dos arquivos companheiros em duplicatas/
e obsoletos/.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tomus.core.periodicals import is_redundant_issue_designation
from tomus.core.prompts import is_institutional_author


def _sobrenome_maiusculo(autor: str) -> str:
    """Extrair o sobrenome e colocá-lo em maiúsculas, preservando o restante.

    * Aceita 'Sobrenome, Nome' ou 'Nome Sobrenome'.
    * Preserva autores institucionais inteiros em maiúsculas (ou 'BRASIL. ...')
      sem inverter a última palavra.
    """
    autor = autor.strip()
    if not autor:
        return ""

    if is_institutional_author(autor):
        if re.match(r"^brasil[.,]\s*", autor, flags=re.IGNORECASE):
            resto = re.sub(r"^brasil[.,]\s*", "", autor, flags=re.IGNORECASE).strip()
            return f"BRASIL. {resto}" if resto else "BRASIL"
        return autor.upper()

    if "," in autor:
        partes = autor.split(",", 1)
        sobrenome = partes[0].strip()
        nome = partes[1].strip()
        return f"{sobrenome.upper()}, {nome}"

    partes = autor.split()
    if len(partes) == 1:
        return partes[0].upper()
    sobrenome = partes[-1].upper()
    nome = " ".join(partes[:-1])
    return f"{sobrenome}, {nome}"


def format_abnt_author(author: str) -> str:
    """Converter um único autor para o formato ABNT.

    * 'Márcio Borges Moreira' -> 'MOREIRA, Márcio Borges'
    * 'Moreira, M. B.' -> 'MOREIRA, M. B.' (preserva/ajusta)
    * 'Conselho Federal de Psicologia' -> 'CONSELHO FEDERAL DE PSICOLOGIA'
    """
    return _sobrenome_maiusculo(author)


def format_abnt_authors(authors: list[str]) -> str:
    """Formatar lista de autores segundo ABNT NBR 6023.

    * 1 autor: 'SILVA, João.'
    * 2 autores: 'SILVA, João; SANTOS, Maria.'
    * 3 autores: 'SILVA, João; SANTOS, Maria; OLIVEIRA, Pedro.'
    * Mais de 3 autores: 'SILVA, João et al.'
    * Sem autor: inicia pelo título (retorna string vazia).
    """
    if not authors:
        return ""
    autores_formatados = [_sobrenome_maiusculo(a) for a in authors if a.strip()]
    if not autores_formatados:
        return ""
    if len(autores_formatados) == 1:
        return f"{autores_formatados[0]}."
    if len(autores_formatados) == 2:
        return f"{autores_formatados[0]}; {autores_formatados[1]}."
    if len(autores_formatados) == 3:
        return f"{autores_formatados[0]}; {autores_formatados[1]}; {autores_formatados[2]}."
    return f"{autores_formatados[0]} et al."


def _primeira_palavra_maiuscula(titulo: str) -> str:
    """Deixar a primeira palavra do título em caixa alta."""
    titulo = titulo.strip()
    if not titulo:
        return ""
    match = re.match(r"^(\S+)(.*)$", titulo)
    if not match:
        return titulo
    primeira, resto = match.group(1), match.group(2)
    return primeira.upper() + resto


def format_abnt_reference(classification: dict[str, Any]) -> str:
    """Gerar referência bibliográfica completa segundo ABNT NBR 6023 em Markdown."""
    authors = classification.get("authors") or []
    title = (classification.get("titulo") or classification.get("title") or "").strip()
    subtitle = (classification.get("subtitulo") or classification.get("subtitle") or "").strip()
    year = classification.get("ano") or classification.get("year")
    edition = classification.get("edicao") or classification.get("edition")
    city = classification.get("cidade") or classification.get("city")
    publisher = classification.get("editora") or classification.get("publisher")
    journal_name = classification.get("periodico") or classification.get("journal_name")
    volume = classification.get("volume")
    volume_label = classification.get("rotulo_volume") or classification.get("volume_label")
    number = classification.get("numero") or classification.get("number")
    pages = classification.get("paginas") or classification.get("pages")
    doi = classification.get("doi")
    isbn = classification.get("isbn")
    tipo = str(classification.get("tipo") or "")

    autores_texto = format_abnt_authors(authors).strip().rstrip(".")

    if not title:
        title = "Sem título"
    title = title.strip()

    partes: list[str] = []

    if tipo == "Artigo" and journal_name:
        if autores_texto:
            partes.append(autores_texto)

        art_title = f"{title}: {subtitle}" if subtitle else title
        if not autores_texto:
            art_title = _primeira_palavra_maiuscula(art_title)
        partes.append(art_title.rstrip("."))

        j_parts = [f"**{journal_name}**"]
        if city:
            j_parts.append(city)
        if volume:
            v_str = f"v. {volume}" if not str(volume).lower().startswith("v.") else str(volume)
            j_parts.append(v_str)
        if number:
            n_str = f"n. {number}" if not str(number).lower().startswith("n.") else str(number)
            j_parts.append(n_str)
        if pages:
            p_str = f"p. {pages}" if not str(pages).lower().startswith("p.") else str(pages)
            j_parts.append(p_str)
        if year is not None:
            j_parts.append(str(year))

        partes.append(", ".join(j_parts))
    elif tipo in ("Revista", "Revista Científica"):
        # Ramo de fascículo (NBR 6023:2025, §7.7.3) ANTES do livro.
        # Inicia pelo periódico em caixa alta. NÃO incluir autores antes do periódico.
        partes = []
        jn = journal_name or title
        partes.append(f"**{jn.upper()}**.")
        # Corpo editorial em UMA string limpa: "city: publisher, ano X, n. Y, mes. ano."
        editorial_parts: list[str] = []
        if city:
            editorial_parts.append(city)
        if publisher:
            editorial_parts.append(f": {publisher}")
        # Rótulo do volume ('ano' vs 'v.').
        if volume is not None:
            v_str = str(volume)
            if volume_label and volume_label.strip().lower().startswith("ano"):
                editorial_parts.append(f", ano {v_str}")
            else:
                v_fmt = f"v. {v_str}" if not v_str.lower().startswith("v.") else v_str
                editorial_parts.append(f", {v_fmt}")
        if number is not None:
            n_fmt = f"n. {number}" if not str(number).lower().startswith("n.") else str(number)
            editorial_parts.append(f", {n_fmt}")
        # Mês por extenso (abreviado) se disponível.
        month = classification.get("publication_month")
        month_pt_abrev = {
            1: "jan.", 2: "fev.", 3: "mar.", 4: "abr.", 5: "mai.", 6: "jun.",
            7: "jul.", 8: "ago.", 9: "set.", 10: "out.", 11: "nov.", 12: "dez.",
        }
        if month is not None and month in month_pt_abrev:
            editorial_parts.append(f", {month_pt_abrev[month]}")
        if year is not None:
            editorial_parts.append(f", {year}")
        # Designação de suplemento/especial após a data.
        designation = classification.get("issue_designation") or classification.get("designacao_fasciculo")
        supplement = classification.get("supplement")
        if supplement:
            editorial_parts.append(f", suplemento {supplement}")
        elif designation and not is_redundant_issue_designation(designation, number):
            editorial_parts.append(f", {designation}")

        partes.append("".join(editorial_parts).lstrip(":, "))
    else:
        if autores_texto:
            partes.append(autores_texto)

        titulo_formatado = f"**{title}**"
        if subtitle:
            titulo_formatado = f"**{title}**: {subtitle}"

        if not autores_texto:
            titulo_formatado = _primeira_palavra_maiuscula(titulo_formatado)
        partes.append(titulo_formatado)

        if edition:
            ed_str = f"{str(edition).rstrip('.')}." if not str(edition).endswith("ed.") else str(edition)
            partes.append(ed_str)

        imprint_parts: list[str] = []
        if city and publisher:
            imprint_parts.append(f"{city}: {publisher}")
        elif publisher:
            imprint_parts.append(f"[S.l.]: {publisher}")
        elif city:
            imprint_parts.append(f"{city}: [s.n.]")

        if year is not None:
            if imprint_parts:
                imprint_parts[0] += f", {year}"
            else:
                imprint_parts.append(str(year))

        if imprint_parts:
            partes.append(imprint_parts[0])

        if pages:
            p_str = f"{pages} p." if str(pages).isdigit() else str(pages)
            partes.append(p_str)

    partes_limpas = [p.strip().rstrip(".") for p in partes if p and p.strip()]
    referencia = ". ".join(partes_limpas) + "."

    if doi:
        doi_clean = str(doi).strip()
        doi_url = doi_clean if doi_clean.startswith("http") else f"https://doi.org/{doi_clean}"
        referencia += f" Disponível em: {doi_url}."
    if isbn:
        referencia += f" ISBN {str(isbn).strip()}."

    return referencia


def generate_companion_markdown(
    destination_path: Path,
    source_path: Path,
    sha256: str,
    classification: dict[str, Any],
    used_ocr: bool = False,
) -> str:
    """Gerar o conteúdo Markdown completo do arquivo companheiro."""
    authors = classification.get("authors") or []
    title = classification.get("titulo") or classification.get("title") or ""
    subtitle = classification.get("subtitulo") or classification.get("subtitle") or ""
    year = classification.get("ano") or classification.get("year")
    publisher = classification.get("editora") or classification.get("publisher")
    city = classification.get("cidade") or classification.get("city")
    edition = classification.get("edicao") or classification.get("edition")
    journal_name = classification.get("periodico") or classification.get("journal_name")
    volume = classification.get("volume")
    number = classification.get("numero") or classification.get("number")
    pages = classification.get("paginas") or classification.get("pages")
    paginas_pdf = classification.get("paginas_pdf")
    grande_area = classification.get("grande_area", "")
    area_basica = classification.get("area_basica", "")
    subarea = classification.get("subarea", "")
    especialidade = classification.get("especialidade", "")
    tipo = classification.get("tipo", "")
    doi = classification.get("doi")
    isbn = classification.get("isbn")
    confidence_score = classification.get("confidence_score", 0.0)

    now = datetime.now()
    organized_at = now.strftime("%Y-%m-%d %H:%M:%S")
    data_amigavel = now.strftime("%d/%m/%Y às %H:%M:%S")

    lines: list[str] = []
    lines.append("---")
    lines.append(f"titulo: {title!r}")
    if subtitle:
        lines.append(f"subtitulo: {subtitle!r}")
    if authors:
        lines.append("autores:")
        for a in authors:
            lines.append(f"  - {a!r}")
    if year is not None:
        lines.append(f"ano: {year}")
    if publisher:
        lines.append(f"editora: {publisher!r}")
    if city:
        lines.append(f"cidade: {city!r}")
    if edition:
        lines.append(f"edicao: {edition!r}")
    if journal_name:
        lines.append(f"periodico: {journal_name!r}")
    if volume:
        lines.append(f"volume: {str(volume)!r}")
    if number:
        lines.append(f"numero: {str(number)!r}")
    if pages:
        lines.append(f"paginas: {str(pages)!r}")
    if paginas_pdf is not None:
        lines.append(f"paginas_pdf: {int(paginas_pdf)}")
    if doi:
        lines.append(f"doi: {doi!r}")
    if isbn:
        lines.append(f"isbn: {isbn!r}")
    # --- Campos seriais (PR #14) ---
    if classification.get("publication_month") is not None:
        lines.append(f"mes: {int(classification['publication_month'])}")
    if classification.get("publication_month_end") is not None:
        lines.append(f"mes_final: {int(classification['publication_month_end'])}")
    if classification.get("publication_year_end") is not None:
        lines.append(f"ano_final: {int(classification['publication_year_end'])}")
    if classification.get("issn"):
        lines.append(f"issn: {classification['issn']!r}")
    if classification.get("journal_genre"):
        lines.append(f"natureza_editorial: {classification['journal_genre']!r}")
    if classification.get("volume_label"):
        lines.append(f"rotulo_volume: {classification['volume_label']!r}")
    if classification.get("issue_designation"):
        lines.append(f"designacao_fasciculo: {classification['issue_designation']!r}")
    if classification.get("serial_evidence"):
        lines.append(f"evidencia_serial: {classification['serial_evidence']!r}")
    lines.append(f"grande_area: {grande_area!r}")
    lines.append(f"area_basica: {area_basica!r}")
    lines.append(f"subarea: {subarea!r}")
    lines.append(f"especialidade: {especialidade!r}")
    lines.append(f"tipo: {tipo!r}")
    lines.append(f"sha256: {sha256}")
    lines.append(f"indice_confianca: {confidence_score}")
    lines.append(f"utilizou_ocr: {str(used_ocr).lower()}")
    lines.append(f"arquivo_origem: {source_path.name!r}")
    lines.append(f"organizado_em: {organized_at!r}")
    lines.append("---")
    lines.append("")

    lines.append(f"# {title}")
    lines.append("")
    referencia = format_abnt_reference(classification)
    lines.append("## Referência Bibliográfica (ABNT NBR 6023)")
    lines.append("")
    lines.append(referencia)
    lines.append("")
    lines.append("## Metadados do Arquivo")
    lines.append("")
    lines.append(f"- **Área Temática:** {grande_area} / {area_basica} / {subarea} / {especialidade}")
    lines.append(f"- **Tipo de Documento:** {tipo}")
    if journal_name:
        lines.append(f"- **Periódico / Revista:** {journal_name}")
    if volume or number:
        vol_str = f"v. {volume}" if volume and not str(volume).lower().startswith("v.") else (volume or "")
        num_str = f"n. {number}" if number and not str(number).lower().startswith("n.") else (number or "")
        vol_num = ", ".join(filter(None, [vol_str, num_str]))
        lines.append(f"- **Volume / Fascículo:** {vol_num}")
    if publisher:
        lines.append(f"- **Editora / Publicador:** {publisher}")
    if city:
        lines.append(f"- **Local de Publicação:** {city}")
    if edition:
        lines.append(f"- **Edição:** {edition}")
    if pages:
        lines.append(f"- **Páginas:** {pages}")
    if paginas_pdf is not None:
        lines.append(f"- **Páginas do PDF:** {int(paginas_pdf)}")
    if doi:
        doi_clean = str(doi).strip()
        doi_url = doi_clean if doi_clean.startswith("http") else f"https://doi.org/{doi_clean}"
        lines.append(f"- **DOI:** {doi_url}")
    if isbn:
        lines.append(f"- **ISBN:** {isbn}")
    lines.append(f"- **Arquivo Original:** {source_path.name}")
    lines.append(f"- **SHA-256:** {sha256}")
    lines.append(f"- **Organizado em:** {data_amigavel}")

    return "\n".join(lines) + "\n"


def _resolve_canonical_paths(
    canonical_dest: Path,
    target_dir: Path | None = None,
) -> tuple[str, str]:
    """Resolver caminhos exibíveis do canônico.

    Se ``target_dir`` for informado, o caminho é tornado relativo a ele.
    Caso contrário, usa o diretório de trabalho atual como referência, com
    fallback para o caminho absoluto se não for possível torná-lo relativo.
    """
    if target_dir is not None:
        try:
            canonical_rel = canonical_dest.resolve().relative_to(target_dir.resolve())
            canonical_path = canonical_rel.as_posix()
        except ValueError:
            canonical_path = canonical_dest.resolve().as_posix()
    else:
        if not canonical_dest.is_absolute():
            canonical_path = canonical_dest.as_posix()
        else:
            try:
                canonical_rel = canonical_dest.resolve().relative_to(Path.cwd().resolve())
                canonical_path = canonical_rel.as_posix()
            except ValueError:
                canonical_path = canonical_dest.resolve().as_posix()
    return canonical_path, Path(canonical_path).with_suffix(".md").as_posix()


_CAMADA_DETECCAO_PT_BR: dict[str, str] = {
    "L3_FINGERPRINT": "L3_IMPRESSAO_DIGITAL",
    "L2_IDENTIFIER": "L2_IDENTIFICADOR",
}


def _traduzir_camada_deteccao(match_layer: str) -> str:
    """Normalizar identificador de camada de detecção para pt-BR."""
    raw = (match_layer or "").strip()
    return _CAMADA_DETECCAO_PT_BR.get(raw, raw)


def generate_duplicate_companion_markdown(
    duplicate_source: Path,
    canonical_dest: Path,
    sha256: str,
    match_layer: str = "L1_SHA256",
    target_dir: Path | None = None,
) -> str:
    """Gerar arquivo companheiro .md para uma duplicata detectada."""
    now = datetime.now()
    detected_at = now.strftime("%Y-%m-%d %H:%M:%S")
    data_detectada = now.strftime("%d/%m/%Y às %H:%M:%S")
    canonical_path, canonical_md = _resolve_canonical_paths(canonical_dest, target_dir)
    camada_pt = _traduzir_camada_deteccao(match_layer)

    lines: list[str] = []
    lines.append("---")
    lines.append("status: 'duplicata'")
    lines.append(f"camada_deteccao: {camada_pt!r}")
    lines.append(f"arquivo_origem: {duplicate_source.name!r}")
    lines.append(f"sha256: {sha256}")
    lines.append(f"caminho_canonico: {canonical_path!r}")
    lines.append(f"detectado_em: {detected_at!r}")
    lines.append("---")
    lines.append("")

    lines.append(f"# {duplicate_source.name}")
    lines.append("")
    lines.append("## Arquivo Duplicado Detectado")
    lines.append("")
    lines.append(f"- **Detectado em:** {data_detectada}")
    lines.append(f"- **Camada de detecção:** {camada_pt}")
    lines.append("")
    lines.append(
        "Este arquivo é uma **duplicata da mesma edição** de uma obra já organizada "
        "na árvore temática. Por não haver conteúdo ou edição mais recente, foi mantido apenas "
        "o exemplar canônico."
    )
    lines.append("")
    lines.append("### Informações da Duplicata")
    lines.append("")
    lines.append(f"- **Arquivo duplicado:** {duplicate_source.name}")
    lines.append(f"- **SHA-256:** {sha256}")
    lines.append(f"- **Detectado em:** {detected_at}")
    lines.append("")
    lines.append("### Obra Canônica")
    lines.append("")
    lines.append(f"- **PDF canônico:** {canonical_path}")
    lines.append(f"- **Companheiro canônico:** {canonical_md}")
    lines.append("")
    lines.append("> Apenas a cópia canônica foi mantida na árvore temática.")

    return "\n".join(lines) + "\n"


def generate_obsolete_companion_markdown(
    obsolete_source: Path,
    canonical_dest: Path,
    sha256: str,
    match_layer: str = "L2_IDENTIFIER",
    obsolete_info: dict[str, Any] | None = None,
    canonical_info: dict[str, Any] | None = None,
    replaced_existing: bool = False,
    target_dir: Path | None = None,
) -> str:
    """Gerar arquivo companheiro .md para uma edição superada enviada a obsoletos/."""
    now = datetime.now()
    detected_at = now.strftime("%Y-%m-%d %H:%M:%S")
    data_detectada = now.strftime("%d/%m/%Y às %H:%M:%S")
    canonical_path, canonical_md = _resolve_canonical_paths(canonical_dest, target_dir)
    camada_pt = _traduzir_camada_deteccao(match_layer)
    obs = obsolete_info or {}
    can = canonical_info or {}

    lines: list[str] = []
    lines.append("---")
    lines.append("status: 'obsoleto'")
    lines.append(f"camada_deteccao: {camada_pt!r}")
    lines.append(f"substituiu_existente: {str(replaced_existing).lower()}")
    lines.append(f"arquivo_origem: {obsolete_source.name!r}")
    if obs.get("titulo"):
        lines.append(f"titulo: {obs['titulo']!r}")
    if obs.get("ano") is not None:
        lines.append(f"ano_obsoleto: {obs['ano']}")
    if obs.get("edicao"):
        lines.append(f"edicao_obsoleta: {obs['edicao']!r}")
    if can.get("ano") is not None:
        lines.append(f"ano_canonico: {can['ano']}")
    if can.get("edicao"):
        lines.append(f"edicao_canonica: {can['edicao']!r}")
    lines.append(f"sha256: {sha256}")
    lines.append(f"caminho_canonico: {canonical_path!r}")
    lines.append(f"detectado_em: {detected_at!r}")
    lines.append("---")
    lines.append("")

    lines.append(f"# {obsolete_source.name}")
    lines.append("")
    lines.append("## Edição Obsoleta Arquivada")
    lines.append("")
    lines.append(f"- **Detectado em:** {data_detectada}")
    lines.append(f"- **Camada de detecção:** {camada_pt}")
    lines.append(f"- **Substituiu exemplar anteriormente na árvore:** {'Sim' if replaced_existing else 'Não'}")
    lines.append("")
    lines.append(
        "Esta edição foi superada por uma edição/ano mais recente da mesma obra. "
        "A edição mais recente permanece ativa na árvore temática e este exemplar "
        "foi preservado em `obsoletos/`."
    )
    lines.append("")
    lines.append("### Edição Superada (Obsoleta)")
    lines.append("")
    lines.append(f"- **Arquivo:** {obsolete_source.name}")
    lines.append(f"- **Ano / Edição:** {obs.get('ano', 's.d.')} / {obs.get('edicao') or 'não especificada'}")
    lines.append(f"- **SHA-256:** {sha256}")
    lines.append("")
    lines.append("### Edição Canônica Ativa (Mais Recente)")
    lines.append("")
    lines.append(f"- **Ano / Edição:** {can.get('ano', 's.d.')} / {can.get('edicao') or 'não especificada'}")
    lines.append(f"- **PDF canônico:** {canonical_path}")
    lines.append(f"- **Companheiro canônico:** {canonical_md}")

    return "\n".join(lines) + "\n"
