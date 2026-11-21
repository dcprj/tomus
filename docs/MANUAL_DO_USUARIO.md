# Manual do Usuário do Tomus

> **Guia Oficial de Uso & Boas Práticas**  
> **Versão do Aplicativo:** 1.3.2  
> **Sistema Operacional:** macOS 14+ e Windows 10/11 64 bits  
> **Autor:** Dario Pinheiro e Equipe Tomus  
> **Suporte Comunitário:** [github.com/dcprj/tomus](https://github.com/dcprj/tomus)

---

## 1. Bem-vindo ao Tomus!

Seja muito bem-vindo ao **Tomus**, o seu assistente pessoal e bancada de trabalho para organização de acervos acadêmicos e científicos.

Se você é pesquisador, professor, pós-graduando, estudante universitário ou bibliotecário, certamente conhece a seguinte situação: com o passar dos meses de pesquisa, sua pasta de downloads ou seus discos rígidos acumulam centenas de arquivos em formato PDF com nomes confusos, tais como `artigo_final_revisado(2).pdf`, `download.pdf` ou códigos indecifráveis de editoras. Encontrar aquele capítulo essencial ou referenciar corretamente uma citação na ABNT consome horas preciosas que deveriam ser dedicadas à sua escrita e reflexão.

O **Tomus** foi criado exatamente para resolver essa dor, de forma automatizada, elegante e com rigor científico:

1. **Ele examina os seus PDFs:** Lê o conteúdo textual e, se o documento for um livro ou artigo antigo escaneado, utiliza o motor de OCR local do seu computador (PyMuPDF + RapidOCR/ONNXRuntime, em macOS e Windows) para transcrever o texto.
2. **Ele identifica a obra com precisão:** Localiza títulos, autores, ano de publicação, editoras ou revistas científicas.
3. **Ele organiza seu acervo por assuntos:** Agrupa seus arquivos na taxonomia oficial de áreas do conhecimento da **CAPES/CNPq** (por exemplo: *Ciências Humanas › Filosofia › Epistemologia*).
4. **Ele padroniza o nome dos arquivos:** Renomeia cada arquivo de forma clara e profissional: `Autor - Título - Ano.pdf`.
5. **Ele entrega a citação pronta:** Gera a referência bibliográfica oficial completa conforme a norma **ABNT NBR 6023**, pronta para copiar com um único clique e colar no seu editor de texto (Word, Docs, Pages ou LaTeX).
6. **Ele protege seus dados:** Seus arquivos PDF **nunca saem do seu computador**. Todo o processamento de arquivos é estritamente local e seguro.

---

## 2. Como Instalar o Tomus (macOS e Windows)

O Tomus é distribuído como instaladores nativos prontos para uso. Não é necessário instalar Python nem configurar ambientes complexos. Escolha o instalador correspondente ao seu sistema operacional.

### 2.1 Instalação no macOS

A instalação do Tomus no macOS é rápida e segue o padrão amigável da Apple:

1. **Baixe o instalador oficial:** Acesse a página do projeto ou a seção de lançamentos (*Releases*) no GitHub e baixe o arquivo `Tomus-1.3.2-macOS.dmg`.
2. **Abra o arquivo `.dmg`:** Dê um duplo clique no arquivo baixado. Uma janela se abrirá mostrando o ícone do **Tomus** ao lado da pasta **Aplicativos** (*Applications*).
3. **Arraste e solte:** Arraste o ícone do Tomus para dentro da pasta Aplicativos.
4. **Inicie o aplicativo:** Abra o seu *Launchpad* ou a pasta Aplicativos no Finder e clique no Tomus.
5. **Primeira abertura (Aviso de Segurança do macOS):**
   * Por se tratar de um aplicativo de código aberto distribuído pela comunidade acadêmica, na primeira vez em que você abri-lo o macOS pode exibir uma mensagem informando que o desenvolvedor não pôde ser verificado pelo Gatekeeper.
   * Caso isso ocorra, clique em **OK**, abra os **Ajustes do Sistema** do seu Mac, vá até a aba **Privacidade e Segurança**, role até o final da página e clique no botão **Abrir Mesmo Assim**. Esta etapa só precisa ser feita uma única vez.

### 2.2 Instalação no Windows

O instalador para Windows (`Tomus_Setup_v1.3.2_Windows_x64.exe`) é gerado com **Inno Setup** e é uma instalação **por usuário**: não exige senha nem privilégios de administrador.

1. **Baixe o instalador oficial:** Acesse a seção de lançamentos (*Releases*) no GitHub e baixe o arquivo `Tomus_Setup_v1.3.2_Windows_x64.exe`.
2. **Execute o instalador:** Dê um duplo clique no arquivo `.exe` baixado para abrir o assistente do Inno Setup.
3. **Siga o assistente:** aceite os termos de licença, escolha a pasta de destino (padrão: `%LocalAppData%\Programs\Tomus`) e marque, se desejar, a criação de um atalho opcional na **Área de Trabalho**. Atalhos são criados automaticamente no **Menu Iniciar**.
4. **Conclua a instalação:** clique em **Concluir** e inicie o Tomus pelo Menu Iniciar ou pelo atalho da Área de Trabalho.

> **Aviso do Windows Defender SmartScreen na primeira execução:** Como o Tomus é um aplicativo comunitário distribuído sem certificado pago Authenticode EV, o Windows Defender SmartScreen pode exibir um aviso na primeira execução (tanto durante o instalador quanto ao abrir o aplicativo pela primeira vez). Isso é esperado para apps independentes sem certificado EV. Para prosseguir, clique em **Mais informações** e, em seguida, em **Executar assim mesmo**.

---

## 2.3 Como Desinstalar o Tomus

### Windows

1. Abra **Configurações > Aplicativos > Aplicativos instalados** (ou **Painel de Controle > Programas e Recursos**).
2. Selecione **Tomus** na lista e clique em **Desinstalar**.
3. Alternativamente, execute `unins000.exe` diretamente na pasta de instalação do Tomus (padrão: `%LocalAppData%\Programs\Tomus`).

> **Limpeza opcional de dados locais:** A desinstalação remove o programa, mas mantém seus dados de usuário. Se quiser remover também configurações, cache e logs, delete manualmente as pastas:
> * `%USERPROFILE%\.config\tomus`
> * `%USERPROFILE%\.cache\tomus`
> * `%USERPROFILE%\.tomus`

### macOS

1. Arraste o aplicativo **Tomus.app** da pasta **Aplicativos** para o **Lixo**.
2. Esvazie o Lixo para concluir a remoção.

> **Limpeza opcional de dados locais:** Se quiser remover também configurações, cache e logs, delete manualmente as pastas:
> * `~/.config/tomus`
> * `~/.cache/tomus`
> * `~/.tomus`

---

## 3. Guia Passo a Passo: Como Obter suas Chaves de Inteligência Artificial (API Keys)

### O que é uma API Key?
Pense em uma **API Key** (chave de acesso) como uma senha especial que você gera nos sites dos provedores de inteligência artificial para permitir que o Tomus converse diretamente com o modelo de linguagem (como Gemini, Groq, NVIDIA ou Claude), sem nenhum intermediário.

> **Importante para a sua tranquilidade:** O Tomus adota a filosofia *Bring Your Own Key* (Traga Sua Própria Chave). Você não paga nada ao Tomus. Além disso, a maioria dos provedores disponibiliza cotas gratuitas generosas que são mais do que suficientes para organizar milhares de livros e artigos.

Abaixo, explicamos em detalhes como obter as chaves dos provedores suportados e da busca de livros do Google.

---

### 3.1 Provedor 1: Google Gemini (Recomendado — Gratuito e Muito Rápido)

O Gemini é o provedor primário padrão do Tomus. Ele é ideal para entender o português e consegue ler folhas de rosto longas com extrema facilidade.

1. Acesse o portal do Google AI Studio em seu navegador:  
   👉 [https://aistudio.google.com/](https://aistudio.google.com/)
2. Faça login com a sua conta Google comum (Gmail).
3. Na barra lateral esquerda ou no topo da página, clique no botão azul **Get API Key** (Obter Chave de API).
4. Clique em **Create API Key** (Criar Chave de API).
5. Selecione a opção **Create API Key in new project** (Criar chave em novo projeto) e confirme.
6. Uma sequência de letras e números será exibida (geralmente iniciando com `AIzaSy...`). Clique no botão **Copy** (Copiar).
7. Guarde essa chave com você para inseri-la no Tomus.

---

### 3.2 Provedor 2: Groq (Altamente Recomendado como 1º Fallback — Gratuito)

O Groq é um provedor que utiliza processadores ultra-rápidos e oferece gratuitamente uma cota de **1.000 requisições por dia**, sendo o parceiro perfeito para atuar como reserva quando a cota diária do Gemini atingir o limite.

1. Acesse o console da Groq:  
   👉 [https://console.groq.com/](https://console.groq.com/)
2. Crie uma conta gratuita ou faça login com sua conta Google ou GitHub.
3. No menu lateral esquerdo, clique em **API Keys**.
4. Clique no botão **Create API Key**.
5. Dê um nome simples para a chave (por exemplo: `Tomus`) e clique em **Submit**.
6. Copie a chave gerada (ela começa com `gsk_...`). **Atenção:** A chave só é mostrada uma única vez na tela por segurança; certifique-se de copiá-la imediatamente.

---

### 3.3 Provedor 3: NVIDIA NIM (Excelente Precisão — Créditos Gratuitos)

A NVIDIA hospeda modelos de inteligência artificial de altíssimo porte com processamento gráfico de ponta.

1. Acesse o portal NVIDIA Build:  
   👉 [https://build.nvidia.com/](https://build.nvidia.com/)
2. Crie sua conta ou faça login. Ao criar a conta, a NVIDIA concede créditos gratuitos de experimentação.
3. Navegue até o modelo **meta/llama-3.2-90b-vision-instruct** ou acesse a seção de chaves em seu perfil.
4. Clique no botão **Generate API Key** (Gerar Chave de API).
5. Copie a chave gerada (ela inicia com `nvapi-...`).

---

### 3.4 Provedor 4: Anthropic Claude (Altíssima Precisão para Textos Raros)

O Claude é mundialmente reconhecido pela precisão impecável na leitura de referências acadêmicas, periódicos antigos e monografias complexas.

1. Acesse o console oficial da Anthropic:  
   👉 [https://console.anthropic.com/](https://console.anthropic.com/)
2. Crie sua conta ou faça login.
3. No painel de controle, vá até a seção **API Keys**.
4. Clique no botão **Create Key** (Criar Chave).
5. Preencha os campos da janela de criação:
   * **Nome:** Digite `Tomus`.
   * **Expiração:** Recomendamos selecionar **Nunca** (*Never*), ou o prazo que preferir.
   * **Escopo:** Selecione **Espaço de trabalho padrão** (*Default workspace*).
6. Clique em **Criar chave** (*Create Key*).
7. Copie o código exibido (ele inicia com `sk-ant-usr-...` ou `sk-ant-api...`).

---

### 3.5 Provedor 5: DeepSeek (Econômico e Veloz)

1. Acesse a plataforma DeepSeek:  
   👉 [https://platform.deepseek.com/](https://platform.deepseek.com/)
2. Crie sua conta e entre no painel.
3. No menu lateral, acesse **API Keys** e clique em **Create API Key**.
4. Copie a chave gerada (`sk-...`).

---

### 3.6 Chave para Busca de Livros: Google Books API (Opcional, mas Recomendada)

O Tomus possui um radar inteligente de códigos **ISBN** (aquele código de barras com números que identifica livros no mundo inteiro). Quando ele encontra um ISBN em um PDF, ele pode consultar o catálogo mundial do Google Livros para obter a capa, sinopse, editora e ano com 100% de precisão.

1. Acesse o console do Google Cloud:  
   👉 [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Faça login com sua conta Google.
3. Crie um projeto novo (ex: `Biblioteca Pessoal`).
4. Na barra de busca do topo, pesquise por **Google Books API** e clique em **Ativar** (*Enable*).
5. Vá na aba lateral **Credenciais** (*Credentials*), clique em **Criar Credenciais** e escolha **Chave de API**.
6. Copie a chave criada. Essa consulta é gratuita e possui limites muito amplos.

---

### 3.7 Onde Colocar suas Chaves no Tomus?

Existem duas formas muito simples:

* **Pelo Menu de Preferências do Tomus:** Na janela principal do Tomus, clique no ícone de engrenagem no rodapé da barra lateral ou abra pelo menu superior: **Tomus › Preferências** (atalho: `Cmd + ,` no macOS; no Windows, acesse via menu superior ou barra lateral de Preferências/Configurações). Na aba de Chaves, cole suas chaves nos campos correspondentes e clique em **Salvar**.
* **Validação Automática:** Ao colar sua chave, o Tomus realiza um teste de conexão discreto de 1 segundo para garantir que ela está ativa e sem erros de digitação.

---

## 4. Como Operar a Bancada de Trabalho do Tomus

A interface do Tomus foi desenhada para ser limpa, intuitiva e agradável de usar durante horas de pesquisa.

```
┌─────────────────┬──────────────────────────────────┬─────────────────┐
│  PAINEL 1:      │  PAINEL 2:                       │  PAINEL 3:      │
│  Navegação      │  Esteira de Documentos           │  Inspetor       │
│                 │                                  │  do Documento   │
│  • Pastas       │  [ Barra de Busca Instantânea ]  │                 │
│  • Modos        │                                  │  • Capa / Prévia│
│  • Status       │  Tabela em Tempo Real:           │  • Título e Ano │
│  • Árvore       │  • Nome do Arquivo               │  • Autores      │
│    CAPES/CNPq   │  • Título Reconhecido            │  • Área CAPES   │
│                 │  • Autor e Ano                   │  • Citação ABNT │
│                 │  • Status e Confiança            │  • Botões Abrir/│
│                 │                                  │    Revelar      │
└─────────────────┴──────────────────────────────────┴─────────────────┘
```

### Passo 1: Selecionar a Pasta de Origem
No canto superior esquerdo da barra lateral, clique no botão **Origem** (com o ícone de pasta) e escolha a pasta onde estão guardados os seus PDFs desorganizados (pode ser a sua pasta de Downloads, uma pasta na sua Mesa de Trabalho ou uma unidade externa).

### Passo 2: Selecionar a Pasta de Destino
Logo abaixo, clique no botão **Destino** e escolha a pasta onde você deseja que o Tomus construa a sua nova biblioteca catalogada. O Tomus criará automaticamente as subpastas organizadas por áreas de conhecimento dentro dela.

### Passo 3: Escolher o Modo de Operação (Copiar vs. Mover)
Você pode escolher entre dois botões:
* **Copiar (Modo Recomendado):** O Tomus deixa seus arquivos originais exatamente onde estão, intactos, e faz uma cópia organizada para a pasta de destino. É o modo mais seguro, pois você nunca perde nada.
* **Mover:** O Tomus transfere os arquivos originais para o novo destino. Use apenas se o espaço em disco do seu computador estiver no limite.

### Passo 4: Ajustar as Opções
* **Varredura Recursiva:** Se marcada, o Tomus não olha apenas os arquivos soltos na pasta de origem, mas também vasculha todas as subpastas internas.
* **Modo Simulado (Dry-Run):** Se você quiser apenas ver como a biblioteca ficaria, sem copiar nenhum arquivo de verdade, marque esta caixa.

### Passo 5: Clicar em "Organizar Acervo"
Clique no botão principal azul **Organizar Acervo**.  
Imediatamente a esteira começará a rodar:
* A barra de progresso no rodapé mostrará a porcentagem concluída e o tempo estimado.
* Cada documento analisado aparecerá na tabela central com seus metadados preenchidos em tempo real.
* Se precisar pausar ou parar o lote a qualquer momento, o botão se transforma em **Interromper Lote** na cor vermelha. Clicar nele finaliza com segurança o documento atual e preserva tudo o que já foi feito.

---

## 5. Explorando sua Nova Biblioteca Organizada

Depois que a esteira processar seus documentos, sua biblioteca se transforma em uma base de conhecimento navegável:

### 5.1 A Árvore de Assuntos CAPES/CNPq
Na barra lateral esquerda, abaixo dos filtros de status, você verá a árvore temática oficial:
* Clique em uma **Grande Área** (ex: *Ciências Exatas e da Terra*) para filtrar apenas os documentos dessa área.
* Abra os ramos com um clique para ver a **Área Básica** (ex: *Física*) e a **Subárea** (ex: *Física Nuclear*).
* Ao lado de cada área, um contador indica exatamente quantos livros ou artigos você possui sobre aquele assunto.

### 5.2 Filtros Rápidos de Status
No topo da barra lateral, você pode clicar nos filtros para focar no que precisa:
* **Todos os Itens:** Restaura a visão geral da biblioteca.
* **Organizados:** Mostra tudo o que foi identificado e catalogado com alta precisão.
* **Revisão Manual:** Mostra documentos que merecem a sua atenção (veja a seção 6).
* **Duplicatas (`duplicatas/`):** Mostra exemplares repetidos da mesma edição (detectados por SHA-256 exato, DOI/ISBN ou impressão digital bibliográfica) para manter apenas um canônico na árvore temática.
* **Obsoletos (`obsoletos/`):** Mostra edições anteriores superadas por versões mais recentes da mesma obra. Sempre que uma edição mais nova é processada, o Tomus mantém a mais recente na árvore temática e move a antiga para `obsoletos/` com uma ficha `.md` explicativa apontando para o exemplar atualizado.
* **Erros / Ignorados:** Mostra se havia algum arquivo com senha ou que não era um PDF válido.

### 5.3 Busca Instantânea
No topo da tabela central, digite qualquer palavra: nome do autor, trecho do título, ano ou assunto. A tabela filtra os resultados instantaneamente à medida que você digita.

### 5.4 O Painel do Inspetor e a Citação ABNT
Ao clicar sobre qualquer linha da tabela, o painel direito (o **Inspetor de Documentos**) exibirá:
* Capa do livro ou a miniatura da primeira página do artigo.
* Ficha catalográfica completa: Grande Área, Área Básica, Subárea, Tipo (Livro, Artigo, Tese, Capítulo) e Grau de Confiança da identificação.
* **Citação Pronta ABNT NBR 6023:** A referência bibliográfica formatada segundo as normas da ABNT, com título da obra em negrito, nomes em caixa alta e sem repetições.
  * Basta clicar no botão **Copiar Citação**. O texto vai para a área de transferência do seu computador e você pode colar direto no seu trabalho acadêmico.
* **Botão "Abrir PDF":** Abre o arquivo organizado imediatamente no visualizador padrão do seu computador.
* **Botão "Revelar no gerenciador de arquivos":** Abre a pasta exata onde o arquivo foi guardado, destacando-o na tela (Finder no macOS, Explorador de Arquivos no Windows).

---

## 6. O que Fazer com Itens em "Revisão Manual"?

Raramente, alguns documentos aparecem marcados com o selo amarelo de **Revisão Manual**. Isso acontece por três motivos transparentes:

1. **O documento é um escaneamento ilegível:** A cópia xerox antiga é muito borrada, manchada ou cortada, e o texto não pôde ser lido com segurança superior a 60%.
2. **O documento tem senha ou proteção de impressão:** Arquivos criptografados que impedem a extração de texto.
3. **Cota de inteligência artificial esgotada temporariamente:** Se a sua chave atingiu o limite de consultas gratuitas do dia e você não cadastrou uma chave reserva de fallback (como Groq ou NVIDIA).

### Como Resolver:
1. Clique no filtro **Revisão Manual** na barra lateral.
2. Clique no documento para abri-lo no Inspetor.
3. Se desejar, clique no botão **Abrir PDF** para ver o arquivo com seus próprios olhos.
4. Utilize o painel de **Aprovação de Triagem** para ajustar manualmente o título ou autor e clique em **Aprovar**. O Tomus completará a organização daquele item imediatamente.

---

## 7. Dicas de Ouro para Tirar o Máximo Proveito

* **Cadastre pelo menos duas chaves (Gemini + Groq):** O Gemini é extraordinário para a maioria dos arquivos. Se você cadastrar também uma chave gratuita do Groq nas Preferências, você nunca ficará na mão: se o Gemini atingir o limite diário no meio de um lote grande com centenas de PDFs, o Tomus migra automaticamente para o Groq sem interromper o seu trabalho.
* **Use o Modo Copiar na primeira vez:** Assim você mantém seus arquivos originais exatamente como estavam, permitindo comparar os resultados com total tranquilidade.
* **Exporte sua bibliografia:** Para cada PDF organizado, o Tomus gera ao lado um arquivo companheiro Markdown (`.md`) com **front matter YAML 100% em português do Brasil** (título, autores, ano, editora, cidade, edição, grande_area, area_basica, subarea, especialidade, tipo, sha256, índice de confiança e arquivo de origem). Nos arquivos de **duplicatas/** e **obsoletos/**, o front matter inclui ainda `camada_deteccao` (L3_IMPRESSAO_DIGITAL, L2_IDENTIFICADOR, etc.) e `caminho_canonico` relativo à raiz da biblioteca, permitindo rastrear qual é a obra canônica e onde ela está. A referência completa segue a norma **ABNT NBR 6023**, facilitando a importação e indexação em ferramentas como Obsidian, Zotero ou Notion.

---

## 8. Glossário de Termos Técnicos

Para garantir total clareza, reunimos abaixo os termos técnicos presentes no aplicativo e na documentação, explicados de forma simples e direta:

* **ABNT NBR 6023:** Norma oficial da Associação Brasileira de Normas Técnicas que estabelece as regras universais para apresentação de referências e citações em trabalhos científicos no Brasil.
* **API Key (Chave de API):** Código identificador alfanumérico pessoal que serve como credencial para acessar serviços digitais de inteligência artificial ou bases de dados.
* **OCR local (PyMuPDF + RapidOCR/ONNXRuntime):** Motor de reconhecimento óptico de caracteres executado localmente no seu computador (macOS e Windows), usado para transcrever páginas digitalizadas sem enviar dados para a nuvem.
* **BYOK (*Bring Your Own Key*):** Modelo de arquitetura onde o usuário utiliza suas próprias credenciais junto aos provedores de serviços, garantindo que nenhum servidor terceiro tenha controle sobre seus acessos ou seus dados.
* **CAPES/CNPq:** Principais órgãos federais de fomento à pesquisa e pós-graduação no Brasil. O Tomus adota a tabela oficial desses órgãos que classifica todo o saber humano em 8 Grandes Áreas e centenas de subáreas.
* **Circuit Breaker:** Mecanismo de proteção em engenharia de software que desativa temporariamente uma via de comunicação quando ela falha repetidas vezes (como quando uma cota gratuita atinge o limite), evitando lentidão e redirecionando a tarefa para outra via disponível.
* **DOI (*Digital Object Identifier*):** Código numérico único internacional atribuído a artigos científicos, livros e teses publicados em periódicos de prestígio (ex: `10.1016/j.cell.2020.01.001`). O Tomus usa esse código para buscar os dados oficiais da obra na internet.
* **Dry-Run (Modo Simulado):** Execução teste onde o sistema simula todas as ações que faria (leitura, classificação, cálculo de caminhos), mas sem gravar, mover ou apagar nenhum arquivo físico no disco.
* **Fallback:** Estratégia de plano de contingência ou reserva. Se o provedor principal de IA estiver indisponível, o sistema recorre instantaneamente ao provedor reserva configurado.
* **ISBN (*International Standard Book Number*):** Número internacional padronizado de 10 ou 13 dígitos que identifica univocamente um livro em todo o mundo.
* **LLM (*Large Language Model*):** Modelo de linguagem de grande porte (inteligência artificial como Gemini, Claude, Llama ou DeepSeek) capaz de compreender nuances de textos, resumir ideias e identificar autoria e títulos.
* **OCR (*Optical Character Recognition*):** Reconhecimento Óptico de Caracteres; tecnologia que converte imagens de páginas impressas ou manuscritas em texto digital selecionável e pesquisável.
* **Pydantic:** Biblioteca de software utilizada no Tomus para validar e garantir que os dados retornados pela inteligência artificial cheguem sem defeitos, campos nulos ou formatações inconsistentes.
* **PySide6 / Qt:** Conjunto de ferramentas de engenharia de software de padrão industrial para criação de interfaces gráficas desktop nativas, fluidas e seguras (macOS e Windows).
* **SHA-256 (Hash Criptográfico):** Uma espécie de "impressão digital" digital única calculada a partir dos dados de um arquivo. Dois arquivos só terão o mesmo código SHA-256 se forem rigorosamente idênticos, até o último ponto. O Tomus usa essa tecnologia para detectar duplicatas sem cometer enganos.
* **Subárea e Especialidade:** Divisões mais específicas dentro de uma área do conhecimento na taxonomia CAPES (exemplo: dentro de *História*, a subárea *História do Brasil* e a especialidade *Brasil República*).
* **TLS (*Transport Layer Security*):** Protocolo criptográfico de segurança que protege a comunicação entre o seu computador e os servidores dos provedores de IA, garantindo que ninguém na rede consiga espionar as informações transmitidas.
