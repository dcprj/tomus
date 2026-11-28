# Backlog do Tomus

> **Última atualização:** 26/11/2026
> **Baseline vigente:** `v1.4.1` (ver `docs/governanca/baseline.md`)
> **Histórico de itens concluídos (v1.0.0 a v1.4.1):** `docs/historico/backlog_v1_concluido.md` e `CHANGELOG.md`

Este documento mantém exclusivamente itens abertos, sem duplicidades e sem histórico encerrado.

## Prioridade Alta (Próximas Entregas)

### [BUG-LLM-01] Investigação e Validação Ponta a Ponta de Todos os Provedores de Classificação
- **Status:** Aberto
- **Responsáveis:** Forja (Core/LLM) e Lince (Testes/Integração)
- **Escopo:** `src/tomus/core/llm.py`, `src/tomus/core/config.py`, `tests/test_multi_provider.py`
- **Objetivo:** Em teste real usando exclusivamente o Groq, a chave foi validada, mas o provedor não classificou os documentos. Investigar a causa raiz no Groq e validar de ponta a ponta a classificação real (envio do prompt, retorno JSON estrito e parsing da resposta) em todos os provedores suportados (Groq, NVIDIA, DeepSeek e Claude), mantendo o Gemini já funcional como referência.

### [TEST-LLM-01] Validação Efetiva da Cadeia de Fallback e Rotação de Chaves
- **Status:** Aberto
- **Responsáveis:** Forja (Core/LLM) e Atlas (Foundation)
- **Escopo:** `src/tomus/core/llm.py`, `src/tomus/core/config.py`, `tests/test_multi_provider.py`
- **Objetivo:** Testar de forma efetiva o comportamento quando uma chave esgota cota ou falha (HTTP 429, erro de autenticação ou indisponibilidade), garantindo tanto a rotação para a próxima chave válida no pool do mesmo provedor quanto a troca automática para o próximo provedor com chave validada na cadeia de fallback.

### [BUG-UI-01] Indicador de Provedor Validado na Tela Principal Não Atualiza ao Trocar Chave
- **Status:** Aberto
- **Responsáveis:** Prisma (UX/UI) e Forja (Bridge/Config)
- **Escopo:** `src/tomus/gui/`, `src/tomus/gui/web/`, `src/tomus/core/key_validator.py`
- **Objetivo:** O badge de "provedor validado" na tela principal não reflete a troca de chave entre provedores (ex.: testando apenas NVIDIA, a tela ainda exibe "Groq validado"). A chave de execução está correta (modelo real usado no lote é `nvidia/nemotron-3.5-super-vl-120b-a12b`), mas o indicador visual fica desatualizado, gerando confusão sobre qual provedor está realmente ativo. Sincronizar o indicador com a chave validada/selecionada no momento.

