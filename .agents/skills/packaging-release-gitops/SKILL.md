---
name: packaging-release-gitops
description: Use when empacotando o Tomus para macOS e Windows, gerenciando o workflow de release (`release.yml`), executando smoke checks, gerando `SHA256SUMS.txt`, versionando (bump <VERSAO_ANTERIOR> → <VERSAO>) ou validando consistência de tag `v*` vs `pyproject.toml`. Disponível para Farol e qualquer agente que toque em build, empacotamento ou publicação.
---

# Packaging, Release e GitOps — Empacotamento, CI/CD e Fluxo de Release

Use when um agente precisa alterar `packaging/pyinstaller.spec`, `packaging/windows_installer.iss`, `packaging/build_macos.sh`, `packaging/build_windows.ps1`, `.github/workflows/release.yml`, `pyproject.toml`, `src/tomus/__init__.py` ou `CHANGELOG.md`, especialmente para bump de versão, adição de passo de CI ou validação de tag antes de publicar.

### Empacotamento macOS

- `packaging/build_macos.sh` executa PyInstaller sobre `packaging/pyinstaller.spec`, corrige caminhos do `QtWebEngineProcess`, aplica assinatura ad-hoc (`codesign --force --deep --sign -`) e gera `.app` + `.dmg` (via `create-dmg` ou `hdiutil`).
- `packaging/pyinstaller.spec` define `CFBundleVersion` e `CFBundleShortVersionString` (deve bater com `pyproject.toml`).
- `packaging/hooks/hook-tomus.py` restringe supressão de symlinks do OpenCV (`**/cv2/.dylibs/libssl*`, etc.) preservando `libavcodec`/`libavformat`/`libavutil`/`libswscale`.
- Smoke check: `packaging/smoke_check_macos.py` valida ausência de `pkg_resources`/`pyi_rth_pkgres`, presença de `libavcodec` em `Contents/Frameworks`, `RapidOCR` + `onnxruntime` embarcados, `--self-test-ocr` com exit 0 e boot offscreen por 5s sem erro.

### Empacotamento Windows

- `packaging/build_windows.ps1` executa PyInstaller, smoke check `packaging/smoke_check_windows.py` e compila o instalador com Inno Setup (`packaging/windows_installer.iss`): `PrivilegesRequired=lowest` (por usuário, sem senha/administrador), `SolidCompression=yes`, `x64compatible`, atalhos no Menu Iniciar, desinstalador `unins000.exe`.
- `MyAppVersion` no `.iss` deve bater com a versão de `pyproject.toml`.
- Instalador gera `Tomus_Setup_v<versao>_Windows_x64.exe` instalando em `%LocalAppData%\Programs\Tomus`.

### Fluxo de release (release.yml)

- O workflow `build-macos` + `build-windows` roda nas tags `v*`, publicando `.dmg` e `.exe` no release do GitHub.
- **FAROL-14:** passo de validação de tag compara `GITHUB_REF` (tag `v*`) com a versão em `pyproject.toml` (`tomllib` lê `project.version`). Se `TAG_NAME != v{PY_VERSION}`, o workflow falha (exit 1). Isso impede publicar tag com versão divergente.
- `SHA256SUMS.txt` é gerado como asset da release (checksums dos instaladores).
- Nenhuma tag é criada nem release é publicada sem autorização explícita de Dario; a tag `v<VERSAO>` só ocorre no commit de merge, depois de CI verde.

### Versionamento

A versão <VERSAO> deve bater em todos estes locais (nenhum número <VERSAO_ANTERIOR> deve sobrar no build):
- `pyproject.toml` → `version = "<VERSAO>"`
- `src/tomus/__init__.py` → `__version__ = "<VERSAO>"`
- `packaging/pyinstaller.spec` → `CFBundleVersion` / `CFBundleShortVersionString = "<VERSAO>"`
- `packaging/windows_installer.iss` → `#define MyAppVersion "<VERSAO>"`
- `packaging/build_macos.sh` e `packaging/build_windows.ps1` → fallbacks de versão `"<VERSAO>"`

### CHANGELOG

- Adicionar seção `## [<VERSAO>] - YYYY-MM-DD (ou (pendente de publicação) até o release)` no topo.
- Listar somente correções efetivamente corrigidas nesta release (agrupadas por área: segurança, configuração, cache, extração, documentação).
- Não listar itens que não foram corrigidos.
- Data fica como `(pendente de publicação)` até a publicação.

### Common mistakes

- Deixar algum arquivo de build com versão `<VERSAO_ANTERIOR>` (quebra a consistência da release).
- Esquecer de atualizar `CFBundleVersion`/`CFBundleShortVersionString` no spec macOS.
- Criar tag `v*` sem que a versão em `pyproject.toml` bata (o passo FAROL-14 falha o workflow).
- Publicar release sem autorização explícita de Dario.
