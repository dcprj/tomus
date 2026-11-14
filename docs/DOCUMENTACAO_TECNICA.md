# Documentação Técnica e Arquitetura do Tomus

> **Versão da Especificação:** 1.2.0  
> **Status:** Ativa / Homologada  
> **Autores:** Dario Pinheiro (Arquiteto-Chefe & Mantenedor) e Equipe de Engenharia Tomus  
> **Licença:** Código Aberto sob [MIT License](https://github.com/dcprj/tomus/blob/main/LICENSE)  
> **Público-Alvo:** Engenheiros de software, arquitetos de sistemas, pesquisadores e desenvolvedores interessados no funcionamento interno, segurança, algoritmos e extensibilidade da bancada.

---

## 1. Visão Geral e Filosofia Arquitetural

O **Tomus** é uma aplicação desktop de alta fidelidade desenvolvida primordialmente para macOS (com suporte arquitetural multiplataforma em camadas desacopladas), concebida para sanar o problema da entropia documental em acervos científicos e acadêmicos.

A grande maioria dos pesquisadores, professores e instituições acumula centenas ou milhares de arquivos em formato PDF com denominações crípticas (e.g., `download (1).pdf`, `artigo_final_v3.pdf`, `1-s2.0-S0140673620301835-main.pdf`), espalhados em pastas sem hierarquia ontológica.

O Tomus atua como uma esteira autônoma e determinística de engenharia da informação, combinando:
1. **Extração de Texto Híbrida e Local:** Camada textual embutida (PyMuPDF / pdfplumber) aliada ao reconhecimento óptico de caracteres acelerado por hardware no macOS (*Apple Vision Framework* via Neural Engine) e fallback OCR baseado em layout.
2. **Identificadores Persistentes da Ciência:** Resolução exata de metadados via regex e APIs REST de identificadores globais (DOI via CrossRef e ISBN-10/ISBN-13 com validação de checksum via Google Books API).
3. **Classificação Ontológica Oficial:** Mapeamento em 4 níveis da tabela de áreas do conhecimento **CAPES/CNPq** (*Grande Área › Área Básica › Subárea › Especialidade*).
4. **Inteligência Artificial Local-First (BYOK):** Inferência semântica com múltiplos provedores em nuvem via TLS direto (*Bring Your Own Key*), operando com pool rotativo multi-chave, circuit breaker para erro 429 (*Too Many Requests*) e cascata automática de fallback.
5. **Renomeação Determinística e Fichamento Canônico:** Padronização nominal rigorosa de arquivos no sistema de arquivos (`SOBRENOME_ANO_TITULO.pdf`) e geração de citação bibliográfica formatada segundo a **ABNT NBR 6023**.

### 1.1 Princípios Fundamentais de Engenharia

```mermaid
flowchart TD
    subgraph Principios ["Princípios Inegociáveis do Tomus"]
        P1["Soberania de Dados & Zero-Telemetry<br>Arquivos PDF jamais sobem para a nuvem"]
        P2["Arquitetura Local-First (BYOK)<br>Comunicação direta cliente-provedor sem proxies"]
        P3["Determinismo & Idempotência<br>Mesmo arquivo gera o mesmo destino e citação"]
        P4["Segurança de I/O em Sistema de Arquivos<br>Caminhos validados contra Path Traversal e colisão"]
        P5["Experiência Visual Nativa e Fluida<br>PySide6 + QWebEngineView a 60fps sem AI-slop"]
    end
```

* **Soberania Absoluta e Privacidade:** Nenhum arquivo PDF, imagem ou conteúdo integral de documento é transmitido para servidores proprietários ou intermediários. O Tomus não possui servidores de backend próprios, bancos de dados em nuvem, nem sistemas de telemetria analítica.
* **Envio Mínimo e Estrito de Metadados:** Quando a inteligência artificial é acionada, apenas uma amostra sintética textual das primeiras páginas (suficiente para capturar título, folha de rosto, cabeçalho, autoria e resumo) é formatada e enviada via TLS diretamente aos endpoints oficiais dos provedores contratados pelo próprio usuário.
* **Idempotência e Cache Criptográfico:** Cada bloco de texto extraído é indexado localmente por seu hash SHA-256 em banco SQLite local (`~/.cache/tomus/cache.db`). A re-execução sobre acervos previamente processados opera com custo zero e latência milimétrica.

---

## 2. Stack Tecnológica e Decisões de Engenharia

O projeto adota uma stack moderna, minimalista e pragmática, priorizando robustez, velocidade de execução e baixo consumo de recursos no macOS.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Camada de Apresentação (GUI)                    │
│   PySide6 (Qt 6.8+) │ QWebEngineView (Chromium) │ QWebChannel (IPC)    │
│   HTML5 Semântico │ CSS Moderno (Design Tokens) │ Vanilla JavaScript  │
├────────────────────────────────────────────────────────────────────────┤
│                     Camada de Orquestração & CLI                       │
│        Click 8.1+ │ Rich 13.0+ │ Threads de Trabalho Qt (QThread)      │
├────────────────────────────────────────────────────────────────────────┤
│                       Camada do Motor Central (Core)                   │
│   Pipeline Reativo │ Pydantic v2 (Schemas) │ SQLite (Cache & Hash)    │
│   Pool Multi-Chave & Circuit Breaker │ Rotação Automática de Fallback │
├────────────────────────────────────────────────────────────────────────┤
│                 Camada de Extração Textual & Visão                     │
│   PyMuPDF (fitz) │ pdfplumber │ Apple Vision Framework (PyObjC)        │
│   Docling / RapidOCR Fallback │ Identificadores (DOI / ISBN / CrossRef)│
├────────────────────────────────────────────────────────────────────────┤
│                  Camada de Armazenamento e Sistema Operacional         │
│   pathlib │ shutil (Atomic I/O) │ macOS Finder Bridge (open / reveal)  │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Detalhamento dos Componentes e Bibliotecas

| Componente | Tecnologia / Biblioteca | Função no Sistema | Justificativa da Decisão Técnica |
| :--- | :--- | :--- | :--- |
| **Linguagem & Runtime** | Python 3.12+ (CPython) | Núcleo de execução do software | Suporte a tipos genéricos modernos (`X \| Y`), alta performance e compatibilidade perfeita com ecossistema de dados. |
| **Framework Gráfico** | `PySide6` (Qt for Python 6.8+) | Shell desktop nativo do macOS | Fornece ciclo de vida de aplicação nativa macOS, menus globais, integração com `QThread`, atalhos de teclado e janelas nativas. |
| **Renderizador Web** | `PySide6.QtWebEngineWidgets` | Visualização da bancada interativa | Permite interface com alta densidade de informação, aceleração gráfica via GPU, CSS Grid/Flexbox e tipografia avançada sem bugs de layout. |
| **Ponte IPC (Qt-JS)** | `PySide6.QtWebChannel` | Canal de transporte seguro entre Python e Web | Comunicação assíncrona bidirecional tipada via JSON, eliminando servidores HTTP locais (`localhost`) e eliminando vetores de ataque CSRF. |
| **Validação de Dados** | `pydantic` (v2.10+) | Modelagem estrita de metadados e schemas LLM | Validação de alta velocidade escrita em Rust, serialização segura e sanitização de respostas de modelos de linguagem. |
| **Extração de PDF** | `PyMuPDF` (`fitz` 1.25+) | Parser de documento, texto vetorial e imagens | A mais rápida biblioteca de processamento de PDFs para Python; processa centenas de páginas por segundo sem vazamento de memória. |
| **Extração Complementar**| `pdfplumber` (0.11+) | Análise de layout estruturado e tabelas | Auxilia na extração de texto quando blocos vetoriais necessitam de inspeção geométrica de caixas delimitadoras (*bounding boxes*). |
| **OCR Nativo no macOS**| Apple Vision (`VNRecognizeTextRequest`) via `pyobjc` | OCR local em PDFs escaneados | 3 a 5 vezes mais rápido que o Tesseract; utiliza a Neural Engine dos chips Apple Silicon (M1/M2/M3/M4) com zero binários externos. |
| **Cliente HTTP / APIs**| `httpx` (0.28+) com HTTP/2 e TLS 1.3 | Comunicação com provedores de IA e metadados | Suporte nativo a chamadas síncronas e assíncronas, pools de conexão e controle fino de timeouts para evitar travamentos de rede. |
| **Persistência de Cache**| `sqlite3` (embutido na stdlib) | Cache local de extração e classificação | Banco relacional serverless, ACID, sem dependências externas, garantindo recuperação instantânea de sessões e integridade de dados. |
| **CLI & Terminal** | `click` (8.1+) + `rich` (13.9+) | Interface de linha de comando para automação | Permite execução headless em servidores, pipelines de laboratório e automações via shell script com logs coloridos. |
| **Empacotamento macOS**| `pyinstaller` (6.11+) + `create-dmg` | Geração de `.app` e imagem de disco `.dmg` | Gera executável autocontido para macOS com assinatura de código e arquitetura universal. |

---

## 3. Arquitetura de Camadas e Módulos do Sistema

O código-fonte do Tomus é estruturado sob o pacote principal `tomus`, com estrita separação de responsabilidades:

```
src/tomus/
├── cli/                 # Interface de Linha de Comando (CLI)
│   ├── main.py          # Ponto de entrada Click e subcomandos (run, config, cache)
│   └── presenter.py     # Renderização visual no terminal com Rich (tabelas, progresso)
├── core/                # Motor de Negócio e Engenharia (agnóstico de interface)
│   ├── config.py        # Configuração Pydantic (TOML, pool de chaves, fallbacks)
│   ├── llm.py           # Provedores de IA (Gemini, Groq, NVIDIA, DeepSeek, Claude)
│   ├── models.py        # Schemas Pydantic (ClassificationResult, DocumentEntry)
│   ├── namer.py         # Algoritmos de higienização de nomes e ABNT NBR 6023
│   ├── pipeline.py      # Orquestrador da esteira de processamento por documento
│   ├── prompts.py       # Engenharia de prompts com injeção estruturada da taxonomia
│   ├── taxonomy.py      # Árvore oficial CAPES/CNPq de 4 níveis e normalização
│   └── cache.py         # Cache de extração e classificação em SQLite
├── extractors/          # Motores de Ingestão de Conteúdo e Visão
│   ├── text_extractor.py# Extração vetorial inteligente via PyMuPDF e pdfplumber
│   ├── apple_vision.py  # OCR nativo macOS acelerado pela Neural Engine
│   ├── ocr_docling.py   # OCR e parser de layout avançado com fallback gracioso
│   └── identifiers.py   # Varredura e resolução de DOI (CrossRef) e ISBN (Google Books)
├── storage/             # Operações de Disco, Integridade e Companions
│   ├── organizer.py     # Execução de cópia/movimentação atômica e resolução de colisões
│   └── companion.py     # Geração de arquivos de metadados (.tomus.json e .bib)
└── gui/                 # Interface Gráfica Desktop
    ├── app.py           # Ponto de entrada PySide6 e inicialização do loop de eventos
    ├── main_window.py   # Janela principal QMainWindow contendo QWebEngineView
    ├── bridge.py        # Ponte QWebChannel (Slots e Signals expostos ao JavaScript)
    ├── worker.py        # QThread de processamento assíncrono em segundo plano
    ├── widgets/         # Componentes auxiliares (Preferências, Cache, Toolbar nativa)
    └── web/             # Aplicação Web Frontend desacoplada
        ├── index.html   # Estrutura semântica da bancada de trabalho
        ├── style.css    # Design System Tomus (Tokens CSS, tema refinado)
        └── app.js       # Estado reativo e renderização em Vanilla JS
```

---

## 4. O Pipeline de Processamento (Esteira de Documentos)

A esteira de catalogação é o coração funcional do Tomus. Cada arquivo PDF passa por um fluxo sequencial e defensivo, garantindo que mesmo documentos corrompidos ou malformatados sejam tratados graciosamente sem travar a aplicação.

```mermaid
sequenceDiagram
    autonumber
    actor Usuario as Usuário / GUI
    participant Worker as Worker Thread (Qt)
    participant Pipe as Pipeline Orchestrator
    participant Extract as Extrator Textual & OCR
    participant ID as Identifiers Engine (DOI/ISBN)
    participant Cache as Cache SQLite (SHA-256)
    participant LLM as Motor LLM (Pool & Fallback)
    participant Org as Organizer & Storage

    Usuario->>Worker: Iniciar Lote (Origem, Destino, Modo, Provedor)
    Worker->>Pipe: Processar Documento(pdf_path)
    
    Pipe->>Extract: Extrair Texto Vetorial (Primeiras Páginas)
    alt PDF tem camada de texto legível
        Extract-->>Pipe: Amostra Textual Obtida
    else PDF é Imagem Escaneada
        Extract->>Extract: Executar Apple Vision OCR (Hardware Nativo)
        Extract-->>Pipe: Texto Recuperado via OCR
    end

    Pipe->>ID: Buscar Identificadores (Regex DOI e ISBN)
    opt DOI Encontrado
        ID->>ID: Consulta CrossRef API
        ID-->>Pipe: Metadados Oficiais do Artigo
    end
    opt ISBN Encontrado
        ID->>ID: Validação Checksum & Google Books API
        ID-->>Pipe: Metadados Oficiais do Livro
    end

    Pipe->>Cache: Consultar Hash SHA-256(Texto)
    alt Resultado em Cache
        Cache-->>Pipe: ClassificationResult Reutilizado
    else Não está em Cache
        Pipe->>LLM: Classificar Amostra (Prompt + Taxonomia CAPES)
        LLM-->>Pipe: ClassificationResult (Validado via Pydantic)
        Pipe->>Cache: Persistir Resultado
    end

    Pipe->>Org: Executar Ação de Disco (Copiar ou Mover)
    Org->>Org: Criar Diretórios CAPES (Grande Área / Área Básica / Subárea)
    Org->>Org: Sanitizar Nome (AUTOR_ANO_TITULO.pdf)
    Org->>Org: Escrever Arquivo Companion (.tomus.json)
    Org-->>Pipe: DocumentEntry Finalizado
    
    Pipe-->>Worker: Emitir Evento item_processed
    Worker-->>Usuario: Atualizar Tabela, Contadores e Árvore na GUI
```

---

## 5. Engenharia da Taxonomia CAPES/CNPq

O Tomus adota formalmente a **Tabela de Áreas do Conhecimento da Coordenação de Aperfeiçoamento de Pessoal de Nível Superior (CAPES)** e do **Conselho Nacional de Desenvolvimento Científico e Tecnológico (CNPq)**.

### 5.1 A Árvore de 4 Níveis

A hierarquia taxonômica implementada em `tomus.core.taxonomy` estrutura os saberes humanos em quatro camadas:
1. **Grande Área:** As 8 grandes divisões do saber (e.g., *Ciências Exatas e da Terra*, *Ciências Humanas*, *Linguística, Letras e Artes*, *Engenharias*).
2. **Área Básica:** O ramo principal do conhecimento (e.g., *Filosofia*, *Educação*, *Ciência da Computação*, *Medicina*).
3. **Subárea:** A ramificação especializada da área básica (e.g., *Epistemologia*, *História da Filosofia*, *Metodologia e Técnicas da Computação*).
4. **Especialidade:** O recorte de pesquisa específico (e.g., *Ética*, *Lógica Matemática*, *Sistemas Operacionais*).

### 5.2 Algoritmo de Higienização de Caminhos de Diretório

Para que os nomes das pastas criadas no sistema de arquivos sejam compatíveis entre macOS, Linux e Windows (e evitem falhas com caracteres reservados), a função `normalize_area_name` executa a seguinte sequência:
1. Decomposição Unicode NFKD e remoção de marcas diacríticas (acentos e cedilhas) apenas para nomes de diretórios de sistema de arquivos quando exigido por portabilidade estrita, mantendo a grafia correta em português nos metadados.
2. Substituição de barras `/` e contrabarras `\` por hifens espelhados para não quebrar a árvore de pastas.
3. Remoção de caracteres de pontuação ilegais no POSIX e Windows (`:`, `*`, `?`, `"`, `<`, `>`, `|`).
4. Colapso de múltiplos espaços em branco em um único espaço e aparamento de bordas (*trim*).

---

## 6. Motor de IA: Pool Multi-Chaves, Rotação e Cascata de Fallback

A classificação semântica e a extração bibliográfica dependem de Grandes Modelos de Linguagem (LLMs). Como as cotas gratuitas ou pagas podem sofrer limites estritos de taxa (*Rate Limits* como `429 Too Many Requests`), o Tomus implementa uma infraestrutura resiliente de tolerância a falhas.

```mermaid
stateDiagram-v2
    [*] --> IniciarRequisicao
    IniciarRequisicao --> ChaveAtual: Obter chave do pool ativo
    ChaveAtual --> ChamadaAPI: Executar requisição TLS
    
    ChamadaAPI --> Sucesso: HTTP 200 (JSON Válido)
    Sucesso --> [*]: Retornar Metadados
    
    ChamadaAPI --> Erro429: HTTP 429 (Cota Excedida)
    Erro429 --> VerificarOutraChave: Há outra chave para o mesmo provedor?
    VerificarOutraChave --> ProximaChave: Sim (Girar round-robin)
    ProximaChave --> ChamadaAPI
    
    VerificarOutraChave --> TentarFallback: Não (Todas as chaves do provedor esgotadas)
    TentarFallback --> ProximoProvedor: Provedor na fallback_chain?
    ProximoProvedor --> ChamadaAPI: Chamar Groq / NVIDIA / Claude / DeepSeek
    
    TentarFallback --> FalhaTotal: Nenhum provedor restante
    FalhaTotal --> RevisaoManual: Marcar documento para Revisão Manual (Status manual_review)
    RevisaoManual --> [*]
```

### 6.1 Provedores Oficiais e Modelos Homologados (v1.2.0)

1. **Google Gemini (`GeminiProvider`):**
   * *Modelo Padrão:* `gemini-3.5-flash`
   * *Características:* Janela de contexto massiva, alta tolerância a textos longos e excelente acurácia em português.
2. **Groq (`GroqProvider`):**
   * *Modelo Padrão:* `llama-3.3-70b-versatile`
   * *Características:* Inferência em chips LPU ultra-rápidos (~500 tokens/s), cota gratuita generosa (1.000 requisições diárias / 30 RPM), posicionado como **1º Fallback** imediato após o Gemini.
3. **NVIDIA NIM (`NvidiaProvider`):**
   * *Modelo Padrão:* `meta/llama-3.2-90b-vision-instruct`
   * *Características:* Modelo open-weights de altíssima escala hospedado na infraestrutura de nuvem acelerada da NVIDIA.
4. **Anthropic Claude (`ClaudeProvider`):**
   * *Modelo Padrão:* `claude-haiku-5-5`
   * *Características:* Raciocínio bibliográfico impecável, suporte nativo a blocos híbridos `thinking` e `text`, excelente precisão em periódicos e teses raras.
5. **DeepSeek (`DeepSeekProvider`):**
   * *Modelo Padrão:* `deepseek-flash`
   * *Características:* Custo operacional extremamente reduzido e suporte veloz à língua portuguesa.

### 6.2 O Pool Multi-Chave com Rotação Round-Robin

Em `src/tomus/core/config.py`, cada provedor pode receber uma única chave de API em string ou uma lista de chaves (`list[str]`):

```python
class ApiKeysConfig(BaseModel):
    gemini_api_key: str | list[str] = ""
    groq_api_key: str | list[str] = ""
    nvidia_api_key: str | list[str] = ""
    deepseek_api_key: str | list[str] = ""
    claude_api_key: str | list[str] = ""
    google_books_api_key: str = ""
```

Quando um provedor dispara uma exceção HTTP `429 (Resource Exhausted / Too Many Requests)`, o método `_get_next_key()` avança atomicamente o índice circular para a próxima chave válida configurada. Se todas as chaves do provedor primário estiverem saturadas, o motor aciona o algoritmo de cascata de fallback (`fallback_chain = ["groq", "nvidia", "claude", "deepseek"]`).

---

## 7. A Norma ABNT NBR 6023 no Tomus

A formatação de referências bibliográficas do Tomus segue com exatidão a norma técnica brasileira **ABNT NBR 6023 (Informação e documentação — Referências — Elaboração)**.

### 7.1 Regras de Formatação Implementadas

* **Autores:** 
  * Sobrenome principal em letras maiúsculas (*CAIXA ALTA*), seguido pelo prenome e outros nomes (e.g., `VYGOTSKY, Lev Semenovitch`).
  * Conforme a norma, nomes de autores são apresentados em **texto normal (sem negrito)**.
* **Título de Livros / Teses / Monografias:**
  * O título da obra recebe destaque tipográfico exclusivo em **negrito puro** (`<strong>TITULO</strong>`).
  * O subtítulo (se houver, precedido por dois pontos `:`) permanece em **caracteres normais**, sem negrito.
* **Edição de Obras:**
  * Higienização contra repetições: se o modelo ou o metadado trouxer `"2ª ed."` ou `"3. ed."`, o formatador sanitiza para o padrão rigoroso: `"2. ed."` ou `"3. ed."`, eliminando a anomalia visual `"1. ed. ed."`.
* **Artigos em Periódicos Científicos:**
  * O título do artigo é apresentado em caracteres normais.
  * O **título do periódico ou revista** recebe o destaque em **negrito puro** (e.g., `Revista Brasileira de Educação`), seguido por local, volume, número, páginas inicial e final, e ano de publicação.
* **Identificadores Digitais:**
  * Se houver DOI válido, insere-se a cláusula normativa: `Disponível em: https://doi.org/... Acesso em: [data]`.

---

## 8. Segurança, Sandboxing e Integridade no macOS

Como ferramenta que opera diretamente sobre arquivos do usuário no disco rígido, o Tomus implementa salvaguardas rigorosas contra corrupção e vulnerabilidades de I/O:

1. **Prevenção de Path Traversal:**
   * A função `_is_safe_path()` valida estritamente todos os caminhos resolvidos via `Path.resolve()`, impedindo que sequências maliciosas como `../../` acessem diretórios de sistema (`/etc`, `/System`, `/usr`, `/Library`) ou pastas ocultas sensíveis (`~/.ssh`, `~/.gnupg`, `~/.aws`).
2. **Operações Atômicas de Cópia e Movimentação:**
   * Durante a cópia ou movimentação, o Tomus verifica a existência de arquivos preexistentes. Havendo colisão com conteúdo idêntico (mesmo hash SHA-256), o arquivo de origem é marcado como `duplicate` sem sobrescrever o destino.
   * Se os nomes coincidirem mas os conteúdos forem distintos, o sistema aplica resolução inteligente de colisão através do sufixo `_v2`, `_v3`... preservando ambos intactos.
3. **Desativação de Menus de Contexto do Navegador:**
   * Para evitar que comandos de navegador web convencional (*Back, Forward, Reload, View Source, Inspect*) interfiram na experiência desktop nativa, o `QWebEngineView` opera com `setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)` e listener defensivo de `contextmenu` no DOM.
4. **Isolamento de Memória IPC:**
   * A ponte `QWebChannel` restringe os métodos invocáveis aos slots explicitamente decorados com `@Slot` na classe `WebBridge`. Nenhuma execução de código arbitrário (`eval`) é permitida no lado Python a partir de eventos da interface.

---

## 9. Suíte de Testes e Garantia de Qualidade (QA)

A estabilidade da aplicação é mantida por uma suíte de testes automatizados com `pytest`, cobrindo todos os módulos vitais:

* `tests/test_multi_provider.py`: Validação de chamadas simuladas aos provedores Gemini, Groq, NVIDIA, DeepSeek e Claude, incluindo rotação de chaves e fallbacks em caso de erro 429.
* `tests/test_gui_web_bridge.py`: Validação da ponte IPC do Qt, saúde das chaves, métodos seguros de cópia para clipboard e segurança de caminhos.
* `tests/test_companion.py`: Testes de geração dos arquivos de metadados `.tomus.json` e exportação `.bib`.
* `tests/test_namer.py`: Testes exatos das regras de renomeação de arquivos e formatação ABNT NBR 6023.
* `tests/test_taxonomy_and_identifiers.py`: Testes de parsing e normalização da árvore de 4 níveis CAPES/CNPq e regexes de DOI e ISBN.
* `tests/test_pipeline_integration.py`: Teste de ponta a ponta simulando ingestão, extração, classificação e organização física em pastas temporárias.

---

## 10. Considerações Finais e Extensibilidade

O Tomus foi concebido sob princípios de baixo acoplamento. Novos provedores de IA podem ser adicionados simplesmente herdando da classe base abstrata `BaseLLMProvider` em `src/tomus/core/llm.py` e implementando o método `classify_text()`.

Da mesma forma, novos formatos de exportação bibliográfica (e.g., EndNote, RIS, CSL-JSON) podem ser integrados no módulo `src/tomus/storage/companion.py` sem qualquer impacto na interface visual ou no extrator de PDFs.
