# Backlog do Tomus

Este documento registra itens de melhoria contínua, débitos técnicos, ideias futuras e bugs reportados para tratamento em sprints posteriores.

---

## 📌 Bugs Identificados em Pacotes / Distribuição

### [BUG-PKG-01] Crash `SIGABRT` (`QMessageLogger::fatal`) ao inicializar `QWebEnginePage` no bundle macOS (.app)

- **Prioridade:** Média (Próxima Sprint de Empacotamento)
- **Status:** Concluído / Resolvido (v1.0.1)
- **Ambiente:** macOS 14+ / Apple Silicon (ARM64), pacote congelado via PyInstaller (`Tomus.app`).
- **Data do Relato:** 2026-11-08
- **Responsável:** Prisma (Tomus UX/UI & Desktop GUI Architect)

#### 1. Sintoma e Log de Falha
Ao iniciar o binário congelado `Tomus.app` (fora do interpretador Python direto do `.venv`), o aplicativo aborta imediatamente na inicialização:
```text
Exception Type:    EXC_CRASH (SIGABRT)
Termination Reason: Namespace SIGNAL, Code 6, Abort trap: 6
Application Specific Information: abort() called

Thread 0 Crashed (Dispatch queue: com.apple.main-thread):
0  libsystem_kernel.dylib   __pthread_kill + 8
1  libsystem_pthread.dylib  pthread_kill + 296
2  libsystem_c.dylib        abort + 148
3  QtCore                   QMessageLogger::fatal(char const*, ...) const + 96
4  QtWebEngineCore          QtWebEngineCore::WebContentsAdapter::WebContentsAdapter() + 96
5  QtWebEngineCore          QWebEnginePagePrivate::QWebEnginePagePrivate(...) + 68
6  QtWebEngineCore          QWebEnginePage::QWebEnginePage(QObject*) + 52
7  QtWebEngineCore.abi3.so  Sbk_QWebEnginePage_Init(...) + 1144
```

#### 2. Causa Raiz Técnica
1. **Localização do `QtWebEngineProcess` e Recursos do Chromium:**  
   No empacotamento com PyInstaller no macOS, o motor Chromium do `QtWebEngineCore` exige o executável auxiliar `QtWebEngineProcess.app` e os arquivos `.pak` (`qtwebengine_resources.pak`, `icudtl.dat`, pastas `locales/`). Quando o bundle `.app` não resolve a árvore padrão do Framework Qt, o `QWebEnginePage` invoca `QMessageLogger::fatal()` gerando um `abort()`.
2. **Chromium Sandbox Confinement:**  
   Em bundles não assinados ou sem Hardened Runtime e entitlements de JIT (`com.apple.security.cs.allow-jit`, `com.apple.security.cs.allow-unsigned-executable-memory`), o sandbox padrão do Chromium pode disparar violação de integridade de processo no macOS Sonoma/Sequoia.

#### 3. Plano de Correção Mapeado
1. **Configuração Defensiva de Ambiente em `src/tomus/gui/app.py`:**
   - Injetar flags de desativação de sandbox antes da criação do `QApplication`:
     ```python
     import os, sys
     if getattr(sys, "frozen", False):
         os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
         # Apontar QTWEBENGINE_PROCESS_PATH se necessário
         process_path = os.path.join(sys._MEIPASS, "PySide6", "Qt", "lib", "QtWebEngineCore.framework", "Helpers", "QtWebEngineProcess.app", "Contents", "MacOS", "QtWebEngineProcess")
         if os.path.exists(process_path):
             os.environ["QTWEBENGINE_PROCESS_PATH"] = process_path
     ```
2. **Ajuste no `packaging/pyinstaller.spec`:**
   - Garantir coleta explícita de `QtWebEngineProcess.app` e arquivos de recursos `.pak` via `collect_data_files('PySide6')` ou hook customizado.
3. **Mecanismo de Resiliência / Fallback Gracioso:**
   - Proteger a instanciação do `QWebEngineView` com bloco `try/except`. Se o motor WebEngine falhar no ambiente congelado do usuário, alternar automaticamente para a bancada nativa pura (`QtWidgets.QTableView` + `QSplitter` nativo já implementada em `document_table.py` e `inspector.py`).

---

