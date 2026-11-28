"""Ponte de comunicação bidirecional (QWebChannel) entre Python e o frontend Web.

Permite que a interface HTML5/CSS moderna invoque métodos do motor
e receba eventos de streaming de processamento em tempo real.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from tomus.core.config import AppConfig, resolve_gemini_api_key
from tomus.core.key_validator import validate_key_syntax
from tomus.core.llm import _sanitize_error_message
from tomus.core.models import FileManifestEntry, PipelineEvent, ProcessStatus
from tomus.gui.os_integration import open_file_in_os, reveal_in_file_manager
from tomus.gui.worker import ManualTriageService, PipelineWorker

_logger = logging.getLogger("tomus.gui.bridge")

# Pastas do usuário consideradas seguras para operações de arquivo.
_USER_SAFE_DIRS = (
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Movies",
    Path.home() / "Pictures",
)

# Nomes de pastas/arquivos sensíveis que devem ser bloqueados.
_PROTECTED_NAMES = (
    ".ssh", ".gnupg", ".aws", ".bashrc", ".bash_profile", ".zshrc",
    ".config", ".local/share", ".cache",
)

# Pastas do sistema que nunca devem ser expostas (Unix/POSIX).
_SYSTEM_ROOTS = (
    Path("/etc"),
    Path("/var"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/boot"),
    Path("/root"),
)

# Raízes do sistema Windows que nunca devem ser expostas, mesmo quando o
# código roda em não-Windows (os caminhos são analisados com PureWindowsPath).
# C:\Users é propositalmente omitido para não bloquear as pastas seguras do
# usuário (Documents, Desktop, Downloads, etc.) que vivem sob ele.
_WINDOWS_SYSTEM_ROOTS = (
    PureWindowsPath(r"C:\Windows"),
    PureWindowsPath(r"C:\Program Files"),
    PureWindowsPath(r"C:\Program Files (x86)"),
    PureWindowsPath(r"C:\ProgramData"),
    PureWindowsPath(r"C:\boot"),
)


def _is_windows_path(value: Path | str) -> bool:
    r"""Detectar se o caminho parece ser um caminho do Windows.

    Reconhece drive letter (``C:\...``) e caminhos UNC
    (``\\servidor\compartilhamento``) independentemente do SO onde roda.
    """
    s = str(value)
    # Caminho UNC: \\servidor\compartilhamento (ou //servidor/compartilhamento).
    if s.startswith(("\\\\", "//")):
        return True
    # Drive letter: letra seguida de :\ (ex.: C:\...).
    if len(s) >= 2 and s[0].isalpha() and s[1] == ":":
        return True
    return False


def _is_safe_windows_path(
    p_path: Path, allowed_roots: list[Path | str]
) -> bool:
    """Verificar segurança de um caminho do Windows (mesmo em não-Windows).

    Usa ``PureWindowsPath`` para analisar o caminho sem depender do SO atual.
    Bloqueia caminhos UNC, raízes do sistema Windows (_WINDOWS_SYSTEM_ROOTS)
    e componentes protegidos dentro de raízes permitidas. Ainda verifica
    symlinks via ``Path.is_symlink`` do objeto original (AppSec A-03).
    """
    try:
        p_win = PureWindowsPath(str(p_path))
    except (ValueError, TypeError):
        return False

    # Caminhos UNC (\\servidor\compartilhamento) são sempre bloqueados.
    if str(p_path).startswith(("\\\\", "//")):
        return False

    # Verificar containment nas raízes permitidas.
    for root in allowed_roots:
        if not root or (isinstance(root, str) and not root.strip()):
            continue
        try:
            root_win = PureWindowsPath(str(root))
        except (ValueError, TypeError):
            continue
        try:
            p_win.relative_to(root_win)
        except ValueError:
            continue
        # Dentro de uma raiz permitida; verificar componentes protegidos.
        rel = p_win.relative_to(root_win)
        for part in rel.parts:
            if part in _PROTECTED_NAMES or part.startswith("."):
                return False
        # Bloquear symlinks (AppSec A-03): usar Path.is_symlink do objeto
        # original, para que monkeypatch no Windows CI funcione.
        try:
            if p_path.is_symlink():
                return False
        except (OSError, ValueError):
            return False
        return True

    # Se não está em nenhuma raiz permitida, verificar raízes do sistema Windows.
    for sys_root in _WINDOWS_SYSTEM_ROOTS:
        try:
            p_win.relative_to(sys_root)
            return False  # dentro de pasta do sistema Windows
        except ValueError:
            pass

    return False


def _is_safe_path(p: Path | str, allowed_roots: list[Path | str]) -> bool:
    r"""Verificar se o caminho resolvido está dentro de raízes permitidas.

    Bloqueia expressamente dotfiles, diretórios sensíveis (.ssh, .gnupg, .aws,
    .bashrc, etc.) e pastas do sistema (/etc, /var, /usr, etc. no Unix;
    C:\Windows, C:\Program Files, C:\ProgramData no Windows) e travessias
    com '..'. Caminhos UNC (\\servidor\compartilhamento) são sempre bloqueados.
    """
    # Caminhos do Windows são analisados com PureWindowsPath (funciona em
    # qualquer SO), sem tentar resolver como caminho POSIX. Ainda assim,
    # verifica symlinks via Path.is_symlink do objeto original (AppSec A-03).
    if _is_windows_path(p):
        p_path = Path(p) if isinstance(p, str) else p
        return _is_safe_windows_path(p_path, allowed_roots)

    try:
        p_path = Path(p) if isinstance(p, str) else p
        resolved = p_path.resolve(strict=False)
    except (OSError, ValueError, TypeError, AttributeError):
        return False

    # Verificar containment nas raízes permitidas.
    for root in allowed_roots:
        if not root or (isinstance(root, str) and not root.strip()):
            continue
        try:
            root_path = Path(root) if isinstance(root, str) else root
            root_resolved = root_path.resolve(strict=False)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        # Caminho está dentro de uma raiz permitida; agora verificar se
        # não é um caminho protegido internamente.
        try:
            rel = resolved.relative_to(root_resolved)
        except ValueError:
            rel = Path(".")
        # Verificar se algum componente do caminho relativo é sensível.
        for part in rel.parts:
            if part in _PROTECTED_NAMES or part.startswith("."):
                return False

        # Bloquear symlinks: o caminho em si e qualquer componente
        # intermediário relativo à raiz não podem ser symlinks (AppSec A-03).
        try:
            if p_path.is_symlink():
                return False
            rel_parts = resolved.relative_to(root_resolved).parts
            check_path = root_resolved
            for part in rel_parts:
                check_path = check_path / part
                if check_path.is_symlink():
                    return False
        except (OSError, ValueError):
            return False

        return True

    # Se não está em nenhuma raiz permitida, verificar se não é uma raiz do sistema.
    for sys_root in _SYSTEM_ROOTS:
        try:
            sys_resolved = sys_root.resolve(strict=False)
        except (OSError, ValueError):
            continue
        try:
            resolved.relative_to(sys_resolved)
            return False  # está dentro de uma pasta do sistema
        except ValueError:
            pass

    return False


class WebBridge(QObject):
    """Ponte QWebChannel exposta ao JavaScript como ``window.backend``."""

    pipelineEvent = Signal(str)
    pipelineFinished = Signal(str)
    sourceChanged = Signal(str)
    targetChanged = Signal(str)
    keyStatusChanged = Signal(bool)
    keyValidationResult = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        parent_widget: QWidget | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.parent_widget = parent_widget
        self.source_dir = ""
        self.target_dir = ""
        self.worker: PipelineWorker | None = None
        self.triage_service: ManualTriageService | None = None
        self._closing = False
        # Rate-limit leve: provedor -> lista de timestamps de tentativas inválidas (AppSec B-03)
        self._key_validation_attempts: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ #
    # Rate-limit leve de validação de chave (AppSec B-03)
    # ------------------------------------------------------------------ #

    def _rate_limit_window(self, provider: str, now: float, window_s: float = 60.0, max_invalid: int = 20) -> bool:
        """Retorna True se o provedor excedeu o limite de tentativas inválidas na janela."""
        attempts = self._key_validation_attempts.get(provider, [])
        # Mantém apenas tentativas dentro da janela deslizante
        recent = [t for t in attempts if now - t <= window_s]
        self._key_validation_attempts[provider] = recent
        return len(recent) >= max_invalid

    def _record_invalid_attempt(self, provider: str) -> None:
        now = time.monotonic()
        attempts = self._key_validation_attempts.get(provider, [])
        attempts.append(now)
        self._key_validation_attempts[provider] = attempts

    # ------------------------------------------------------------------ #
    # Estado inicial & Validação de Chaves
    # ------------------------------------------------------------------ #

    @Slot(str, result=str)
    def getProviderKeyStatus(self, provider: str) -> str:
        """Retorna o status da chave do provedor: 'valid', 'invalid' ou 'missing'."""
        prov = (provider or "").strip().lower()
        key = ""
        if prov == "gemini":
            key = resolve_gemini_api_key() or self.config.api_keys.gemini_api_key or ""
        elif prov == "groq":
            key = (
                self.config.api_keys.groq_api_key
                or os.getenv("TOMUS_GROQ_API_KEY")
                or os.getenv("GROQ_API_KEY")
                or ""
            )
        elif prov == "nvidia":
            key = (
                self.config.api_keys.nvidia_api_key
                or os.getenv("TOMUS_NVIDIA_API_KEY")
                or os.getenv("NVIDIA_API_KEY")
                or ""
            )
        elif prov == "deepseek":
            key = (
                self.config.api_keys.deepseek_api_key
                or os.getenv("TOMUS_DEEPSEEK_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY")
                or ""
            )
        elif prov == "claude":
            key = (
                self.config.api_keys.claude_api_key
                or os.getenv("TOMUS_CLAUDE_API_KEY")
                or os.getenv("CLAUDE_API_KEY")
                or os.getenv("ANTHROPIC_API_KEY")
                or ""
            )

        if isinstance(key, list):
            key = key[0] if key else ""
        key = str(key).strip()
        if not key:
            return "missing"

        first_token = key.split(",")[0].strip()
        try:
            ok, _ = validate_key_syntax(prov, first_token)
        except Exception:
            ok = False
        if not ok:
            self._record_invalid_attempt(prov)
            if self._rate_limit_window(prov, time.monotonic()):
                return "rate_limited"
        return "valid" if ok else "invalid"

    @Slot(str, result=bool)
    def checkProviderKey(self, provider: str) -> bool:
        """Verifica se o provedor especificado possui chave configurada e sintaticamente válida."""
        return self.getProviderKeyStatus(provider) == "valid"

    @Slot(result=str)
    def getInitialState(self) -> str:
        initial_provider = self.config.llm.provider or "gemini"
        has_key = self.checkProviderKey(initial_provider)
        from tomus.core.taxonomy import _load_taxonomy
        taxonomy = _load_taxonomy()
        return json.dumps({
            "source": self.source_dir,
            "target": self.target_dir,
            "provider": initial_provider,
            "hasKey": bool(has_key),
            "taxonomy": taxonomy,
        }, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # Seleção de Pastas
    # ------------------------------------------------------------------ #

    @Slot(result=str)
    def browseSource(self) -> str:
        path = QFileDialog.getExistingDirectory(
            self.parent_widget,
            "Selecionar Diretório de Origem dos PDFs",
            self.source_dir or str(Path.home()),
        )
        if path:
            self.source_dir = path
            self.sourceChanged.emit(path)
        return path or ""

    @Slot(result=str)
    def browseTarget(self) -> str:
        path = QFileDialog.getExistingDirectory(
            self.parent_widget,
            "Selecionar Diretório de Destino da Biblioteca",
            self.target_dir or str(Path.home()),
        )
        if path:
            self.target_dir = path
            self.targetChanged.emit(path)
        return path or ""

    # ------------------------------------------------------------------ #
    # Pipeline & Execução
    # ------------------------------------------------------------------ #

    @Slot(str)
    def startOrganize(self, params_json: str) -> None:
        try:
            params = json.loads(params_json)
        except Exception:
            params = {}

        source = Path(params.get("source_dir", self.source_dir))
        target = Path(params.get("target_dir", self.target_dir))
        provider_name = params.get("provider", "gemini")

        # SEN-05: containment de caminhos vindos do frontend via QWebChannel.
        # Rejeita caminhos fora das raízes autorizadas (pastas do usuário e
        # diretórios seguros padrão), prevenindo path traversal.
        _safe_roots = [
            Path(d) for d in (self.source_dir, self.target_dir) if d and str(d).strip()
        ] + list(_USER_SAFE_DIRS)
        if not _is_safe_path(source, _safe_roots):
            raise ValueError(f"Caminho de origem fora das raízes autorizadas: {source}")
        if not _is_safe_path(target, _safe_roots):
            raise ValueError(f"Caminho de destino fora das raízes autorizadas: {target}")
        file_operation = params.get("file_operation", "copy")
        recursive = bool(params.get("recursive", True))
        dry_run = bool(params.get("dry_run", False))

        self.source_dir = str(source)
        self.target_dir = str(target)

        # Clonar configuração e atualizar parâmetros
        cfg = AppConfig(**self.config.model_dump())
        cfg.general.file_operation = file_operation
        cfg.general.recursive = recursive
        cfg.llm.provider = provider_name

        model_defaults = {
            "gemini": "gemini-3.5-flash",
            "groq": "openai/gpt-oss-120b",
            "nvidia": "nvidia/nemotron-3.5-super-vl-120b-a12b",
            "deepseek": "deepseek-flash",
            "claude": "claude-haiku-5-5",
        }
        if provider_name in model_defaults:
            cfg.llm.model = model_defaults[provider_name]

        self.triage_service = ManualTriageService(target, cfg)

        workers = max(1, int(cfg.general.workers))
        use_cache = bool(cfg.general.use_cache)

        self.worker = PipelineWorker(
            source_dir=source,
            target_dir=target,
            config=cfg,
            dry_run=dry_run,
            use_cache=use_cache,
            workers=workers,
            parent=self,
        )
        self.worker.event_received.connect(self._on_worker_event)
        self.worker.pipeline_finished.connect(self._on_worker_finished)
        self.worker.pipeline_failed.connect(self._on_worker_failed)
        self.worker.start()

    @Slot()
    def cancelPipeline(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_cancel()

    def shutdown(self) -> None:
        """Encerra o bridge com segurança, evitando callbacks pendentes e
        deixando o worker para ser finalizado antes do fechamento da janela."""
        self._closing = True

        if self.worker is not None and self.worker.isRunning():
            self.worker.request_cancel()

            # Desconecta sinais com segurança para evitar reentrada
            try:
                self.worker.event_received.disconnect(self._on_worker_event)
            except (TypeError, RuntimeError):
                pass
            try:
                self.worker.pipeline_finished.disconnect(self._on_worker_finished)
            except (TypeError, RuntimeError):
                pass
            try:
                self.worker.pipeline_failed.disconnect(self._on_worker_failed)
            except (TypeError, RuntimeError):
                pass

            # Aguarda término graceful do worker
            if not self.worker.wait(3000):
                if self.worker.isRunning():
                    self.worker.terminate()
                    self.worker.wait(1000)

    @staticmethod
    def _safe_js_json(payload: Any) -> str:
        """Serializar payload para JSON seguro para injecao em runJavaScript.

        Escapa sequencias que podem quebrar o contexto de uma string literal JS
        embutida em HTML: ``</`` (quebra de tag script), ``\\u2028`` (Line
        Separator) e ``\\u2029`` (Paragraph Separator).
        """
        json_str = json.dumps(payload, ensure_ascii=False)
        json_str = json_str.replace("</", "\\u003c/")
        json_str = json_str.replace("\u2028", "\\u2028")
        json_str = json_str.replace("\u2029", "\\u2029")
        return json_str

    def _on_worker_event(self, event: PipelineEvent) -> None:
        if self._closing:
            return
        try:
            payload = event.model_dump()
            payload_json = self._safe_js_json(payload)
            self.pipelineEvent.emit(payload_json)

            # Invocação direta no V8 do Chromium para entrega imediata garantida
            if self.parent_widget and hasattr(self.parent_widget, "web_view"):
                js = f"if (window.handlePipelineEvent) {{ window.handlePipelineEvent({payload_json}); }}"
                self.parent_widget.web_view.page().runJavaScript(js)
        except Exception as exc:
            print(f"[WebBridge] Erro em _on_worker_event: {exc}", file=sys.stderr)

    def _on_worker_finished(self, summary: Any, was_cancelled: bool) -> None:
        if self._closing:
            return
        try:
            data = {
                "total_scanned": summary.total_scanned,
                "organized_count": summary.organized_count,
                "manual_review_count": summary.manual_review_count,
                "duplicate_skipped_count": summary.duplicate_skipped_count,
                "ignored_non_pdf_count": summary.ignored_non_pdf_count,
                "error_count": summary.error_count,
                "obsolete_count": summary.obsolete_count,
                "manual_review_ratio": summary.manual_review_ratio,
                "exceeded_manual_review_ceiling": summary.exceeded_manual_review_ceiling,
                "was_cancelled": was_cancelled,
            }
            data_json = self._safe_js_json(data)
            self.pipelineFinished.emit(data_json)

            if self.parent_widget and hasattr(self.parent_widget, "web_view"):
                js = f"if (window.handlePipelineFinished) {{ window.handlePipelineFinished({data_json}); }}"
                self.parent_widget.web_view.page().runJavaScript(js)
        except Exception as exc:
            print(f"[WebBridge] Erro em _on_worker_finished: {exc}", file=sys.stderr)

    def _on_worker_failed(self, error_msg: str) -> None:
        if self._closing:
            return
        try:
            data = {
                "error": error_msg,
                "was_cancelled": False,
            }
            data_json = self._safe_js_json(data)
            self.pipelineFinished.emit(data_json)

            if self.parent_widget and hasattr(self.parent_widget, "web_view"):
                js = f"if (window.handlePipelineFinished) {{ window.handlePipelineFinished({data_json}); }}"
                self.parent_widget.web_view.page().runJavaScript(js)
        except Exception as exc:
            print(f"[WebBridge] Erro em _on_worker_failed: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------ #
    # Ações Contextuais de Arquivos (Nativas macOS / Multiplataforma)
    # ------------------------------------------------------------------ #

    @Slot(str)
    def openPdf(self, path: str) -> None:
        if not path:
            return
        p = Path(path)
        if not p.exists():
            return
        roots = [
            Path(d) for d in (self.source_dir, self.target_dir) if d and str(d).strip()
        ] + list(_USER_SAFE_DIRS)
        if not _is_safe_path(p, roots):
            _logger.warning("rejeitado openPdf em caminho não seguro: %s", path)
            return
        p_resolved = p.resolve()
        # Delegar abertura ao adaptador multiplataforma (macOS/Linux/Windows),
        # preservando a validação de existência e _is_safe_path já feitas acima.
        open_file_in_os(p_resolved)

    @Slot(str, str, result=str)
    def validateProviderKey(self, provider: str, key: str) -> str:
        """Validar uma chave de provedor via chamada real à API (dry-run de 1 token).

        Retorna JSON: {'valid': True/False, 'error': ''/'mensagem clara'}.
        """
        from tomus.core.key_validator import validate_provider_key_live

        prov = (provider or "").strip().lower()
        key = (key or "").strip()
        if not key:
            result = json.dumps({"valid": False, "error": "Chave não informada"})
            self.keyValidationResult.emit(result)
            return result

        ok, msg = validate_provider_key_live(prov, key)
        if not ok:
            self._record_invalid_attempt(prov)
            if self._rate_limit_window(prov, time.monotonic()):
                result = json.dumps(
                    {"valid": False, "error": "Rate limite excedido. Tente novamente em 60 segundos."}
                )
                self.keyValidationResult.emit(result)
                return result
        result = json.dumps({"valid": ok, "error": "" if ok else msg})
        self.keyValidationResult.emit(result)
        return result

    @Slot(str)
    def revealPath(self, path: str) -> None:
        if not path:
            return
        p = Path(path)
        if not p.exists():
            return
        roots = [
            Path(d) for d in (self.source_dir, self.target_dir) if d and str(d).strip()
        ] + list(_USER_SAFE_DIRS)
        if not _is_safe_path(p, roots):
            _logger.warning("rejeitado revealPath em caminho não seguro: %s", path)
            return
        p_resolved = p.resolve()
        target = p_resolved if p_resolved.exists() else p_resolved.parent
        # Delegar revelação ao adaptador multiplataforma (macOS/Linux/Windows),
        # preservando a validação de existência e _is_safe_path já feitas acima.
        reveal_in_file_manager(target)

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:
        """Copiar texto para a área de transferência do sistema."""
        if not text:
            return
        try:
            from PySide6.QtGui import QGuiApplication

            cb = QGuiApplication.clipboard()
            if cb is not None:
                cb.setText(text)
        except Exception as exc:  # pragma: no cover - dependente do ambiente Qt
            print(f"[WebBridge] Falha ao copiar para área de transferência: {exc}", file=sys.stderr)

    @Slot(str)
    def openExternalUrl(self, url: str) -> None:
        """Abrir link ou documentação externa no navegador padrão do sistema.

        Apenas esquemas http e https são permitidos. Qualquer outro esquema
        (file, smb, javascript, data, ftp, about, chrome, qrc, etc.) é rejeitado
        e logado, prevenindo abertura de arquivos locais e execução de código
        remoto via navegador.
        """
        if not url:
            return
        esquema = QUrl(url).scheme().lower()
        if esquema not in ("http", "https"):
            _logger.warning(
                "openExternalUrl rejeitado: esquema '%s' não permitido em url=%s",
                esquema,
                url,
            )
            return
        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------------ #
    # Triagem Manual Assistida
    # ------------------------------------------------------------------ #

    @Slot(str, result=str)
    def approveManualTriage(self, triage_json: str) -> str:
        if not self.triage_service:
            target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
            if target and Path(target).exists():
                self.triage_service = ManualTriageService(target, self.config)
            else:
                return json.dumps({"success": False, "error": "Serviço de triagem indisponível"})
        try:
            data = json.loads(triage_json)
            entry = FileManifestEntry(
                source_path=data["source_path"],
                destination_path=data.get("destination_path"),
                sha256=data.get("sha256", ""),
                status=ProcessStatus.MANUAL_REVIEW,
            )
            area_basica = (data.get("area_basica") or "Outros").strip()
            grande_area = data.get("grande_area")
            if not grande_area or grande_area == "Outros":
                from tomus.core.taxonomy import _build_area_to_grande_area
                mapping = _build_area_to_grande_area()
                grande_area = mapping.get(area_basica, "Outros")
            subarea = (data.get("subarea") or "").strip() or "Geral"

            updated = self.triage_service.approve_and_materialize(
                entry=entry,
                grande_area=grande_area,
                area_basica=area_basica,
                subarea=subarea,
                tipo=data.get("tipo", "Outros"),
                title=data.get("title", ""),
                subtitle=data.get("subtitle", ""),
                authors=data.get("authors") or [],
                year=int(data["year"]) if data.get("year") else None,
            )
            # Notificar o frontend com evento de atualização
            event = PipelineEvent(
                stage="organizer",
                source_path=updated.source_path,
                destination_path=updated.destination_path,
                sha256=updated.sha256,
                status=ProcessStatus.ORGANIZED.value,
                message=f"Aprovado manualmente: {Path(updated.destination_path or '').name}",
                classification=updated.classification,
            )
            self._on_worker_event(event)
            return json.dumps({"success": True})
        except Exception as exc:
            safe = _sanitize_error_message(str(exc))
            print(f"[WebBridge] Erro na triagem manual: {safe}")
            return json.dumps({"success": False, "error": safe})

    @Slot(result=str)
    def undoManualTriage(self) -> str:
        """Desfazer a última aprovação manual de triagem."""
        if not self.triage_service:
            return json.dumps({"success": False, "message": "Serviço de triagem indisponível"})
        ok, msg = self.triage_service.undo_last_approval()
        return json.dumps({"success": ok, "message": msg})

    # ------------------------------------------------------------------ #
    # Revisão Manual - Listagem e Promoção (FEAT-TRIAGE-01)
    # ------------------------------------------------------------------ #

    @Slot(result=str)
    def listManualReviewItems(self) -> str:
        """Listar itens pendentes na pasta revisao_manual/."""
        target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
        if not target or not Path(target).exists():
            return json.dumps({"success": True, "itens": []})
        try:
            from tomus.storage.organizer import LibraryOrganizer
            org = LibraryOrganizer(target)
            itens = org.list_manual_review_items()
            return json.dumps({"success": True, "itens": itens}, ensure_ascii=False)
        except Exception as exc:  # pragma: no cover - defesa geral
            safe = _sanitize_error_message(str(exc))
            print(f"[WebBridge] Erro ao listar revisão manual: {safe}")
            return json.dumps({"success": False, "error": safe, "itens": []})

    @Slot(str, result=str)
    def promoteFromManualReview(self, promo_json: str) -> str:
        """Promover um item de revisao_manual para a árvore definitiva.

        Não reclassifica via LLM. Recusa com motivo claro se campos
        obrigatórios estiverem incompletos.
        """
        target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
        if not target or not Path(target).exists():
            return json.dumps({"success": False, "error": "Diretório de destino não configurado"})
        try:
            data = json.loads(promo_json)
            source_path = data.get("source_path")
            classificacao = data.get("classificacao")
            motivo_promocao = data.get("motivo_promocao", "Promovido manualmente pelo usuário")
            usuario_responsavel = data.get("usuario_responsavel", "local")

            from tomus.storage.organizer import LibraryOrganizer
            org = LibraryOrganizer(target)
            entry = org.promote_from_manual_review(
                source_path=source_path,
                classificacao=classificacao,
                motivo_promocao=motivo_promocao,
                usuario_responsavel=usuario_responsavel,
            )
            # Notificar o frontend com evento de atualização
            event = PipelineEvent(
                stage="organizer",
                source_path=entry.source_path,
                destination_path=entry.destination_path,
                sha256=entry.sha256,
                status=ProcessStatus.ORGANIZED.value,
                message=f"Promovido de revisão manual: {Path(entry.destination_path or '').name}",
                classification=entry.classification,
            )
            self._on_worker_event(event)
            return json.dumps({"success": True, "destination_path": str(entry.destination_path or "")})
        except ValueError as exc:
            # Recusa com motivo claro (campos obrigatórios incompletos)
            return json.dumps({"success": False, "error": str(exc), "recusado": True})
        except Exception as exc:  # pragma: no cover - defesa geral
            safe = _sanitize_error_message(str(exc))
            print(f"[WebBridge] Erro ao promover revisão manual: {safe}")
            return json.dumps({"success": False, "error": safe})

    # ------------------------------------------------------------------ #
    # Auditoria de Biblioteca (FEAT-AUDIT-01)
    # ------------------------------------------------------------------ #

    @Slot(result=str)
    def auditLibrary(self) -> str:
        """Auditor read-only de toda a biblioteca organizada.

        Identifica problemas de integridade sem gravar nada no disco.
        Retorna resumo e lista de itens com problemas e ação sugerida.
        """
        target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
        if not target or not Path(target).exists():
            return json.dumps({"success": False, "error": "Diretório de destino não configurado", "itens": [], "resumo": {}})
        try:
            from tomus.storage.organizer import LibraryOrganizer
            org = LibraryOrganizer(target)
            resultado = org.auditar_biblioteca(target)
            return json.dumps({"success": True, **resultado}, ensure_ascii=False)
        except Exception as exc:  # pragma: no cover - defesa geral
            safe = _sanitize_error_message(str(exc))
            print(f"[WebBridge] Erro ao auditar biblioteca: {safe}")
            return json.dumps({"success": False, "error": safe, "itens": [], "resumo": {}})

    @Slot(str, result=str)
    def recolocarNaFila(self, source_path: str) -> str:
        """Encaminhar um item para a fila de classificação (revisao_manual).

        Ação explícita do usuário — nunca executada automaticamente.
        Copia o PDF para revisao_manual/ e gera o .md companheiro com motivo
        de auditoria.
        """
        target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
        if not target or not Path(target).exists():
            return json.dumps({"success": False, "error": "Diretório de destino não configurado"})
        try:
            from tomus.storage.organizer import LibraryOrganizer
            org = LibraryOrganizer(target)
            entry = org.recolocar_na_fila(Path(source_path))
            event = PipelineEvent(
                stage="organizer",
                source_path=entry.source_path,
                destination_path=entry.destination_path,
                sha256=entry.sha256,
                status=ProcessStatus.MANUAL_REVIEW.value,
                message=f"Enviado para fila de classificação (auditoria): {Path(entry.source_path or '').name}",
                classification=entry.classification,
            )
            self._on_worker_event(event)
            return json.dumps({"success": True, "destination_path": str(entry.destination_path or "")})
        except Exception as exc:  # pragma: no cover - defesa geral
            safe = _sanitize_error_message(str(exc))
            print(f"[WebBridge] Erro ao recolocar na fila: {safe}")
            return json.dumps({"success": False, "error": safe})

    @Slot(str, str, result=str)
    def confirmarIntegridade(self, item_caminho_rel: str, usuario_responsavel: str = "local") -> str:
        """Confirmar integrência de um item no bloco de auditoria do companion.

        Atualiza o front matter do .md companheiro com uma transição de
        auditoria "organizado -> confirmado". Ação explícita do usuário.
        """
        target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
        if not target or not Path(target).exists():
            return json.dumps({"success": False, "error": "Diretório de destino não configurado"})
        try:
            from tomus.storage.organizer import LibraryOrganizer
            org = LibraryOrganizer(target)
            org.confirmar_integridade(item_caminho_rel, usuario_responsavel=usuario_responsavel)
            return json.dumps({"success": True, "message": "Integridade confirmada com sucesso"})
        except FileNotFoundError as exc:
            return json.dumps({"success": False, "error": str(exc)})
        except ValueError as exc:
            return json.dumps({"success": False, "error": str(exc)})
        except Exception as exc:  # pragma: no cover - defesa geral
            safe = _sanitize_error_message(str(exc))
            print(f"[WebBridge] Erro ao confirmar integridade: {safe}")
            return json.dumps({"success": False, "error": safe})

    # ------------------------------------------------------------------ #
    # Preferências & Cache
    # ------------------------------------------------------------------ #

    @Slot()
    def openPreferences(self) -> None:
        from tomus.gui.widgets.preferences_dialog import PreferencesDialog

        dlg = PreferencesDialog(self.config, parent=self.parent_widget)
        if dlg.exec():
            # Recarregar AppConfig a partir do disco para sincronização total
            from tomus.core.config import AppConfig

            self.config = AppConfig()

            # Atualizar status da chave para o provedor selecionado
            current_provider = self.config.llm.provider or "gemini"
            has_key = self.checkProviderKey(current_provider)
            self.keyStatusChanged.emit(bool(has_key))

    @Slot()
    def openCacheDialog(self) -> None:
        try:
            from tomus.core.cache import FileCache

            cache = FileCache(enabled=True)
            total = cache.count()
            db_path = str(cache.db_path)

            box = QMessageBox(self.parent_widget)
            box.setWindowTitle("Gerenciamento de Cache — Tomus")
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(f"Entradas ativas no cache SQLite: {total}\nLocalização: {db_path}")

            btn_clear = box.addButton("Esvaziar Cache", QMessageBox.ButtonRole.DestructiveRole)
            btn_close = box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_close)

            box.setStyleSheet("""
                QMessageBox {
                    background-color: #FFFFFF;
                }
                QLabel {
                    color: #0F172A;
                    font-size: 13px;
                    background-color: transparent;
                }
                QPushButton {
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-size: 13px;
                    font-weight: 500;
                }
            """)
            btn_clear.setStyleSheet("background-color: #DC2626; color: #FFFFFF; border: none; font-weight: 600; padding: 6px 14px;")
            btn_close.setStyleSheet("background-color: #1E3A8A; color: #FFFFFF; border: none; font-weight: 600; padding: 6px 18px;")

            box.exec()

            if box.clickedButton() == btn_clear:
                confirm = QMessageBox(self.parent_widget)
                confirm.setWindowTitle("Confirmar Limpeza")
                confirm.setIcon(QMessageBox.Icon.Warning)
                confirm.setText(f"Deseja realmente apagar todas as {total} entradas salvas no cache?\n\nIsso forçará a reclassificação completa de todos os PDFs em futuras execuções.")
                btn_yes = confirm.addButton("Sim, Esvaziar", QMessageBox.ButtonRole.YesRole)
                btn_no = confirm.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
                confirm.setDefaultButton(btn_no)
                confirm.setStyleSheet("QMessageBox { background-color: #FFFFFF; } QLabel { color: #0F172A; font-size: 13px; }")
                btn_yes.setStyleSheet("background-color: #DC2626; color: #FFFFFF; border: none; border-radius: 6px; padding: 6px 14px; font-weight: 600;")
                btn_no.setStyleSheet("background-color: #F1F5F9; color: #0F172A; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 14px; font-weight: 500;")
                confirm.exec()
                if confirm.clickedButton() == btn_yes:
                    cache.clear()
                    success_box = QMessageBox(self.parent_widget)
                    success_box.setWindowTitle("Cache Limpo")
                    success_box.setIcon(QMessageBox.Icon.Information)
                    success_box.setText("O cache foi esvaziado com sucesso.")
                    success_box.setStyleSheet("QMessageBox { background-color: #FFFFFF; } QLabel { color: #0F172A; }")
                    success_box.exec()
            cache.close()
        except Exception as exc:
            print(f"[WebBridge] Erro ao abrir diálogo de cache: {exc}", file=sys.stderr)
            box = QMessageBox(self.parent_widget)
            box.setWindowTitle("Aviso de Cache")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"Não foi possível gerenciar o cache:\n{exc}")
            box.setStyleSheet("QMessageBox { background-color: #FFFFFF; } QLabel { color: #0F172A; }")
            box.exec()
