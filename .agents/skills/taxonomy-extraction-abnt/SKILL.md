---
name: taxonomy-extraction-abnt
description: Use when trabalhando com a árvore CAPES/CNPq, OCR (RapidOCR/ONNXRuntime), enriquecedores de metadados (DOI via CrossRef, ISBN/ISSN via Google Books/OpenAlex) e formatação de referência bibliográfica segundo ABNT NBR 6023. Disponível para Atlas, Lince e Córtex.
---

# Taxonomia, Extração e ABNT NBR 6023 — Classificação e Metadados do Tomus

Use when um agente precisa alterar `src/tomus/core/taxonomy.py`, `src/tomus/core/llm.py`, `src/tomus/extractors/ocr.py`, `src/tomus/extractors/identifiers.py`, `src/tomus/core/enrichers.py`, `src/tomus/storage/namer.py`, `src/tomus/storage/companion.py` ou módulos de taxonomia, especialmente para normalização de áreas, validação de identificadores ou geração de citações.

### Taxonomia CAPES/CNPq

- Árvore de 4 níveis: Grande Área › Área Básica › Subárea › Especialidade (9 Grandes Áreas oficiais).
- `normalize_and_resolve_taxonomy()` consolida sinônimos em vocabulário controlado e resolve desambiguações semânticas.
- `repair_taxonomy_levels()` repara pares deslocados de Grande Área / Área Básica.
- `AREA_BASICA_ALIASES` normaliza variantes de acento/caixa (ex.: `"ciencia da computacao"` → `"Computação"`).
- **Enums (ATL-01, ATL-02):** não alterar valores já gravados em cache, manifesto ou front matter. Corrigir por coerção/alias na leitura (`_missing_`), sem migração de dados.
- `TESE_DISSERTACAO` não muda de valor; aceitar as duas grafias (`Tese/Dissertacao` e `Tese_Dissertacao`) via coerção na leitura.

### OCR (RapidOCR/ONNXRuntime)

- OCR seletivo local (PyMuPDF + RapidOCR/ONNXRuntime, 150 DPI), páginas prioritárias (primeiras e últimas) com `early stop` em 15k caracteres alfanuméricos.
- **LINCE-01:** o OCR deve inspecionar as mesmas páginas que o extrator nativo sinaliza (`needs_ocr`). O teto de páginas pode permanecer por desempenho, desde que nenhuma página sinalizada fique de fora sem motivo registrado.
- `opencv-python-headless < 4.11` com `cv2.setNumThreads(0)` e `OPENCV_FOR_THREADS_NUM=1` para evitar contenção de threads com onnxruntime em bundles PyInstaller; fallback seguro retorna texto vazio sem quebrar o processo.

### Enriquecedores de identificadores

- **DOI:** regex estrita + consulta CrossRef API; validação de similaridade `rapidfuzz.fuzz.token_set_ratio >= 88.0`.
- **ISBN:** `normalize_isbn()` converte ISBN-10 → ISBN-13 com validação de checksum; dígito verificador inválido retorna `None`. Normalização é idempotente.
- **ISSN:** `normalize_issn()` com validação.
- **Google Books:** busca por ISBN para capa, editora e ano exato (chave gratuita opcional).
- **OpenAlex:** endpoint `mailto` aposentado; busca por título compartilha cota de 0,10 USD/dia por IP; protegido em `try/except` (falha graciosa).

### ABNT NBR 6023

- Autores: sobrenome em CAIXA ALTA, prenome normal; autoria institucional (`BRASIL. Ministério...`) sem inversão indevida.
- Livros/tese: título em **negrito puro** (`<strong>`); subtítulo após dois pontos em caracteres normais.
- Periódicos: título do artigo normal; nome da revista em **negrito puro**.
- Edição: sanitizar `"2ª ed."` / `"3. ed."` → `"2. ed."` / `"3. ed."` (eliminar `"1. ed. ed."`).
- DOI válido: cláusula `Disponível em: https://doi.org/... Acesso em: [data]`.

### Arquivos companheiros (.md)

- `generate_companion_markdown()` gera front matter YAML 100% em pt-BR com chaves `titulo`, `autores`, `ano`, `grande_area`, `area_basica`, `subarea`, `tipo`, `sha256`, `caminho_canonico`, etc.
- `caminho_canonico` é relativo à raiz da biblioteca (não absoluto), tornando a biblioteca portável.
- Arquivos `.md` orfãos sem PDF irmão são ignorados na inicialização do índice (`md_path.with_suffix(".pdf")` inexistente → `continue`).

### Common mistakes

- Alterar valor de enum já persistido em cache/front matter (quebra leitura de dados existentes).
- Aceitar ISBN com dígito verificador inválido.
- Deixar OCR inspecionar páginas que o extrator nativo não sinalizou (páginas escaneadas caem fora da janela).
- Gerar citação ABNT com título do livro sem negrito ou autor em negrito (inverte a norma).