### [BUG-TRIAGE-01] Falha na Materialização da Triagem Manual Assistida sob Modo "Mover"
- **Prioridade:** Alta (Bloqueador de Triagem sob `file_operation = "move"`)
- **Status:** Concluído / Resolvido (v1.2.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Teste Real com Acervo (Dario)
- **Responsáveis:** Atlas (Foundation) & Forja (Core/Pipeline)
- **Escopo:** `src/tomus/gui/worker.py`, `src/tomus/gui/bridge.py`, `src/tomus/gui/web/app.js`
- **Sintoma:** Ao clicar em "Aprovar e Materializar na Biblioteca" em um item de revisão manual, a tela não alterava e o arquivo não era materializado na pasta temática de destino.
- **Causa Raiz:**
  1. No modo *Mover*, o pipeline move o PDF de origem para `/Destino/revisao_manual/<nome>.pdf`. O `ManualTriageService` tentava ler o arquivo em `entry.source_path` (que já não existia mais), disparando `FileNotFoundError`.
  2. A função `_resolve_collision` não estava importada no escopo de `worker.py`, gerando `NameError`.
- **Solução Implementada:**
  1. Busca em cascata do arquivo físico: Origem -> `entry.destination_path` -> `/Destino/revisao_manual/<nome>.pdf`.
  2. Limpeza automática do arquivo obsoleto de `revisao_manual/` após materializar no destino definitivo.
  3. Importação canônica de `_resolve_collision` e inclusão do teste de regressão automatizado `test_triage_service_materialize_from_revisao_manual` (20/20 testes passando).

---

### [FEAT-BRAND-01] Aplicação da Identidade Visual Oficial (Logo e Ícone de /logo_e_icone)

- **Prioridade:** Alta (Identidade Oficial do Aplicativo)
- **Status:** Concluído / Resolvido (v1.0.0)
- **Escopo:** `logo_e_icone/`, `packaging/icons/`, `src/tomus/gui/resources/`, `src/tomus/gui/web/`
- **Data do Relato:** 2026-11-08
- **Responsável:** Prisma (UX/UI) & Chefe

#### 1. Diagnóstico e Fontes Oficiais
Foram disponibilizadas as artes oficiais em alta resolução:
- `/Users/dario/Projetos-de-aplicativos/tomus/logo_e_icone/icone.png` (1254 x 1254 px)
- `/Users/dario/Projetos-de-aplicativos/tomus/logo_e_icone/Logo.png` (1774 x 887 px)

#### 2. Entregas Pré-processadas
1. **Ícones Multiplataforma:**
   - `packaging/icons/icon.icns`: Pacote Apple Silicon / Retina multi-camada (16x16 até 1024x1024) com transparência de cantos gerado via `iconutil`.
   - `packaging/icons/icon.ico`: Pacote multi-resolução para Windows (16, 32, 48, 64, 128, 256) integrado no instalador Inno Setup (`packaging/windows_installer.iss`).
   - `src/tomus/gui/resources/tomus_icon.png`: Bitmap oficial 256x256 injetado no `app.setWindowIcon` e `window.setWindowIcon`.
2. **Logo e Web GUI:**
   - Cópias em `src/tomus/gui/resources/` e `src/tomus/gui/web/logo.png`.
   - Pendência ao retomar: finalizar inserção do elemento `<img>` na toolbar e no modal "Sobre o Tomus".

---

### [FEAT-UI-01] Substituição do Ícone Padrão do Python por Ícone Personalizado do Tomus

- **Prioridade:** Média / Alta (Polimento de Produto)
- **Status:** Concluído / Resolvido (v1.0.1)
- **Escopo:** macOS (.app / Dock), Windows (.exe / Taskbar / Inno Setup)
- **Data do Relato:** 2026-11-08
- **Responsáveis:** Prisma (UX/UI) & Atlas (Foundation)

#### 1. Objetivo
Substituir o ícone genérico padrão do Python (exibido atualmente no Dock do macOS, na barra de tarefas do Windows e nos binários empacotados) por uma identidade visual exclusiva e personalizada do **Tomus** (*Editorial Academic Workbench*), remetendo a organização acadêmica, catalogação e rigor tipográfico.

#### 2. Requisitos de Entrega
1. **Arte e Formatos Multiplataforma:**
   - **macOS (`.icns`):** Arquivo multi-resolução com camadas de 16x16 até 1024x1024 (Retina @2x), integrado em `Contents/Resources/icon.icns` do `.app`.
   - **Windows (`.ico`):** Arquivo contendo resoluções de 16x16, 32x32, 48x48, 64x64, 128x128 e 256x256 incorporado ao `Tomus.exe` e ao instalador Inno Setup (`SetupIconFile`).
2. **Runtime do Aplicativo (`src/tomus/gui/app.py`):**
   - Configurar `app.setWindowIcon(QIcon(icon_path))` no `QApplication` e em `MainWindow` para que janelas secundárias e diálogos modais herdem o ícone oficial.
   - Definir `AppUserModelID` no Windows (`ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID`) para garantir que o Windows agrupe a janela corretamente na barra de tarefas com o ícone customizado.
3. **Scripts de Empacotamento (`packaging/`):**
   - No `packaging/pyinstaller.spec`: adicionar parâmetro `icon='assets/icons/tomus.icns'` no bloco `BNDL` (macOS) e `icon='assets/icons/tomus.ico'` no bloco `EXE` (Windows).
   - No `packaging/windows_installer.iss`: configurar `SetupIconFile=..\assets\icons\tomus.ico` e `UninstallDisplayIcon={app}\Tomus.exe`.

---

## 📦 Empacotamento e Distribuição macOS

### [FEAT-PKG-02] Janela DMG Profissional no macOS com Atalho "Arrastar para Aplicativos" (Drag-to-Applications)

- **Prioridade:** Média (Polimento da Experiência macOS)
- **Status:** Concluído / Resolvido (v1.0.1)
- **Escopo:** `packaging/build_macos.sh`, `.github/workflows/release.yml`
- **Data do Relato:** 2026-11-08
- **Responsável:** Atlas (Tomus Foundation Engineer)

#### 1. Objetivo
Ao montar e abrir o arquivo `Tomus-1.0.0-macOS.dmg`, o Finder deve abrir automaticamente uma janela limpa e customizada contendo:
- O ícone do aplicativo **`Tomus.app`** à esquerda.
- Um atalho simbólico nativo para a pasta **`Applications` (Aplicativos)** à direita.
- (Opcional) Fundo ilustrativo com seta discreta e texto instrucional orientando a arrastar o aplicativo para instalar.

#### 2. Requisitos Técnicos
1. **Estrutura do Volume DMG:**
   - Criar link simbólico `ln -s /Applications "${DMG_TEMP_DIR}/Applications"` no diretório base da imagem.
2. **Posicionamento e Propriedades do Finder:**
   - Utilizar ferramenta automatizada como `create-dmg` ou script AppleScript / `dmgbuild` para configurar:
     - Dimensão da janela (ex.: 540x380 px).
     - Tamanho dos ícones (ex.: 100px ou 128px).
     - Coordenadas exatas dos ícones (ex.: `Tomus.app` em `(140, 190)` e `Applications` em `(400, 190)`).
     - Ocultação da barra lateral e barra de status do Finder no volume montado.
3. **Automação no CI/CD e Script Local:**
   - Atualizar `packaging/build_macos.sh` para suportar `create-dmg` (instalável via Homebrew ou GitHub Actions `brew install create-dmg`).
   - Atualizar a etapa `build-macos` no `.github/workflows/release.yml` para gerar o `.dmg` com o layout padronizado.

---

## 📦 Distribuição Multiplataforma e Assets no GitHub Releases

### [FEAT-PKG-03] Empacotamento Oficial Multiplataforma (macOS .dmg e Windows .exe)

- **Prioridade:** Alta (Lançamento Oficial v1.0.0)
- **Status:** Concluído / Resolvido (v1.0.0)
- **Escopo:** `.github/workflows/release.yml`, `packaging/windows_installer.iss`, GitHub Releases
- **Data do Relato:** 2026-11-08
- **Responsável:** Farol (Release & GitOps Manager) & Atlas (Foundation Engineer)

#### 1. Diretriz Estratégica de Lançamento
Conforme decisão de produto, o lançamento inicial foca na estabilização dos dois maiores ecossistemas desktop acadêmicos:
1. **macOS**: Imagem DMG com suporte a Apple Silicon / Intel e atalho Finder para `/Applications`.
2. **Windows**: Instalador `.exe` profissional com assistente moderno Inno Setup, criação de atalhos e desinstalador limpo.

#### 2. Requisitos de Entrega
1. **Compilação do Instalador Windows:**
   - Executar o workflow de CI em runner Windows (`windows-latest`).
   - Gerar o bundle via PyInstaller e compilar o instalador Inno Setup (`packaging/windows_installer.iss`).
   - Validar que o instalador crie atalhos no Menu Iniciar, Área de Trabalho e suporte desinstalação limpa.
   - Gerar o arquivo final `Tomus_Setup_v1.0.0_Windows_x64.exe`.
2. **Compilação do Instalador macOS:**
   - Executar o workflow de CI em runner macOS (`macos-latest`).
   - Gerar o bundle via PyInstaller e compilar a imagem DMG com Finder layout (`packaging/build_macos.sh`).
   - Gerar o arquivo final `Tomus-1.0.0-macOS.dmg`.
3. **Publicação Consolidada na Seção Assets:**
   - Anexar ambos os arquivos (`.dmg` e `.exe`) à página de releases do repositório `dcprj/tomus`.
   - Garantir que ambos os instaladores oficiais (macOS e Windows) apareçam listados com seus hashes SHA-256 e tamanhos.

---

## 🔑 Guia de APIs e Credenciais: Google Books API Key

### 1. Para que a chave é necessária no Tomus
1. **Enriquecimento Bibliográfico Oficial:** O extrator `metadata_google_books.py` consulta o catálogo mundial do Google Books para enriquecer livros e e-books com metadados canônicos (título padronizado, nomes completos dos autores, editora, cidade, ano de publicação exato, sinopse e categorização temática), além de validar e formatar o ISBN-13.
2. **Prevenção de Rate Limiting (HTTP 429):** Requisições anônimas (sem chave) compartilham um pool restrito de cotas baseado em IP público. Em varreduras de pastas com dezenas de PDFs acadêmicos, requisições repetidas sem chave sofrem bloqueio temporário (erro `429 Too Many Requests`). A chave pessoal garante requisições dedicadas e sem bloqueio.
3. **Cota Diária Gratuita:** O Google Cloud oferece gratuitamente uma cota de 1.000 requisições por dia por projeto, o que cobre com folga qualquer biblioteca pessoal ou acadêmica.

### 2. Passo a Passo para Gerar a Chave no Google Cloud Console
1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) com a sua conta Google.
2. Selecione ou crie um projeto (ex.: `Tomus`).
3. No menu de navegação lateral (☰), vá em **APIs e Serviços** > **Biblioteca**.
4. No campo de busca, pesquise por **Books API** (ou **Google Books API**) e clique em **Ativar** (Enable).
5. Após ativada, vá em **APIs e Serviços** > **Credenciais**.
6. Clique no botão superior **+ Criar Credenciais** e selecione **Chave de API**.
7. *(Boa prática de segurança)*: Clique nos três pontinhos ao lado da chave criada e selecione **Editar chave**:
   - Em **Restrições de API**, marque **Restringir chave** e selecione exclusivamente a **Books API**.
   - Salve a configuração.
8. Copie a chave gerada (iniciada por `AIzaSy...`).
9. **Configuração no Tomus:**
   - **Interface Gráfica (Recomendado):** Abra o modal **Preferências (⚙️)** > aba **Chaves de API** > preencha o campo **Google Books API Key** e salve.
   - **Arquivo Local:** Adicione em `tomus.toml`: `google_books_api_key = "AIzaSy..."`.
   - **Variável de Ambiente:** Exporte `export TOMUS_GOOGLE_BOOKS_API_KEY="AIzaSy..."`.

---

## 🌐 Presença Web e Distribuição: Landing Page no GitHub Pages [FEAT-WEB-01]

- **Prioridade:** Média (Pós-v1.0.1)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Responsáveis:** Prisma (UX/UI Designer) & Farol (GitOps)
- **Hospedagem:** Gratuita via GitHub Pages (`https://dcprj.github.io/tomus/`)
- **Evidência no Código:** `docs/index.html` existente com hero section, botões de download (`Baixar .dmg`, `Baixar Tomus para macOS`), showcase visual e garantias de privacidade.

### 1. Escopo e Objetivos
1. **Página Estática Leve e Responsiva:** Desenvolvida em HTML5/CSS3 moderno na pasta `docs/` ou branch dedicada, sem dependências de frameworks pesados.
2. **Hero Section:**
   - Logotipo oficial e identidade visual do Tomus.
   - Slogan acadêmico voltado a pesquisadores e estudantes de pós-graduação.
   - Botões de download inteligentes que direcionam para os assets oficiais da última release:
     - `Tomus_Setup_v{VERSION}_Windows_x64.exe`
     - `Tomus-{VERSION}-macOS.dmg`
