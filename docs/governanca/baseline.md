# Baseline e Estado Atual do Projeto

> **Última atualização:** 26/11/2026
> **Responsável:** Dario

## Baseline Vigente (Ponto Zero do Repositório)

- **Versão do produto:** `1.4.1` (`pyproject.toml` e `src/tomus/__init__.py`)
- **Tag de referência:** `v1.4.1` (ponto inicial limpo do repositório, sem histórico de commits anteriores)
- **Branches iniciais:** `main`, `stage` e `develop` partindo do mesmo estado `1.4.1`
- **Fluxo Git ativo:** `develop -> stage -> main` (ver `docs/governanca/fluxo_trabalho.md`)

## Decisões Arquiteturais Vigentes

1. **Estrutura de times enxuta (desde 26/11/2026):** equipe principal centralizada no macOS (Chefe, Córtex sob demanda, Forja, Prisma, Sentinela e Farol) e atuação no Windows concentrada em um único Agente Windows sob ordens do Chefe via Maestri Wire.
2. **OCR local primário (desde v1.3.3):** PyMuPDF + RapidOCR/ONNXRuntime 100% offline. `docling`, `torch`, `torchvision` e `transformers` removidos do empacotamento e validados via `--self-test-ocr` nos smoke checks de macOS e Windows.
3. **Segurança de arquivos e ponte GUI (desde v1.4.1):** precedência de configuração `ENV > ./tomus.toml > global`, contenção de caminhos em `startOrganize`/`revealPath`/`openPdf`, e ACL fail-closed via `src/tomus/core/file_security.py` (`chmod 0o600` em POSIX e `icacls` atômico em Windows).
4. **Empacotamento multiplataforma:** macOS (`.app` / `.dmg` via PyInstaller + `create-dmg`) e Windows (`.exe` por usuário em `%LocalAppData%\Programs\Tomus` via PyInstaller + Inno Setup), ambos integrados ao CI e ao `release.yml`.

## Pendências de Acompanhamento

- **Ao recriar o repositório no GitHub:** criar `main`, `stage` e `develop` a partir do commit inicial `1.4.1`, enviar a tag `v1.4.1` (disparando `.github/workflows/release.yml` para validar o relançamento limpo dos instaladores) e configurar proteção das branches `main` e `stage` para aceitar apenas Pull Requests.
- **Reteste empírico em Windows 11 local (não bloqueante):** validação complementar de ACL (`icacls`) em conta não elevada fora do runner do CI.
- **Direcionamento de produto (no backlog):** marcação visual de versão beta (`[PROD-BETA-01]`) e avaliação de migração exclusiva para GUI (`[PROD-GUI-01]`).
