# Auditoria Completa do Tomus — Consolidado (24/11/2026)

Base: `main @ 2c512e1`. Pente fino linha a linha pela equipe (exceto Córtex), coordenado pelo Chefe.
Relatórios individuais: ficam fora do repositório (pasta temporária da sessão). Este documento é o consolidado oficial para revisão.

**Regra desta auditoria:** análise apenas. Nenhum código foi alterado durante a auditoria.

---

## 1. Resumo

| Agente | Escopo | Achados reportados | Achados após recontagem | Observação |
|--------|--------|--------------------|-------------------------|------------|
| Atlas | Core, modelos, cache, taxonomia, testes | 18 | 17 | ATL-17 é "sem achado". Severidades recontadas (3 alta, 6 média, 8 baixa). |
| Lince | Extractors, enriquecedor, testes | 12 | 12 | Relatado 3/6/3. Recontado 2 alta, 5 média, 5 baixa. |
| Forja | Pipeline, LLM, config, storage, CLI, testes | 5 | 5 | Sem alteração. Verificação do PR #28 sem regressão. |
| Prisma | GUI, documentação web | 9 | 2 válidos | 7 refutados por grep. 1 confirmado (PRSM-03), 1 mantido (PRSM-09). |
| Sentinela | Segurança transversal | 12 | 12 | SEN-01 e SEN-02 rebaixados de crítica para baixa (ver §3). |
| Farol | Release, packaging, CI, docs de alinhamento | 13 (listados 15) | 15 | Relatado como 13, mas há 15 IDs. Recontado 1 crítica, 3 alta, 6 média, 5 baixa. |

**Total após recontagem: 63 achados válidos** (1 crítica, 14 altas, 23 médias, 25 baixas), mais 7 refutados.

---

## 2. Ponto crítico que exige decisão do usuário

**A versão do Tomus está inconsistente entre código, release publicada e documentação.**

- Código: `pyproject.toml` e `src/tomus/__init__.py` estão em **1.4.0**.
- GitHub Releases: a mais recente é **v1.4.0** (publicada em 23/11/2026). **Não existe v1.4.1.**
  - A v1.4.0 tem os assets `Tomus-1.4.0-macOS.dmg` e `Tomus_Setup_v1.4.0_Windows_x64.exe`, além de assets antigos `Tomus-1.3.3-macOS.dmg` e `Tomus_Setup_v1.3.3_Windows_x64.exe`.
- Documentação (`docs/ALINHAMENTO_EQUIPES.md`, `CHANGELOG.md`): afirmam **v1.4.1 publicada**. Isso é falso.
- Na sessão anterior, trocamos "1.4.0" por "1.4.1" na documentação com base nessa premissa. A premissa estava errada: a versão do código e da release é 1.4.0.

**Opções:**
1. **Publicar v1.4.1 de verdade:** subir versão em `pyproject.toml`, `__init__.py`, `pyinstaller.spec`, `windows_installer.iss`, scripts de build; gerar assets; publicar a release. Exige autorização explícita de release.
2. **Manter 1.4.0:** reverter a documentação para 1.4.0 (incluindo o MANUAL_DO_USUARIO.md, que hoje está "certo" para 1.4.0 e "errado" para a 1.4.1 que criamos), remover a seção `[1.4.1]` do CHANGELOG e corrigir o ALINHAMENTO.

Decisão pendente. Não será executada sem a sua autorização.

---

## 3. Reclassificações e refutações

**Refutados (não entram no backlog):**
- PRSM-01, PRSM-02: `docs/index.html` não contém `1.4.0` (grep).
- PRSM-04, PRSM-05: `docs/manual_do_usuario.html` não contém `1.4.0`.
- PRSM-06: `docs/DOCUMENTACAO_TECNICA.md` não contém `1.4.0`.
- PRSM-07: `docs/documentacao_tecnica.html` não contém `1.4.0`.
- PRSM-08: `docs/site_assets/style.css` não contém `1.4.0`.

