# Fluxo de Trabalho, Git e Sincronização (macOS + Agente Windows)

> **Fonte única de processo operacional do Tomus.**
> Papéis da equipe principal ficam em `AGENTS.md`.
> Baseline vigente e decisões ativas ficam em `docs/governanca/baseline.md`.

## 1. Modelo de Operação: Equipe Principal (macOS) e Agente Windows

A engenharia, arquitetura e orquestração do projeto concentram-se na **equipe principal no macOS** (Chefe + especialistas). Não há uma segunda equipe espelhada no Windows.

- **No macOS (Equipe Principal):** conduz o desenvolvimento em `src/tomus/`, `tests/`, `docs/`, `pyproject.toml`, empacotamento macOS e a orquestração geral.
- **No Windows (Agente Windows):** existe exclusivamente em uma máquina Windows dedicada e **só atua mediante ordens explícitas do Chefe**, enviadas pelo canal de comunicação do OneDrive. Executa builds, testes e smoke checks em Windows 11 (podendo acionar especialistas pontuais apenas para resolver questões específicas do Windows) e reporta o resultado de volta ao Chefe.
- **Registro de decisões:** decisões técnicas, contratos e mudanças de escopo só passam a valer quando registradas no repositório (`docs/governanca/baseline.md`, `docs/backlog.md` ou no corpo de um Pull Request).
- **Canal assíncrono (quando necessário entre máquinas):** pasta `comunicacao_mac_win/chefes_mac_win/` no OneDrive, mantendo mensagens objetivas em `NNNN_YYYY-MM-DD_slug.md` e sem expor chaves ou segredos (validação opcional via `scripts/validate_onedrive_protocol.py`).

## 2. Fluxo Git Vigente: `develop -> stage -> main`

O projeto adota o fluxo em três estágios para separar desenvolvimento diário, homologação de release e código estável em produção.

- **Regra geral:** nunca commitar, mesclar ou fazer push diretamente na `main` ou na `stage`. Todo código novo entra primeiro em `develop` via Pull Request.
- **Falhas de CI por infraestrutura:** se um runner do GitHub Actions falhar por indisponibilidade ou erro interno do GitHub, reexecutar o CI antes de investigar regressão de código.

### Os três estágios

1. **`develop` (integração contínua):**
   - Recebe Pull Requests de funcionalidades (`feat/*`), correções (`fix/*`), documentação (`docs/*`) e ajustes de plataforma (`mac/*`, `win/*`).
   - Exige CI verde (`ruff`, checagem de nomes ASCII e suíte `pytest` em macOS e Windows) antes do merge.
   - Alterações exclusivas de documentação (`docs/` e arquivos `.md`) exigem lint/CI verde, sem necessidade de rebuild dos instaladores.
2. **`stage` (homologação de release):**
   - Criada a partir de `develop` com escopo congelado para preparar uma versão (ou a partir da `main` em caso de hotfix). Nada novo entra após o congelamento.
   - Gera os builds reais dos instaladores macOS (`.dmg`) e Windows (`.exe`) e o manifesto `SHA256SUMS.txt` com nomes relativos.
   - Exige **smoke check real em ambos os SOs** (instalação, abertura do aplicativo e processamento de PDF de teste pela GUI em ambiente isolado). Sem smoke aprovado no macOS e no Windows, a promoção para `main` é bloqueada.
3. **`main` (produção e publicação):**
   - Recebe exclusivamente candidatos vindos de `stage`, sem alterações adicionais depois da homologação.
   - Todo merge na `main` exige **autorização explícita de Dario**, caso a caso.
   - **Publicação é um ato separado do merge:** criar tag `v*`, publicar GitHub Release e atualizar o site oficial dependem de autorização explícita adicional e reaproveitam os instaladores já homologados em `stage` (qualquer rebuild exige nova passagem por `stage`).

### Hotfix (correção urgente em produção)

Quando houver bug crítico na versão publicada, a branch `fix/*` parte da `main`, passa por uma `stage` própria de hotfix (sem arrastar mudanças pendentes de `develop`) e segue para a `main` após smoke check aprovado e autorização de Dario. Depois, a correção é trazida de volta para `develop`.

## 3. Passo a Passo de Trabalho (Abrir e Fechar uma Tarefa)

### Ao iniciar uma tarefa

1. Atualizar o repositório local com `develop` (`git fetch origin develop`).
2. Conferir `docs/governanca/baseline.md` e `docs/backlog.md` para confirmar prioridade e contexto.
3. Criar uma branch dedicada a partir de `develop` (ou de `main` apenas para hotfix), usando prefixo claro:
   - `feat/<escopo>`: nova funcionalidade
   - `fix/<escopo>`: correção de bug
   - `docs/<escopo>`: documentação, governança ou backlog
   - `mac/<escopo>`: ajuste específico de macOS (`.app`, `.dmg`, smoke check)
   - `win/<escopo>`: ajuste específico de Windows (instalador, build, smoke check)

### Ao concluir uma tarefa

1. Rodar a validação local: `QT_QPA_PLATFORM=offscreen pytest tests/ -m 'not slow' -q` (100% aprovado) e garantir nomes de arquivo estritamente ASCII.
2. Atualizar a branch com `origin/develop` e abrir Pull Request contra `develop` usando `.github/PULL_REQUEST_TEMPLATE.md`.
3. Registrar no corpo do PR qualquer decisão técnica ou atualização do `docs/backlog.md`.
4. Aguardar CI verde em macOS e Windows para integrar em `develop`.

## 4. Responsabilidade por Arquivos (macOS vs. Windows)

Como a equipe principal conduz o projeto no macOS e o Agente Windows atua sob demanda no ambiente Windows, a divisão prática evita que mudanças locais quebrem o outro sistema:

- **Código e base compartilhada (conduzidos no macOS com cuidado multiplataforma):** `src/tomus/`, `pyproject.toml`, `tests/`, `docs/`, `.github/PULL_REQUEST_TEMPLATE.md`.
  - Manter compatibilidade com Windows em caminhos (`pathlib.Path`, limite de caminho `WIN_SAFE_FULL_PATH_CHARS`), encoding UTF-8 e dependências.
  - Em `pyproject.toml`, pacotes exclusivos de um único sistema operacional devem usar marcadores PEP 508 (ex.: `; sys_platform == 'win32'`). Dependências usadas pelos dois sistemas não devem ser restringidas sem validar o impacto nos dois builds.
- **Específicos de macOS (Farol / equipe macOS):** `packaging/build_macos.sh`, `packaging/hooks/hook-tomus.py`, `packaging/smoke_check_macos.py`, seções macOS de `packaging/pyinstaller.spec`, `src/tomus/gui/app.py` (`_apply_webengine_defenses`), `dist/Tomus.app/` e `dist/*.dmg`.
- **Específicos de Windows (Agente Windows / validação Windows):** `packaging/build_windows.ps1`, `packaging/windows_installer.iss`, `packaging/smoke_check_windows.py`, `packaging/icons/icon.ico`, job `build-windows` no CI/release, `dist/Tomus.exe/` e `dist/*.exe`.
