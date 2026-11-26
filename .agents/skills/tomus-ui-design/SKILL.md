---
name: tomus-ui-design
description: >-
  Diretrizes unificadas de UX/UI, direção visual, densidade de layout,
  tipografia, estados vazios e microinterações para a interface gráfica (GUI)
  e páginas web do Tomus. Substitui design-anti-generico, desktop-ui-craft,
  frontend-design e web-design-guidelines.
---

# Tomus UI Design System (Editorial Academic Workbench)

Diretriz única de design visual e ergonomia para o Tomus (`src/tomus/gui/web/`, diálogos Qt e páginas estáticas em `docs/`), inspirada em ferramentas utilitárias de precisão como Zotero 7, Linear, Things 3 e Panic Nova.

## 1. Regras Anti-AI-Slop (O que é proibido)

1. **Sem gradientes neon ou brilhos artificiais:** nunca usar fundos ou botões `purple-to-pink`, `indigo-to-cyan` ou sombras coloridas brilhantes.
2. **Zero emojis como ícones de interface:** usar exclusivamente ícones vetoriais monocromáticos consistentes (traço de `1.5px` a `1.75px`, estilo Lucide / SF Symbols).
3. **Sem estética de landing page na GUI desktop:** nada de hero sections promocionais, eyebrows em caixa alta espaçada ou cartões gigantes (`border-radius > 12px`) flutuando no vazio.
4. **Sem baixa densidade nem truncamento cego:** nenhum botão, checkbox ou rótulo (como "Recursivo" ou "Simulação (Dry-Run)") pode ter largura fixa menor que seu texto intrínseco.
5. **Sem badges decorativos soltos ou setas forçadas:** usar badges discretos apenas para estados reais do pipeline (`Organizado`, `Revisão Manual`, `Duplicata`, `Cache Hit`, `OCR`, `Erro`).

## 2. Identidade Visual e Paleta Oficial

- **Modo Claro (Editorial Paper):**
  - Superfície base (janela/sidebar): `#F6F5F1`
  - Superfície principal (tabela/dados): `#FFFFFF`
  - Superfície elevada / hover: `#EFECE6`
  - Bordas hairline (`1px`): `#E2DFD7`
  - Texto primário: `#18181B` | Texto secundário: `#52525B`
  - Acento primário (Azul Cobalto Acadêmico): `#1E3A5F` (hover `#162B47`)
- **Modo Escuro (Technical Graphite):**
  - Superfície base (sidebar): `#141517`
  - Superfície principal (dados): `#1B1C1F`
  - Superfície elevada / input: `#232529`
  - Bordas hairline (`1px`): `#2E3036`
  - Texto primário: `#F4F4F6` | Texto secundário: `#9CA3AF`
  - Acento primário: `#4A7BB0`
- **Cores semânticas sóbrias (fundo dessaturado + texto contrastado):**
  - `Organizado`: `#15803D` (claro) / `#4ADE80` (escuro)
  - `Revisão Manual`: `#B45309` (claro) / `#FBBF24` (escuro)
  - `Duplicata`: `#0369A1` (claro) / `#38BDF8` (escuro)
  - `Erro`: `#B91C1C` (claro) / `#F87171` (escuro)

## 3. Tipografia, Layout e Tabela de Alta Densidade

- **Fontes:** sans-serif nativa (`SF Pro Text` / `Inter`) com `font-variant-numeric: tabular-nums` em contadores, anos, porcentagens, tempos e scores. Caminhos, SHA-256 e logs em monoespaçada (`SF Mono` / `JetBrains Mono`).
- **Citação ABNT NBR 6023:** autores em texto normal com sobrenome em CAIXA ALTA (sem negrito); título de livro/tese em **negrito** sem itálico (subtítulo em texto normal); em artigos, apenas o nome do periódico em **negrito**.
- **Toolbar em 2 níveis lógicos:**
  - Linha principal: campos de Origem e Destino (altura mínima `32px`, raio `4px` a `6px`, suporte a Drag & Drop) e botão de ação primária (`Organizar Acervo` / `Interromper`).
  - Linha secundária: seletor de provedor ativo (`Gemini`, `Groq`, `NVIDIA`, `DeepSeek`, `Claude`), modo (`Copiar` / `Mover`), toggles (`Recursivo`, `Simulação`) e ações utilitárias (`Preferências`, `Cache`, `Sobre`).
- **Bancada em 3 painéis redimensionáveis:**
  - Esquerda: filtros de status (com precedência global sobre a árvore) e árvore CAPES/CNPq colapsável.
  - Centro: grade de alta densidade com coluna de título em modo expansível (`Stretch`), exibindo o nome original do arquivo enquanto o LLM processa (nunca travessões vazios).
  - Direita: inspetor colapsável com citação ABNT copiável em 1 clique, metadados (`DOI`, `ISBN`, `SHA-256`, `reasoning`, provedor/modelo) e botões `Abrir PDF` e `Mostrar na Pasta`.
- **Rodapé de telemetria:** progresso em tempo real (`X / Y processados`, `Restam: N`, média por arquivo, tempo estimado e taxa de revisão manual com alerta acima de 20%), protegido contra layout shift com `tabular-nums` e `white-space: nowrap`.

## 4. Estados Vazios e Microinterações

- **Empty states dignos:** nunca deixar o inspetor ou a grade como um vazio seco. Usar ícone vetorial sutil (`48x48px`, baixa opacidade), título em peso `600` e instrução curta de orientação.
- **Auto-seleção pós-execução:** ao concluir ou interromper um lote com itens na grade, selecionar automaticamente a primeira linha para preencher o inspetor imediatamente.
- **Transições sutis:** usar transições CSS leves em hover, abertura de modais e feedback de cópia/interrupção ("Interrompendo com segurança..."), sem animações excessivas que atrapalhem o uso diário.
