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

### [FEAT-UI-05] Filtrar Dropdown de Provedor Apenas para Chaves Testadas e Validadas
- **Status:** Aberto
- **Responsáveis:** Prisma (UX/UI) e Forja (Bridge/Config)
- **Escopo:** `src/tomus/gui/web/index.html`, `src/tomus/gui/web/app.js`, `src/tomus/gui/bridge.py`, `src/tomus/gui/widgets/preferences_dialog.py`
- **Objetivo:** No seletor (dropdown) da barra principal para escolher o provedor usado na classificação, exibir exclusivamente os provedores que possuem chave testada e validada nas Preferências, evitando que o usuário selecione um provedor sem credencial funcional.

### [BUG-UI-01] Indicador de Provedor Validado na Tela Principal Não Atualiza ao Trocar Chave
- **Status:** Aberto
- **Responsáveis:** Prisma (UX/UI) e Forja (Bridge/Config)
- **Escopo:** `src/tomus/gui/`, `src/tomus/gui/web/`, `src/tomus/core/key_validator.py`
- **Objetivo:** O badge de "provedor validado" na tela principal não reflete a troca de chave entre provedores (ex.: testando apenas NVIDIA, a tela ainda exibe "Groq validado"). A chave de execução está correta (modelo real usado no lote é `nvidia/nemotron-3.5-super-vl-120b-a12b`), mas o indicador visual fica desatualizado, gerando confusão sobre qual provedor está realmente ativo. Sincronizar o indicador com a chave validada/selecionada no momento.

### [FEAT-LLM-02] Rebaixar Groq para o Fim da Cadeia de Fallback
- **Status:** Aberto
- **Responsáveis:** Forja (Core/LLM)
- **Escopo:** `src/tomus/core/config.py`
- **Objetivo:** Alterar o padrão de `fallback_chain` para priorizar provedores mais estáveis antes do Groq (ex.: `["nvidia", "claude", "deepseek", "groq"]`), atualizando também `generate_config_template()` e substituindo o comentário obsoleto `llama-3.3-70b-versatile` na linha 350 por `openai/gpt-oss-120b`. Motivo: o Groq (`openai/gpt-oss-120b`) tem cota gratuita restrita (8.000 TPM) e travou 10 de 14 PDFs por cooldown quando colocado em primeiro na cadeia (relatório em `temp/relatorios/relatorio_provedores_llm_2026-11-26.md`).

### [FEAT-LLM-03] Ajustar Consumo de Tokens e Cadenciamento do GroqProvider
- **Status:** Aberto
- **Responsáveis:** Forja (Core/LLM)
- **Escopo:** `src/tomus/core/llm.py`
- **Objetivo:** Reduzir o orçamento por requisição no `GroqProvider` (`max_sampled_chars` para 6.000–8.000 caracteres, `max_tokens = 1024`) para gastar ~3.000–3.500 tokens por PDF e caber nos 8.000 TPM gratuitos da Groq. Ler os cabeçalhos de rate-limit da Groq (`x-ratelimit-remaining-tokens`, `x-ratelimit-reset-tokens`, `x-ratelimit-remaining-requests`, `retry-after`) para controlar o ritmo de envio: com outros provedores saudáveis na cadeia, um `429` deve acionar fallback imediato; quando o Groq for o último recurso, respeitar a janela de reset de TPM antes de falhar o lote em cascata. Manter `openai/gpt-oss-120b` como modelo padrão.

### [TEST-LLM-02] Testes de Nova Ordem de Fallback e Cadenciamento do Groq
- **Status:** Aberto
- **Responsáveis:** Forja (Core/LLM) e Lince (Testes/Integração)
- **Escopo:** `tests/test_multi_provider.py`, `tests/test_config.py`
- **Objetivo:** Validar a nova ordem padrão de `fallback_chain` com Groq ao final; testar envio reduzido (`max_tokens` / `max_sampled_chars`) e o respeito aos headers de rate-limit/cadenciamento do `GroqProvider` sem quebrar a política de 0-sleep quando há outro provedor elegível no `FallbackLLMDispatcher`.

### [FEAT-UI-06] Sinalizar Groq como Opção de Fallback na GUI
- **Status:** Aberto
- **Responsáveis:** Prisma (UX/UI)
- **Escopo:** `src/tomus/gui/web/index.html`, `src/tomus/gui/widgets/preferences_dialog.py`
- **Objetivo:** Identificar o Groq como opção recomendada apenas para fallback (ex.: `Groq — Fallback (openai/gpt-oss-120b)`), orientando o usuário a usar Gemini ou NVIDIA NIM como provedor principal gratuito. Inclui a correção de atualização visual do seletor/indicador de provedor na tela principal ao trocar de provedor (ref. BUG-UI-01).

### [FEAT-DOC-01] Documentar Limites Gratuitos do Groq no Manual do Usuário
- **Status:** Aberto
- **Responsáveis:** Prisma (UX/UI)
- **Escopo:** `docs/produto/MANUAL_DO_USUARIO.md`, `docs/manual_do_usuario.html`, `README.md`
- **Objetivo:** Registrar explicitamente que o Groq não exige cartão de crédito, mas tem limite gratuito restrito a 8.000 tokens por minuto (TPM) e 200.000 tokens por dia (TPD). Recomendar configurá-lo apenas na cadeia de fallback (atrás de Gemini e NVIDIA NIM), explicando que o uso isolado em lotes médios/grandes é naturalmente mais lento por conta do cadenciamento de 8.000 TPM.

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

### [REFACT-MOD-01] Modularização Gradual dos 4 Módulos Monolíticos
- **Status:** Aberto (pré-requisito técnico antes de `[FEAT-BATCH-01]` e da v2.0)
- **Responsáveis:** Atlas (Foundation) e Forja (Pipeline)
- **Escopo:** `src/tomus/core/llm.py`, `src/tomus/storage/organizer.py`, `src/tomus/gui/web/app.js`, `src/tomus/gui/widgets/preferences_dialog.py`
- **Objetivo:** Quebrar esses quatro arquivos em submódulos menores e coesos sem alterar o comportamento externo nem quebrar testes.

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
