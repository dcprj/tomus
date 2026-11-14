---
name: design-anti-generico
description: Cria interfaces frontend premium fugindo do visual genérico de IA. Integra Taste Skills (direção de arte), Transitions.dev (microinterações) e React Bits (componentes animados).
---
# Design Anti-Genérico (Frontend)

## Resumo
Esta skill orquestra a construção de interfaces web premium integrando Taste Skills, Transitions.dev e React Bits para evitar o "design padrão de IA".

## Quando Usar
- Para construir landing pages, dashboards ou componentes web (React, Next.js, Vue, HTML puro).
- Quando o usuário pedir um design mais sofisticado, animado, premium ou "fora da caixa".
- Quando o usuário mencionar referências do Awwwards, One Page Love, ou pedir para aplicar Taste Skills, Transitions ou React Bits.

## Passos

1. **Estrutura e Direção de Arte (Taste Skills)**
   - Instrua ou aplique o uso do **Taste Skills** (`npx skills add Leonxlnx/taste-skill`) para estabelecer um layout base inspirado em sites premiados.
   - Utilize hierarquia assimétrica, tipografia marcante e sugira imagens reais e contextuais (de fontes CC/Domínio público), evitando ao máximo placeholders cinzas e templates tradicionais (como o famigerado "gradiente roxo com 3 cards de vidro").

2. **Suavidade na Experiência (Transitions.dev)**
   - Evite que a interface tenha mudanças de estado "secas" (ex: informações que aparecem do nada após um clique).
   - Aplique microinterações em todo momento de transição de estado: hover em botões, skeletons de loading fluidos, expansão suave de cards e mensagens de sucesso animadas, usando a filosofia do **Transitions.dev**.
   - Use CSS transitions bem ajustadas para garantir uma sensação premium e moderna na navegação.

3. **Componentes Modernos (React Bits)**
   - Substitua elementos que ficaram com visual "sem graça" por componentes do **React Bits** para adicionar charme.
   - Sugira a importação pontual de animações de texto, backgrounds interativos, bordas luminosas ou carrosséis 3D (ex: `npx shadcn@latest add @react-bits/NomeDoComponente`).
   - Ajuste rigorosamente as cores e os raios de borda do componente importado para que não destoe da paleta principal e da tipografia definidas no Passo 1.

## Cuidados
- **Sobrecarga Cognitiva:** Não entupa a página de animações. Use o React Bits em pontos focais de atenção (ex: Hero section, CTA) e limite o Transitions.dev para a sutileza do uso diário da interface.
- **Harmonia de Design System:** As ferramentas não podem parecer "remendadas". Garanta que as tipografias, sombras e variáveis de cor se comuniquem perfeitamente entre o código base do Taste Skills e os componentes importados do React Bits.