**Reclassificados:**
- SEN-01 e SEN-02: de **crítica** para **baixa**. O `tomus.example.toml` tem campos de chave **vazios**, e `key_validator.py` contém prefixos de validação, não segredos. O `github_token` é um campo sem uso, o que é inconsistência, não vazamento.
- FAROL-01: a parte "release sem tag v1.4.1" está correta. A parte "asset `.dmg` mal nomeado" é incompleta: a v1.4.0 tem o asset `Tomus-1.4.0-macOS.dmg` **e** o antigo `Tomus-1.3.3-macOS.dmg`.

**Premissas da documentação que não se sustentam:**
- Sentinela afirmou que `pyproject.toml` e `__init__.py` estavam em 1.4.1. Está em 1.4.0.
- Prisma afirmou "zero referências a v1.4.0 em docs/". Havia referências em `MANUAL_DO_USUARIO.md`, e a própria premissa de 1.4.1 estava errada.

---

## 4. Achados válidos por agente

### 4.1 Atlas (Foundation, core, cache, taxonomia)

| ID | Sev. | Local | Resumo |
|----|------|-------|--------|
| ATL-01 | alta | `core/models.py:21` | `TESE_DISSERTACAO = "Tese_Dissertacao"` (underline) inconsistente com `"Tese/Dissertacao"`. |
| ATL-02 | alta | `core/models.py:49` | `DUPLICATE` e `DUPLICATE_SKIPPED` têm o mesmo valor; `.value` não distingue. |
| ATL-03 | média | `core/models.py:171` | `classification` é `dict` sem schema; risco de KeyError silencioso. |
| ATL-04 | média | `core/scanner.py:65-80` | Arquivo aberto duas vezes (hash e assinatura). |
| ATL-05 | alta | `core/cache.py:329` | Checagem de `"mock"` compara nome de modelo, não classificação. |
| ATL-06 | média | `core/cache.py:272-284` | Fallback silencioso de modelo no `get`. |
| ATL-07 | média | `core/cache.py:175-176` | `except Exception: pass` na ACL do Windows. |
| ATL-08 | média | `core/cache.py:71-176` | Função de ACL do Windows com ~100 linhas de ctypes, difícil de manter e testar. |
| ATL-09 | baixa | `core/taxonomy.py:152, 213` | Índices reconstruídos a cada chamada, sem cache. |
| ATL-10 | baixa | `core/taxonomy.py:322-331` | `defaultdict(lambda: 2)` promove subáreas não ranqueadas. |
| ATL-11 | baixa | `core/periodicals.py:43-44` | Alias `"micro sistemas"` duplicado. |
| ATL-12 | média | `core/periodicals.py:415-417` | `int(volume)` sem validação; `ValueError` possível. |
| ATL-13 | baixa | `core/session.py:17` | `SESSION_FILE` relativo ao diretório atual. |
| ATL-14 | baixa | `core/logging.py:107-115` | `except Exception` amplo no FileHandler. |
| ATL-15 | baixa | `core/key_validator.py:194-298` | Validação ativa depende de rede; sem opção offline documentada. |
| ATL-16 | baixa | `tests/test_periodicals_v133.py:1` | Nome e docstring com "v1.3.3". |
| ATL-18 | baixa | `core/taxonomy.py:360-368` | `canon_label` aceita rótulos fora do vocabulário sem aviso. |

ATL-17: sem achado (teste verificado como correto).

### 4.2 Lince (extractors e enriquecedores)

