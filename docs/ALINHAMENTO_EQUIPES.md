# Alinhamento de Equipes (Mac <-> Windows)

## Baseline Atual

- **Branch de referência:** `main`
- **Commit atual da baseline:** `67c0929` (merge PR #10 — paridade macOS + Windows no README.md)
- **Tag de release vigente:** `v1.3.2`
- **Último release publicado:** v1.3.2 (GitHub Releases, assets `Tomus-1.3.2-macOS.dmg` e `Tomus_Setup_v1.3.2_Windows_x64.exe`)
- **Data do alinhamento:** 2026-11-20
- **PRs integrados:** #1 a #10

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
- `.github/workflows/release.yml` (job `build-windows` do instalador integrado desde PR #5/v1.3.2: build + smoke check + upload do instalador nas tags `v*`)

### Proteção dos pins do `pyproject.toml` (marcadores PEP 508)

Dependências **compartilhadas pelos dois SOs** (como `opencv-python-headless>=4.5.1.48,<4.11`, usado pelo RapidOCR tanto no macOS quanto no Windows) **não devem ser alteradas nem restringidas com marcadores PEP 508 de SO sem consenso de ambas as equipes**. Marcadores PEP 508 aplicam-se apenas a pacotes realmente exclusivos de um SO (ex.: um pacote que existe só no macOS ou só no Windows). Qualquer alteração de versão ou adição de dependência específica de SO deve ser acordada por ambos os Chefes e registrada no PR antes do merge.

---

## Alvos Windows Entregues na v1.3.2

O job `build-windows` está **presente** tanto em `.github/workflows/ci.yml` (testes em `windows-latest` a cada PR) quanto em `.github/workflows/release.yml` (build + smoke check + upload do instalador nas tags `v*`). Os alvos Windows foram entregues na v1.3.2:

1. **Job `build-windows`**: presente em `ci.yml` e `release.yml` no runner `windows-latest` (Python 3.11).
2. **Defesas do QtWebEngine no Windows**: `src/tomus/gui/app.py` injeta `QTWEBENGINE_DISABLE_SANDBOX=1` e resolve `QtWebEngineProcess` dentro de `sys._MEIPASS` (`QTWEBENGINEPROCESS_PATH`, `QTWEBENGINE_PROCESS_PATH`, `QTWEBENGINE_RESOURCES_PATH`) no bundle congelado.
3. **PyInstaller + smoke check Windows**: `packaging/build_windows.ps1` + `packaging/smoke_check_windows.py` (ausência de `pkg_resources`/`pyi_rth_pkgres`, DLLs do onnxruntime, `docling_slim`, `QtWebEngineProcess.exe`, boot offscreen por 5s sem erro) e `packaging/windows_installer.iss` (Inno Setup, `PrivilegesRequired=lowest`, `SolidCompression=no`, `x64compatible`, `unins000.exe`).
4. **Integração com SO unificada**: `src/tomus/gui/os_integration.py` padroniza `open` (macOS), `os.startfile` / `SHOpenFolderAndSelectItems` via ctypes (Windows) e `xdg-open` (Linux).
5. **Instalador Windows por usuário**: `Tomus_Setup_v1.3.2_Windows_x64.exe` instala em `%LocalAppData%\Programs\Tomus` sem privilégios de administrador, com atalhos no Menu Iniciar (opcional na Área de Trabalho) e desinstalador `unins000.exe`.
6. **Release v1.3.2 publicada**: assets `Tomus-1.3.2-macOS.dmg` (macOS) e `Tomus_Setup_v1.3.2_Windows_x64.exe` (Windows) disponíveis em https://github.com/dcprj/tomus/releases/tag/v1.3.2.

> Nota: esses itens constituem o escopo Windows da frente de empacotamento e estão integrados ao `main` (commit `7e5f3c6`) e ao release `v1.3.2`.

---

## Registro Cronológico — 2026-11-18: OpenAlex

- **Status:** Não obrigatório na v1.3.1.
- **Alteração de provedor:** O endpoint `mailto` foi aposentado pela OpenAlex.
- **DOI:** Custa zero (consulta pública gratuita).
- **Busca por título:** Compartilha cota de 0,10 USD/dia por IP.
- **Stage 3:** Protegido em `try/except` (falha graciosa sem interromper o pipeline).
- **Item relacionado:** `[FEAT-ENRICH-01]` Suporte Opcional a `openalex_api_key` (OpenAlex) substituindo/complementando o mailto legado (ver `docs/backlog.md`).

---

## Registro Cronológico — 2026-11-18: Aceite e Status Inicial da Frente Windows

- **Status:** Aceite formal da Frente Windows.
- **Concordância total:** A Frente Windows concorda integralmente com:
  - `AGENTS.md` — Seção 5 (Sincronização Contínua Entre Equipes Mac <-> Windows);
  - `docs/ALINHAMENTO_EQUIPES.md` (baseline vigente, alinhamento de 2026-11-18);
  - `docs/backlog.md` — item `[FEAT-ENRICH-01]` OpenAlex;
  - `.github/PULL_REQUEST_TEMPLATE.md`;
  - `.github/workflows/ci.yml`;
  - preservação dos pins compartilhados do `pyproject.toml` e do job `build-macos` (sem marcadores PEP 508 de SO sem consenso de ambas as equipes).
- **Status das branches:**
  - `win/fix-portability-and-gui` (`7ed3375`): 259/259 testes verdes.
  - `win/packaging-windows` (`c4fa23d`): validada no mundo real em 490 PDFs com `Setup.exe`, 0 erros, 38 OCR, `Abrir PDF` e `Mostrar na pasta` OK.
- **Achados reais:**
  1. Periódicos "Micro Sistemas" L2/L3 e ISBN `9780123456786`.
  2. `MAX_PATH` de 290 chars (caminho longo do Windows na árvore CAPES).
  3. `AutoImageProcessor` com fallback `RapidOCR`.
- **Ordem de PRs contra `main` após merge de `docs/team-sync`:**
  `win/fix-portability-and-gui` → `win/packaging-windows` → `win/ci-build-windows`.

---

## Comunicado Aberto — 2026-11-20: Solicitação de Confirmação Conjunta sobre Docling no macOS (v1.3.2 → v1.3.3)

**Status:** AGUARDANDO RETORNO DO CHEFE MACOS (decisão conjunta obrigatória via AGENTS.md Seção 5.6 antes de qualquer alteração em `pyproject.toml`).

### Evidência direta comprovada no Windows v1.3.2
Arquivo de log: `~/.tomus\tomus.log` (equivalente a `~/.tomus/tomus.log` no macOS) + build-windows run 44742327545:

* **5/5 PDFs escaneados falharam no Docling** em `AutoImageProcessor` (após gastar 36,25s e baixar 163,81 MB de `docling-layout-heron` da HuggingFace na primeira execução) e foram **100% processados pelo fallback RapidOCR 3.10.0 + onnxruntime**.
* **Causa-raiz identificada pelo Córtex:** `pyinstaller-hooks-contrib` 2026.10 busca `torchvision._C` / `torchvision.image` enquanto `torchvision` 0.29.2 usa `_C_stable` / `image_stable` (deixando 0 binários nativos do torchvision no bundle) somado a imports dinâmicos do `transformers` 5.23.0 / `huggingface_hub` 1.33.0.

### Indícios observados no empacotamento e CI do macOS
Build-macos job 136308824934:

* Mesmo stack instalado no build-macos: `docling` 2.151.1, `transformers` 5.23.0, `torchvision` 0.29.2, `pyinstaller` 6.22.3, `pyinstaller-hooks-contrib` 2026.10.
* Mesmos warnings no log do build-macos: `Hidden import torchvision._C not found` e `torchvision.image not found`.
* Em `packaging/pyinstaller.spec` (L116), `collect_all('transformers')` está restrito a `sys.platform == win32` (não roda no macOS), e `packaging/smoke_check_macos.py` não executa OCR real em runtime (testa apenas presença de dist-info e boot offscreen 5s).
* **Observação explícita:** sem log de runtime macOS neste host Windows, a falha em runtime no macOS é apenas uma inferência de alta probabilidade, **não prova direta**.

### Solicitação ao Chefe da Equipe macOS

1. **Confirmar empiricamente em hardware macOS**, executando o app empacotado `Tomus.app` v1.3.2 sobre 1 PDF escaneado (sem camada de texto) e verificando `~/.tomus/tomus.log` se aparece falha do Docling / fallback para RapidOCR ou se o Docling realmente extrai com sucesso no macOS.
2. **Informar de volta por PR / atualização neste arquivo** (ou na Issue correspondente) sua avaliação conjunta sobre:
   * **Opção B (recomendada pelo Córtex):** adotar PyMuPDF 200 DPI + RapidOCR/ONNXRuntime direto removendo `docling`/`torch`/`torchvision`/`transformers` do `pyproject.toml` e `pyinstaller.spec` (−680 MB / −42% no disco, instaladores ~240–350 MB, CI ~8 min, OCR 100% offline desde o 1º uso e `--self-test-ocr` real nos dois smoke checks); **OU**
   * **Opção A:** corrigir o empacotamento completo de Docling/torchvision/transformers nos dois SOs (mantendo ~1,62 GB e build ~26 min) com `--self-test-ocr` comprovando execução sem fallback.

### Compromisso da Frente Windows
Nenhuma alteração em `pyproject.toml` (especialmente `docling`) ou no motor OCR compartilhado será iniciada antes do retorno e consenso formal entre ambos os Chefes.

### Nota de contexto para a futura v1.3.3 (sem iniciar execução ainda)
O teste Windows v1.3.2 também mapeou `[BUG-WIN-PATH]` / `[BUG-PIPE-RESILIENCE]` (caminho 281 chars em Oliva et al. sem `try/except` no Stage 5), `[BUG-WIN-EXIT]` (`TomusMainWindow` sem `closeEvent`), `[BUG-ENRICH-01]` (contaminação OpenAlex em livros), `[BUG-TAX-01]`, `[BUG-TXT-01]` e `[BUG-DEDUP-MS]` já especificados e aguardando alinhamento para abrir o ciclo v1.3.3.