### [BUG-UI-02] Validação de Múltiplas Chaves sem Feedback Individual no Campo do Provedor
- **Status:** Aberto (relato do Chefe em 27/11/2026, confirmado em código)
- **Responsáveis:** Prisma (UX/UI) e Forja (Worker/Validação)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py` (`_gather_pending_credentials`, `_on_validation_result`, `KeyValidationWorker`), `tests/`
- **Diagnóstico confirmado:** o campo de chave do provedor aceita múltiplas chaves separadas por vírgula, mas `_gather_pending_credentials()` aplica `raw.split(",")[0]` e valida ao vivo **apenas a primeira** — as demais são gravadas no `config.toml` sem nunca serem testadas. Além disso `_on_validation_result()` registra o resultado em `_validation_results[field_name]` (por provedor), então o feedback visual é **um único ✓/✗ por campo**, sem distinguir as chaves.
- **Objetivo:** validar **todas** as chaves informadas em cada campo e apresentar feedback individual por chave (ex.: lista com a chave mascarada e status ✓ validado / ✗ 401 / ✗ 403 / ✗ formato inválido), mantendo a persistência sempre garantida antes da validação e o comportamento não-bloqueante. Alinhar com o feedback por chave que o `KeyPoolDialog` já oferece.

### [FEAT-TRIAGE-01] Companion Markdown em Revisão Manual, Edição Guiada e Materialização Seletiva
- **Status:** Aberto
- **Responsáveis:** Forja (Core/Pipeline/Storage) e Prisma (UX/UI)
- **Escopo:** `src/tomus/storage/companion.py`, `src/tomus/storage/organizer.py`, `src/tomus/gui/bridge.py`, `src/tomus/gui/web/`
- **Objetivo:** Gerar arquivo `.md` também para documentos enviados a `revisao_manual/` (com metadados preliminares e motivo da revisão), permitir edição direta dos campos no inspetor da GUI (título, autores, ano, taxonomia CAPES/CNPq e tipo documental), registrar trilha de auditoria no front matter YAML (`revisao_manual.editado_manualmente`, `revisado_em`, `campos_alterados`) e oferecer ação para promover itens completos à árvore definitiva com relatório de desfecho.

### [FEAT-BATCH-01] Processamento Fracionado de Grandes Acervos (Sub-Lotes de 50 a 100 PDFs com Retomada)
- **Status:** Aberto (recomendado executar após `[REFACT-MOD-01]`)
- **Responsáveis:** Forja (Core/Session) e Prisma (UX/UI)
- **Escopo:** `src/tomus/core/session.py`, `src/tomus/core/pipeline.py`, `src/tomus/storage/organizer.py`, `src/tomus/gui/web/`
- **Objetivo:** Ao detectar mais de 100 PDFs pendentes na origem, oferecer fatiamento opcional em sub-lotes de 50 ou 100 arquivos, com persistência determinística do progresso por par `(source_dir, target_dir)`, consolidação cumulativa em `manifest.json` e `relatorio_revisao.md` sem sobrescrever lotes anteriores, e banner de retomada ao reabrir o app.

### [FEAT-AUDIT-01] Auditoria e Saneamento Automático de Biblioteca Organizada
- **Status:** Aberto
- **Responsáveis:** Sentinela (AppSec/Quality) e Forja (Core/Pipeline)
- **Escopo:** `src/tomus/storage/organizer.py`, `src/tomus/storage/companion.py`, `src/tomus/gui/bridge.py`
- **Objetivo:** Inspecionar uma biblioteca já organizada para identificar PDFs sem companion `.md` válido (órfãos, cópias soltas ou corrompidos), permitindo recolocar pendências na fila de classificação ou confirmar integridade.

### [FEAT-AUTH-02] Validação Ativa de Chaves no Salvamento (Google Books e Provedores)
- **Status:** Aberto (parcialmente coberto em Preferências; revisar uniformidade entre provedores e modo offline)
- **Responsáveis:** Prisma (UX/UI) e Atlas (Foundation)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`, `src/tomus/core/key_validator.py`
- **Objetivo:** Garantir verificação assíncrona uniforme ao salvar credenciais (incluindo Google Books), com feedback contextualizado para HTTP 401/403 e salvamento não-bloqueante quando o usuário estiver offline.

## Prioridade Média (Enriquecimento, Arquitetura e UX)

### [GOV-01] Higiene Pós-Aposentadoria do Canal OneDrive
- **Status:** Aberto (decisão do Chefe em 28/11/2026)
- **Responsáveis:** Sentinela (auditoria) e Farol (docs/governança)
- **Escopo:** `scripts/validate_onedrive_protocol.py` (trackeado), `AGENTS.md`, `docs/governanca/fluxo_trabalho.md`, `scripts/sync_maestri_roles.py`
- **Objetivo:** com o canal OneDrive aposentado (substituído pelo Maestri Wire), o validador do protocolo OneDrive (`scripts/validate_onedrive_protocol.py`) e seu teste (`tests/test_validate_onedrive_protocol.py`) ficam obsoletos, assim como as seções de `AGENTS.md` e `fluxo_trabalho.md` que descrevem o canal e o Agente Windows operando "mediante ordens do Chefe pelo OneDrive". Avaliar por `develop`: remover o script e o teste, atualizar a documentação de governança para refletir o Maestri Wire como canal primário, e registrar que os artefatos operacionais internos (scripts de monitoramento, VM/smoke e roteiros) estão protegidos no `.gitignore`.

