---
name: cross-platform-desktop-gui
description: >-
  Guia de engenharia para a camada desktop PySide6/QtWebEngine em src/tomus/gui/
  (threads, cancelamento cooperativo, QtWebChannel, integração multiplataforma
  de SO, cache e retomada de sessão). Direção visual fica em tomus-ui-design;
  empacotamento fica em packaging-release-gitops.
---

# Engenharia de GUI Desktop (PySide6 / QtWebEngine) — Tomus

Esta skill cobre exclusivamente a arquitetura de engenharia de `src/tomus/gui/` sobre `tomus.core`. Diretrizes visuais ficam em `tomus-ui-design`; segurança de caminhos e IPC ficam em `appsec-cross-platform`; empacotamento fica em `packaging-release-gitops`.

## 1. Contratos de Integração com `tomus.core`

A UI nunca pode bloquear o loop principal de eventos durante varredura, OCR ou chamadas de rede:

1. **Worker Thread e Cancelamento Cooperativo:**
   - Executar `run_pipeline(...)` em thread dedicada (`QThread` / `threading.Thread`) passando `event_callback` (emitindo sinais thread-safe para a UI) e `cancel_event` (`threading.Event()`).
   - Ao acionar **Interromper**, sinalizar `cancel_event.set()` e encerrar o lote sem corromper `~/.cache/tomus/state.db` nem truncar arquivos.
   - Implementar `closeEvent` na janela principal para interromper workers ativos com segurança antes de encerrar o processo.
2. **Configuração e Credenciais (`tomus.core.config`):**
   - Ler e gravar `~/.config/tomus/config.toml` via `AppConfig` e `src/tomus/core/file_security.py` (ACL `0600` em POSIX e `icacls` fail-closed no Windows).
   - Suportar os provedores ativos (`gemini`, `groq`, `nvidia`, `deepseek`, `claude`), pool de múltiplas chaves por provedor e validação ativa de chaves em Preferências.
3. **Retomada de Sessão e Cache:**
   - Consultar `tomus.core.session.load_session()` na inicialização para oferecer retomada ou descarte de sessões interrompidas.
   - Expor estatísticas e limpeza segura do cache SQLite (`~/.cache/tomus/state.db`) via `FileCache`.

## 2. Ponte WebEngine, Clipboard e Integração Multiplataforma

1. **QtWebEngine defensivo em bundles congelados (`src/tomus/gui/app.py`):**
   - Configurar `QTWEBENGINE_DISABLE_SANDBOX=1` e resolver `QtWebEngineProcess` dentro de `sys._MEIPASS` tanto no macOS quanto no Windows.
   - Desabilitar menu de contexto padrão do navegador no `QWebEngineView` (`NoContextMenu`), preservando menu nativo apenas em inputs editáveis.
2. **Clipboard nativo via Bridge (`src/tomus/gui/bridge.py`):**
   - Expor `copyToClipboard` usando `QGuiApplication.clipboard()` (evitando falhas de permissão de `navigator.clipboard` em `file://` e evitando instanciamento direto de `QMimeData` propenso a crash de GC no PySide6).
3. **Integração com SO unificada (`src/tomus/gui/os_integration.py`):**
   - Centralizar abertura de PDFs e revelação em pasta usando `open` / `open -R` (macOS), `os.startfile` / `SHOpenFolderAndSelectItems` via ctypes (Windows) e `xdg-open` (Linux), sempre usando `pathlib.Path` e passando pela validação de segurança `_is_safe_path`.
4. **Testabilidade headless:**
   - Toda lógica da GUI precisa passar sob `QT_QPA_PLATFORM=offscreen` no CI (macOS e Windows), incluindo `--self-test-ocr`.
