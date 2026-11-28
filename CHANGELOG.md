# Changelog do Tomus

Este arquivo é o registro de versões do Tomus, escrito em linguagem clara para usuários finais. Ele descreve, de forma resumida, o que mudou em cada versão do aplicativo — sem detalhes técnicos de implementação.

## [1.4.2] - publicada em 2026-11-28

### O que há de novo
- O provedor Groq agora fica apenas como reserva (fallback) da cadeia de provedores, atrás do Gemini e do NVIDIA NIM. Isso ocorre porque o Groq tem uma cota gratuita limitada e, quando usado como principal em acervos grandes, pode esgotar rapidamente e tornar o processamento mais lento.
- O seletor de provedor na tela principal agora mostra apenas as opções com chave de API já validada, evitando que o usuário selecione um provedor sem credencial funcional.
- As chaves de API ficam mais protegidas: o arquivo de configuração recebe permissão restrita imediatamente após ser gravado, eliminando janelas de exposição dos dados.
- O botão Salvar agora grava a configuração antes de validar a chave ao vivo, de modo que o salvamento funciona mesmo quando não há acesso à rede ou a validação demora para responder.
- O manual do usuário agora informa explicitamente os limites gratuitos do Groq (8.000 tokens por minuto e 200.000 tokens por dia) e recomenda configurá-lo apenas como reserva de fallback.

### Correções
- Chaves de API não ficam mais expostas brevemente no arquivo de configuração durante a gravação.
- Ao salvar com a rede indisponível, a configuração é preservada e o usuário é informado, sem interromper o uso do aplicativo.

## [1.4.1] - publicada

### Correções
- Ajustes de empacotamento e CI/CD para garantir que a versão publicada corresponde à versão configurada no projeto.
- Geração do arquivo SHA256SUMS.txt com nomes relativos dos instaladores, permitindo verificação de integridade dos arquivos baixados.

## [1.4.0] - 2026-11-23 - publicada

### O que há de novo
- Instalador Windows com tamanho reduzido graças à compressão sólida.
- Arquivo de checksums (SHA256SUMS.txt) disponível como asset da release para verificação de integridade dos instaladores.
- Maior coerência entre a landing page, os manuais e o código do aplicativo.

### Correções
- Correção urgente na landing page: versão do botão, requisitos de sistema, links de download, mockup da janela e seção de créditos atualizados para a versão 1.4.0.

## [1.3.3] - 2026-11-22 - publicada

### O que há de novo
- Motor de OCR mais rápido e leve, sem dependências pesadas de aprendizado de máquina.
- Suporte a pools de chaves do NVIDIA NIM para classificação de documentos.
- Suporte a periódicos e fascículos (revistas científicas) na organização e citação.
- Melhorias de segurança na sanitização de caminhos e identificadores.

### Correções
- Ajustes de desempenho no OCR e na classificação por IA.
- Proteção contra caminhos de arquivo muito longos no Windows.
- Atualização de dependências e pinos de versão nas ações de CI/CD.

## [1.3.2] - 2026-11-20 - publicada

### O que há de novo
- Suporte completo à geração do instalador para Windows no pipeline de CI/CD.
- Builds para macOS e Windows publicados juntos em cada release.

### Correções
- Correções de portabilidade da interface e do motor Web no Windows.
- Detecção automática do instalador Inno Setup no Windows.
- Integração cross-OS passando 100% nos testes de CI.

## [1.3.1] - 2026-11-16 - publicada

### Correções
- Correções de empacotamento para macOS, removendo dependências fantasma e garantindo a inicialização do aplicativo.
- Ajustes no especificação do instalador para macOS.

## [1.3.0] - 2026-11-16 - publicada

### O que há de novo
- Detecção de duplicatas e obsolescência em três camadas (SHA-256, identificadores DOI/ISBN/ISSN e impressão digital bibliográfica).
- Arquivos companheiros (.md) gerados para cada documento organizado, incluindo duplicatas e obsoletos.
- Taxonomia CAPES/CNPq controlada com normalização de sinônimos e desambiguação automática de áreas.
- Melhorias de segurança na interface web (sanitização de exceções e prevenção de XSS).
- Melhorias de empacotamento para macOS, evitando conflitos de bibliotecas.

### Correções
- Reparo automático de níveis taxonômicos inconsistentes.
- Sanitização de chaves de API em mensagens de erro retornadas ao usuário.

## [1.2.0] - 2026-11-14 - publicada

### O que há de novo
- Suporte a múltiplas chaves de API por provedor com rotação automática ao atingir limites de cota.
- Novos provedores homologados: NVIDIA NIM, Anthropic Claude e Groq, além do já existente Google Gemini.
- Triagem manual com subárea e inferência automática da grande área CAPES.
- Barras de redimensionamento de painéis e colunas na interface.
- Validador ativo de chaves de API na janela de Preferências.
- Citação ABNT NBR 6023 aprimorada com formatação normativa de títulos e autores.
- Experiência de desktop pura, sem menus de navegador irrelevantes.

