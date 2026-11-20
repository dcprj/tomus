# Template de Pull Request — Tomus

## Resumo da mudança
Descreva brevemente o que este PR implementa ou corrige.

## Branch
- [ ] Branch criada a partir de `main` (não commitou diretamente na `main`)
- [ ] Nome da branch segue a convenção (`win/*`, `mac/*`, `feat/*`, `fix/*`, `docs/*`)

## Alinhamento entre equipes
- [ ] `git fetch origin main` executado antes de iniciar o trabalho
- [ ] `docs/ALINHAMENTO_EQUIPES.md` lida e a baseline vigente confirmada
- [ ] `docs/backlog.md` lida e prioridades conferidas
- [ ] Decisões/contratos/backlog registrados neste PR (não apenas em conversa)
- [ ] Pins do `pyproject.toml` com marcadores PEP 508 respeitados (se houver dependência específica de SO)

## Testes
- [ ] `QT_QPA_PLATFORM=offscreen pytest tests/ -m 'not slow' -q` executado localmente
- [ ] Resultado: 100% passed (ou justificativa documentada para qualquer falha)

## Compatibilidade cross-OS
- [ ] Alterações testadas ou revisadas para macOS (quando tocar em `packaging/build_macos.sh`, `pyinstaller.spec`, `app.py`)
- [ ] Alterações testadas ou revisadas para Windows (quando tocar em `windows_installer.iss`, `pyinstaller.spec`, caminhos de arquivo)
- [ ] Smoke check executado (macOS: `packaging/smoke_check_macos.py`; Windows: `packaging/smoke_check_windows.py` se existir)

## Checklist de segurança (AppSec)
- [ ] Nenhuma chave de API ou segredo commitado no código
- [ ] Caminhos de arquivo sanitizados (prevenção de path traversal)
- [ ] Sanitização de entrada/saída mantida (escapeHtml, _sanitize_error_message)

## Evidências (se houver alteração de interface)
- [ ] Capturas de tela ou descrição do antes/depois na GUI

---

**Nota:** Este PR só deve ser mesclado na `main` com CI 100% verde e autorização explícita para releases.
