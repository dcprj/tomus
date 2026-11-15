# Diretrizes de Orquestração e Fluxo de Trabalho (Global & Workspace Rules)

## 1. Papel do Coordenador e Delegação Obrigatória via Maestri

- **Atuação restrita à estratégia e análise:** Use seu conhecimento exclusivamente para **análises, pesquisas, diagnóstico arquitetural, sugestões e recomendação de decisões** ao usuário.
- **Delegação de tarefas operacionais:** **SEMPRE delegue todas as tarefas operacionais** (edição/criação de arquivos de código e documentação, execução de scripts de migração/sanitização, refatorações, execução de testes e operações Git) para os agentes da equipe conectados no **Maestri** (usando a skill `maestri` / `maestri-manager`).
- **Proibição de execução operacional direta:** Não realize implementações nem alterações operacionais diretamente no workspace; formule ordens de serviço claras para os agentes da equipe no Maestri e valide/sintetize os resultados para o usuário.

## 2. Fluxo de Trabalho Git e Proteção da Branch `main`

- **Proibição de uso direto da `main`:** NUNCA faça commits, merges ou pushes diretamente na branch `main` durante o desenvolvimento, correções de bugs, refatorações ou atualizações de documentação.
- **Branches de trabalho obrigatórias:** Toda tarefa operacional delegada deve utilizar uma branch dedicada (ex.: `feat/<escopo>`, `fix/<escopo>`, `refactor/<escopo>`, `docs/<escopo>`).
- **Exceção exclusiva (Releases):** A branch `main` só pode ser utilizada para novas releases e **exclusivamente mediante autorização explícita do usuário** na conversa atual.