3. **Showcase Visual:**
   - Demonstração da taxonomia curricular CAPES/CNPq.
   - Extração de metadados canônicos via DOI/Crossref e Google Books.
   - Resgate de documentos escaneados antigos via Docling OCR.
   - Geração de companion markdown (.md) com referências ABNT NBR 6023.
   - Garantia de privacidade 100% local (sem envio de documentos acadêmicos para a nuvem).
4. **Instruções de Instalação e FAQ:** Requisitos para macOS (Apple Silicon / Intel) e Windows 10/11.

---

## 🏛️ Governança de Engenharia: Modelo de Pull Requests & Code Review [GOV-01]

- **Prioridade:** Alta (Para as próximas sprints v1.0.2 e v1.1.0)
- **Status:** Planejado
- **Responsáveis:** Farol (Release Manager), Sentinela (AppSec) e Chefe (Arquiteto)

### 1. Regras de Proteção de Branch (`main`)
- Bloqueio de commits diretos na branch principal.
- Exigência de Pull Request aprovado e esteira de CI/CD 100% verde antes de qualquer merge.

### 2. Mapeamento de Responsabilidades (`.github/CODEOWNERS`)
- `src/tomus/gui/`: Revisão obrigatória de Prisma (UX/UI).
- `src/tomus/core/`: Revisão obrigatória de Atlas (Foundation).
- `src/tomus/extractors/`: Revisão obrigatória de Lince (Extractors).
- `src/tomus/cli/`: Revisão obrigatória de Forja (Pipeline & CLI).
- `packaging/`, `.github/workflows/`: Revisão obrigatória de Farol (Release Manager).
- Todo o código / credenciais / segurança: Gatekeeper Sentinela (AppSec).

### 3. Template de PR Padronizado (`.github/pull_request_template.md`)
- Checklist de testes unitários executados.
- Checklist de segurança da informação (ausência de chaves, sanitização de entradas e caminhos).
- Evidências gráficas para alterações de interface.

---

## 🏛️ Rebranding Oficial para TOMUS [BRAND-01]

- **Prioridade:** Alta (Alvo da versão v1.1.0)
- **Status:** Aprovado pela Direção (Dario)
- **Responsáveis:** Prisma (UX/UI Designer) & Atlas (Foundation)
- **Novo Nome Oficial:** **Tomus — Organizador Acadêmico de PDFs**
- **Conceito & Etimologia:** Do latim *tomus* (volume encadernado, seção de um compêndio ou enciclopédia do saber).
- **Identidade Visual Aprovada:** Opção 1 — Neoclássico Editorial
  - **Paleta:** Fundo Navy Slate (`#0f172a`), filetes em ouro acetinado e iluminação azul etéreo.
  - **Emblema:** Tomo encadernado clássico com páginas organizadas formando a letra **"T"**.
  - **Arquivos de Referência:**
    - Ícone: `docs/designs/tomus_branding/tomus_app_icon.jpg`
    - Banner: `docs/designs/tomus_branding/tomus_horizontal_logo.jpg`
- **Etapas de Execução para v1.1.0:**
  1. Criação dos pacotes de ícones vetoriais: `icon.icns` (macOS Retina) e `icon.ico` (Windows multi-resolução 16-256px).
  2. Atualização dos cabeçalhos, títulos da janela e logo no WebView da GUI.
  3. Atualização do `README.md` e metadados de empacotamento.
  4. Lançamento da Landing Page no GitHub Pages já ostentando a nova marca **Tomus**.

---

## 🔑 Validação Ativa de Chaves de API no Salvamento [FEAT-AUTH-02]

- **Prioridade:** Alta (UX & Resiliência - Sprint v1.1.0/v1.2.0)
- **Status:** Planejado
- **Responsáveis:** Prisma (UX/UI) & Atlas (Foundation)
- **Origem:** Demanda de Produto (Dario)

### 1. Problema Identificado
Atualmente, a aplicação grava qualquer string inserida nos campos de chave de API no arquivo de configuração sem validação imediata. Se a chave estiver expirada, digitada incorretamente ou for um token inválido (como tokens OAuth em vez de API Keys), o usuário só descobre a falha muito tempo depois, durante a execução de um lote de PDFs, gerando erros HTTP 401/403 ou paradas inesperadas.

### 2. Requisitos de Entrega
1. **Health Check Ativo no Salvamento:**
   - Ao clicar no botão **"Salvar"** no modal de Preferências (ou via comando `config set`), disparar uma verificação assíncrona leve para cada chave informada:
     - **Google Gemini:** Consulta rápida de modelos disponíveis ou teste mínimo de conexão.
     - **Google Books:** Consulta leve com a chave fornecida (`q=isbn:0000000000&key=...`).
     - **Provedores Alternativos (Groq, DeepSeek, NVIDIA):** Ping leve de autenticação (`/models`).
2. **Feedback Visual Imediato na Interface:**
   - **Chave Válida:** Indicador visual verde (badge "Ativa e Validada").
   - **Chave Inválida / Não Autorizada (HTTP 401/403):** Alerta claro e contextualizado (ex.: *"Chave da Google Books recusada pelo Google Cloud. Verifique se a Books API foi ativada nas credenciais do seu projeto"*), permitindo correção imediata.
3. **Não-Bloqueio Gracioso:**
   - Se o usuário estiver temporariamente offline no momento de salvar, informar que a chave foi gravada mas não pôde ser testada por ausência de conexão.

---

## 🎨 Design do Ícone & Resolução Visual do Aplicativo [BRAND-02]

- **Prioridade:** Alta (Qualidade Visual & Identidade de Produto)
- **Status:** Concluído / Resolvido (v1.1.1)
- **Responsável:** Prisma (UX/UI Designer)
- **Evidências Visuais Fornecidas:**
  1. **Instalador DMG (`Tomus.app` ao lado da pasta `Applications`):** Exibição de uma moldura retangular/escura falsa de estúdio com cantos sujos e símbolo reduzido.
  2. **Dock do macOS (Comparativo direto com `Google Chrome`, `Maestri`, `WhatsApp`, `ChatGPT`, `Ajustes`, `Terminal`):**
     - Enquanto todas as aplicações profissionais do sistema preenchem 100% da silhueta do squircle oficial da Apple com fundos contínuos e ícones vetoriais nítidos, o Tomus apresentava uma moldura cinza clara de estúdio fotográfico (mockup 3D) em volta de outro squircle minúsculo, parecendo um "ícone minúsculo dentro de outro ícone".
     - O símbolo central ("T" / Tomo) ocupava menos de 25% da área total, gerando desfoque, baixa resolução percebida e quebra total da harmonia do Dock e da barra de tarefas do Windows.

### Problemas Identificados e Solucionados
1. **Falso Fundo Cinza Eliminado:** O ícone foi redimensionado a partir do canvas base 1024x1024 RGBA limpo, com squircle cobrindo ~82.5% da área e transparência alfa pura (`alpha=0`) nos quatro cantos externos.
2. **Ícone Windows Multi-Resolução (7 Camadas):** O arquivo `packaging/icons/icon.ico` foi compilado contendo 7 resoluções (16, 24, 32, 48, 64, 128 e 256 px) totalizando 48.7 KB, sanando definitivamente o desfoque na Área de Trabalho e Barra de Tarefas do Windows.
3. **Pacotes Atualizados:** `packaging/icons/icon.png`, `packaging/icons/icon.icns`, `packaging/icons/icon.ico`, `src/tomus/gui/resources/tomus_icon.png`, `src/tomus/gui/web/logo.png` e `src/tomus/gui/web/logo_transparent.png`.

---

## 🎨 Identidade Visual do Repositório [BRAND-03]

- **Prioridade:** Média / Alta (Alinhamento de Marca)
- **Status:** Concluído / Resolvido (v1.1.1)
- **Responsável:** Prisma (UX/UI Designer)
- **Entregas:**
  1. Cabeçalho do `README.md` atualizado com o banner horizontal oficial do Tomus.
  2. Substituição integral de referências remanescentes ao nome antigo nos textos, links de download da v1.1.1 e comandos de liberação do Gatekeeper e SmartScreen.
  3. Pasta `logo_e_icone/` sincronizada com as artes vetoriais e de alta definição da nova marca.

---

## 🐛 Correção da Injeção de Binários do ONNXRuntime no PyInstaller [BUG-PKG-05]

- **Prioridade:** Crítica (Correção Definitiva do OCR no Windows)
- **Status:** Concluído / Resolvido (v1.1.1)
- **Responsável:** Atlas (Foundation)
- **Resolução:** Linha 90 do `packaging/pyinstaller.spec` ajustada para `binaries=binaries`, garantindo que as DLLs coletadas pelo `collect_dynamic_libs("onnxruntime")` sejam embarcadas no `Tomus.exe`.

---

## 💥 Crash Imediato na Inicialização do Tomus no macOS e Windows [BUG-PKG-06]