### [REFACT-MOD-01] Modularização Gradual dos 4 Módulos Monolíticos
- **Status:** Aberto (pré-requisito técnico antes de `[FEAT-BATCH-01]` e da v2.0)
- **Responsáveis:** Atlas (Foundation) e Forja (Pipeline)
- **Escopo:** `src/tomus/core/llm.py`, `src/tomus/storage/organizer.py`, `src/tomus/gui/web/app.js`, `src/tomus/gui/widgets/preferences_dialog.py`
- **Objetivo:** Quebrar esses quatro arquivos em submódulos menores e coesos sem alterar o comportamento externo nem quebrar testes.

### [FEAT-REL-01] Publicar Release como Draft até o Smoke dos Assets Gerados pela Action
- **Status:** Aberto (decisão do Chefe em 27/11/2026 — fica para a **próxima** release; a 1.4.2 já está testada e validada)
- **Responsáveis:** Farol (Release & GitOps)
- **Escopo:** `.github/workflows/release.yml`
- **Objetivo:** adicionar `draft: true` ao passo `softprops/action-gh-release` para que os bundles gerados pela action sejam publicados como rascunho e testados **antes** da publicação definitiva. Fluxo alvo: criar tag `v*` no commit da `stage` → action gera `.dmg`, `.exe` e `SHA256SUMS.txt` e publica como **draft** → baixar os assets do draft e aplicar o smoke real nos dois SOs → aprovado, publicar (`gh release edit <tag> --draft=false`) → promover `stage → main`. Benefício: o artefato testado é **exatamente** o publicado (mesmo run), eliminando a divergência de hash entre o bundle gerado localmente e o publicado pela action — builds PyInstaller/Inno não são bit-a-bit reproduzíveis.
- **Observação:** hoje o job `release` exige tag com prefixo `v` e valida a tag contra `pyproject.toml`; tags `RC-*` não disparam o job de release, por isso a solução por rascunho é preferível à estratégia de tag RC.
- **Notas de release curadas:** na 1.4.2 o `generate_release_notes: true` gerou um "What's Changed" listando todos os PRs (inclusive chores internos e promoções de branch), o que polui o changelog — o texto teve de ser reescrito manualmente após a publicação. Para a próxima release: usar `generate_release_notes: false` e um corpo curado (novidades em linguagem de usuário, correções, instalação, verificação de hashes e requisitos), mantendo o `CHANGELOG.md` do repositório como registro técnico completo.

### [FEAT-ENRICH-01] Suporte Opcional a `openalex_api_key` (OpenAlex)
- **Status:** Aberto
- **Responsáveis:** Lince (Extractors) e Atlas (Foundation)
- **Escopo:** `src/tomus/core/enrichers.py`, `src/tomus/core/key_validator.py`, `src/tomus/core/config.py`, `src/tomus/gui/widgets/preferences_dialog.py`
- **Objetivo:** Substituir ou complementar o parâmetro `mailto` legado da OpenAlex por autenticação opcional via `openalex_api_key`, mantendo falha graciosa em `try/except` no Stage 3.

### [FEAT-UX-03] Botão Apoio com Destaque Sutil e QR Code Pix Offline
- **Status:** Aberto (prioridade baixa/média)
- **Responsáveis:** Prisma (UX/UI) e Sentinela (Validação)
- **Escopo:** `src/tomus/gui/web/index.html`, `src/tomus/gui/web/styles.css`, `src/tomus/gui/web/app.js`, `tests/`
- **Objetivo:** Adicionar botão discreto `Apoio` na barra utilitária abrindo modal com chave Pix (`dpinheiro+tomus@gmail.com`), botão copiar, aviso legal (Art. 538 CC) e QR Code Pix EMVCo BR Code gerado localmente sem dependência externa.