| ID | Sev. | Local | Resumo |
|----|------|-------|--------|
| LINCE-01 | alta | `extractors/native_pdf.py:53-56` vs `ocr.py:384-387` | Janelas de inspeção diferentes (nativo 10+5; OCR 8+2). Páginas escaneadas podem ficar sem OCR. |
| LINCE-02 | média | `native_pdf.py:19`, `ocr.py:33` | `_ALPHANUM_THRESHOLD = 30` duplicado. |
| LINCE-03 | média | `ocr.py:89-97` | `_pages_without_text` varre o documento inteiro. |
| LINCE-04 | alta | `identifiers.py:59-71` | `extract_isbn` retorna valor bruto; normalização repetida no enriquecedor. |
| LINCE-05 | média | `identifiers.py:161-186` | Bloco CIP encerra na primeira linha vazia. |
| LINCE-06 | média | `core/enrichers.py:456-480` | `except Exception: pass` sem log nas chamadas de API. |
| LINCE-07 | média | `core/enrichers.py:482-510` | Sem deduplicação entre OpenAlex e Google Books. |
| LINCE-08 | baixa | `extractors/ocr_docling.py` | Nome sugere Docling, mas é RapidOCR. |
| LINCE-09 | baixa | `native_pdf.py:42-43` | Sem validação prévia da assinatura `%PDF-`. |
| LINCE-10 | baixa | `ocr.py:360-406` | Sem timeout absoluto no OCR. |
| LINCE-11 | baixa | `tests/test_ocr_extractor.py:181-188` | Teste de DPI cobre valor explícito, não o padrão. |
| LINCE-12 | baixa | `tests/test_extractors.py:94-96` | Teste de integração não exercita a blacklist no fluxo completo. |

### 4.3 Forja (pipeline, LLM, config, storage, CLI)

| ID | Sev. | Local | Resumo |
|----|------|-------|--------|
| FORJA-01 | alta | `core/llm.py:2270` vs `core/config.py:205` | Gemini lê `BIBLIOTEC_GEMINI_API_KEY`; `AppConfig` lê `TOMUS_GEMINI_API_KEY`. Caminhos de configuração divergentes. |
| FORJA-02 | baixa | `core/pipeline.py:151`, `storage/organizer.py:1187, 1223` | `_journal_canonical` ainda é injetado pelo pipeline, mas não é consumido na entrada do organizer. |
| FORJA-03 | média | `core/llm.py:1474, 1568, 1668` | Provedores não-Gemini sem fallback de modelo. |
| FORJA-04 | baixa | `core/llm.py:1186` vs `docs/designs/tomus.md:99` | Design documenta 1 fallback; código tem 3. |
| FORJA-05 | baixa | `cli/main.py:362` | Imprime "Manifesto gravado em: False" quando não há entradas. |

Verificação do PR #28: chaves pt/en com fallback consistentes (`organizer.py:562-587`); sem regressão.

### 4.4 Prisma (GUI e documentação)

| ID | Sev. | Local | Resumo |
|----|------|-------|--------|
| PRSM-03 | alta | `docs/MANUAL_DO_USUARIO.md:4` (e ocorrências em linhas 36, 47, 49) | Versão 1.4.0 no manual e nomes de arquivo `1.4.0`. Ver §2: a correção depende da decisão de versão. |
| PRSM-09 | média | `src/tomus/gui/web/app.js` (`formatTriageError`) | Mensagens de erro exibidas sem mascarar tokens (`sk-ant-`, `nvapi-`, `gsk-`, `gsh-`). |

### 4.5 Sentinela (segurança transversal)