- **Prioridade:** Bloqueador / Crítica (v1.1.0 não abria no macOS nem em diretórios protegidos do Windows)
- **Status:** Concluído / Resolvido (v1.1.1)
- **Responsáveis:** Atlas (Foundation) & Forja (Core/Pipeline)
- **Resolução:**
  1. Remoção de `setup_logging` do escopo global de importação de `src/tomus/gui/app.py`.
  2. Inicialização segura de logging dentro de `launch_gui()` apontando para `Path.home() / ".tomus" / "tomus.log"`.
  3. Tratamento defensivo em `src/tomus/core/logging.py` com bloco `try/except` envolvendo a criação do `FileHandler` e fallback gracioso para `NullHandler()`, impedindo qualquer interrupção do aplicativo por falha de I/O de log.

---

## ⏱️ Estimativa de Tempo para Finalização (ETA) na Barra de Status da GUI [FEAT-UI-02]

- **Prioridade:** Média / Alta (UX & Acompanhamento de Lotes Grandes)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda de Produto (Dario — identificada durante teste com lote de 907 PDFs)
- **Responsável:** Prisma (Tomus UX/UI & Desktop GUI Architect)
- **Evidência no Código:** `state.batchStartTime`, `el.avgTimeIndicator` e `el.etaIndicator` implementados em `src/tomus/gui/web/app.js` (cálculo de média por arquivo e total estimado, com reset ao finalizar/interromper o lote).

### 1. Objetivo e Layout do Rodapé (Design Aprovado)
Exibir no rodapé da interface gráfica (`footer.status-bar`), onde já constam a barra de progresso, o percentual, o estágio atual, a contagem de processados (`X / Y processados`) e os itens restantes (`Restam: Z`), duas métricas dinâmicas essenciais desenhadas e aprovadas pelo Arquiteto-Chefe (Dario):

1. **`Média por arquivo: <tempo>`** (ex.: `3 min` quando há OCR neural em PDFs escaneados, ou `2.5 s` em PDFs digitais nativos);
2. **`Total estimado: <tempo>`** (ex.: `1 h e 30 min` ou `12 min`), calculando dinamicamente a estimativa até o término do lote.

#### Estrutura Visual do Rodapé (Mockup Homologado):
```text
[━━━━━               ] 13%  Estágio: Extração de Texto  |  55 / 420 processados  |  Restam: 365  |  média por arquivo: 3 min  |  Total estimado: 1 h e 30 min
```

### 2. Especificação Técnica e UX
1. **Posicionamento no DOM (`src/tomus/gui/web/index.html`):**
   - No container `.status-metrics` do rodapé (`footer.status-bar`), logo após `<span id="remainingIndicator">Restam: 0</span>`, adicionar:
     - Separador vertical: `<span class="sep">|</span>`
     - Média por arquivo: `<span id="avgTimeIndicator">média por arquivo: —</span>`
     - Separador vertical: `<span class="sep">|</span>`
     - Total estimado: `<span id="etaIndicator">Total estimado: —</span>`
2. **Cálculo Dinâmico e Amortecido (`src/tomus/gui/web/app.js`):**
   - Registrar `state.batchStartTime = Date.now()` no disparo de `startOrganize`.
   - Em `handlePipelineEvent(ev)`, quando `ev.completed_files > 0` e `ev.total_files > ev.completed_files`:
     - Calcular o tempo decorrido total: `elapsedSec = (Date.now() - state.batchStartTime) / 1000`.
     - Calcular o tempo médio real por arquivo: `avgSec = elapsedSec / ev.completed_files`.
     - Formatar **Média por arquivo**:
       - `>= 60s`: `${Math.round(avgSec / 60)} min`
       - `< 60s`: `${avgSec.toFixed(1)} s`
     - Calcular o **Total estimado** (tempo restante): `remainingSec = Math.round(avgSec * (ev.total_files - ev.completed_files))`.
     - Formatar **Total estimado**:
       - `>= 3600s`: `${Math.floor(remainingSec / 3600)} h e ${Math.round((remainingSec % 3600) / 60)} min`
       - `>= 60s`: `${Math.round(remainingSec / 60)} min`
       - `< 60s`: `${remainingSec} s`
   - Ao finalizar ou interromper o lote (`handlePipelineFinished` / `clearScreenForNewBatch`), exibir o tempo total consolidado e resetar os indicadores.
3. **Tipografia & Prevenção de Layout Shift (`src/tomus/gui/web/styles.css`):**
   - Aplicar `font-variant-numeric: tabular-nums` e largura mínima com `white-space: nowrap` para que a alteração de segundos e minutos não cause pulos visuais na barra de status.

---

## 📦 Processamento Fracionado Inteligente de Grandes Acervos (Sub-Lotes de 50 a 100 PDFs com Persistência e Retomada) [FEAT-BATCH-01]

- **Prioridade:** Alta (UX, Resiliência de Cotas de API & Ergonomia em Grandes Bibliotecas)
- **Status:** Planejado (Backlog)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda Estratégica de Produto (Dario — concebida durante processamento real de acervo de 907 PDFs)
- **Responsáveis:** Forja (Core, Pipeline & Persistência de Sessão) & Prisma (UX/UI & Fluxo Interativo na GUI)

### 1. Problema e Motivação
Ao organizar bibliotecas acadêmicas volumosas (centenas ou milhares de PDFs), processar tudo em uma única corrida contínua pode levar dezenas de minutos ou horas, consumir limites de *rate limit* / cota diária de APIs gratuitas (BYOK) e exigir que o usuário mantenha o computador ativo sem pausas naturais de revisão. Oferecer o fatiamento opcional em sub-lotes (*chunks*) de **50 a 100 PDFs** proporciona controle total, segurança contra quedas de energia/rede e pontos naturais de parada e retomada.

### 2. Fluxo de Experiência do Usuário (UX)
1. **Detecção de Lote Grande (Pré-Voo / Pre-Flight Check):**
   - Ao clicar em **"Organizar Acervo"**, o scanner realiza uma contagem rápida dos PDFs pendentes na pasta de origem (descontando os já organizados/cacheados no destino, se aplicável).
   - Se o total de PDFs a processar for **superior a 100 arquivos**, exibir um modal de sugestão amigável antes de iniciar:
     - **Título:** *"Grande Acervo Detectado (ex.: 907 PDFs)"*
     - **Mensagem:** *"Deseja dividir o processamento em lotes menores (50 a 100 PDFs por etapa)? Isso permite revisar resultados parciais, poupar cotas de API e pausar/retomar com segurança quando quiser."*
     - **Seletor de Tamanho do Sub-Lote:** Opções rápidas `50 PDFs por lote` | `100 PDFs por lote` (padrão recomendado: `100`).
     - **Botões de Decisão:**
       - **`Dividir em Lotes Menores (Recomendado)`**: Ativa o modo fracionado.
       - **`Processar Tudo de Uma Vez`**: Segue o fluxo contínuo tradicional exatamente como funciona hoje.
2. **Transição ao Finalizar Cada Sub-Lote:**
   - Ao concluir um sub-lote (ex.: Lote 1 de 10 — 100 PDFs processados), exibir o modal de conclusão da etapa com o resumo parcial daquele lote e o progresso global da biblioteca (`100 / 907 concluídos — 807 restantes`), perguntando ao usuário:
     - **`Prosseguir para o Próximo Lote (+100 PDFs)`**: Inicia imediatamente o próximo sub-lote.
     - **`Continuar Depois (Salvar Progresso)`**: Encerra a sessão de forma limpa, mantendo todo o estado persistido em disco para retomada futura.
3. **Banner e Detecção Automática de Retomada:**
   - Ao reabrir o aplicativo (ou ao selecionar novamente o mesmo par `Origem -> Destino`), se houver uma sessão fracionada pendente, exibir em destaque no topo da janela (ou ao clicar em Organizar):
     - *"Sessão em Lotes Pendente: 100 de 907 PDFs já processados (Lote 1/10 concluído). Deseja retomar do Lote 2?"* com botões **`[Retomar Próximo Lote]`** e **`[Reiniciar / Descartar Estado]`**.

### 3. Arquitetura de Persistência e Retomada (`tomus.core.session` & `manifest.json`)
1. **Registro Determinístico do Plano de Lotes (`~/.cache/tomus/batch_sessions.json` ou tabela SQLite `batch_sessions`):**
   - Persistir para cada par `(source_dir, target_dir)`:
     - `session_id`, `created_at`, `updated_at`
     - `batch_size` (`50` ou `100`)
     - `total_discovered_pdfs`: lista ordenada e determinística dos caminhos/hashes SHA-256 escaneados.
     - `completed_paths` / `completed_sha256`: conjunto de arquivos já processados nos sub-lotes anteriores.
     - `current_batch_index` e `total_batches`.