### [FEAT-UX-04] Imagem de Fundo no DMG Instruindo "Arraste Tomus.app para Aplicativos"
- **Status:** Aberto (sugestão do Chefe em 27/11/2026, durante smoke do `.dmg`)
- **Responsáveis:** Prisma (UX/UI) e Farol (Empacotamento)
- **Escopo:** `packaging/build_macos.sh`, imagem de fundo do DMG (ex.: `packaging/dmg_background.png`), `packaging/`
- **Objetivo:** Adicionar imagem de fundo à janela do DMG montado instruindo usuários novatos a arrastar `Tomus.app` para a pasta `Applications`. Hoje o volume abre mostrando apenas `Tomus.app`, o `.Volumelcon.icns` e a pasta Aplicativos, sem nenhuma instrução visual — há risco de o usuário executar o aplicativo direto do volume montado. Adotar o padrão de apps estabelecidos (ilustração/seta com "Arraste para Aplicativos"), aplicado via `create-dmg --background` (ou o mecanismo de posicionamento/background já usado no build macOS), mantendo o tamanho do instalador inalterado.

### [AUD-RESIDUAL] Itens Médios e Baixos Remanescentes da Auditoria de 24/11/2026
- **Status:** Aberto (ref. detalhada em `docs/historico/2026-11-24_auditoria_completa.md`)
- **Responsáveis:** Atlas, Lince e Sentinela
- **Escopo:** `src/tomus/core/`, `src/tomus/extractors/`, `tomus.example.toml`
- **Objetivo:** Tratar pendências não-bloqueantes remanescentes: validação explícita de cabeçalho `%PDF-` e timeout no OCR (LINCE-09/10), eliminação de leitura dupla no scanner, cache da estrutura de taxonomia, validação de `int(volume)`, limpeza do campo `github_token` sem uso em `tomus.example.toml` e renomeação de testes com versão no nome (`test_periodicals_v133.py`).

### [BUG-UI-03] Badge do Provedor Não se Adapta à Janela Reduzida
- **Status:** Aberto (achado cosmético do smoke da 1.4.3, 28/11/2026)
- **Responsáveis:** Prisma (UX/UI)
- **Escopo:** `src/tomus/gui/web/index.html`, `src/tomus/gui/web/style.css`
- **Objetivo:** o badge de provedor validado na barra principal não reduz proporcionalmente quando a janela é estreitada, ficando cortado ou sobrepondo o campo de modelo. Aplicar responsividade (flex-shrink, min-width, ellipsis ou reorganização em duas linhas).

### [FEAT-UX-05] Instrução de Instalação no DMG com Mecanismo Robusto
- **Status:** Aberto (decorrente do smoke da 1.4.3)
- **Responsáveis:** Farol (empacotamento)
- **Escopo:** `packaging/build_macos.sh`, `packaging/`
- **DOIS problemas, não um** (revisado após o Chefe inspecionar a imagem, 28/11/2026):
  1. **Conteúdo:** a imagem não tem instrução nenhuma. Visual confirmado: retângulo branco com faixa azul na borda direita, sem seta e sem texto. Corrigir apenas o `.DS_Store` entregaria um fundo inútil.
  2. **Renderização:** o `.DS_Store` carrega `backgroundType_` como **cor** além de `backgroundImageAlias_`, e o `create-dmg` não sobrescreve isso no runner headless do CI (sem WindowServer, o AppleScript falha). Renomear o asset para `background.png` não resolve — verificado duas vezes no smoke.
