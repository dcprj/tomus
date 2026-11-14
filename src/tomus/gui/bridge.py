"""Ponte de comunicação bidirecional (QWebChannel) entre Python e o frontend Web.

Permite que a interface HTML5/CSS moderna invoque métodos do motor
e receba eventos de streaming de processamento em tempo real.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from tomus.core.config import AppConfig
from tomus.core.models import FileManifestEntry, PipelineEvent, ProcessStatus
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

# Pastas do sistema que nunca devem ser expostas.
_SYSTEM_ROOTS = (
    Path("/etc"),
    Path("/var"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/boot"),
    Path("/root"),
)


def _is_safe_path(p: Path | str, allowed_roots: list[Path | str]) -> bool:
    """Verificar se o caminho resolvido está dentro de raízes permitidas.

    Bloqueia expressamente dotfiles, diretórios sensíveis (.ssh, .gnupg, .aws,
    .bashrc, etc.) e pastas do sistema (/etc, /var, /usr, etc.) e travessias
    com '..'.
    """
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

    # ------------------------------------------------------------------ #
    # Estado inicial & Validação de Chaves
    # ------------------------------------------------------------------ #

    @Slot(str, result=str)
    def getProviderKeyStatus(self, provider: str) -> str:
        """Retorna o status da chave do provedor: 'valid', 'invalid' ou 'missing'."""
        import os
        from tomus.core.key_validator import validate_key_syntax

        prov = (provider or "").strip().lower()
        key = ""
        if prov == "gemini":
            key = (
                self.config.api_keys.gemini_api_key
                or os.getenv("TOMUS_GEMINI_API_KEY")
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("BIBLIOTEC_GEMINI_API_KEY")
                or ""
            )
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
        ok, _ = validate_key_syntax(prov, first_token)
        return "valid" if ok else "invalid"

    @Slot(str, result=bool)
    def checkProviderKey(self, provider: str) -> bool:
        """Verifica se o provedor especificado possui chave configurada e sintaticamente válida."""
        return self.getProviderKeyStatus(provider) == "valid"

    @Slot(result=str)
    def getInitialState(self) -> str:
        initial_provider = self.config.llm.provider or "gemini"
        has_key = self.checkProviderKey(initial_provider)
        return json.dumps({
            "source": self.source_dir,
            "target": self.target_dir,
            "provider": initial_provider,
            "hasKey": bool(has_key),
        })

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
            "nvidia": "meta/llama-3.2-90b-vision-instruct",
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

    def _on_worker_event(self, event: PipelineEvent) -> None:
        try:
            payload = event.model_dump()
            payload_json = json.dumps(payload, ensure_ascii=False)
            self.pipelineEvent.emit(payload_json)

            # Invocação direta no V8 do Chromium para entrega imediata garantida
            if self.parent_widget and hasattr(self.parent_widget, "web_view"):
                js = f"if (window.handlePipelineEvent) {{ window.handlePipelineEvent({payload_json}); }}"
                self.parent_widget.web_view.page().runJavaScript(js)
        except Exception as exc:
            print(f"[WebBridge] Erro em _on_worker_event: {exc}", file=sys.stderr)

    def _on_worker_finished(self, summary: Any, was_cancelled: bool) -> None:
        try:
            data = {
                "total_scanned": summary.total_scanned,
                "organized_count": summary.organized_count,
                "manual_review_count": summary.manual_review_count,
                "duplicate_skipped_count": summary.duplicate_skipped_count,
                "ignored_non_pdf_count": summary.ignored_non_pdf_count,
                "error_count": summary.error_count,
                "manual_review_ratio": summary.manual_review_ratio,
                "exceeded_manual_review_ceiling": summary.exceeded_manual_review_ceiling,
                "was_cancelled": was_cancelled,
            }
            data_json = json.dumps(data, ensure_ascii=False)
            self.pipelineFinished.emit(data_json)

            if self.parent_widget and hasattr(self.parent_widget, "web_view"):
                js = f"if (window.handlePipelineFinished) {{ window.handlePipelineFinished({data_json}); }}"
                self.parent_widget.web_view.page().runJavaScript(js)
        except Exception as exc:
            print(f"[WebBridge] Erro em _on_worker_finished: {exc}", file=sys.stderr)

    def _on_worker_failed(self, error_msg: str) -> None:
        try:
            data = {
                "error": error_msg,
                "was_cancelled": False,
            }
            data_json = json.dumps(data, ensure_ascii=False)
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
        ] + [Path.home()] + list(_USER_SAFE_DIRS)
        if not _is_safe_path(p, roots):
            _logger.warning("rejeitado openPdf em caminho não seguro: %s", path)
            return
        p_resolved = p.resolve()
        if sys.platform == "darwin":
            # Abrir 100% infalível no leitor padrão do macOS via 'open'.
            subprocess.Popen(["open", str(p_resolved)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p_resolved)))

    @Slot(str, str, result=str)
    def validateProviderKey(self, provider: str, key: str) -> str:
        """Validar uma chave de provedor via chamada real à API (dry-run de 1 token).

        Retorna JSON: {'valid': True/False, 'error': ''/'mensagem clara'}.
        """
        from tomus.core.key_validator import validate_provider_key_live

        prov = (provider or "").strip().lower()
        key = (key or "").strip()
        if not key:
            result = _json.dumps({"valid": False, "error": "Chave não informada"})
            self.keyValidationResult.emit(result)
            return result

        ok, msg = validate_provider_key_live(prov, key)
        result = _json.dumps({"valid": ok, "error": "" if ok else msg})
        self.keyValidationResult.emit(result)
        return result

    def _validate_gemini(self, api_key: str) -> str:
        """Validar chave Gemini fazendo uma chamada mínima à API."""
        import httpx
        import json as _json

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": api_key},
                )
                if resp.status_code == 200:
                    return _json.dumps({"valid": True, "error": ""})
                elif resp.status_code in (400, 403):
                    return _json.dumps(
                        {"valid": False, "error": "Chave Gemini inválida ou não autorizada"}
                    )
                else:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": f"Erro HTTP {resp.status_code} validando chave Gemini",
                        }
                    )
        except httpx.ConnectError:
            return _json.dumps(
                {"valid": False, "error": "Não foi possível conectar à API do Gemini"}
            )
        except httpx.TimeoutException:
            return _json.dumps(
                {"valid": False, "error": "Timeout ao validar chave Gemini"}
            )
        except Exception as exc:
            return _json.dumps({"valid": False, "error": str(exc)})

    def _validate_groq(self, api_key: str) -> str:
        """Validar chave Groq fazendo uma chamada mínima à API."""
        import httpx
        import json as _json

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    return _json.dumps({"valid": True, "error": ""})
                elif resp.status_code == 401:
                    return _json.dumps(
                        {"valid": False, "error": "Chave Groq inválida ou não autorizada"}
                    )
                else:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": f"Erro HTTP {resp.status_code} validando chave Groq",
                        }
                    )
        except httpx.ConnectError:
            return _json.dumps({"valid": False, "error": "Não foi possível conectar à API do Groq"})
        except httpx.TimeoutException:
            return _json.dumps({"valid": False, "error": "Timeout ao validar chave Groq"})
        except Exception as exc:
            return _json.dumps({"valid": False, "error": str(exc)})

    def _validate_nvidia(self, api_key: str) -> str:
        """Validar chave NVIDIA NIM fazendo uma chamada mínima à API."""
        import httpx
        import json as _json

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    return _json.dumps({"valid": True, "error": ""})
                elif resp.status_code == 401:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": "Chave NVIDIA NIM inválida ou não autorizada",
                        }
                    )
                else:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": f"Erro HTTP {resp.status_code} validando chave NVIDIA",
                        }
                    )
        except httpx.ConnectError:
            return _json.dumps(
                {"valid": False, "error": "Não foi possível conectar à API da NVIDIA NIM"}
            )
        except httpx.TimeoutException:
            return _json.dumps({"valid": False, "error": "Timeout ao validar chave NVIDIA NIM"})
        except Exception as exc:
            return _json.dumps({"valid": False, "error": str(exc)})

    def _validate_deepseek(self, api_key: str) -> str:
        """Validar chave DeepSeek fazendo uma chamada mínima à API."""
        import httpx
        import json as _json

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    return _json.dumps({"valid": True, "error": ""})
                elif resp.status_code == 401:
                    return _json.dumps(
                        {"valid": False, "error": "Chave DeepSeek inválida ou não autorizada"}
                    )
                else:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": f"Erro HTTP {resp.status_code} validando chave DeepSeek",
                        }
                    )
        except httpx.ConnectError:
            return _json.dumps(
                {"valid": False, "error": "Não foi possível conectar à API da DeepSeek"}
            )
        except httpx.TimeoutException:
            return _json.dumps({"valid": False, "error": "Timeout ao validar chave DeepSeek"})
        except Exception as exc:
            return _json.dumps({"valid": False, "error": str(exc)})

    def _validate_claude(self, api_key: str) -> str:
        """Validar chave Anthropic Claude fazendo uma chamada mínima à API."""
        import httpx
        import json as _json

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    return _json.dumps({"valid": True, "error": ""})
                elif resp.status_code == 401:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": "Chave Anthropic Claude inválida ou não autorizada",
                        }
                    )
                else:
                    return _json.dumps(
                        {
                            "valid": False,
                            "error": f"Erro HTTP {resp.status_code} validando chave Claude",
                        }
                    )
        except httpx.ConnectError:
            return _json.dumps(
                {"valid": False, "error": "Não foi possível conectar à API da Anthropic Claude"}
            )
        except httpx.TimeoutException:
            return _json.dumps({"valid": False, "error": "Timeout ao validar chave Claude"})
        except Exception as exc:
            return _json.dumps({"valid": False, "error": str(exc)})

    @Slot(str)
    def revealPath(self, path: str) -> None:
        if not path:
            return
        p = Path(path)
        if not p.exists():
            return
        roots = [
            Path(d) for d in (self.source_dir, self.target_dir) if d and str(d).strip()
        ] + [Path.home()] + list(_USER_SAFE_DIRS)
        if not _is_safe_path(p, roots):
            _logger.warning("rejeitado revealPath em caminho não seguro: %s", path)
            return
        p_resolved = p.resolve()
        target = p_resolved if p_resolved.exists() else p_resolved.parent
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        elif sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{target}"])
        else:
            subprocess.run(["xdg-open", str(target)])

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
        """Abrir link ou documentação externa no navegador padrão do sistema."""
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------------ #
    # Triagem Manual Assistida
    # ------------------------------------------------------------------ #

    @Slot(str, result=bool)
    def approveManualTriage(self, triage_json: str) -> bool:
        if not self.triage_service:
            target = getattr(self, "target_dir", None) or getattr(self.config.general, "target_dir", None)
            if target and Path(target).exists():
                self.triage_service = ManualTriageService(target, self.config)
            else:
                return False
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
            return True
        except Exception as exc:
            print(f"[WebBridge] Erro na triagem manual: {exc}")
            return False

    @Slot(result=str)
    def undoManualTriage(self) -> str:
        """Desfazer a última aprovação manual de triagem."""
        if not self.triage_service:
            return json.dumps({"success": False, "message": "Serviço de triagem indisponível"})
        ok, msg = self.triage_service.undo_last_approval()
        return json.dumps({"success": ok, "message": msg})

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