2. **Idempotência e Consolidação Cumulativa no Destino:**
   - Quando um novo sub-lote é executado, o `LibraryOrganizer` **acumula** (faz *merge*) as novas entradas no `manifest.json` e no `revisao_manual/relatorio_revisao.md` existentes no diretório de destino, em vez de sobrescrevê-los apenas com os itens do sub-lote atual.
   - O `FileCache` SQLite (`~/.cache/tomus/state.db`) atua como segunda camada de garantia: qualquer arquivo já aprovado em sub-lotes anteriores jamais consome nova chamada de LLM ou OCR.

---

## 🗂️ Precedência de Filtros e Retorno à Visão Inicial da Organização [FEAT-UI-03]

- **Prioridade:** Alta (Ergonomia de Navegação & UX da Bancada)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda de Usabilidade (Dario — detectada durante acompanhamento de lote de 907 PDFs)
- **Responsável:** Prisma (Tomus UX/UI & Desktop GUI Architect)
- **Evidência no Código:** `state.activeAreaFilter` implementado em `src/tomus/gui/web/app.js` (linhas 21, 585, 596, 613-616, 628, 1329, 1356) com reset ao clicar em "Todos os Itens".

### 1. Diagnóstico do Problema
1. **Filtro de Árvore Preso:** Ao navegar por um nó da Árvore CAPES/CNPq (`state.activeAreaFilter`), o estado do nó permanecia ativo mesmo ao clicar em filtros de status laterais (*Duplicatas*, *Erros*, *Ignorados*). Isso provocava uma interseção lógica restritiva (ex.: `status == 'duplicate_skipped' AND area == 'Linguística'`), resultando em tela vazia e impedindo o usuário de inspecionar os arquivos daquela categoria.
2. **Impossibilidade de Retornar à Visão Inicial:** Ao clicar em **"Todos os Itens"**, a árvore mantinha sua seleção prévia, impedindo o usuário de voltar à visão global e fluida da esteira de classificação em andamento.

### 2. Especificação da Nova Lógica de Precedência
1. **Precedência Global dos Filtros de Status:**
   - Os botões de status (*Todos os Itens*, *Organizados*, *Revisão Manual*, *Duplicatas*, *Ignorados*, *Erros*) possuem precedência hierárquica sobre a árvore.
   - Ao clicar em **Duplicatas**, a tabela exibe **todas as duplicatas** detectadas no lote global, limpando automaticamente o filtro de área (`state.activeAreaFilter = null`) e desmarcando visualmente nós ativos na árvore.
   - O mesmo comportamento aplica-se rigorosamente a **Erros**, **Ignorados**, **Revisão Manual** e **Organizados**.
2. **"Todos os Itens" como Reset Geral da Bancada:**
   - O clique em **Todos os Itens** limpa integralmente quaisquer filtros de árvore (`state.activeAreaFilter = null`), desmarca seleções e retorna imediatamente à visão panorâmica original da organização em tempo real.
3. **Navegação Taxonômica Contextual:**
   - O filtro de área só é ativado quando o usuário clica expressamente em um nó da Árvore CAPES/CNPq (atuando por padrão sobre os itens organizados/classificados daquela área).

---

## 📋 Botão Copiar Citação ABNT e Rigor Tipográfico NBR 6023 [BUG-UI-01]

- **Prioridade:** Alta (Qualidade Visual, Ergonomia & Conformidade Normativa)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda de Usabilidade (Dario — detectada com evidência fotográfica no Inspetor de Documentos)
- **Responsáveis:** Prisma (UX/UI & Frontend Web) & Atlas (Ponte Nativa PySide6/Bridge)
- **Evidência no Código:** `copyToClipboard(self, text: str)` implementado em `src/tomus/gui/bridge.py` (linha 592) usando `QGuiApplication.clipboard().setText(text)`.

### 1. Diagnóstico dos Problemas Identificados
1. **Falha no Botão "Copiar Citação ABNT":**
   - `navigator.clipboard.writeText` no Chromium embarcado (`QWebEngineView`) sob protocolo de arquivos locais (`file://`) falha silenciosamente por restrições de permissão de clipboard sem handshake nativo. Como a Promise não possui fallback, o botão não copia o texto nem exibe o feedback visual.
2. **Inversão Tipográfica na Referência ABNT NBR 6023:**
   - No `src/tomus/gui/web/app.js`, os **Autores** estavam envolvidos incorretamente em `<strong>` (negrito), enquanto o **Título** estava envolvido em `<em><strong>` (renderizando em itálico).
   - **Padrão Oficial ABNT NBR 6023:**
     - **Autores:** Texto normal com sobrenomes em caixa alta (ex.: `KATO, Maria da Penha A. Campos de Almeida; ...`) — **sem negrito**.
     - **Título de Livros/Teses:** Destacado em **negrito puro** (`<strong>Título</strong>`), sem itálico. Subtítulo após dois pontos permanece em texto normal (sem negrito).
     - **Artigos em Periódicos:** Título do artigo em texto normal; apenas o **Nome do Periódico** em **negrito**.
3. **Duplicação no Campo de Edição (`1. ed. ed.`):**
   - No `app.js`, a concatenação `${item.edition}. ed.` gerou `1. ed. ed.` quando o metadado já continha a abreviação `ed.`.

### 2. Plano de Correção Técnica
1. **Área de Transferência Nativa via Bridge PySide6 (`src/tomus/gui/bridge.py`):**
   - Adicionar o método `@Slot(str) def copyToClipboard(self, text: str) -> bool` utilizando `QGuiApplication.clipboard().setText(text)`.
   - No JavaScript (`app.js`), acionar prioritariamente `backend.copyToClipboard(text)` com feedback visual garantido (`✔ Copiado!`) e fallback secundário para `navigator.clipboard` / `document.execCommand('copy')`.
2. **Ajuste Cirúrgico no Renderizador de Citação (`app.js`):**
   - Remover `<strong>` dos autores: `parts.push(escapeHtml(authors))`.
   - Ajustar destaque do título de livros: `parts.push('<strong>' + escapeHtml(title) + '</strong>' + escapeHtml(subtitle))`.
   - Sanitizar string de edição para evitar repetições: regex substituindo `(?:\s*ed\.?)+$` por `. ed.`.

---

## 🚫 Desativação do Menu de Contexto Padrão do Navegador (Back, Reload, View Source) [BUG-UI-02]

- **Prioridade:** Média / Alta (Polimento de Produto & Integridade de Estado Desktop)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda de Usabilidade (Dario — identificada ao clicar na interface da bancada)
- **Responsáveis:** Atlas (Foundation/Main Window) & Prisma (UX/UI Web)
- **Evidência no Código:** `self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)` em `src/tomus/gui/main_window.py` (linha 75) e listener defensivo de `contextmenu` no DOM.

### 1. Diagnóstico do Problema
No macOS e Windows, cliques secundários (ou gestos acidentais de dois dedos no trackpad / mouse) disparam o menu de contexto nativo padrão do Chromium no `QWebEngineView`, exibindo opções de navegador web como:
- *Back* (Voltar)
- *Forward* (Avançar)
- *Reload* (Recarregar)
- *Save page* (Salvar página como)
- *View page source* (Exibir código-fonte da página)

Esse comportamento expõe os bastidores web da aplicação, quebra a experiência de app nativo desktop e, caso o usuário clique acidentalmente em *Reload*, pode reiniciar o DOM e resetar a visualização da fila de documentos em andamento.

### 2. Solução Técnica
1. **No PySide6 (`src/tomus/gui/main_window.py`):**
   - Configurar `self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)` na inicialização da janela.
2. **No Frontend (`src/tomus/gui/web/app.js`):**
   - Adicionar listener defensivo: `document.addEventListener('contextmenu', e => { if (!['INPUT', 'TEXTAREA'].includes(e.target.tagName)) e.preventDefault(); });` para bloquear qualquer menu nativo do motor em áreas não editáveis.

---

## 🎛️ Redimensionamento Interativo via Mouse de Painéis (Splitters) e Colunas da Tabela [FEAT-UI-04]

- **Prioridade:** Média / Alta (Ergonomia Visual & Customização do Espaço de Trabalho)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda de Usabilidade (Dario — detectada durante acompanhamento de lote volumoso de 907 PDFs)
- **Responsável:** Prisma (Tomus UX/UI & Desktop GUI Architect)
- **Evidência no Código:** `sidebarResizer` e `tableResizer` implementados em `src/tomus/gui/web/app.js` (linhas 1483-1551) com divs correspondentes em `src/tomus/gui/web/index.html` (linhas 155, 206).