- **Consequência:** os dois defeitos precisam ser corrigidos juntos. Qualquer solução que trate apenas um deles continua entregando um DMG sem instrução utilizável.
- **Duas fases:** (a) curto prazo — incluir um arquivo `Instrucoes.txt` visível dentro do DMG com a orientação de arrastar `Tomus.app` para Aplicativos. Robusto, independente de `.DS_Store`, funciona em qualquer geração; (b) evolução — gerar o `.dmg` em Mac com Finder e subir como asset, para ter o visual de fato.
- **Ressalva:** a fase (b) adiciona passo manual ao release, que tende a ser pulado. Recomenda-se (a) como padrão.

### [FEAT-UX-06] QR Code Pix Real no Modal de Apoio
- **Status:** Aberto (o QR falso foi removido na 1.4.3)
- **Responsáveis:** Forja (backend) e Prisma (interface)
- **Escopo:** backend de geração de imagem, `src/tomus/gui/web/`
- **Objetivo:** gerar QR Code EMVCo BR Code válido no backend com biblioteca Python pura (ex.: `segno`, sem dependência de runtime externo) e servir a imagem para o modal. Critério de aceitação testável: **um aplicativo bancário lê o QR** e o payload EMVCo corresponde à chave Pix configurada.
- **Aprendizado:** itens que declaram integração externa (QR, API, formato de arquivo) precisam de critério de aceitação que valide a integração, não apenas que o código não quebra.

### [FEAT-ORG-01] Hierarquia CAPES Completa na Árvore de Destino
- **Status:** Aberto (achado do smoke da 1.4.3 — lacuna de design, não regressão)
- **Responsáveis:** Forja (storage)
- **Escopo:** `src/tomus/storage/organizer.py`
- **Contexto:** o caminho de destino usa `area_basica/subarea/tipo` desde a baseline v1.4.1. A taxonomia resolve corretamente `Psicologia → Ciências Humanas`, `Turismo → Ciências Sociais Aplicadas` etc., mas `grande_area` nunca é usada no path. Consequência: hierarquia truncada em 2 níveis; áreas básicas de grandes áreas diferentes ficam irmãs no topo.
- **Impacto de mudar:** afeta bibliotecas já organizadas (do Dario e de usuários). Exige migração ou reclassificação.
- **Recomendação:** decidir fora do calor de release. Se um dia o Tomus for usado por bibliotecas grandes, o terceiro nível passa a importar mais.

### [FEAT-WEB-06] Domínio Próprio na Landing Page
- **Status:** Aberto (domínio `tomus.app.br` registrado; DNS em transição em 28/11/2026)
- **Responsáveis:** Farol (Pages) e Prisma (landing)
- **Escopo:** `docs/CNAME`, configuração do GitHub Pages, DNS
- **Objetivo:** servir a landing page e a documentação em `tomus.app.br` via GitHub Pages (gratuito, HTTPS automático). Passos: 4 registros A do GitHub (185.199.108-111.153) + CNAME de www para dcprj.github.io; custom domain em Settings → Pages; arquivo `docs/CNAME`; Enforce HTTPS. Downloads continuam no GitHub Releases.
- **Futuro:** subdomínio de downloads ou espelho dos assets no domínio próprio.

## Qualidade e Automação de Smoke