| ID | Sev. | Local | Resumo |
|----|------|-------|--------|
| SEN-01 | baixa (rebaixado) | `tomus.example.toml:42-56` | Campos de chave no exemplo (vazios). Sugestão: comentar uso de variáveis de ambiente. |
| SEN-02 | baixa (rebaixado) | `tomus.example.toml:56` | `github_token` sem uso em `config.py`. Remover ou tratar. |
| SEN-03 | alta | `core/config.py:185-201` | Ordem de fontes `(init, local_toml, env, global)` coloca TOML local acima de variáveis de ambiente. Confirmar no código antes de corrigir. |
| SEN-04 | alta | `core/config.py:347-480` | ACL Windows com `return` silenciosos; falha não é logada. |
| SEN-05 | alta | `gui/bridge.py:287-337` (`startOrganize`) | `source_dir` e `target_dir` vindos do frontend sem `_is_safe_path`. |
| SEN-06 | alta | `gui/bridge.py:433-449`, `653-670` | `revealPath` e `openPdf` incluem `Path.home()` como raiz. |
| SEN-07 | média | `core/llm.py:1326-1329` | Erro do LLM interpolado no `reasoning` exibido na UI. |
| SEN-08 | média | `gui/bridge.py:380-383` | Interpolação de f-string em `runJavaScript`. |
| SEN-09 | média | `gui/web/app.js:1085` | Link DOI aceita `javascript:` em `href`. |
| SEN-10 | média | `gui/main_window.py:34-39` | Console JS vai para o terminal se `verbose=True`; sem garantia em produção. |
| SEN-11 | baixa | CLI (flags `--api-key`) | Chave visível em `ps`/`/proc`. |
| SEN-12 | baixa | `core/logging.py:65` | `tomus.log` gravado no diretório atual. |

Mitigações do `RELATORIO_AUDITORIA_SEGURANCA.md` confirmadas no código.

### 4.6 Farol (release, packaging, CI, docs de alinhamento)

| ID | Sev. | Local | Resumo |
|----|------|-------|--------|
| FAROL-01 | crítica | `docs/ALINHAMENTO_EQUIPES.md:7-8` | Documento declara v1.4.1 publicada; não existe. Ver §2. |
| FAROL-02 | alta | `packaging/pyinstaller.spec:199` | `CFBundleVersion` = 1.4.0. |
| FAROL-03 | alta | `packaging/pyinstaller.spec:200` | `CFBundleShortVersionString` = 1.4.0. |
| FAROL-04 | alta | `packaging/windows_installer.iss:6` | `MyAppVersion` = 1.4.0. |
| FAROL-05 | média | `packaging/build_macos.sh:15-19` | Fallbacks de versão 1.4.0. |
| FAROL-06 | média | `packaging/build_windows.ps1:8-12` | Fallback de versão 1.4.0. |
| FAROL-07 | baixa | `packaging/windows_installer.iss:2` | Comentário cita `v1.1.0`. |
| FAROL-08 | média | `.github/workflows/release.yml:168-169` | `SHA256SUMS.txt` com caminhos `release-assets/...`; `sha256sum -c` falha para o usuário. |
| FAROL-09 | baixa | `CHANGELOG.md:22` | Seção `[1.4.1]` sem release publicada. |
| FAROL-10 | média | `docs/ALINHAMENTO_EQUIPES.md:6` | Baseline registrada como `d566b62`; `main` está em `2c512e1`. |
| FAROL-11 | baixa | `docs/ALINHAMENTO_EQUIPES.md:79-96` | Registros de v1.3.2 sem marcação de histórico. |
| FAROL-12 | baixa | `packaging/build_macos.sh:100-103` | Assinatura ad-hoc; releases públicas exigem ID de desenvolvedor Apple. |
| FAROL-13 | média | `.github/workflows/release.yml:168-169` | Mesmo problema de FAROL-08, pelo lado do usuário. |
| FAROL-14 | baixa | `.github/workflows/release.yml:141` | Tag `v*` não é validada contra `pyproject.toml`. |
| FAROL-15 | média | `pyproject.toml:7` | `version = "1.4.0"` vs documentação 1.4.1. Ver §2. |

---

## 5. Próximos passos

1. **Decidir a versão (§2).** Publicar 1.4.1 ou manter 1.4.0. Depois disso, os itens AUD-01 e AUD-12 ganham escopo definido.
2. **Revisar as prioridades** das entradas AUD-01 a AUD-12 no `docs/backlog.md`.
3. **Confirmar SEN-03** antes de corrigir, porque a ordem de precedência do pydantic-settings precisa ser testada.
4. **Autorização de merge:** este PR só documenta. O merge depende de autorização explícita.
