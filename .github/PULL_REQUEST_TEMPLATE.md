# Template de Pull Request — Tomus

## Resumo da mudança
Descreva brevemente o que este PR implementa ou corrige.

## Branch
- [ ] Branch criada a partir de `develop` (ou a partir de `main` apenas em caso de hotfix)
- [ ] Nome da branch segue a convenção (`feat/*`, `fix/*`, `docs/*`, `mac/*`, `win/*`)

## Alinhamento e governança
- [ ] `git fetch origin develop` executado antes de iniciar o trabalho
- [ ] `docs/governanca/baseline.md` lida e baseline vigente confirmada
- [ ] `docs/backlog.md` conferida
- [ ] Decisões técnicas ou mudanças de backlog registradas neste PR
- [ ] Marcadores PEP 508 no `pyproject.toml` respeitados (se houver dependência específica de SO)

## Testes
- [ ] `QT_QPA_PLATFORM=offscreen pytest tests/ -m 'not slow' -q` executado localmente
- [ ] Resultado: 100% passed (ou justificativa documentada)

## Compatibilidade cross-OS
- [ ] Alterações revisadas para macOS (quando tocar em `packaging/build_macos.sh`, `pyinstaller.spec`, `app.py`)
- [ ] Alterações revisadas para Windows (quando tocar em `packaging/build_windows.ps1`, `windows_installer.iss`, `pyinstaller.spec`, caminhos de arquivo)
- [ ] Smoke check executado quando aplicável (`packaging/smoke_check_macos.py` / `packaging/smoke_check_windows.py`)

## Checklist de segurança (AppSec)
- [ ] Nenhuma chave de API ou segredo commitado no código
- [ ] Caminhos de arquivo sanitizados (prevenção de path traversal)
- [ ] Sanitização de entrada/saída mantida (`escapeHtml`, sanitização de erros)

## Evidências (se houver alteração de interface)
- [ ] Capturas de tela ou descrição do antes/depois na GUI

---

**Nota:** PRs normais entram em `develop`; promoção para `stage` exige smoke check em macOS e Windows; merge na `main` e publicação exigem autorização explícita de Dario.