### 1. Diagnóstico e Necessidade de Interface
1. **Painéis Laterais com Larguras Fixas:**
   - Atualmente, a estrutura principal de 3 painéis (`.main-content`) utiliza um grid fixo (`230px 1fr 370px`). Em telas de diferentes resoluções (Retina, ultrawide ou notebooks compactos), o usuário não consegue expandir a árvore de taxonomia para visualizar ramos profundos, nem encolher o inspetor lateral para dar mais amplitude à tabela central.
2. **Colunas da Tabela Central com Largura Rígida:**
   - As colunas de *Título / Arquivo*, *Autor(es)* e *Grande Área / Área Básica* possuem larguras pré-determinadas em CSS com `text-overflow: ellipsis`. Em livros com múltiplos autores ou títulos acadêmicos longos com subtítulos explicativos, o usuário fica impedido de alargar a coluna diretamente pelo cabeçalho para leitura integral.

### 2. Especificação Técnica da Entrega
1. **Splitters Horizontais entre Painéis (`.panel-resizer`):**
   - Inserir divisores verticais arrastáveis com cursor `col-resize` entre:
     - **Divisor Esquerdo:** Barra Lateral (Filtros & Taxonomia) ↔ Tabela Central.
     - **Divisor Direito:** Tabela Central ↔ Inspetor de Documentos.
   - **Limites Defensivos:**
     - Barra Lateral: Mínimo 180px, Máximo 420px.
     - Inspetor: Mínimo 280px, Máximo 560px.
     - Tabela Central: Flexível (`1fr`), preservando área mínima de 400px.
2. **Redimensionadores de Coluna na Tabela (`.table-resizer`):**
   - Inserir alças arrastáveis na borda direita dos cabeçalhos (`th`):
     - Entre `TÍTULO / ARQUIVO` e `AUTOR(ES)`.
     - Entre `AUTOR(ES)` e `ANO`.
     - Entre `GRANDE ÁREA / ÁREA BÁSICA` e `TIPO`.
   - Cursor interativo `col-resize`, feedback visual de guia vertical durante o arraste e suporte a clique duplo para ajuste automático ao conteúdo (*auto-fit*).
3. **Persistência de Preferências do Usuário (`localStorage`):**
   - Gravar as larguras personalizadas dos painéis e das colunas no `localStorage` do WebView (`tomus_panel_widths` e `tomus_column_widths`), restaurando automaticamente o layout customizado nas próximas aberturas do aplicativo.

---

## ⚡ Atualização do Modelo Padrão NVIDIA NIM para Llama 3.2 90B [FEAT-LLM-02]

- **Prioridade:** Alta (Resiliência do Roteamento Multi-Provedor & Fallback Ativo)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Diagnóstico de API pós-lote de 907 PDFs
- **Responsável:** Forja (Pipeline & LLM Engine)
- **Evidência no Código:** Modelo padrão alterado para `meta/llama-3.2-90b-vision-instruct` em `src/tomus/core/llm.py` (linha 614), `src/tomus/core/config.py` (linha 324), `src/tomus/gui/bridge.py` (linha 269) e `src/tomus/gui/widgets/preferences_dialog.py` (linha 235).

### 1. Diagnóstico do Problema
O modelo anteriormente configurado no Tomus (`nvidia/llama-3.1-nemotron-70b-instruct`) foi descontinuado pela NVIDIA e retorna `404 Function Not Found` para requisições em novas contas. Isso fez com que, quando a cota gratuita do Gemini se esgotou às 11:08:08, o fallback para a NVIDIA falhasse em cadeia, enviando documentos perfeitamente saudáveis para a revisão manual.

### 2. Especificação da Correção
1. **Novo Modelo Homologado:** Alterar o identificador do modelo em `src/tomus/core/config.py` e `src/tomus/core/llm.py` de `nvidia/llama-3.1-nemotron-70b-instruct` para **`meta/llama-3.2-90b-vision-instruct`**.
2. **Atualização da Chave:** Atualizar a chave validada `nvapi-OG0t...` em `~/.config/tomus/config.toml`.
3. **Validação de Teste Real:** Teste de inferência real executado com sucesso retornando classificação taxonômica precisa (Freud, *Luto e Melancolia* classificado em Psicologia/Psicanálise com 95% de confiança).

---

## 🗑️ Remoção do Provedor "GitHub Models (gpt-4o)" da Interface e Preferências [FEAT-LLM-03]

- **Prioridade:** Imediata / Alta (Sprint v1.2.0 - Limpeza de Interface)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda de Produto (Dario — remoção de modelo desnecessário do menu de provedores)
- **Responsáveis:** Prisma (UX/UI & Dropdown Web) & Forja (Config & Backend)
- **Evidência no Código:** Nenhuma referência a `github`/`gpt-4o` encontrada em `src/tomus/`; provedor removido de dropdowns, preferências e bridge.

### 1. Diagnóstico e Decisão de Produto
O seletor de modelos da barra superior do Tomus exibia a opção `GitHub Models (gpt-4o)`. Conforme decisão da Direção, esse provedor deve ser removido da interface gráfica, simplificando a esteira para os provedores de alta capacidade e gratuidade voltados ao uso acadêmico (Gemini, Groq, NVIDIA, DeepSeek, Claude).

### 2. Escopo da Remoção
1. **Dropdown Principal (`src/tomus/gui/web/index.html`):**
   - Remover `<option value="github">GitHub Models (gpt-4o)</option>`.
2. **Componentes Desktop Nativos:**
   - Remover `("github", "GitHub Models")` de `src/tomus/gui/widgets/toolbar.py`.
   - Remover campo de token do GitHub de `src/tomus/gui/widgets/preferences_dialog.py`.
3. **Bridge e Fallbacks:**
   - Remover `"github": "gpt-4o"` do mapeamento padrão em `src/tomus/gui/bridge.py`.

---

## ⚡ Homologação e Priorização do Groq (Llama 3.3 70B Versatile) na Cadeia de Fallback [FEAT-LLM-04]

- **Prioridade:** Alta (Resiliência de Cota Gratuita & Velocidade de Inferência LPU)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Análise estratégica de limites de API (`console.groq.com/settings/limits`)
- **Responsáveis:** Forja (Core/Pipeline/LLM) & Prisma (Preferências GUI)
- **Evidência no Código:** `fallback_chain = ["groq", "nvidia", "claude", "deepseek"]` em `src/tomus/core/config.py` (linha 312) e `src/tomus/gui/widgets/preferences_dialog.py` (linha 681).

### 1. Diagnóstico e Vantagens Técnicas
O provedor Groq oferece uma das maiores capacidades operacionais gratuitas do mercado para o modelo denso de 70 bilhões de parâmetros (`llama-3.3-70b-versatile`):
- **Cota Diária Gratuita:** 1.000 requisições por dia (RPD), permitindo organizar acervos volumosos (como o lote de 907 PDFs) em uma única corrida sem interrupção.
- **Taxa por Minuto:** 30 requisições por minuto (RPM) — o dobro do limite do Gemini gratuito (15 RPM).
- **Tempo de Resposta dos Chips LPU:** Inferência entre 1 e 2 segundos por PDF com JSON estrito validado.
- **Janela de Contexto:** 128.000 tokens (cobre sumários e metadados densos sem truncamento).

### 2. Escopo de Implementação
1. **Cadeia Padrão de Fallback:**
   - Posicionar a Groq como primeiro fallback imediato caso a cota do Gemini oscile: `fallback_chain = ["groq", "nvidia", "deepseek"]`.
2. **Integração no Pool Multi-Chaves (`[FEAT-POOL-01]`):**
   - Suporte ao cadastro de múltiplas chaves Groq (`groq_api_keys`) nas Preferências, com rotação automática em caso de 429.
3. **Health Check Ativo:**
   - Teste de 1 token ao salvar a chave da Groq em Preferências via endpoint compatível OpenAI (`https://api.groq.com/openai/v1/chat/completions`).

---

## 🧠 Homologação do Anthropic Claude (Claude Haiku 5.5) e Suporte a Blocos de Resposta [FEAT-LLM-05]

- **Prioridade:** Alta (Homologação de Provedor Pago de Alta Precisão)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Integração de chave paga da Anthropic (`sk-ant-usr-...`)
- **Responsáveis:** Forja (Pipeline/LLM) & Prisma (Preferências GUI)
- **Evidência no Código:** Claude na `fallback_chain` (`src/tomus/core/config.py` linha 312) e suporte a blocos `thinking`/`text` no `ClaudeProvider` (`src/tomus/core/llm.py`).

### 1. Diagnóstico e Validação em Tempo Real
- A chave gerada e configurada pelo usuário foi testada com sucesso diretamente na API da Anthropic (`https://api.anthropic.com/v1/messages`).
- O modelo topo de linha atual homologado é o **`claude-haiku-5-5`**, que demonstrou altíssima acurácia taxonômica (classificando *Luto e Melancolia* em Psicologia > Psicanálise > Teoria Psicanalítica com 90% de confiança em menos de 2 segundos).
- **Ajuste Técnico no Parser de Resposta (`ClaudeProvider`):** Os modelos da geração Claude 5 emitem blocos estruturados contendo `thinking` e `text`. O método `_call_claude` em `src/tomus/core/llm.py` deve extrair o bloco cujo `type == 'text'`, evitando a exceção `KeyError: 'text'` ao acessar cegamente `content[0]`.

