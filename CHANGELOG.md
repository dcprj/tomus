# Changelog do Tomus

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e este projeto adota versionamento semântico ([Semantic Versioning](https://semver.org/lang/pt-BR/)).

## [1.4.1] - (pendente de publicação)

### Correções de empacotamento e CI/CD

- **Versão 1.4.0 → 1.4.1:** `pyproject.toml`, `src/tomus/__init__.py`, `packaging/windows_installer.iss`, `packaging/build_macos.sh`, `packaging/build_windows.ps1`, `packaging/pyinstaller.spec`.
- **CI/CD:** `.github/workflows/release.yml` — passo de validação de tag (`v*`) contra versão em `pyproject.toml` para evitar publicar tag com versão divergente (FAROL-14).
- **Distribuição (checksums — PR #41):** `.github/workflows/release.yml` — `SHA256SUMS.txt` gera apenas nomes relativos (basename) de cada asset (`.dmg` e `.exe`) e remove CR residual (`tr -d '\r'`), permitindo que o usuário verifique com `sha256sum -c SHA256SUMS.txt` quando os assets baixados e o manifesto estão no mesmo diretório.

## [1.4.0] - 2026-11-23

### PR #20 — [FEAT-PKG-04] SolidCompression=yes no instalador Windows
- **`packaging/windows_installer.iss`**: `SolidCompression=no` → `SolidCompression=yes` para reduzir o tamanho do instalador `.exe` via compressão sólida do Inno Setup.

### PR #21 — [FEAT-PKG-05] SHA256SUMS.txt como asset da release
- **`.github/workflows/release.yml`**: adicionada etapa "Gerar SHA256SUMS.txt" que calcula checksums SHA-256 dos instaladores (.dmg e .exe) e publica o arquivo como asset da release no GitHub Releases.

### PR #22 — [FEAT-WEB-02 a 05] Coerência site↔código
- **`docs/index.html`, `docs/site_assets/style.css`, `docs/manual_do_usuario.html`, `docs/documentacao_tecnica.html`**: correções de coerência entre landing page, manuais e código (autoria, xattr `com.apple.quarantine`, tamanhos de download, créditos).

### PR #23 — Correção urgente da landing page v1.4.0
- **`docs/index.html`**: versão do botão hero v1.3.3 → v1.4.0; badge macOS 14+ → 12+; links de download apontando para assets v1.4.0; mockup da janela Tomus v1.4.0; seção de créditos (Dario como mantenedor, agentes de IA como ferramentas); explicação de `xattr -cr` para `com.apple.quarantine`.

## [1.3.3] - 2026-11-22

### PR #13 — RapidoOCR como motor primário (sem Docling/Torch/Transformers) + `--self-test-ocr` + NVIDIA NIM pool
- **`packaging/pyinstaller.spec`**: removido `torch`, `torchvision`, `docling`, `docling-slim`, `docling_core`, `docling_parse`, `docling_ibm_models`, `latex2mathml`, `pylatexenc`, `pypdfium2`, `pypdfium2_raw` e o bloco `collect_all(transformers)` das hiddenimports/datas; mantido `fitz`, `rapidocr`, `onnxruntime`, `collect_dynamic_libs(onnxruntime)`, PySide6 WebEngine e filtro de `libcrypto.3.dylib`/`libssl.3.dylib` do OpenCV no macOS; `CFBundleVersion`/`CFBundleShortVersionString` atualizados para `1.3.3`.
- **`packaging/hooks/hook-tomus.py`**: `bindepend_symlink_suppression` restrito a `**/cv2/.dylibs/libssl*`, `**/cv2/.dylibs/libcrypto*`, `**/cv2/__dot__dylibs/libssl*` e `**/cv2/__dot__dylibs/libcrypto*`, preservando symlinks de `libavcodec`/`libavformat`/`libavutil`/`libswscale`.
- **`src/tomus/extractors/ocr_docling.py`**: `_configure_opencv_threads()` com `cv2.setNumThreads(0)` e `OPENCV_FOR_THREADS_NUM=1`.
- **`src/tomus/gui/app.py`**: `_apply_webengine_defenses()` com `QTWEBENGINE_DISABLE_SANDBOX=1`, `QTWEBENGINEPROCESS_PATH`, recursos do QtWebEngine.
- **`pyproject.toml`**: `opencv-python-headless>=4.5.1.48,<4.11` (bloqueia ≥ 4.11).

### PR #14 — Revistas/Fascículos (periodicals.py), anti-contaminação Enrichers, Windows WIN_SAFE_FULL_PATH_CHARS, AppSec
- **`src/tomus/core/periodicals.py`**: novo módulo com `canonical_journal`, `format_display_name`, `format_sortable_name`, `AREA_BASICA_ALIASES` para periódicos, `JOURNAL_ALIASES`, `MONTH_ALIASES`.
- **`src/tomus/core/enrichers.py`**: enriquecedores de metadados com anti-contaminação e normalização de identificadores.
- **`src/tomus/core/taxonomy.py`**: `WIN_SAFE_FULL_PATH_CHARS = 245` para limitação de caminho no Windows.
- **AppSec C-01/A-01..A-03/B-02..B-04**: auditoria de sanitização de caminhos, identificadores e exceções.

### PR #15 — [PERF-OCR-01] 150 DPI + early stop; [PERF-LLM-01] + R3
- **`[PERF-OCR-01]`**: OCR seletivo em 150 DPI (fallback 120 DPI para páginas > 4000 px), priorização `[p0, p1, p2, p_última, ...]`, early stop ao atingir ≥ 15.000 alfanuméricos preservando ordem crescente das páginas.
- **`[PERF-LLM-01]`**: pool LLM thread-safe com `_PoolCooldownState` (threading.Lock), classificação estruturada de falhas HTTP (C-01: 401/403 permanente, 429 PerDay/RPD vs RPM/FreeTier, retryDelay > 60s, 503/504/529, 404 por par), cálculo da meia-noite de America/Los_Angeles protegido com `try/except` para Windows/PyInstaller sem tzdata, estado volátil thread-safe em memória com cursor por família, gerações, reserva única de sondagem e deduplicação de chaves.
- **`[R3]`**: `ClientError`/`ServerError`, `quotaDimensions` aninhado, fallback multi-família, `410 Gone`, `nvidia/nemotron-3.5-super-vl-120b-a12b`, `model_aliases` em `state.db`.

### Fechamento v1.3.3
- **`pyproject.toml`**: `pydantic>=2.5,<3` (D-01).
- **`.github/workflows/*.yml`**: `R-01` — SHA-pins em todas as Actions (`actions/checkout@11d5960a... # v4`, `actions/setup-python@a26af69be... # v5`, `actions/upload-artifact@ea165f8d... # v4`, `actions/download-artifact@d3f86a10... # v4`, `softprops/action-gh-release@3bb12739... # v2`).
- **Documentação**: `docs/backlog.md`, `docs/ALINHAMENTO_EQUIPES.md` atualizados; limpeza D-01 de caminhos locais absolutos.

## [1.3.2] - 2026-11-20

### Empacotamento Windows e CI cross-OS (v1.3.2)
- **`.github/workflows/release.yml`**: workflow renomeado para `Release Tomus (macOS + Windows)`; adicionado job `build-windows` (windows-latest) com checkout, setup-python, venv isolado, instalação de dependências (`-e .[dev]`, `pyinstaller`), testes offscreen, Inno Setup (ISCC.exe via PATH/Program Files/x86 com fallback `choco install innosetup`), execução de `packaging\build_windows.ps1` (PyInstaller + smoke_check_windows.py + ISCC.exe com `/DMyAppVersion`) e upload do artifact `tomus-windows-installer`. O job `release` agora depende de `build-macos` e `build-windows` e publica ambos os artifacts (`.dmg` e `.exe`) via `softprops/action-gh-release@v2`.
- **`packaging/build_windows.ps1`**: leitura dinâmica da versão de `pyproject.toml` (fallback `1.3.2`); detecção do ISCC.exe incluindo caminhos x86 (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe` e `7\ISCC.exe`); passagem de `/DMyAppVersion=$VERSION` e validação com `Test-Path` do instalador `dist\Tomus_Setup_v${VERSION}_Windows_x64.exe`.
- **Portabilidade Windows**: correções de GUI/WebEngine, storage, config e backend OCR no Windows (`win/fix-portability-and-gui`); empacotamento, smoke check Windows e correção Explorer (`win/packaging-windows`).
- **CI cross-OS**: build-macos e build-windows passando 100% no PR de integração.

## [1.3.1] - 2026-11-16

### Correções de Empacotamento macOS / CI (Hotfix)
- **`.github/workflows/release.yml`**: removida a instalação de `setuptools<70` (que deixava `pkg_resources` fantasma após o upgrade do torch para setuptools 84). O workflow agora cria um venv isolado (`python -m venv .venv`), expõe `${GITHUB_WORKSPACE}/.venv/bin` via `GITHUB_PATH` para todos os passos seguintes e instala dependências com `.venv/bin/pip` (`--upgrade pip`, `-e .[dev]`, `pyinstaller`). Adicionado passo de smoke check após `build_macos.sh` validando: ausência de `pyi_rth_pkgres` no binário (via `CArchiveReader`, chave direta em `arch.toc`), ausência de `pkg_resources` no PYZ (via `open_embedded_archive("PYZ-00.pyz").toc`), presença de `libavcodec` em `Contents/Frameworks`, coleta do `docling_slim` dist-info e boot offscreen do executável `Tomus` por 5s via `subprocess.Popen` + `communicate(timeout=5)` (falha se encerrar antes de 5s ou emitir Traceback/ImportError/AttributeError/SIGABRT; `terminate()` se permanecer vivo).
- **`packaging/pyinstaller.spec`**: `pkg_resources` incluído em `excludes`; adicionado `copy_metadata` para `docling-slim` (resolvendo `picture_description_vlm_engine` no Docling congelado); `CFBundleVersion` e `CFBundleShortVersionString` atualizados para `1.3.1`.
- **`packaging/hooks/hook-tomus.py`**: `bindepend_symlink_suppression` restringido exclusivamente a `**/cv2/.dylibs/libssl*`, `**/cv2/.dylibs/libcrypto*`, `**/cv2/__dot__dylibs/libssl*` e `**/cv2/__dot__dylibs/libcrypto*`, preservando symlinks de `libavcodec`/`libavformat`/`libavutil`/`libswscale` em `Contents/Frameworks/` para que `import cv2` funcione no bundle.

## [1.3.0] - 2026-11-16

### Deduplicação em 3 camadas e Obsolescência (`src/tomus/storage/organizer.py`)
- **`LibraryIndex`** (em `src/tomus/storage/organizer.py`, não em `library_index.py`): índice em memória inicializado via `LibraryIndex.from_target_dir()` que lê `.md` companheiros da árvore temática, ignorando arquivos `.md` órfãos sem PDF-irmão (evita entradas zumbis).
- **L1_SHA256**: hash SHA-256 do conteúdo do PDF para detecção de cópias exatas entre todas as subáreas/pastas (`duplicatas/`).
- **L2_IDENTIFICADOR**: DOI / ISBN-13 / ISSN normalizados (via `normalize_doi`, `normalize_isbn`, `normalize_issn`) com camadas `L2_DOI`, `L2_ISBN`, `L2_ISSN` e Guardas G1/G2/G3.
- **L3_IMPRESSAO_DIGITAL**: impressão digital bibliográfica (`work_fingerprint` / `_build_title_fingerprint`) com camada `L3_FINGERPRINT`.
- **Guardas G1-G3**: G1 — discriminadores estruturais de volume/parte/público (`vol`, `part`, `aud`, `livro`) via `_extract_discriminators()`; G2 — proporção de páginas `>= 0.25` (`MIN_PAGE_RATIO`) via `is_structurally_compatible()`; G3 — subtítulos disjuntos (`_sub_tokens` disjuntos) para não confundir edições distintas.
- **`compare_editions()`**: veredito `DUPLICATE`/`OBSOLETE` com vencedor (`can`/`inc`) baseado em ano e edição.
- **Substituição reversa segura para `obsoletos/`**: edição antiga movida para `obsoletos/` e nova promovida à árvore temática, validada por `_is_within()` (contenção de caminho) em `_demote_canonical_to_obsolete()`.

### Companions `.md` e Front Matter YAML (`src/tomus/storage/companion.py`, `src/tomus/core/prompts.py`)
- **`generate_companion_markdown()`** (`companion.py`): front matter YAML 100% em pt-BR com chaves `titulo`, `subtitulo`, `autores`, `ano`, `editora`, `cidade`, `edicao`, `periodico`, `volume`, `numero`, `paginas`, `paginas_pdf`, `doi`, `isbn`, `grande_area`, `area_basica`, `subarea`, `especialidade`, `tipo`, `sha256`, `indice_confianca`, `utilizou_ocr`, `arquivo_origem`, `organizado_em`. Não existe chave `gramc`.
- **Duplicatas/obsoletos**: `generate_duplicate_companion_markdown()` e `generate_obsolete_companion_markdown()` com `status`, `camada_deteccao`, `substituiu_existente`, `caminho_canonico` (relativo à raiz da biblioteca via `_resolve_canonical_paths()`) e `detectado_em`.
- **Autoria institucional ABNT NBR 6023**: `is_institutional_author()` e `_sobrenome_maiusculo()`/`format_abnt_authors()` preservam entidades (ex.: Conselho Federal de Psicologia) sem inversão de nome; sobrenomes pessoais em caixa alta.
- `caminho_canonico` é relativo à raiz da biblioteca (não absoluto), tornando a biblioteca portável.

### Taxonomia Controlada CAPES/CNPq (`src/tomus/core/taxonomy.py`, `src/tomus/core/llm.py`)
- **`normalize_and_resolve_taxonomy()`**: normaliza sinônimos e aplica regras determinísticas de desambiguação (Grande Área / Área Básica / Subárea / Especialidade) consistentes com `taxonomy_capes.json`.
- **`repair_taxonomy_levels()`** e **`validate_or_repair_pair()`**: reparo de níveis taxonômicos inconsistentes e deslocamento Grande Área ↔ Área Básica.
- **`AREA_BASICA_ALIASES`**: mapeamento de aliases de áreas básicas (ex.: `"ciencia da computacao" -> "Computação"`).
- Usado pelo classificador LLM em `src/tomus/core/llm.py` (`_finalize_classification`).

### OCR e Empacotamento macOS (`pyproject.toml`, `src/tomus/extractors/ocr_docling.py`, `src/tomus/gui/app.py`, `packaging/`)
- **`pyproject.toml`**: pin `opencv-python-headless>=4.5.1.48,<4.11` (bloqueia versões `>= 4.11`, incompatíveis com OpenSSL 3 do macOS moderno); não é "menor que 4.11", é inferior a 4.11.
- **`src/tomus/extractors/ocr_docling.py`**: `_configure_opencv_threads()` define `cv2.setNumThreads(0)` e `OPENCV_FOR_THREADS_NUM=1` para evitar contenção de threads do Apple GCD com onnxruntime em bundles congelados.
- **`src/tomus/gui/app.py`**: `_apply_webengine_defenses()` define `QTWEBENGINE_DISABLE_SANDBOX=1`, `QTWEBENGINEPROCESS_PATH`, `QTWEBENGINE_RESOURCES_PATH` e `QTWEBENGINE_LOCALES_PATH` antes de instanciar `QWebEnginePage` (evita SIGABRT no sandbox do macOS).
- **`packaging/hooks/hook-tomus.py`**: `bindepend_symlink_suppression = ["**/cv2/.dylibs/*", "**/cv2/__dot__dylibs/*"]` — **suprime** (não copia) os binários dinâmicos do OpenCV para não sobrescrever o OpenSSL 3 do bundle.
- **`packaging/pyinstaller.spec`**: filtra `libcrypto.3.dylib` e `libssl.3.dylib` de `cv2/.dylibs/` e `cv2/__dot__dylibs/`; coleta binários/dados do QtWebEngine; `CFBundleVersion`/`CFBundleShortVersionString` = `1.3.0`.
- **`packaging/build_macos.sh`**: symlinks relativos do `QtWebEngineProcess` (`Contents/MacOS/QtWebEngineProcess` e `.../QtWebEngineCore.framework/Helpers`) e assinatura ad-hoc (`codesign --force --deep --sign -`).

### Hardening AppSec (`src/tomus/gui/bridge.py`, `src/tomus/gui/web/app.js`)
- **`approveManualTriage`** (`bridge.py`): exceções sanitizadas via `_sanitize_error_message()` (redação de chaves `sk-`, `nvapi-`, `gsk-`, `gsh_`) antes de retornar ao frontend; validação de caminho seguro em `openPdf`/`revealPath` (`_is_safe_path`, `_PROTECTED_NAMES`, `_SYSTEM_ROOTS`).
- **`src/tomus/gui/web/app.js`**: `escapeHtml()` aplicado em `buildTriageAreaOptionsHtml()` e na tabela/inspetor para prevenir XSS via `innerHTML`; citação ABNT NBR 6023 renderizada com escape de saída.

### Documentação & Backlog v1.3.0 (`docs/`, `docs/backlog.md`)
- `docs/DOCUMENTACAO_TECNICA.md`, `docs/MANUAL_DO_USUARIO.md`, `docs/index.html` e correspondentes `.html` do GitHub Pages atualizados (Prisma UX).
- `docs/backlog.md` com itens para v1.3.1+ e v2.0.0+.

## [1.2.0] - 2026-11-14

### Motor de LLM & Resiliência
- **Pool Multi-Chave com Rotação Automática (`src/tomus/core/config.py`, `src/tomus/core/llm.py`)**: suporte a listas de chaves de API (`gemini_api_key`, `groq_api_key`, etc.) com rotação circular automática round-robin ao detectar `HTTP 429 Too Many Requests`.
- **Provedores e Modelos Homologados**:
  - `NvidiaProvider`: atualizado para o modelo de alta precisão `meta/llama-3.2-90b-vision-instruct`.
  - `ClaudeProvider`: homologado com o modelo `claude-haiku-5-5`, compatível com blocos híbridos `thinking` e `text`.
  - `GroqProvider`: homologado com `llama-3.3-70b-versatile` (cota gratuita de 1.000 requisições/dia) posicionado como 1º fallback imediato da cadeia.
  - Cascata oficial de contingência (`fallback_chain = ["groq", "nvidia", "claude", "deepseek"]`).
- **Remoção de Legado**: `GitHubModelsProvider` e `github_token` descontinuados e removidos do core, CLI, GUI e documentação.

### Interface Gráfica & Ergonomia
- **Triagem Manual com Subárea e Auto-Inferência de Grande Área (`src/tomus/gui/web/index.html`, `src/tomus/gui/web/app.js`, `src/tomus/gui/bridge.py`, `src/tomus/gui/widgets/inspector.py`)**: substituição do campo de Grande Área por Área Específica (Subárea) na revisão manual (com inferência automática da Grande Área CAPES a partir da Área Básica) e reorganização da Árvore CAPES/CNPq exibindo Subáreas abaixo de cada Área Básica.
- **Alças de Redimensionamento de Painéis e Colunas (`src/tomus/gui/web/index.html`, `src/tomus/gui/web/style.css`, `src/tomus/gui/web/app.js`)**: adição de splitter redimensionável entre a barra lateral e a tabela (`#sidebarResizer`), guia visual na divisória do inspetor (`#tableResizer`) e redimensionamento livre de todas as 7 colunas da tabela (incluindo redução abaixo da largura do texto com truncamento por reticências).
- **Validador Ativo de Chaves de API (`src/tomus/core/key_validator.py`, `src/tomus/gui/bridge.py`)**: verificação em tempo real da validade das chaves configuradas na janela de Preferências.
- **Citação ABNT NBR 6023 Normativa (`src/tomus/gui/web/app.js`, `src/tomus/gui/bridge.py`)**:
  - Título da obra destacado em negrito puro (`<strong>`), subtítulo em caracteres normais.
  - Autores em texto normal (sem negrito), com sobrenomes em caixa alta.
  - Sanitização de edições duplicadas (eliminando a anomalia `"1. ed. ed."`).
  - Botão "Copiar Citação" integrado à área de transferência do sistema via `QGuiApplication.clipboard` nativo.
- **Experiência Desktop Pura**:
  - Desativação do menu de contexto de navegador web do Chromium (`NoContextMenu` no Qt e `contextmenu` preventDefault no JS), eliminando opções irrelevantes como *Reload*, *Back* e *View Source*.
  - Precedência de status sobre a árvore CAPES: clicar em qualquer filtro de status desativa a seleção da árvore e "Todos os Itens" restaura a esteira completa.

### Documentação & Engenharia
- **Documentação Técnica & Arquitetura**: elaboração de [`docs/DOCUMENTACAO_TECNICA.md`](docs/DOCUMENTACAO_TECNICA.md) e [`docs/documentacao_tecnica.html`](docs/documentacao_tecnica.html) com diagramas de camadas, esteira e máquina de estados em Mermaid.
- **Manual do Usuário Didático**: elaboração de [`docs/MANUAL_DO_USUARIO.md`](docs/MANUAL_DO_USUARIO.md) e [`docs/manual_do_usuario.html`](docs/manual_do_usuario.html) com tutorial de obtenção de chaves (Gemini, Groq, NVIDIA, Claude, Google Books) e glossário de termos técnicos.
- **Landing Page**: atualização de [`docs/index.html`](docs/index.html) com navegação balanceada e links diretos para a documentação técnica e o manual.

---

## [1.1.2] - 2026-11-10

### Corrigido
- **Renomeação integral para `tomus`**: todos os pacotes, módulos e caminhos de importação renomeados de `bibliotec` para `tomus` (src/, pyproject.toml, CLI, imports internos).
- **Redação de segredos em logs (`src/tomus/core/logging.py`)**: `RedactingFilter` mascara chaves de API e tokens (`key=`, `sk-`, `nvapi-`, `gsk-`, `token=`) em todas as mensagens gravadas em `tomus.log`.
- **Path Traversal e Catálogo de Destino no QtWebChannel (`src/tomus/gui/bridge.py`)**: função `_is_safe_path()` valida containment do caminho resolvido em `source_dir`, `target_dir` e pastas do usuário, bloqueando `..`, dotfiles e diretórios sensíveis.
- **Sanitização de exceções LLM (`src/tomus/core/llm.py`, `src/tomus/core/pipeline.py`)**: `_sanitize_error_message()` aplica máscara regex a chaves de API antes de injetar em `reasoning` ou `error_message`.
- **Sanitização em `runJavaScript` (`src/tomus/gui/bridge.py`)**: payloads serializados com `json.dumps(..., ensure_ascii=False)`, sem risco de escape de string JS.
- **Prevenção de XSS em link DOI (`src/tomus/gui/web/app.js`)**: DOI validado para apenas protocolos seguros (`https://`, `http://`, `10.`); protocolos inseguros (`javascript:`, `data:`) renderizados como texto puro.
- **Silenciar logs de console JS (`src/tomus/gui/main_window.py`)**: `javaScriptConsoleMessage` imprime apenas com `verbose=True`.
- **Avisos de segurança na CLI (`src/tomus/cli/main.py`)**: flags `--api-key` e `--google-books-key` incluem aviso recomendando variáveis de ambiente.

### Adicionado
- **Identidade visual TOMUS v1.1.2**: ícones oficiais (`icon.ico` com 7 resoluções 16px–256px, `icon.icns` Retina, `icon.png` com transparência alfa), logotipo horizontal 1014x334, emblema isolado 28x28/44x44 na toolbar e modal Sobre.
- **Suporte completo a RapidOCR + ONNXRuntime no Windows**: DLLs do onnxruntime embarcadas via `binaries=binaries` no PyInstaller spec.
- **Landing Page oficial (`docs/index.html`)**: redesign editorial studio-grade com seção de créditos celebrando a parceria entre Dario e o enxame de agentes de IA.
- **README focado em macOS**: instruções de instalação atualizadas para o ecossistema Apple Silicon e Intel.

### Alterado
- **Versão**: 1.1.1 → 1.1.2 em pyproject.toml, Inno Setup, PyInstaller spec, badge da GUI web e docs/index.html.

---

## [1.0.1] - 2026-11-09

### Corrigido — Vulnerabilidades de Segurança (Relatório de Auditoria Sentinela)

#### CRT-02 — Vazamento de chaves de API em logs (`src/tomus/core/logging.py`)
- Adicionado `RedactingFilter` que faz regex replace mascarando chaves de API e tokens (`key=...`, `sk-...`, `nvapi-...`, `gsk-...`, `token=...`) em todas as mensagens de log gravadas no arquivo `tomus.log`.
- Definido nível `WARNING` para o logger `httpx`, impedindo que URLs completas com query params (incluindo `key=`) sejam gravadas em nível INFO.

#### ALT-01 e ALT-02 — Path Traversal e Catálogo de Destino no QtWebChannel (`src/tomus/gui/bridge.py`)
- Implementada função `_is_safe_path(p, allowed_roots)` que verifica containment do caminho resolvido em `source_dir`, `target_dir` e pastas do usuário, bloqueando `..`, dotfiles e diretórios sensíveis (`.ssh`, `.gnupg`, `.aws`, `.bashrc`, `/etc`, etc.).
- `revealPath()` e `openPdf()` agora validam o caminho com `_is_safe_path()` antes de abrir ou revelar; arquivos fora das pastas autorizadas são rejeitados com aviso de log.

#### MED-01 — Vazamento de chaves em exceções (`src/tomus/core/llm.py`, `src/tomus/core/pipeline.py`)
- Adicionada função `_sanitize_error_message()` que aplica máscara (regex) a chaves de API e tokens em mensagens de erro antes de injetá-las em `reasoning` ou `error_message`.
- Todas as chamadas `f"Falha na chamada ao LLM {exc}"` agora usam `_sanitize_error_message(str(exc))`.

#### MED-02 — Sanitização em `runJavaScript` (`src/tomus/gui/bridge.py`)
- Todos os payloads enviados para `web_view.page().runJavaScript` agora usam `json.dumps(..., ensure_ascii=False)`, garantindo serialização segura e sem risco de escape de string JS.

#### MED-03 — Prevenção de XSS em link DOI (`src/tomus/gui/web/app.js`)
- Na função `buildAbntCitation()`, o DOI é validado: apenas links que começam com `https://`, `http://` ou `10.` são renderizados como `<a>`; protocolos inseguros (`javascript:`, `data:`) são renderizados como texto puro sem tag `<a>`.

#### MED-04 — Silenciar logs de console JS no terminal (`src/tomus/gui/main_window.py`)
- `javaScriptConsoleMessage` agora imprime no stdout apenas quando `verbose=True` (desativado por padrão).

#### BAI-01 — Avisos de segurança na CLI (`src/tomus/cli/main.py`)
- As flags `--api-key` e `--google-books-key` agora incluem aviso no help recomendando o uso de variáveis de ambiente (`TOMUS_GEMINI_API_KEY`, `TOMUS_GOOGLE_BOOKS_API_KEY`).

---

## [1.0.0] - 2026-11-07

### Added
- **Desktop GUI Multiplataforma (`tomus.gui`)**: Bancada de trabalho de 3 painéis com identidade visual *Editorial Academic Workbench* inspirada em Zotero 7 e Things 3 (100% Anti-AI-Slop, sem emojis e sem gradientes neon).
  - Paletas semânticas *Editorial Paper* (Light) e *Technical Graphite* (Dark) com tokens imutáveis e renderização determinística via motor Qt6 `Fusion` + QSS.
  - Grade de documentos virtualizada a 60fps (`QTableView` + `QAbstractTableModel`) com 8 colunas de alta densidade e busca textual instantânea.
  - Inspetor documental com renderização tipográfica da referência **ABNT NBR 6023**, cópia rápida de citação e da ficha Markdown (`.md`) companheira.
  - Triagem manual assistida (`ManualTriageBox`) permitindo aprovar e mover documentos de `revisao_manual/` para a árvore temática CAPES/CNPq com atualização do cache SQLite.
  - Barra de telemetria ao vivo com monitor do teto de revisão manual (meta $\le 20\%$) e gaveta expansível para logs e inspeção do cache.
  - Subcomando `tomus gui` na CLI e script executável `tomus-gui`.
  - Suíte de 46 testes automatizados de interface rodando em modo offscreen (`test_gui_base.py` e `test_gui_components.py`).

## [0.4.0] - 2026-11-06

### Entregas da Sprint v0.4.0

#### [SCH-01] Schema JSON explícito para Provedores OpenAI-Compatíveis (`src/tomus/core/prompts.py`, `src/tomus/core/llm.py`)
* Prompt de sistema atualizado com especificação JSON formal completa para todos os campos (`title`, `subtitle`, `year`, `authors`, `grande_area`, `area_basica`, `tipo`, `confidence_score`, `reasoning`).
* Elevação da acurácia e riqueza de nomenclatura de arquivos gerados por DeepSeek, NVIDIA NIM, Groq e GitHub Models para o mesmo nível editorial do Gemini.
* Proteção contra respostas vazias ou nulas (`choice.message.content is None`) em todos os adaptadores HTTP.

#### [DIAG-06] Diagnósticos Detalhados e Notificação de Atalhos Ignorados (`src/tomus/storage/organizer.py`, `src/tomus/cli/main.py`)
* Diagnóstico tipado automático de arquivos não-PDF no scanner e organizador, diferenciando atalhos de internet do macOS (`.webloc`), Windows (`.url`), e-books (`.epub`, `.mobi`), documentos de escritório e mídias.
* Geração da seção `## Arquivos Não-PDF e Atalhos Ignorados` no relatório `revisao_manual/relatorio_revisao.md`, com caminho de origem e diagnóstico detalhado de cada item ignorado.
* Notificação contextual amigável na saída de console da CLI (`_print_summary`) discriminando atalhos macOS e arquivos não suportados.

#### [REV-07] Consolidação Arquitetural Pré-GUI (`organizer.py`, `enrichers.py`, `llm.py`, `pipeline.py`, `docs/designs/tomus.md`)
* Resolução de colisão por SHA-256 (`_resolve_collision`) estendida para `revisao_manual/` (`add_manual_review` e `add_error`), prevenindo sobrescrita de arquivos homônimos de subpastas distintas e evitando re-hashing desnecessário em disco.
* Correção do cabeçalho `User-Agent` (`mailto:` do Polite Pool) nas buscas por título e DOI do OpenAlex, filtro de retry para erros transitórios e extração de candidatos distintos de título/autor em `enrichers.py`.
* Inclusão de `provider_name` e `model_name` efetivos em `ClassificationResult`, persistência do modelo efetivo no cache SQLite sob fallback e suporte a `cancel_event: threading.Event | None` e `dry_run` diretamente em `run_pipeline` para acoplamento da Desktop GUI (`v1.0.0`).
* Sincronização integral da especificação de design (`docs/designs/tomus.md`) com a arquitetura `v0.4.0`.

---

## [0.3.0] - 2026-11-06

### Entregas da Sprint v0.3.0

#### [CLI-10] Novos provedores LLM: Groq e GitHub Models (`src/tomus/core/llm.py`, `src/tomus/cli/main.py`)
* `create_provider_chain()` expande suporte para provedores `"groq"` e `"github"`.
  * `"groq"`: instancia `GroqProvider` (API Groq /chat/completions), resolve `groq_api_key` via CLI > env > config.
  * `"github"`: instancia `GitHubModelsProvider` (API GitHub Models /chat/completions), resolve `github_token` via CLI > env > config.
* Flag `--provider` / `-p` na CLI aceita: `gemini`, `nvidia`, `deepseek`, `claude`, `groq`, `github`.
* `config show` exibe `api_keys.groq_api_key` e `api_keys.github_token` (mascarados).

#### [TST-11] Testes de Groq e GitHub Models (`tests/test_multi_provider.py`)
* Instanciação de `GroqProvider` e `GitHubModelsProvider`.
* Mock de chamada com sucesso para Groq (formato OpenAI) e GitHub Models (formato OpenAI).
* `FallbackLLMDispatcher`: falha no primário Groq → chaveamento automático para GitHub Models.

---

## [0.2.0] - 2026-11-06

### Entregas da Sprint v0.2.0

#### [FAL-04] Múltiplos provedores LLM com fallback automático (`src/tomus/core/llm.py`)
* `FallbackLLMDispatcher`: implementa o protocolo `LLMProvider` com cadeia ordenada de provedores.
  Tenta o primário; em caso de exceção ou resultado com reasoning 'Falha na chamada ao LLM',
  loga warning no logger `tomus.llm` e despacha para o próximo da cadeia.
* `create_provider_chain()`: fábrica que monta a cadeia a partir da `AppConfig` e flags CLI.
  Suporta provedores: `gemini`, `nvidia`, `deepseek`, `claude`.
  Resolução de chave: CLI > variável de ambiente > config.toml.
  Se o provedor primário não tiver chave, o primeiro com chave válida torna-se primário efetivo.
* Novos provedores: `DeepSeekProvider` (API DeepSeek /chat/completions) e
  `ClaudeProvider` (API Anthropic /messages), ambos com retry em 429/503/529 e
  travas determinísticas de confiança idênticas aos demais provedores.

#### [CLI-04] Novos provedores na CLI e `config show` expandido (`src/tomus/cli/main.py`)
* Flag `--provider` / `-p` aceita: `gemini`, `nvidia`, `deepseek`, `claude`.
* `_build_provider` agora usa `create_provider_chain()` para montar a cadeia com fallback.
* `config show` exibe: `llm.default_provider`, `llm.fallback_chain`,
  `api_keys.deepseek_api_key` e `api_keys.claude_api_key` (mascarados).
* Erro amigável quando nenhum provedor tem chave de API configurada.

#### [TST-05] Testes de múltiplos provedores (`tests/test_multi_provider.py`)
* Instanciação de `DeepSeekProvider` e `ClaudeProvider`.
* Mock de chamada com sucesso para DeepSeek (formato OpenAI) e Claude (formato Anthropic).
* `FallbackLLMDispatcher`: falha no primário (exceção / erro de rede) → chaveamento para o fallback.
* `FallbackLLMDispatcher`: primário retorna erro de rede → fallback responde com sucesso.
* `FallbackLLMDispatcher`: todos falham → retorna último erro.

---

## [0.1.0] - 2026-11-05

### Entregas da Release Minor v0.1.0

#### [LOG-01] Sistema de Logs Profissional (`src/tomus/core/logging.py`)
* Configuração de logging estruturado que redireciona logs detalhados para arquivo
  (`tomus.log`), mantendo o terminal 100% limpo para a barra de progresso do Rich.
* `setup_logging(verbose=verbose)`: quando `verbose=True`, anexa um StreamHandler ao console;
  caso contrário, apenas o arquivo de log recebe as mensagens.
* Silenciamento defensivo de loggers de terceiros (RapidOCR, docling, transformers, torch,
  urllib3, httpx, fitz) e variáveis de ambiente (GLOG_minloglevel, TORCH_CPP_LOG_LEVEL,
  TOKENIZERS_PARALLELISM, HF_HUB_DISABLE_PROGRESS_BARS).

#### [RES-02] Persistência de Sessão para Retomada (`src/tomus/core/session.py`)
* `SessionState` (Pydantic BaseModel): serializa estado de execução (source_dir, target_dir,
  recursive, move, dry_run, provider, model, confidence_min, workers, no_cache, created_at).
* `save_session(state)`: grava o estado em `.tomus_session.json`.
* `load_session()`: carrega o estado salvo, retornando None se o arquivo não existir ou
  estiver corrompido.
* `clear_session()`: remove o arquivo de sessão com tolerância a arquivo ausente.
* Novo comando CLI `./tomus resume` para retomada automática da execução interrompida.

#### [LLM-03] Provedor NVIDIA NIM (`src/tomus/core/llm.py`)
* `NvidiaProvider`: chama a API NVIDIA NIM em `POST /chat/completions` via httpx, com retry
  em 429/503, strip de blocos markdown JSON e travas determinísticas de confiança idênticas
  às do GeminiProvider (short-circuit < 50 chars, teto 0.50 para título genérico).
* Modelo padrão: `meta/llama-3.2-90b-vision-instruct`.
* Resolução de chave: flag CLI `--api-key` > env `TOMUS_NVIDIA_API_KEY` / `NVIDIA_API_KEY`
  > config `nvidia_api_key`.

#### [CLI-04] Integração CLI + Pipeline para release v0.1.0 (`src/tomus/cli/main.py`)
* Novas flags globais: `--verbose` / `-v` e `--provider` / `-p` (gemini ou nvidia).
* `setup_logging(verbose=verbose)` chamado no início de `_executar_organize`.
* `_build_provider` agora aceita parâmetro `provider`; suporte a NVIDIA com resolução de chave
  e erro amigável quando ausente.
* Sessão e Retomada: `save_session(SessionState(...))` no início de `_executar_organize`;
  `clear_session()` após conclusão bem-sucedida.
* Subcomando `organize` ocultado do `--help` raiz (`hidden=True`).
* Comando `tomus resume` adicionado.
* Barra de progresso Rich reescrita com `rich.console.Group` + `rich.live.Live`:
  barra consolidada no topo e linha de status do arquivo abaixo.
* Comando `tomus cache` com subcomandos `clean`/`clear`, `status` e `path`.
* Remoção do resquício `progress.update(task, description="Concluído")` do bloco `finally`.
* Bump de versão para **0.1.0** em `pyproject.toml` e `src/tomus/__init__.py`.

---

## [0.0.6] - 2026-11-04

### Adicionado
* **Arquivo companheiro (.md)**: `src/tomus/storage/companion.py` com funções
  `format_abnt_author`, `format_abnt_authors`, `format_abnt_reference`,
  `generate_companion_markdown` e `generate_duplicate_companion_markdown`.
* **Gerenciamento de duplicatas**: `LibraryOrganizer` encaminha duplicatas para
  `target_dir/duplicatas/` com resolução de colisão de nomes, `.md` companheiro e
  suporte a `move` (limpa a origem) e `copy`.
* **Comando `tomus cache`**: subcomandos `clean`/`clear`, `status` e `path` para
  gerenciar o banco SQLite `~/.cache/tomus/state.db`.
* **Barra de progresso Rich**: reescrita com `Group(prog_bar, status_prog)` e `Live`,
  com barra consolidada no topo e linha de status do arquivo abaixo.

### Alterado
* `src/tomus/storage/organizer.py`: integração do arquivo companheiro na etapa
  `add_organized` (quando `status == ORGANIZED` e não `dry_run`).

---

## [0.0.5] - 2026-11-03

### Corrigido
* **Modelo Gemini**: padrão atualizado para `gemini-3.8-flash` em `config.py`, `llm.py`
  e `tomus.toml`.
* **Fallback inteligente**: `GeminiProvider._call_gemini` tenta cadeia de modelos
  (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`)
  quando o modelo atual retorna HTTP 404 NOT_FOUND.
* **Poluição do cache SQLite**: `FileCache` aceita `db_path`; nunca lê/grava resultados
  com `reasoning == 'mock'` no cache real (~/.cache/tomus/state.db); 113 entradas
  mock removidas; testes usam `db_path=tmp_path/'state.db'`.
* **CLI sem chave**: levanta erro amigável + `typer.Exit(1)` em vez de usar
  `MockLLMProvider` silenciosamente.
* **Colisão de nomes em `--dry-run`**: `LibraryOrganizer._planned_destinations`
  detecta colisões contra arquivos planejados na mesma execução, funcionando em
  modo dry-run.
* **Ambiente virtual Python 3.12**: `.venv` criado na raiz; `./tomus` re-executa
  com `.venv/bin/python` se existir.
* **Silenciamento de avisos**: `HF_HUB_DISABLE_PROGRESS_BARS=1`,
  `TOKENIZERS_PARALLELISM=false`, filtros para `google.*`, `fitz.*`, urllib3 OpenSSL,
  `SwigPy`/`swigvarlink`, `Redirects are currently not supported`, `UserWarning` do torch.
* **Bug da barra de progresso**: corrigido `NameError` no `_emit` (variável
  `completed_count` inexistente no escopo) que congelava a barra em `0/?`; eventos
  `duplicate_skipped` agora avançam a barra; `on_event` removido do callback.

---

## [0.0.4] - 2026-11-02

### Adicionado
* **Ergonomia da CLI**: `tomus -o <origem> -d <destino> [--dry-run]` executa o
  organize automaticamente sem precisar do subcomando.
* **Opções curtas**: `--origem/-o/--source` e `--destino/-d/--target` tanto no callback
  raiz quanto no subcomando `organize`.
* **Script executável `./tomus`**: adiciona `src/` ao `sys.path` automaticamente e
  chama `tomus.cli.main:main`; usa `.venv/bin/python` se existir.
* **Testes de ergonomia**: `tests/test_cli_ergonomia.py` com `typer.testing.CliRunner`
  cobrindo `-o/-d`, `--origem/--destino`, posições, opções source/target, precedência
  e casos de erro.

### Alterado
* `src/tomus/cli/main.py`: refatorado para extrair lógica comum em
  `_executar_organize`, evitando duplicação entre callback raiz e `organize`.

---

## [0.0.3] - 2026-11-01

### Adicionado (Itens 17 a 27 — Fase 2/3)
* **`src/tomus/core/prompts.py`**: prompt de sistema e payload contextual com
  truncamento de `sampled_text` a 15.000 caracteres priorizando `cip_text`; regras dos
  5 tipos documentais; autores no formato `'Sobrenome, Nome'`; catálogo fechado via
  `format_taxonomy_for_prompt`.
* **`src/tomus/core/llm.py`**: `Protocol LLMProvider`; short-circuit < 50 chars
  sem metadado externo (`confidence_score = 0.0`); `GeminiProvider` com
  `google-genai` (`response_mime_type='application/json'`,
  `response_schema=LLMClassificationOutput`); retry em HTTP 429; validação via
  `validate_or_repair_pair` forçando `confidence_score = 0.0` se retornar `None`;
  teto `min(score, 0.50)` quando título for vazio/genérico sem autor.
* **`src/tomus/storage/__init__.py`**: exporta `format_academic_filename` e
  `LibraryOrganizer`.
* **`src/tomus/storage/namer.py`**: `<autor> - <titulo> - <subtitulo> - <ano>.pdf`
  com 1/2/3+ autores; omissão de subtítulo vazio; `s.d.` quando `year` for `None`;
  normalização Unicode NFC; sanitização de proibidos; truncamento progressivo em
  fronteira de palavra garantindo ≤ 240 bytes UTF-8.
* **`src/tomus/storage/organizer.py`**: árvore temática
  `<Grande Área>/<Área Básica>/<Tipo>/<nome>.pdf`; `revisao_manual/` preservando nome
  original; `shutil.copy2` ou move seguro; `dry_run` sem pastas temáticas nem cópias;
  colisão por SHA-256 (`duplicate_skipped` ou sufixo ` (2).pdf`); gravação de
  `manifest.json` e `revisao_manual/relatorio_revisao.md`.
* **`src/tomus/core/pipeline.py`**: orquestrador de 5 estágios
  (scan → cache → extrator → enriquecer → LLM → organizador); `workers=1` padrão ou
  rede paralela com lock no OCR + finalização; `ExecutionSummary` com teto de 20%
  para `revisao_manual/`; emissão de `PipelineEvent`.
* **`src/tomus/cli/__init__.py`** e **`src/tomus/cli/main.py`**: Typer+Rich
  com comandos `organize`, `config init [--local]`, `config show`, `config path`.
* **Testes**: `tests/test_namer.py`, `tests/test_taxonomy_and_identifiers.py`,
  `tests/test_pipeline_integration.py` (31 testes não-slow).

### Alterado
* `src/tomus/core/__init__.py`: exporta novos módulos (prompts, llm).

---

## [0.0.2] - 2026-10-29

### Adicionado (Itens 12 a 16 — Fase 1, implementados pelo agente Lince)
* **`src/tomus/extractors/__init__.py`**: `extract_document_content(path, sha256)`.
* **`src/tomus/extractors/identifiers.py`**: extração de DOI por regex estrita,
  ISBN validado via `python-stdnum`, detecção de Ficha Catalográfica CIP.
* **`src/tomus/extractors/native_pdf.py`**: extração nativa via PyMuPDF das 10
  primeiras e 5 últimas páginas; decisão de necessidade de OCR.
* **`src/tomus/extractors/ocr_docling.py`**: fallback de OCR seletivo via Docling
  com recorte de páginas sem texto (máximo 8 páginas).
* **`src/tomus/core/enrichers.py`**: consultas HTTP para OpenAlex e Google Books
  com `httpx` + `tenacity` (retry 3 tentativas, timeout 8s); validação de similaridade
  `rapidfuzz.fuzz.token_set_ratio >= 88.0`.

---

## [0.0.1] - 2026-10-27

### Adicionado (Fase 1 — Itens 1 a 11)
* **`pyproject.toml`**: metadados do pacote, dependências, ponto de entrada
  `tomus = "tomus.cli.main:app"`.
* **`src/tomus/__init__.py`**: `__version__ = "0.1.0"`.
* **`src/tomus/core/__init__.py`**: exporta entidades de domínio.
* **`src/tomus/core/config.py`**: `AppConfig` com `pydantic-settings`, fontes TOML
  aninhadas, ordem de precedência (CLI > env > local TOML > global TOML), geração de
  template TOML com permissão `0600`.
* **`src/tomus/core/models.py`**: enums (`DocumentType`, `ProcessStatus`,
  `FileOperation`) e modelos Pydantic (`ExtractedDocument`, `ExternalMetadata`,
  `LLMClassificationOutput`, `FileManifestEntry`, `ExecutionSummary`, `PipelineEvent`).
* **`src/tomus/core/resources/taxonomy_capes.json`**: 9 Grandes Áreas e Áreas
  Básicas da CAPES/CNPq.
* **`src/tomus/core/taxonomy.py`**: carregamento da taxonomia,
  `validate_or_repair_pair`, `format_taxonomy_for_prompt`.
* **`src/tomus/core/scanner.py`**: varredura recursiva/plana, validação de
  assinatura `%PDF-`, SHA-256, exclusão da subárvore do destino.
* **`src/tomus/core/cache.py`**: cache SQLite em `~/.cache/tomus/state.db`
  (modo WAL), persistência apenas de classificações aprovadas.
* **`.gitignore`**: ignora ambientes virtuais, caches, chaves de API, bancos SQLite.
* **`README.md`**: documentação de instalação, configuração e uso.
