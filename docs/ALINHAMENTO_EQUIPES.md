# Alinhamento de Equipes (Mac <-> Windows)

## Baseline Atual

- **Branch de referência:** `main`
- **Commit atual da baseline:** `3403c18` (merge: aplica hotfix v1.3.1 — smoke check CI corrigido)
- **Tag de release vigente:** `v1.3.1`
- **Último release publicado:** v1.3.1 (GitHub Releases, asset `Tomus-1.3.1-macOS.dmg`)
- **Data do alinhamento:** 2026-11-18

---

## Regra de Ouro de Sincronização

> **Decisões, contratos e itens do backlog só contam entre Mac e Windows quando registrados no Git.**

Nada que seja decidido em conversa, reunião ou mensagens avulsas tem efeito entre as equipes até que esteja documentado em um arquivo versionado no repositório (preferencialmente neste `docs/ALINHAMENTO_EQUIPES.md`, `docs/backlog.md` ou em um Pull Request vinculado ao `main`).

---

## Protocolo de Início e Fim de Ciclo (Ambos os Chefes)

### Início de ciclo (antes de qualquer trabalho)

1. Executar `git fetch origin main` para sincronizar o estado remoto.
2. Ler `docs/ALINHAMENTO_EQUIPES.md` (este documento) para conferir a baseline vigente.
3. Ler `docs/backlog.md` para verificar os próximos itens abertos e prioridades.
4. Criar uma branch dedicada a partir de `main` (ex.: `win/...`, `mac/...`, `feat/...`, `fix/...`, `docs/...`).
5. Registrar a intenção de trabalho no Pull Request antes de iniciar a implementação.

### Fim de ciclo (antes de ir para a main)

1. Executar `git fetch origin main` e confirmar que a branch de trabalho está atualizada com `origin/main`.
2. Rodar a suíte de testes: `QT_QPA_PLATFORM=offscreen pytest tests/ -m 'not slow' -q` (deve ser 100% passed).
3. Abrir um Pull Request contra `main` com o template `.github/PULL_REQUEST_TEMPLATE.md` preenchido.
4. Registrar todas as decisões, contratos e mudanças de backlog no corpo do PR.
5. Somente após aprovação do PR e CI 100% verde, fazer merge na `main` (apenas com autorização explícita para releases).

---

## Convenção de Branches Curtas

Use prefixos curtos e descritivos, sempre a partir de `main`:

| Prefixo | Uso |
|---------|-----|
| `win/*` | Trabalho específico de Windows (instalador, build, smoke check Windows) |
| `mac/*` | Trabalho específico de macOS (.app, .dmg, smoke check macOS) |
| `feat/*` | Nova funcionalidade ou feature |
| `fix/*` | Correção de bug ou regressão |
| `docs/*` | Documentação, alinhamento, backlog |

Exemplos: `win/build-smoke`, `mac/dmg-layout`, `feat/openalex`, `fix/cv2-openssl`, `docs/team-sync`.

---

## Fronteiras de Arquivos: Windows vs macOS vs Compartilhados

### Arquivos compartilhados (ambos os SO)
- `src/tomus/` (código Python do motor, GUI, storage, taxonomy, LLM, extractors, cli)
- `pyproject.toml` (dependências principais e metadados do projeto)
- `tests/` (suíte de testes)
- `docs/` (documentação geral)
- `.github/PULL_REQUEST_TEMPLATE.md`

### Arquivos específicos de macOS
- `packaging/build_macos.sh` (script de build do .app e .dmg)
- `packaging/hooks/hook-tomus.py` (hook PyInstaller macOS — supressão de libssl/libcrypto do cv2)
- `packaging/pyinstaller.spec` (seções de bundle macOS, `CFBundleVersion`, symlinks QtWebEngine)
- `src/tomus/gui/app.py` (`_apply_webengine_defenses` com `QTWEBENGINE_DISABLE_SANDBOX`, `QTWEBENGINEPROCESS_PATH`)
- `dist/Tomus.app/` e `dist/*.dmg` (artefatos de build, não versionados)

