"""Janela principal da bancada desktop do Tomus baseada em QWebEngineView.

Hospeda a interface moderna HTML5/CSS (Mockup 1 / Dribbble Aesthetics) com
comunicação bidirecional nativa via QWebChannel para o motor Python.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from tomus.core.config import AppConfig
from tomus.gui.bridge import WebBridge

_logger = logging.getLogger("tomus.gui.main_window")

__all__ = ["TomusMainWindow"]

_MIN_SIZE = (1080, 680)
_DEFAULT_SIZE = (1360, 840)


class TomusWebPage(QWebEnginePage):
    """Página customizada que repassa logs e erros do console JS para o terminal Python."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._verbose = False

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        src_name = Path(sourceID).name if sourceID else "inline"
        # Imprimir logs de console JS apenas em modo verbose para evitar
        # vazamento acidental de dados sensíveis no terminal.
        if self._verbose:
            print(f"[Tomus-JS] ({src_name}:{lineNumber}) {message}")


class TomusMainWindow(QMainWindow):
    """Janela principal do Tomus com casca Web moderna e motor Python."""

    def __init__(
        self,
        config: AppConfig,
        source_dir: Path | str | None = None,
        target_dir: Path | str | None = None,
        parent: QWidget | None = None,
        verbose: bool = False,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._source_dir = Path(source_dir) if source_dir else None
        self._target_dir = Path(target_dir) if target_dir else None
        self._verbose = verbose

        self.setWindowTitle("Tomus — Organizador Acadêmico de PDFs")
        self.setMinimumSize(*_MIN_SIZE)
        self.resize(*_DEFAULT_SIZE)

        self.bridge = WebBridge(self._config, parent_widget=self, parent=self)
        if self._source_dir:
            self.bridge.source_dir = str(self._source_dir)
        if self._target_dir:
            self.bridge.target_dir = str(self._target_dir)

        # Configurar WebEngineView com página de logging personalizada e fallback defensivo
        try:
            self.web_page = TomusWebPage(self)
            self.web_page._verbose = verbose
            self.web_view = QWebEngineView(self)
            self.web_view.setPage(self.web_page)
            self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.setCentralWidget(self.web_view)

            # Configurar QWebChannel e Ponte Python <-> JS
            self.channel = QWebChannel(self.web_page)
            self.channel.registerObject("backend", self.bridge)
            self.web_page.setWebChannel(self.channel)

            # Carregar interface HTML5 (compatível com desenvolvimento local e bundle PyInstaller)
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                meipass = Path(sys._MEIPASS)
                candidates = [
                    meipass / "tomus" / "gui" / "web",
                    meipass / "web",
                    Path(__file__).parent / "web",
                ]
                web_dir = next((p for p in candidates if p.exists()), candidates[0])
            else:
                web_dir = Path(__file__).parent / "web"

            index_file = web_dir / "index.html"
            self.web_view.load(QUrl.fromLocalFile(str(index_file.resolve())))
        except Exception:
            # Fallback seguro para ambientes headless ou sem suporte a Chromium
            self.web_page = None
            self.web_view = QWidget(self)
            self.setCentralWidget(self.web_view)
            self.channel = None

        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Drag & Drop de pastas nativo
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        p = Path(path)
        if p.is_dir():
            if not self.bridge.source_dir:
                self.bridge.source_dir = str(p)
                self.bridge.sourceChanged.emit(str(p))
            else:
                self.bridge.target_dir = str(p)
                self.bridge.targetChanged.emit(str(p))
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        """Encerramento limpo da janela: para o pipeline, desmonta o
        QtWebEngine de forma determinística e evita processos órfãos
        (Tomus.exe / QtWebEngineProcess.exe) no Windows."""
        # 1. Encerra o bridge e pede cancelamento graceful do worker
        try:
            self.bridge.shutdown()
        except Exception:
            _logger.warning("Falha ao encerrar bridge no closeEvent", exc_info=True)

        # 2. Desmonta o QtWebEngine em ordem determinística
        try:
            if getattr(self, 'web_view', None) and hasattr(self.web_view, 'stop'):
                self.web_view.stop()
        except Exception:
            _logger.warning("Falha ao parar web_view no closeEvent", exc_info=True)

        try:
            if getattr(self, 'channel', None) is not None:
                self.channel.deregisterObject(self.bridge)
        except Exception:
            _logger.warning("Falha ao deregistrar objeto do WebChannel", exc_info=True)

        try:
            if getattr(self, 'web_page', None) is not None:
                self.web_page.setWebChannel(None)
        except Exception:
            _logger.warning("Falha ao limpar WebChannel da página", exc_info=True)

        try:
            if getattr(self, 'web_view', None) and hasattr(self.web_view, 'setPage'):
                self.web_view.setPage(None)
        except Exception:
            _logger.warning("Falha ao limpar página da web_view", exc_info=True)

        try:
            if getattr(self, 'web_page', None) is not None:
                self.web_page.deleteLater()
                self.web_page = None
        except Exception:
            _logger.warning("Falha ao deletar web_page", exc_info=True)

        try:
            if getattr(self, 'web_view', None) is not None:
                self.web_view.deleteLater()
        except Exception:
            _logger.warning("Falha ao deletar web_view", exc_info=True)

        # 3. Garante que a aplicação encerre quando a última janela fechar
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)

        # Garante liberação determinística do QWebEnginePage no event loop
        # antes de encerrar (AppSec B-02).
        try:
            if app is not None:
                app.processEvents()
                app.processEvents()
        except Exception:
            _logger.warning("Falha ao processar eventos do QApplication no closeEvent", exc_info=True)

        event.accept()
        super().closeEvent(event)
