"""Prompt de sistema e payload contextual do classificador LLM (Item 17).

Concentra as instruções de classificação e o controle de orçamento de tokens:
* texto amostrado (sampled_text) limitado a 15.000 caracteres, priorizando cip_text;
* regras dos 5 tipos documentais (Livro, Revista Científica, Artigo,
  Tese_Dissertacao, Outros);
* padronização de autores pessoais ('Sobrenome, Nome') e autoria institucional;
* catálogo fechado da CAPES/CNPq via format_taxonomy_for_prompt;
* pistas de arquivo de origem sanitizadas contra prompt injection.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from tomus.core.models import ExternalMetadata
from tomus.core.taxonomy import format_taxonomy_for_prompt

# Tamanho máximo do texto amostrado enviado ao classificador (em caracteres).
MAX_SAMPLED_TEXT_CHARS = 15_000

# Valores genéricos de título que reduzem a confiança quando não há autor.
GENERIC_TITLES = {
    "sem título", "sem titulo", "untitled", "unknown", "desconhecido",
    "documento", "pdf", "artigo", "livro", "slide",
}

# Prefixos genéricos de exportação de escritório que reduzem a confiança.
GENERIC_TITLE_PREFIXES = ("microsoft powerpoint -", "microsoft word -")

# ---------------------------------------------------------------------------
# Normalização de autores pessoais e institucionais
# ---------------------------------------------------------------------------
_INSTITUTIONAL_RE = re.compile(
    r"\b(conselho|associa|association|organiza|organization|minist|secretaria|"
    r"universidade|university|instituto|institute|fundacao|fundação|foundation|"
    r"sociedade|society|federa|comissao|comissão|comite|comitê|governo|forum|fórum|"
    r"centro|world health|unesco|unicef|brasil|crp|cfp|oms|who|apa)\b"
)

_INSTITUTIONAL_ALIASES: dict[str, str] = {
    "cfp": "Conselho Federal de Psicologia",
    "conselho federal de psicologia": "Conselho Federal de Psicologia",
    "apa": "American Psychiatric Association",
    "apa american psychiatric association": "American Psychiatric Association",
    "american psychiatric association": "American Psychiatric Association",
    "associacao americana de psiquiatria": "American Psychiatric Association",
    "oms": "Organização Mundial da Saúde",
    "who": "Organização Mundial da Saúde",
    "world health organization": "Organização Mundial da Saúde",
    "organizacao mundial da saude": "Organização Mundial da Saúde",
}

_SURNAME_SUFFIXES = {"filho", "junior", "jr", "neto", "sobrinho", "segundo"}
_UNKNOWN_AUTHORS = {"autor desconhecido", "desconhecido", "anonimo", "anônimo", "unknown", "n/a"}


def _fold_author_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def is_institutional_author(raw: str) -> bool:
    """Identificar se o nome de autor representa uma instituição/órgão."""
    cleaned = " ".join(str(raw or "").replace("\u00a0", " ").split()).strip(" .;")
    if not cleaned:
        return False
    folded = _fold_author_text(cleaned)
    if folded in _INSTITUTIONAL_ALIASES:
        return True
    if _INSTITUTIONAL_RE.search(folded):
        # Evita falsos positivos caso um autor pessoal tenha sobrenome curto antes de vírgula
        if "," in cleaned and len(cleaned.split(",", 1)[0].split()) == 1 and not folded.startswith("brasil"):
            return False
        return True
    return False


def normalize_author_name(raw: str) -> str:
    """Normalizar nome de autor (pessoal ou institucional) preservando 'Sobrenome, Nome'.

    * Instituições são preservadas por extenso sem inversão (ex.: ``CFP`` ->
      ``Conselho Federal de Psicologia``; ``Brasil, Ministério...`` ->
      ``Brasil. Ministério...``).
    * Nomes pessoais já em ``Sobrenome, Nome`` têm apenas espaços limpos,
      preservando prenomes ou iniciais existentes.
    * Nomes pessoais sem vírgula (ex.: ``Donald Woods Winnicott``) são convertidos
      para ``Winnicott, Donald Woods`` (respeitando sufixos como Filho/Júnior/Neto).
    """
    cleaned = " ".join(str(raw or "").replace("\u00a0", " ").split()).strip(" .;")
    folded = _fold_author_text(cleaned)
    if not cleaned or folded in _UNKNOWN_AUTHORS:
        return "Autor Desconhecido"

    if folded in _INSTITUTIONAL_ALIASES:
        return _INSTITUTIONAL_ALIASES[folded]

    if is_institutional_author(cleaned):
        return re.sub(r"^(Brasil)\s*[,.]\s*", r"\1. ", cleaned, flags=re.I)

    if "," in cleaned:
        surname, given = [part.strip() for part in cleaned.split(",", 1)]
        return f"{surname}, {given}".strip(", ")

    parts = cleaned.split()
    if len(parts) == 1:
        return parts[0]

    cut = len(parts) - 1
    if _fold_author_text(parts[-1]) in _SURNAME_SUFFIXES and len(parts) > 2:
        cut -= 1
    surname = " ".join(parts[cut:])
    given = " ".join(parts[:cut])
    return f"{surname}, {given}"


def normalize_authors(authors: list[str] | None) -> list[str]:
    """Normalizar e deduplicar a lista de autores mantendo a ordem."""
    if not authors:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in authors:
        norm = normalize_author_name(raw)
        if not norm:
            continue
        key = _fold_author_text(norm)
        if key not in seen:
            seen.add(key)
            result.append(norm)
    return result


def extract_first_author_key(authors: list[str] | None) -> str:
    """Extrair chave canônica do sobrenome (ou instituição) do primeiro autor."""
    if not authors:
        return ""
    norm = normalize_author_name(authors[0])
    if norm == "Autor Desconhecido":
        return ""
    if is_institutional_author(norm):
        return _fold_author_text(norm)
    surname = norm.split(",", 1)[0].strip() if "," in norm else norm
    surname = re.sub(r"^(de|da|do|dos|das)[- ]+", "", surname, flags=re.I)
    return _fold_author_text(surname).replace(" ", "")


def _sanitize_path_hint(value: str, max_len: int = 180) -> str:
    """Sanitizar pistas de caminho de arquivo contra prompt injection.

    Remove caracteres de controle, quebras de linha, blocos de código,
    marcadores de cabeçalho e tokens típicos de injeção de prompt
    (ex.: ``<<``, ``>>``, ``{{``, ``}}``, ``<|``, ``|>``, ``###``, ``---``,
    palavras-chave de instrução) antes de compor o trecho enviado ao LLM.
    """
    clean = str(value or "")
    # Neutralizar blocos de código e marcadores de seção.
    clean = clean.replace("```", " ").replace("###", " ")
    clean = clean.replace("<<", " ").replace(">>", " ")
    clean = clean.replace("{{", " ").replace("}}", " ")
    clean = clean.replace("<|", " ").replace("|>", " ")
    clean = clean.replace("---", " ").replace("...", " ")
    # Remover tokens comuns de injeção de prompt.
    injection_tokens = (
        "ignore previous", "ignore anterior", "sobreescrever", "overwrite",
        "system:", "user:", "assistant:", "instrução:", "instruction:",
        "prompt:", "esqueça", "forget", "disregard", "desconsidere",
        "jailbreak", "dan ", "developer mode", "modo desenvolvedor",
    )
    lowered = clean.lower()
    for token in injection_tokens:
        lowered = lowered.replace(token, " ")
    clean = lowered
    # Colapsar espaços e remover caracteres de controle/residuais.
    clean = re.sub(r"[\r\n\x00-\x1f\x7f]+", " ", clean)
    clean = " ".join(clean.split())
    return clean[:max_len]


def _truncate_sampled_text(sampled_text: str, cip_text: str) -> str:
    """Truncar sampled_text priorizando a integralidade de cip_text.

    A Ficha Catalográfica (CIP) é sempre preservada completa; o restante do
    texto amostrado é preenchido com o espaço restante dentro do limite de
    15.000 caracteres.
    """
    if len(sampled_text) <= MAX_SAMPLED_TEXT_CHARS:
        return sampled_text

    reserve = len(cip_text)
    budget = MAX_SAMPLED_TEXT_CHARS - reserve
    if budget <= 0:
        return cip_text[:MAX_SAMPLED_TEXT_CHARS]

    return sampled_text[:budget] + "\n..." + cip_text


def build_system_prompt() -> str:
    """Construir o prompt de sistema com regras de classificação fechadas e schema JSON explícito."""
    return (
        "Você é um classificador acadêmico especializado na tabela CAPES/CNPq e na catalogação ABNT NBR 6023.\n"
        "Sua tarefa é classificar um documento PDF com base no texto amostrado "
        "extraído (páginas iniciais e finais) e na Ficha Catalográfica (CIP) "
        "quando disponível, extraindo com máximo rigor todos os metadados bibliográficos disponíveis.\n\n"
        "Regras obrigatórias de classificação e extração de metadados:\n"
        "1. Responda SOMENTE em JSON válido estritamente no esquema solicitado.\n"
        "2. 'grande_area' e 'area_basica' devem pertencer ao catálogo fechado "
        "CAPES/CNPq fornecido no contexto; não invente categorias.\n"
        "3. 'subarea' deve priorizar o vocabulário controlado fornecido para a Área Básica "
        "(ex: 'Psicanálise', 'Avaliação Psicológica', 'Psicologia Clínica' dentro de Psicologia). "
        "Use 'Geral' quando não houver subárea mais específica.\n"
        "4. 'especialidade' é a especialidade dentro da subárea. Use 'Não especificada' se não houver.\n"
        "5. 'tipo' deve ser exatamente um dos cinco valores: Livro, \"Revista\", Artigo, Tese_Dissertacao ou Outros. "
        "Use 'Revista' para fascículo completo de periódico (capa, expediente e sumário com múltiplas seções independentes). "
        "Use 'Artigo' somente para contribuição individual com delimitação de páginas.\n"
        "6. 'authors': para fascículo de revista usar lista vazia [] por padrão (autoria do todo é do periódico/editora; "
        "manter editora em 'publisher'). Para pessoas físicas use 'Sobrenome, Nome'. Para autoria institucional ou "
        "corporativa (ex: Conselho Federal de Psicologia, Organização Mundial da Saúde, American Psychiatric Association, "
        "Brasil. Ministério da Saúde), mantenha o nome oficial completo por extenso SEM inverter por vírgula e NUNCA use "
        "'Autor Desconhecido' quando a entidade estiver explicitada. Use ['Autor Desconhecido'] somente se não houver "
        "autor identificável (apenas em Artigo/Livro).\n"
        "7. 'title' deve ser o título principal da obra/documento em português ou idioma original.\n"
        "8. 'subtitle' deve ser o subtítulo da obra se houver, ou string vazia (\"\") se ausente.\n"
        "9. 'year' deve ser o ano civil de publicação da edição efetiva do PDF como inteiro de 4 dígitos. "
        "Distinguir ano civil de ano editorial (ex.: \"Ano V\"): 'Ano V' nunca preenche o ano civil; registrar separadamente "
        "quando houver respaldo editorial. Priorizar o ano desta edição/tradução na ficha catalográfica/folha de rosto sobre o "
        "ano da obra original, ou null se não puder ser determinado.\n"
        "10. 'publisher' deve ser o nome da editora ou publicador, ou null se não constar.\n"
        "11. 'city' deve ser a cidade / local de publicação, ou null se não constar.\n"
        "12. 'edition' deve ser a edição da obra quando explicitada (ex: '2. ed.', '6. ed.'), ou null.\n"
        "13. 'journal_name' deve ser o título do periódico científico se o tipo for Artigo ou Revista, ou null se livro.\n"
        "14. 'volume' deve ser o volume do periódico ou volume da obra se explicitado, ou null.\n"
        "15. 'number' deve ser o número ou fascículo do periódico se indicado, ou null. "
        "Preservar valores como '52/53', '52A' e zero apenas quando explicitamente impresso.\n"
        "16. 'pages' deve ser a paginação inicial e final do artigo (ex: '134-155') ou total de páginas do livro, ou null.\n"
        "17. 'doi' deve ser extraído somente se o identificador DOI real (formato '10.xxxx/xxxxx') constar no texto ou nos metadados externos; "
        "caso contrário, use null (nunca invente). Não converter DOI de uma matéria citada em identidade do fascículo.\n"
        "18. 'isbn' deve ser extraído somente se um ISBN real (formato '978-xx-xxxx-xxx-x' ou 10 dígitos) constar na ficha catalográfica, texto ou metadados externos; "
        "caso contrário, use null (nunca invente).\n"
        "19. 'confidence_score' deve estar entre 0.0 e 1.0 representando o grau de certeza na classificação temática.\n"
        "20. 'reasoning' deve justificar brevemente a escolha da Grande Área, Área Básica e Subárea com base no texto analisado.\n\n"
        "Formato JSON obrigatório:\n"
        "{\n"
        '  "grande_area": "string (exata da tabela CAPES)",\n'
        '  "area_basica": "string (exata da tabela CAPES)",\n'
        '  "subarea": "string (subárea controlada ou \"Geral\")",\n'
        '  "especialidade": "string (especialidade dentro da subárea ou \"Não especificada\")",\n'
        '  "tipo": "Livro | Revista | Artigo | Tese_Dissertacao | Outros",\n'
        '  "authors": ["Sobrenome, Nome"],\n'
        '  "title": "string (título completo)",\n'
        '  "subtitle": "string (subtítulo ou vazio)",\n'
        '  "year": 2022,\n'
        '  "publisher": "string ou null",\n'
        '  "city": "string ou null",\n'
        '  "edition": "string ou null",\n'
        '  "journal_name": "string ou null",\n'
        '  "volume": "string ou null",\n'
        '  "number": "string ou null",\n'
        '  "pages": "string ou null",\n'
        '  "doi": "string ou null",\n'
        '  "isbn": "string ou null",\n'
        '  "confidence_score": 0.95,\n'
        '  "reasoning": "string (justificativa sucinta)"\n'
        "}\n\n"
        "Distinga os tipos documentais assim:\n"
        "- Livro: obra monográfica completa, livro-texto ou coletânea.\n"
        "- Revista: fascículo completo de periódico (capa, expediente e sumário com múltiplas seções/colaborações independentes). "
        "Ler cabeçalho, capa, expediente e sumário; registrar periódico, número, volume, ano civil e mês quando houver respaldo editorial.\n"
        "- Artigo: artigo científico individual, ensaio acadêmico ou revisão de literatura avulsa publicado em revista/periódico ou anais.\n"
        "- Tese_Dissertacao: teses, dissertações, TCCs e monografias acadêmicas.\n"
        "- Outros: slides de aula, apostilas institucionais, cartilhas, relatórios ou ementas.\n\n"
        "Edição especial (ex.: 'Especial Pascal', 'Informática 86') apenas quando identificada inequivocamente no expediente/capa; "
        "uma chamada de matéria na capa não torna a edição inteira especial. '86', nome de origem, extensão ou número de página isolados não autorizam extrair fascículo.\n"
        "Extraia cidade, editora, periódico, volume, número, mês e páginas examinando atentamente o cabeçalho, rodapé da primeira página ou ficha catalográfica CIP."
    )


def build_context_payload(
    sampled_text: str,
    cip_text: str,
    external_metadata: ExternalMetadata | None = None,
    source_path: Path | None = None,
) -> str:
    """Montar o payload contextual enviado ao LLM.

    O texto amostrado é truncado a no máximo 15.000 caracteres, priorizando a
    preservação integral de cip_text. Metadados externos e pistas sanitizadas
    do caminho de origem (quando disponíveis) auxiliam a classificação.
    """
    lines: list[str] = []
    lines.append("### Contexto do documento")
    lines.append("")
    lines.append(format_taxonomy_for_prompt())
    lines.append("")

    if source_path is not None:
        safe_name = _sanitize_path_hint(source_path.name)
        safe_parent = _sanitize_path_hint(source_path.parent.name)
        if safe_name or safe_parent:
            lines.append("### Pistas do arquivo de origem (auxiliar; menor prioridade que CIP e folha de rosto)")
            if safe_name:
                lines.append(f"Nome do arquivo: {safe_name}")
            if safe_parent:
                lines.append(f"Pasta de origem: {safe_parent}")
            lines.append("")

    texto_amostrado = _truncate_sampled_text(sampled_text, cip_text)

    if cip_text:
        lines.append("### Ficha Catalográfica (CIP) - prioridade integral")
        lines.append(cip_text)
        lines.append("")

    lines.append("### Texto amostrado (páginas iniciais e finais)")
    lines.append(texto_amostrado)
    lines.append("")

    if external_metadata is not None:
        lines.append("### Metadados externos (OpenAlex / Google Books)")
        lines.append(f"Título: {external_metadata.title or '(não informado)'}")
        lines.append(f"Subtítulo: {external_metadata.subtitle or '(não informado)'}")
        authors = ", ".join(external_metadata.authors) or "(não informado)"
        lines.append(f"Autores: {authors}")
        lines.append(f"Ano: {external_metadata.publication_year or '(não informado)'}")
        if external_metadata.journal_name:
            lines.append(f"Periódico / Revista sugerido: {external_metadata.journal_name}")
        if external_metadata.publisher:
            lines.append(f"Editora sugerida: {external_metadata.publisher}")
        if external_metadata.volume or external_metadata.number:
            vol_str = f"v. {external_metadata.volume}" if external_metadata.volume else ""
            num_str = f"n. {external_metadata.number}" if external_metadata.number else ""
            lines.append(f"Volume / Fascículo: {vol_str} {num_str}".strip())
        if external_metadata.pages:
            lines.append(f"Páginas: {external_metadata.pages}")
        if external_metadata.doi:
            lines.append(f"DOI: {external_metadata.doi}")
        if external_metadata.isbn:
            lines.append(f"ISBN: {external_metadata.isbn}")
        lines.append(f"Tipo sugerido: {external_metadata.document_type_hint or '(não informado)'}")
        lines.append(f"Pontuação da correspondência: {external_metadata.match_score}")
        lines.append("")
        lines.append("Orientação: ignore os metadados externos sugeridos (especialmente periódico, volume, número e DOI) "
                     "sempre que autor, tipo documental (ex.: Livro vs Artigo) ou ano divergirem do conteúdo real do PDF; "
                     "priorize o texto do próprio documento.")
        lines.append("")

    return "\n".join(lines)


def is_generic_title(title: str) -> bool:
    """Verificar se um título é genérico/vazio sem autor identificável."""
    if not title or not title.strip():
        return True
    lowered = title.strip().lower()
    if lowered in GENERIC_TITLES:
        return True
    return any(lowered.startswith(prefix) for prefix in GENERIC_TITLE_PREFIXES)


def format_authors_for_filename(authors: list[str]) -> str:
    """Formatar lista de autores para composição do nome de arquivo.

    * 1 autor: 'Sobrenome, Nome' (usa authors[0] tal qual).
    * 2 autores: 'Sobrenome1; Sobrenome2' (sobrenome antes da vírgula de cada um).
    * 3+ autores: 'Sobrenome1 et al.'
    * lista vazia: 'Autor Desconhecido'.
    """
    if not authors:
        return "Autor Desconhecido"
    if len(authors) == 1:
        return authors[0].strip() or "Autor Desconhecido"
    if len(authors) == 2:
        sobrenomes = [a.split(",")[0].strip() for a in authors if a.strip()]
        sobrenomes = [s for s in sobrenomes if s]
        if len(sobrenomes) == 2:
            return f"{sobrenomes[0]}; {sobrenomes[1]}"
        if len(sobrenomes) == 1:
            return sobrenomes[0]
        return "Autor Desconhecido"
    primeiro_sobrenome = authors[0].split(",")[0].strip() if authors[0].strip() else ""
    return f"{primeiro_sobrenome} et al." if primeiro_sobrenome else "Autor Desconhecido"