### Arquivos específicos de Windows
- `packaging/windows_installer.iss` (Inno Setup, `MyAppVersion`, `SetupIconFile`, `OutputBaseFilename`)
- `dist/Tomus.exe/` e `dist/*.exe` (artefatos de build, não versionados)
- `packaging/icons/icon.ico` (ícone Windows)
- `.github/workflows/ci.yml` (testes de PR em runner `windows-latest`)
- `.github/workflows/release.yml` (futuro job `build-windows` do instalador, ainda ausente)

### Proteção dos pins do `pyproject.toml` (marcadores PEP 508)

Dependências **compartilhadas pelos dois SOs** (como `opencv-python-headless>=4.5.1.48,<4.11`, usado pelo RapidOCR tanto no macOS quanto no Windows) **não devem ser alteradas nem restringidas com marcadores PEP 508 de SO sem consenso de ambas as equipes**. Marcadores PEP 508 aplicam-se apenas a pacotes realmente exclusivos de um SO (ex.: um pacote que existe só no macOS ou só no Windows). Qualquer alteração de versão ou adição de dependência específica de SO deve ser acordada por ambos os Chefes e registrada no PR antes do merge.

---

## 6 Alvos Windows Mapeados na v1.3.1

O job `build-windows` está **ausente** do `.github/workflows/release.yml` (apenas `build-macos` existe). Os 6 alvos Windows a serem mapeados e implementados no futuro job `build-windows` são:

1. **Job `build-windows` ausente em `release.yml`**: criar job paralelo no runner `windows-latest`.
2. **`_apply_webengine_defenses` em `app.py`**: garantir que as defesas do QtWebEngine (`QTWEBENGINE_DISABLE_SANDBOX`, `QTWEBENGINEPROCESS_PATH`, caminhos de recursos) funcionem no Windows congelado.
3. **PyInstaller + onnxruntime / RapidOCR / docling-slim / upx + `smoke_check_windows.py`**: coletar DLLs do onnxruntime, metadados do docling-slim, configurar upx, excluir `pkg_resources` no `packaging/pyinstaller.spec` e criar o smoke check equivalente ao macOS para o bundle Windows (verificar ausência de `pkg_resources`, presença de DLLs essenciais, boot do executável por 5s sem erro).
4. **Unificar `openPdf`/`revealPath` de `bridge.py` com `os_integration.py`**: padronizar abertura de arquivos e revelação de pasta entre SO.
5. **`secure_chmod_600` e `MAX_PATH`**: unificar `src/tomus/core/config.py` e `src/tomus/gui/widgets/preferences_dialog.py` usando `os_integration.secure_chmod_600()` para ignorar chmod POSIX no Windows, e verificar o limite de caminho longo do Windows (`MAX_PATH` de 260 chars) na árvore CAPES.
6. **Validação obrigatória no instalador real `Setup.exe`/`Tomus.exe`**: após a build do instalador Inno Setup, testar o fluxo completo com PDF nativo + PDF escaneado (OCR) + `openPdf` + `revealPath` + tela de Preferências/chaves + geração de `tomus.log`.

> Nota: esses 6 alvos são o escopo do futuro job `build-windows` no CI. Eles estão listados aqui para alinhamento entre equipes Mac e Windows.

---

## Registro Cronológico — 2026-11-18: OpenAlex

- **Status:** Não obrigatório na v1.3.1.
- **Alteração de provedor:** O endpoint `mailto` foi aposentado pela OpenAlex.
- **DOI:** Custa zero (consulta pública gratuita).
- **Busca por título:** Compartilha cota de 0,10 USD/dia por IP.
- **Stage 3:** Protegido em `try/except` (falha graciosa sem interromper o pipeline).
- **Item relacionado:** `[FEAT-ENRICH-01]` Suporte Opcional a `openalex_api_key` (OpenAlex) substituindo/complementando o mailto legado (ver `docs/backlog.md`).

---