### 2. Escopo de Entrega
1. Configuração do modelo padrão Anthropic para `claude-haiku-5-5` em `config.py` e `llm.py`.
2. Extração resiliente de blocos textuais (`[b['text'] for b in data['content'] if b.get('type') == 'text']`).
3. Gravação da chave validada no `~/.config/tomus/config.toml` (`claude_api_key`).
4. Adição do Claude na lista de provedores ativos e na cadeia de fallback.

---

## 📝 Companion Markdown em Revisão Manual, Edição Guiada na GUI e Materialização Seletiva [FEAT-TRIAGE-01]

- **Prioridade:** Alta (Ergonomia de Triagem, Preservação de Metadados & Ciclo Completo de Acervo)
- **Status:** Planejado (Backlog)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda Estratégica de Produto (Dario — concebida após análise dos arquivos não classificados)
- **Responsáveis:** Forja (Core/Pipeline/Storage) & Prisma (UX/UI & Triagem na GUI)

### 1. Requisitos de Entrega e Fluxo de Trabalho

1. **Geração Incondicional do Arquivo Companheiro (`.md`):**
   - Mesmo quando um documento for direcionado para `revisao_manual/`, o Tomus deve gerar imediatamente o arquivo `.md` correspondente ao lado do PDF (`revisao_manual/<nome_original>.md`).
   - O arquivo conterá os metadados preliminares já resgatados pelo sistema (título sugerido pelo PyMuPDF, autor prévio, ISBN se houver, amostra de texto e motivo explícito da ida para revisão manual).

2. **Edição Manual de Metadados na Interface Gráfica:**
   - Ao final da classificação do lote (ou filtrando por "Revisão Manual"), o usuário poderá inspecionar cada item no painel lateral e editar diretamente os campos:
     - Título e Subtítulo
     - Autores
     - Ano
     - Grande Área, Área Básica, Subárea e Especialidade (via dropdowns sincronizados com o catálogo CAPES/CNPq)
     - Tipo Documental (Livro, Artigo, Tese, etc.)

3. **Rastreabilidade no Front Matter YAML do Companion:**
   - Gravar explicitamente no front matter do arquivo `.md` um bloco de auditoria de revisão manual indicando quais campos foram alterados pelo usuário:
     ```yaml
     revisao_manual:
       editado_manualmente: true
       revisado_em: "2026-11-11T16:00:00Z"
       campos_alterados:
         - "area_basica"
         - "subarea"
         - "ano"
         - "authors"
     ```

4. **Materialização Seletiva na Árvore:**
   - Ao concluir as edições, fornecer o botão de ação **"Organizar Itens Revisados na Árvore"**:
     - **Itens Elegíveis:** Documentos que receberam área básica, subárea e metadados mínimos suficientes são movidos automaticamente de `revisao_manual/` para sua pasta definitiva `/Destino/<area_basica>/<subarea>/<tipo>/`, renomeados para o padrão canônico (`Autor - Título - Ano.pdf`), junto com seu companion `.md` atualizado, e integrados ao `manifest.json`.
     - **Itens Incompletos:** Documentos que não possuem informações suficientes permanecem com segurança em `revisao_manual/`.

5. **Relatório de Desfecho da Triagem:**
   - Ao término do processo de materialização, exibir modal/notificação detalhando:
     - *"X documentos foram promovidos e organizados na árvore temática com sucesso."*
     - *"Y documentos continuam na pasta de Revisão Manual por informações pendentes."*

---

## ⚙️ Refinamentos da Tela de Preferências e Gestão de Chaves (Sprint v1.2.1+)

### [BUG-PREF-01] Menu de Contexto e Semântica de Janela nas Preferências
- **Prioridade:** Média (Ergonomia e Padrão macOS)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario)
- **Responsáveis:** Prisma (UX/UI) & Atlas (Foundation)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`
- **Evidência no Código:** `Qt.WindowType.Dialog` usado em `src/tomus/gui/widgets/preferences_dialog.py` (linha 545) e `setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)` nos campos de texto (linhas 719, 923, 1068, 1115, 1226, 1232).
- **Descrição:**
  1. Revisar o menu de contexto na tela de Preferências: assegurar que os campos de texto (`QLineEdit`) tenham acesso ao menu nativo de edição do sistema (*Copiar*, *Colar*, *Recortar*, *Selecionar Tudo*), enquanto o fundo do diálogo não exiba menus desnecessários.
  2. Ajustar as flags de janela no macOS (`Qt.WindowType.Dialog` ou `Qt.WindowType.Sheet`), desabilitando o botão verde de maximização/zoom indevido em caixas de diálogo de ajustes e fixando dimensões adequadas ao design.

---

### [FEAT-AUTH-03] Verificação Ativa de Status da Chave de API antes de Considerá-la Ativa
- **Prioridade:** Alta (Confiabilidade e Prevenção de Falhas em Lote)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario)
- **Responsáveis:** Atlas (Foundation/Bridge) & Forja (Core/LLM)
- **Escopo:** `src/tomus/gui/bridge.py`, `src/tomus/gui/web/app.js`, `src/tomus/gui/widgets/preferences_dialog.py`
- **Evidência no Código:** `validate_provider_key_live` importado e chamado em `src/tomus/gui/widgets/preferences_dialog.py` (linhas 50, 442, 806, 973) com feedback de erro/sucesso.
- **Descrição:**
  1. Atualmente, a interface marca a chave como "Chave Ativa" apenas checando a presença da string (`bool(api_key)`), sem atestar se ela é funcional.
  2. Implementar verificação ativa de integridade (*health check ping* de 1 token) via `validateProviderKey()` antes de marcar o badge como verde.
  3. Se a chave estiver ausente, expirada, inválida (HTTP 401) ou sem créditos (HTTP 403), exibir status específico (*Chave Inválida / Não Autorizada / Sem Créditos*) com aviso visual, impedindo que o usuário inicie um lote grande acreditando que o provedor está pronto.

---

### [FEAT-POOL-02] Interface Gráfica de Múltiplas Chaves por Provedor nas Preferências
- **Prioridade:** Alta (Usabilidade do Pool Multi-Chave)
- **Status:** Registrado no Backlog
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario)
- **Responsáveis:** Prisma (UX/UI) & Forja (Core)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`
- **Descrição:**
  1. O motor central (`tomus.core`) já possui suporte a listas de chaves com rotação round-robin em HTTP 429 (`FEAT-POOL-01`). No entanto, o diálogo de Preferências atual só possui um campo simples de texto por provedor.
  2. Criar componente de UI que permita cadastrar, visualizar e remover múltiplas chaves para cada provedor (ex.: lista dinâmica com botão `+ Adicionar Chave` ou campo multi-linhas expansível).
  3. Exibir o status individual de cada chave cadastrada no pool (Ativa, Esgotada/Cooldown ou Inválida).

---

### [FEAT-PREF-02] Ordenação Visual e Reordenável da Cadeia de Fallback
- **Prioridade:** Média (Clareza Operacional)
- **Status:** Concluído / Resolvido (v1.3.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario — "Aqui não mostra, efetivamente uma ordem")
- **Responsáveis:** Prisma (UX/UI)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`
- **Evidência no Código:** `fallback_list` (`QListView` com `FallbackItemDelegate`) implementado em `src/tomus/gui/widgets/preferences_dialog.py` (linhas 1110-1116, 1167, 1195, 1201, 1204, 1210, 1282) com botões de reordenação ▲/▼.
- **Descrição:**
  1. Na aba "Provedores LLM & Fallback", a seção de fallback atualmente apresenta apenas checkboxes horizontais simples (`[x] groq  [x] nvidia  [x] deepseek`), o que não explicita a ordem nem permite ao usuário personalizar a hierarquia.
  2. Substituir por uma lista vertical numerada clara:
     - `1º Fallback: Groq (llama-3.3-70b-versatile)`
     - `2º Fallback: NVIDIA NIM (llama-3.2-90b)`
     - `3º Fallback: Anthropic Claude (claude-haiku-5.5)`
     - `4º Fallback: DeepSeek (deepseek-flash)`
  3. Disponibilizar controles de reordenação (botões ▲ / ▼ ou drag-and-drop) para que o usuário defina explicitamente qual provedor assume a esteira em caso de contingência.

---

### [FEAT-PREF-03] Restaurar Configurações Padrão do Aplicativo (Reset to Defaults)
- **Prioridade:** Média (Recuperação de Erros e Ergonomia)
- **Status:** Concluído / Resolvido (v1.2.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario)
- **Responsáveis:** Prisma (UX/UI) & Forja (Core/Config)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`, `src/tomus/core/config.py`
- **Descrição:**
  1. Adicionado botão "Restaurar Padrões" no rodapé à esquerda do diálogo de Preferências.
  2. Ao clicar, exibe confirmação modal via `QMessageBox.question` advertindo que as configurações de modelos, fallbacks e pipeline serão redefinidas para os valores padrão de fábrica.
  3. Ao confirmar, preserva integralmente as chaves de API cadastradas, restaurando apenas os modelos oficiais (`gemini-3.5-flash`), a cadeia de fallback padrão (`groq -> nvidia -> claude -> deepseek`), o limiar de confiança (0.70) e o uso do cache local SQLite. Coberto por teste automatizado `test_preferences_dialog_restore_defaults_preserves_keys`.

