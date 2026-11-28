# Critérios de Aceitação — AUD-RESIDUAL (Itens da Auditoria de 24/11/2026)

> **Produzido por:** Sentinela (Information Security & AppSec)
> **Data:** 28/11/2026
> **Escopo:** Documento de critérios de aceitação (não contém código). Destinado ao roteamento da implementação ao Forja e revisão posterior pela Sentinela.
> **Regra:** apenas definição de critérios objetivos. Nenhuma alteração de código de produto nem de `docs/backlog.md`.

---

## Itens confirmados como já resolvidos (não requerem ação)

| ID | Severidade | Conclusão | Base da confirmação |
|----|-----------|-----------|---------------------|
| ATL-12 | média | **Já resolvido** | `format_sortable_name` em `periodicals.py:412-413` aplica `.isdigit()` antes de `int(volume)` / `int(issue)`, com fallback (`v999` / `n9999`). Não há outro local com `int(...)` sem validação de dígitos no escopo do item. |
| SEN-02 | baixa | **Já resolvido** | `grep github_token` negativo em `tomus.example.toml` e em `src/tomus/core/config.py`. O campo inexiste; item descartado. |

---

## 1. ATL-04 — Eliminação de leitura dupla no scanner (médio)

**Local:** `src/tomus/core/scanner.py` (`scan_directory`, `_compute_sha256`, `_validate_pdf_signature`)

**Critério objetivo de aceitação:**
- Cada arquivo PDF candidato é aberto **uma única vez** por passagem de varredura.
- Na mesma passagem (mesmo descritor de arquivo / mesmo `open`), são calculados: (a) SHA-256 em blocos de 64 KB e (b) validação da assinatura `%PDF-` nos primeiros bytes.
- Não há segunda abertura do mesmo arquivo para validar a assinatura após já ter sido lido para hash.
- O resultado `is_valid_pdf` e o `sha256` são ambos preenchidos a partir dessa única leitura.
- Testes existentes do scanner continuam passando (comportamento externo inalterado: `ScannedFile.sha256` e `is_valid_pdf` mantêm os mesmos valores para entradas válidas e inválidas).

**Risco se não for feito:**
- I/O duplicado em acervos grandes: cada PDF é lido duas vezes do disco, dobrando o tempo de varredura e o tráfego de disco em Stage 1, sem ganho funcional.
- Possível inconsistência entre hash e assinatura se o arquivo for modificado entre as duas leituras (race condition rara, mas tecnicamente possível).

**Severidade:** Média

---

## 2. LINCE-09 — Validação explícita do cabeçalho `%PDF-` antes de abrir com PyMuPDF (baixo)

**Local:** `src/tomus/extractors/native_pdf.py` (`extract_native_pdf`, linha ~42)

**Critério objetivo de aceitação:**
- Antes de chamar `fitz.open(str(path))`, o código valida que os primeiros bytes do arquivo contêm a assinatura binária `b"%PDF-"`.
- Arquivos sem a assinatura `%PDF-` são tratados como não-PDF / inválidos **antes** de qualquer tentativa de abertura pelo PyMuPDF (não lançam exceção de parsing do PyMuPDF para arquivos claramente não-PDF).
- A validação é feita lendo um número limitado de bytes (ex.: primeiros 1024 bytes, alinhado ao `PDF_SIGNATURE_BYTES` já definido em `scanner.py`), sem ler o arquivo inteiro.
- Não há regressão: PDFs válidos continuam sendo abertos e processados normalmente; arquivos corrompidos ou com extensão `.pdf` mas sem assinatura são rejeitados liminarmente.

**Risco se não for feito:**
- `fitz.open` pode lançar exceções ou consumir recursos ao tentar interpretar arquivos que não são PDF válidos (ex.: cópias soltas, arquivos renomeados, corrompidos), gerando ruído de erro e possível degradação de desempenho no extrator nativo.

**Severidade:** Baixa

---

## 3. LINCE-10 — Timeout absoluto no OCR (baixo)