### Correções
- Remoção de provedores e tokens de legado não utilizados.
- Documentação técnica, manual do usuário e landing page atualizados.

## [1.1.2] - 2026-11-10 - publicada

### O que há de novo
- Identidade visual oficial do Tomus (ícones, logotipo e emblema).
- Suporte completo a RapidOCR + ONNXRuntime no Windows.
- Landing page oficial com design editorial.
- README focado na instalação no macOS.

### Correções
- Redação automática de chaves de API e tokens em arquivos de log.
- Bloqueio de tentativas de navegação para pastas sensíveis no sistema.
- Sanitização de exceções da IA para não expor credenciais.
- Prevenção de XSS em links DOI e silenciamento de logs de console desnecessários.
- Avisos de segurança na linha de comando recomendando variáveis de ambiente.

## [1.0.1] - 2026-11-09 - publicada

### Correções
- Correção de vulnerabilidades de segurança identificadas na auditoria do Sentinela:
  - Chaves de API não vazam mais em arquivos de log.
  - Caminhos de arquivo são validados antes de abrir ou revelar arquivos no sistema.
  - Exceções da IA não expõem credenciais ao usuário.
  - Links DOI previnem execução de código inseguro.

## [1.0.0] - 2026-11-07 - publicada

### O que há de novo
- Interface gráfica desktop multiplataforma com bancada de trabalho de três painéis.
- Visualização de documentos com grade virtualizada e busca instantânea.
- Inspetor documental com referência ABNT NBR 6023 e cópia rápida de citação.
- Triagem manual assistida para mover documentos da revisão manual para a árvore temática.
- Monitor do teto de revisão manual (meta de até 20%).
- Suporte a 46 testes automatizados de interface.

## [0.4.0] - 2026-11-06 - publicada

### O que há de novo
- Especificação JSON formal para melhorar a acurácia da classificação por IA.
- Diagnósticos detalhados para arquivos não-PDF e atalhos ignorados.
- Consolidação arquitetural pré-interface gráfica.

## [0.3.0] - 2026-11-06 - publicada

### O que há de novo
- Suporte a novos provedores de IA: Groq e GitHub Models.

## [0.2.0] - 2026-11-06 - publicada

### O que há de novo
- Vários provedores de IA com fallback automático entre eles.
- Novos provedores disponíveis na linha de comando.

## [0.1.0] - 2026-11-05 - publicada

### O que há de novo
- Sistema de logs profissional com terminal limpo para a barra de progresso.
- Persistência de sessão para retomada automática após interrupções.
- Provedor NVIDIA NIM para classificação de documentos.
- Integração completa da linha de comando com o pipeline de organização.

## [0.0.6] - 2026-11-04 - publicada

### O que há de novo
- Arquivos companheiros (.md) gerados para cada documento organizado.
- Gerenciamento de duplicatas com encaminhamento para pasta dedicada.
- Comando para gerenciar o cache local.
- Barra de progresso aprimorada com status por arquivo.

## [0.0.5] - 2026-11-03 - publicada

### O que há de novo
- Modelo padrão do Gemini atualizado.
- Fallback inteligente entre modelos do Gemini quando um não é encontrado.

### Correções
- Cache SQLite não armazena mais resultados simulados (mock).
- Erro amigável quando nenhuma chave de API está configurada.
- Detecção de colisão de nomes em modo de simulação.
- Correção de bug que travava a barra de progresso em zero.

## [0.0.4] - 2026-11-02 - publicada

### O que há de novo
- Organização automática a partir da linha de comando com opções curtas de origem e destino.
- Script executável que configura automaticamente o ambiente Python.

## [0.0.3] - 2026-11-01 - publicada

### O que há de novo
- Prompts de sistema e payload contextual para classificação por IA.
- Nomeação automática de arquivos no padrão "Autor - Título - Ano.pdf".
- Árvore temática organizada por Grande Área, Área Básica e Tipo.
- Pipeline de cinco estágios (varredura, cache, extração, enriquecimento, classificação e organização).
- Interface de linha de comando com Typer e Rich.
- Testes automatizados de nomeação, taxonomia e pipeline.

## [0.0.2] - 2026-10-29 - publicada

### O que há de novo
- Extração de conteúdo de documentos (DOI, ISBN, ficha catalográfica).
- Extração nativa de texto via PyMuPDF.
- Fallback de OCR seletivo via Docling para páginas sem texto.
- Consultas a OpenAlex e Google Books para enriquecimento de metadados.

## [0.0.1] - 2026-10-27 - publicada

### O que há de novo
- Primeira versão do projeto com metadados do pacote, configuração, modelos de domínio, taxonomia CAPES/CNPq, varredura de arquivos, cache SQLite e documentação inicial.