---

### [FEAT-POOL-02] Interface Gráfica de Múltiplas Chaves por Provedor nas Preferências
- **Prioridade:** Alta (Resiliência de Cota, Zero Custos em Lotes Grandes & Alta Disponibilidade)
- **Status:** Concluído / Resolvido (v1.2.0)
- **Data do Registro:** 2026-11-11
- **Origem:** Demanda Estratégica de Produto (Dario)
- **Responsáveis:** Forja (Core/Config/LLM Dispatcher) & Prisma (UX/UI Modal de Preferências)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`, `src/tomus/core/llm.py`
- **Descrição:**
  1. O diálogo de Preferências suporta cadastro de múltiplas chaves por provedor separadas por vírgula no campo de credenciais.
  2. Validação sintática individual para cada chave do pool.
  3. Feedback visual em tempo real indicando a quantidade de chaves ativas (ex.: `✓ 2 chaves no Pool`).
  4. O despachante `_resolve_api_key` aceita listas ou strings delimitadas por vírgula. Coberto por testes automatizados em `test_gui_components.py`.

---

### [FEAT-CLIPBOARD-02] Suporte Robusto a Cópia de Citação ABNT com Formatação (Rich Text e Markdown)
- **Prioridade:** Média / Alta (Produtividade Acadêmica e Fidelidade ABNT)
- **Status:** Concluído / Resolvido (v1.2.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario — Confirmação em 12/11 de que a cópia já preserva o negrito no Word e asteriscos no Markdown)
- **Responsáveis:** Prisma (UX/UI) & Atlas (Foundation)
- **Escopo:** `src/tomus/gui/web/app.js`, `src/tomus/gui/bridge.py`
- **Descrição:**
  1. A injeção na área de transferência alimenta simultaneamente o canal `text/html` (com tag `<strong>` para Word, Docs, Pages) e o canal `text/plain` (com `**Título**` para Markdown, Obsidian, Notion).
  2. Evita completamente o instanciamento perigoso de `QMimeData` em Python para afastar qualquer crash do coletor de lixo C++/PySide6 (`QMimeDataWrapper::~QMimeDataWrapper()`).

---

### [FEAT-UX-02] Tradução Amigável de Erros de LLM e Rede na Revisão Manual
- **Prioridade:** Média (Clareza e Anti-AI-Slop na Interface)
- **Status:** Concluído / Resolvido (v1.2.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Feedback de Uso (Dario — Exibição de mensagens brutas de erro HTTP no card de triagem)
- **Responsáveis:** Prisma (UX/UI) & Forja (Core/LLM)
- **Escopo:** `src/tomus/core/llm.py`, `src/tomus/gui/web/app.js`
- **Descrição:**
  1. Implementada a função `humanize_error_message` em `src/tomus/core/llm.py` e sanitização inteligente `formatTriageError` em `src/tomus/gui/web/app.js`.
  2. Erros técnicos crus (HTTP 401, 429, 503, 504, timeout) são convertidos em linguagem humana, compreensível e orientada à ação:
     - **HTTP 401:** *"Chave de API não autorizada ou expirada no provedor {nome}. Por favor, verifique suas credenciais na tela de Preferências."*
     - **HTTP 429:** *"Cota de requisições por minuto ou limite diário excedido no provedor {nome}."*
     - **HTTP 503 / 504 / 529:** *"Instabilidade temporária nos servidores no provedor {nome}. Tente novamente mais tarde."*
     - **Timeout:** *"Tempo limite de resposta esgotado ao consultar o provedor {nome}."*
  3. Coberto por testes automatizados em `tests/test_security.py`.

---

### [FEAT-AUTH-04] Validação Estrutural e Sintática de Chaves de API nas Preferências
- **Prioridade:** Alta (Prevenção de Erros de Configuração)
- **Status:** Concluído / Resolvido (v1.2.0)
- **Data do Registro:** 2026-11-12
- **Origem:** Constatação técnica (chave DeepSeek gravada como UUID em vez de iniciar com `sk-`)
- **Responsáveis:** Atlas (Foundation) & Prisma (UX/UI)
- **Escopo:** `src/tomus/gui/widgets/preferences_dialog.py`
- **Descrição:**
  1. Validação regex em tempo real no evento de digitação/colagem de chaves:
     - **DeepSeek:** deve iniciar com `sk-` e ter no mínimo 20 caracteres (bloqueia UUIDs avulsos).
     - **Groq:** deve iniciar com `gsk_`.
     - **NVIDIA NIM:** deve iniciar com `nvapi-`.
     - **Anthropic Claude:** deve iniciar com `sk-ant-`.
     - **Google Gemini:** formato `AIzaSy` ou chave com comprimento mínimo adequado.
  2. Alerta visual contextual com cor vermelha e mensagem orientativa quando o formato for incompatível. Coberto por testes automatizados em `tests/test_gui_components.py`.

---

## 🔴 Próximos Itens Abertos (v1.3.1+)

### [FEAT-AUDIT-01] Auditoria e Saneamento Automático de Biblioteca Organizada

- **Prioridade:** Alta (Manutenção de Acervo & Qualidade de Dados)
- **Status:** Aberto (Backlog)
- **Data do Registro:** 2026-11-16
- **Origem:** Pós-release v1.3.0 (Chefe / Sentinela)
- **Responsáveis:** Sentinela (AppSec & Quality) & Forja (Core/Pipeline)
- **Escopo:** `src/tomus/storage/organizer.py`, `src/tomus/storage/companion.py`, `src/tomus/gui/bridge.py`
- **Descrição:** Analisar biblioteca já organizada em busca de PDFs sem companion .md válido (cópias em subpastas ou órfãos/corrompidos), mover pendências para pasta de trabalho de origem e submeter a classificação, ou informar que está tudo íntegro.

### [FEAT-ENRICH-01] Suporte Opcional a openalex_api_key (OpenAlex)

- **Prioridade:** Média (Enriquecimento Bibliográfico & Redução de Custo)
- **Status:** Aberto (Backlog)
- **Data do Registro:** 2026-11-18
- **Origem:** Pós-release v1.3.1 (Chefe / Sentinela / Lince)
- **Responsáveis:** Lince (Extractors) & Atlas (Foundation)
- **Escopo:** `src/tomus/extractors/`, `src/tomus/core/config.py`, `src/tomus/gui/widgets/preferences_dialog.py`, `docs/ALINHAMENTO_EQUIPES.md`
- **Descrição:** Substituir/complementar o endpoint `mailto` legado (aposentado pela OpenAlex) por autenticação opcional via `openalex_api_key`. O DOI custa zero (consulta pública gratuita); a busca por título compartilha cota de 0,10 USD/dia por IP. O Stage 3 de enriquecimento deve ser protegido em `try/except` para falha graciosa sem interromper o pipeline. Não obrigatório para a v1.3.1.

### Visão v2.0.0+

#### [LIB-01] Modo Gerenciar Biblioteca Existente

- **Prioridade:** Média (Visão de Longo Prazo v2.0.0)
- **Status:** Aberto (Visão)
- **Responsáveis:** Atlas (Foundation) & Lince (Extractors)
- **Descrição:** Varredura e indexação de .md já organizados.

#### [LIB-02] Ciclo de Leitura no Front Matter

- **Prioridade:** Média (Visão de Longo Prazo v2.0.0)
- **Status:** Aberto (Visão)
- **Responsáveis:** Prisma (UX/UI) & Forja (Core/Pipeline)
- **Descrição:** status_leitura: a_ler | lendo | lido.

#### [LIB-03] Fichamento Acadêmico e Exportador

- **Prioridade:** Média (Visão de Longo Prazo v2.0.0)
- **Status:** Aberto (Visão)
- **Responsáveis:** Atlas (Foundation) & Prisma (UX/UI)
- **Descrição:** Templates e exportação de referências.