### [FEAT-QA-01] Automação Completa do Smoke na VM do Windows (Camada C — Clique na GUI)
- **Status:** Aberto (camadas A e B implementadas na sprint 28/11; camada C pendente)
- **Responsáveis:** Forja (script) e Agente Windows (execução na VM)
- **Escopo:** `scripts/vm_smoke_pipeline.py`, `packaging/vm_smoke_installer.ps1`, `packaging/smoke_check_windows.py`
- **O que já existe:** instalador verificado dentro da VM (tamanho + SHA-256), instalação silenciosa com `EXITCODE=0`, self-test OCR aprovado, boot da GUI confirmado por indicadores (processo vivo, CPU acumulando, QtWebEngine ativo, stderr limpo) e credencial não-interativa do convidado resolvida via **DPAPI** (substitui o `Get-Credential`, que travava por diálogo modal).
- **O que falta:** confirmar a abertura da janela por `MainWindowHandle` — o `.NET` não detecta o handle do app Qt, então o boot ainda depende de confirmação visual no console; e automatizar o processamento pela GUI.
- **Objetivo:** avaliar automação de clique com FlaUI ou pywinauto para eliminar a última dependência de operador. **Ressalva técnica:** controles QtWebEngine não expõem árvore de acessibilidade confiável, e um seletor quebrado produz falso negativo — o pior tipo de falha em teste. Manter A+B (instalação + boot + pipeline via API do core) como caminho principal e tratar C como opcional, sem bloquear release.
- **Limpeza pendente na VM:** remover a instância de diagnóstico em sessão 0 e a Tarefa Agendada `SmokeLaunch143`.

### [FEAT-QA-02] Snapshot Canônico e Conjunto de Referência do Smoke
- **Status:** Aberto
- **Responsáveis:** Agente Windows (VM) e Farol (documentação)
- **Escopo:** VM `Tomus-QA-Win11-x64`, `packaging/smoke_check_windows.py`, documentação de release
- **Achado:** o snapshot `PFDs_para_testes_no_disco_c` (nome com typo) **não** tem a conta `tomusagent`, portanto a credencial falha ali e ele não serve para execução autônoma. A base que funciona é **`tomusagent_com_pdfs`**, que tem conta e PDFs.
- **Objetivo:** tornar `tomusagent_com_pdfs` a base canônica do smoke (renomear `PFDs_para_testes_no_disco_c` ou documentar explicitamente a distinção, para que ninguém repita o erro), e manter uma subpasta `pdfs_teste/` com **10 PDFs de referência** cobrindo variedade de tipos documentais (livro, revista, tese, artigo), de tamanhos (ao menos um pequeno e um grande), pelo menos um arquivo escaneado sem camada de texto (para exercitar o OCR) e anos distintos, sem duplicatas óbvias.
- **Benefício:** conjunto fixo transforma o smoke em teste reproduzível — mesmos arquivos em toda release, resultado comparável entre execuções, e variação no número de organizados passa a indicar regressão em vez de sorte da amostra.

## Decisões de Produto (Sem Prazo Definido)

### [PROD-BETA-01] Identificar o Tomus como Versão Beta nas Superfícies Oficiais
- **Status:** Aberto (aguardando definição de momento por Dario)
- **Responsáveis:** Prisma (UX/UI) e Farol (Release)
- **Escopo:** `src/tomus/gui/`, `src/tomus/gui/web/`, `docs/`, landing page e textos de release
- **Objetivo:** Exibir identificação visual e textual de versão beta nas superfícies voltadas ao usuário sem alterar a tag `v1.4.1` existente.

### [PROD-GUI-01] Tomus Exclusivamente pela GUI (Remoção da CLI de Produto)
- **Status:** Aberto (aguardando definição de momento por Dario)
- **Responsáveis:** Prisma (UX/UI) e Forja (Pipeline/CLI)
- **Escopo:** `src/tomus/cli/`, `pyproject.toml`, `README.md`, `docs/`, `packaging/`
- **Objetivo:** Remover entry points, subcomandos, flags e documentação de uso via terminal do produto final, preservando apenas scripts internos de desenvolvimento, empacotamento e CI.

## Visão de Longo Prazo (v2.0.0+)

- **`[LIB-01]` Modo Gerenciar Biblioteca Existente:** varredura e indexação de `.md` já organizados (Atlas e Lince).
- **`[LIB-02]` Ciclo de Leitura no Front Matter:** campo `status_leitura: a_ler | lendo | lido` (Prisma e Forja).
- **`[LIB-03]` Fichamento Acadêmico e Exportador:** templates e exportação de referências (Atlas e Prisma).