**Local:** `src/tomus/extractors/ocr.py` (`ocr_scanned_pages`, `_ocr_with_rapidocr`)

**Critério objetivo de aceitação:**
- Existe um **tempo absoluto máximo** (timeout de parede/wall-clock) para a execução completa do OCR de um documento, independentemente do número de páginas ou do tempo por página.
- Quando o timeout absoluto é atingido, o OCR é interrompido e retorna o texto parcial extraído até aquele momento (ou string vazia se nada foi extraído), **sem travar** o pipeline.
- O timeout é configurável/documentado e não depende apenas do early stop por caractere alfanumérico (15.000) nem do teto de páginas (15).
- Não há deadlock nem bloqueio indefinido da thread de processamento mesmo que o mecanismo RapidOCR demore mais que o esperado em uma página específica.
- Testes de OCR continuam passando em ambiente sem RapidOCR (fallback seguro mantido: retorna string vazia).

**Risco se não for feito:**
- Documentos escaneados grandes ou páginas complexas podem fazer o OCR travar indefinidamente, bloqueando o pipeline de classificação (Stage 3) e deixando a interface ou o processo sem resposta.

**Severidade:** Baixa

---

## 4. ATL-09 — Cache da estrutura de taxonomia (baixo)

**Local:** `src/tomus/core/taxonomy.py` (`_index_areas_basicas`, `_build_area_to_grande_area`, `_build_subarea_to_owner_areas`)

**Critério objetivo de aceitação:**
- Os índices construídos a partir de `taxonomy_capes.json` (mapeamentos Grande Área ↔ Área Básica, subárea ↔ áreas proprietárias) são **construídos uma única vez** e reutilizados em chamadas subsequentes (memoização/cache em nível de módulo).
- `validate_or_repair_pair` e `repair_taxonomy_levels` não reconstroem `_index_areas_basicas()` nem `_build_area_to_grande_area()` a cada invocação.
- O cache é invalidador/consistente: se o arquivo da taxonomia for recarregado (`_load_taxonomy`), os índices derivados são reconstruídos corretamente.
- Não há regressão comportamental: `validate_or_repair_pair`, `repair_taxonomy_levels`, `normalize_and_resolve_taxonomy` retornam os mesmos resultados para as mesmas entradas.

**Risco se não for feito:**
- Cada chamada de validação/reparo taxonômico percorre todo o JSON da taxonomia reconstruindo dicionários e conjuntos; em classificações de muitos documentos (Stage 3/4), isso adiciona overhead CPU desproporcional e repetitivo.

**Severidade:** Baixa

---

## 5. ATL-16 — Renomeação de teste com versão no nome (baixo)

**Local:** `tests/test_periodicals_v133.py`

**Critério objetivo de aceitação:**
- O arquivo de teste `tests/test_periodicals_v133.py` é renomeado para remover a referência de versão no nome do arquivo (ex.: `test_periodicals.py` ou outro nome sem `v133`).
- A docstring interna e comentários que referenciam "v1.3.3" são atualizados para não vincular o teste a uma versão específica do produto.
- Todas as referências de importação/caminho ao arquivo de teste (se houver em outros lugares do repositório) são atualizadas para o novo nome.
- Todos os testes do arquivo continuam passando após a renomeação (cobertura funcional preservada).

**Risco se não for feito:**
- Nome de teste com versão incorporada gera confusão de manutenção e sugere escopo vinculado a uma release específica, dificultando a evolução do conjunto de testes e a busca por cobertura relevante.

**Severidade:** Baixa

---

## Próximos passos (apenas roteamento)

1. Forja implementa os itens acima conforme estes critérios de aceitação.
2. Sentinela revisa a implementação (AppSec/quality) antes de qualquer promoção para `stage`.
3. Nenhuma escrita destrutiva nem alteração de caminho fora do alvo é feita nesta etapa.

---

Assinado: Sentinela (apenas definição de critérios, sem código).