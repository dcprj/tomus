---
name: appsec-cross-platform
description: Use when auditando ou implementando segurança de sistema de arquivos no Tomus: validação de `_is_safe_path`, slots `openPdf`/`revealPath`/`startOrganize`/`openExternalUrl` na WebBridge, chmod 0600 de config.toml em POSIX e icacls em NTFS/Windows. Disponível para Sentinela e qualquer agente que toque em caminhos de arquivo ou ponte IPC QtWebChannel.
---

# AppSec Cross-Platform — Segurança de Caminhos, WebBridge e ACLs

Use when um agente precisa revisar, endurecer ou testar a camada de segurança de I/O do Tomus em macOS, Linux e Windows, especialmente ao adicionar novos slots QWebChannel que aceitam caminhos do frontend ou ao alterar permissões de ficheiros de configuração.

O Tomus expõe a GUI via `QWebChannel` (`window.backend`) e aceita caminhos de origem/destino do frontend. Qualquer slot que receba um caminho deve validá-lo com `_is_safe_path()` contra raízes autorizadas antes de tocar no disco. Slots que abrem URLs externas (`openExternalUrl`) devem permitir apenas esquemas `http` e `https`.

### Regras de ouro (não negociáveis)

- **Nunca confie em caminho vindo do frontend.** Sempre passe por `_is_safe_path(p, allowed_roots)` onde `allowed_roots` inclui `source_dir`, `target_dir` e `_USER_SAFE_DIRS`.
- **Bloqueie path traversal.** Sequências `..`, caminhos absolutos fora das raízes, caminhos UNC (`\\servidor\share`) e dotfiles sensíveis (`.ssh`, `.gnupg`, `.aws`, `.bashrc`, etc.) são rejeitados.
- **Bloqueie raízes do sistema.** `/etc`, `/var`, `/usr`, `/bin`, `/sbin`, `/boot`, `/root` (Unix) e `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `C:\boot` (Windows) nunca são raízes permitidas.
- **Symlinks são bloqueados.** `Path.is_symlink()` é verificado no caminho e em cada componente relativo à raiz (AppSec A-03).
- **Configuração com permissão restritiva.** `config.toml` é gravado com `set_restrictive_file_permissions()` de `src/tomus/core/file_security.py`: POSIX `chmod 0o600`; Windows aplica ACL restritiva via icacls atômico (`/inheritance:r /grant:r *<SID>:F`, `shell=False`). Falha de ACL vira `PermissionError` claro (fail-closed absoluto) tanto em `config.py` quanto em `cache.py`; nunca silenciosa.

### Slots da WebBridge que exigem validação de caminho

| Slot | Validação obrigatória |
|------|----------------------|
| `openPdf(path)` | `_is_safe_path(p, roots)` antes de `open_file_in_os()`; caminho inexistente é ignorado silenciosamente. |
| `revealPath(path)` | `_is_safe_path(p, roots)` antes de `reveal_in_file_manager()`. |
| `startOrganize(source_dir, target_dir)` | Ambos os caminhos por `_is_safe_path` com `_safe_roots` montado de `source_dir`, `target_dir` + `_USER_SAFE_DIRS`. |
| `openExternalUrl(url)` | `QUrl(url).scheme().lower() in ("http", "https")`; qualquer outro esquema é rejeitado e logado. |

### Funções-chave do módulo `bridge.py`

- `_is_safe_path(p, allowed_roots)` — containment POSIX com resolução de symlinks e verificação de componentes protegidos.
- `_is_safe_windows_path(p_path, allowed_roots)` — análise via `PureWindowsPath` (funciona em qualquer SO), bloqueia UNC, raízes do sistema Windows e componentes protegidos.
- `set_restrictive_file_permissions(path)` de `src/tomus/core/file_security.py` — aplica permissão restritiva (POSIX: 0o600; Windows: ACL restritiva via icacls); falhas no Windows são logadas com caminho e motivo, nunca silenciosas.

### Exemplo de uso (seguro)

```python
from tomus.gui.bridge import _is_safe_path
from pathlib import Path

roots = [Path(source_dir), Path(target_dir)] + list(_USER_SAFE_DIRS)
if not _is_safe_path(user_path, roots):
    _logger.warning("caminho rejeitado: %s", user_path)
    return  # não toca no disco
```

### Common mistakes

- Chamar `open_file_in_os()` ou `reveal_in_file_manager()` sem `_is_safe_path` antes.
- Usar `Path.home()` como raiz permitida (foi removido em `revealPath`/`openPdf` por AppSec SEN-06).
- Tratar falha de `icacls` silenciosamente no Windows.
