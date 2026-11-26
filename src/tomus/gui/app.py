"""Ponto de entrada da GUI do Tomus (PySide6 / Qt6 Fusion).

Implementa ``launch_gui()`` e ``main()`` (registro em ``pyproject.toml`` como
``tomus-gui = "tomus.gui.app:main"``).

A importação de PySide6 ocorre apenas quando a GUI é invocada, preservando a
execução headless do motor (CLI sem depender de Qt).

Inclui proteções defensivas para inicialização do ``QWebEnginePage`` em
bundles macOS (.app) via ``sys.frozen`` (evita crash SIGABRT no sandbox do
QtWebEngine) e define o ícone oficial da aplicação.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from tomus.core.config import AppConfig
from tomus.core.logging import setup_logging

__all__ = ["launch_gui", "main", "run_self_test_ocr"]

# Caminho do ícone oficial da aplicação (marca Tomus, PNG em alta resolução; fallback para SVG).
_RES_DIR = Path(__file__).parent / "resources"
ICON_PATH = _RES_DIR / "tomus_icon.png" if (_RES_DIR / "tomus_icon.png").exists() else _RES_DIR / "tomus_icon.svg"


def _apply_webengine_defenses() -> None:
    """Aplicar variáveis de ambiente defensivas para QWebEnginePage no macOS e bundles.

    Em ambientes congelados (PyInstaller), o QtWebEngine pode falhar
    com SIGABRT devido a restrições do WindowServer (HIServices) ou
    caminhos incorretos do processo auxiliar. Apontar
    ``QTWEBENGINEPROCESS_PATH`` para o binário dentro do bundle
    (``sys._MEIPASS``) garante que o processo auxiliar seja encontrado.

    O sandbox do Chromium é reativado no macOS (sys.platform == "darwin")
    quando o bundle está devidamente assinado com entitlements Apple.
    No Windows congelado, ``QTWEBENGINE_DISABLE_SANDBOX`` é mantido para
    compatibilidade com o comportamento atual do QtWebEngine em bundles
    não assinados.

    Chamado *antes* de qualquer instância de QApplication / QWebEnginePage.
    """
    if sys.platform == "darwin":
        # No macOS (congelado ou não): manter sandbox ativo (não desabilitar)
        # para permitir o sandbox do Chromium com entitlements Apple.
        pass
    else:
        # Windows e outros SOs congelados: manter comportamento existente
        # para evitar regressão em bundles não assinados.
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

    if getattr(sys, "frozen", False):
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        if meipass and meipass.exists():
            # Caminho canônico do QtWebEngineProcess dentro do bundle congelado.
            # O PyInstaller preserva a estrutura relativa dos arquivos coletados.
            candidate_paths = [
                meipass / "PySide6" / "Qt" / "lib" / "QtWebEngineCore.framework" / "Versions" / "Resources" / "Helpers" / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess",
                meipass / "PySide6" / "QtWebEngineCore.framework" / "Versions" / "Resources" / "Helpers" / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess",
                meipass / "QtWebEngineProcess",
                meipass / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess",
            ]
            if sys.platform == "win32":
                # No Windows, o QtWebEngineProcess é um executável .exe distribuído
                # dentro da pasta PySide6 (ou raiz) do bundle congelado (PyInstaller).
                candidate_paths.extend(
                    [
                        meipass / "PySide6" / "QtWebEngineProcess.exe",
                        meipass / "PySide6" / "Qt" / "bin" / "QtWebEngineProcess.exe",
                        meipass / "QtWebEngineProcess.exe",
                    ]
                )
            for candidate in candidate_paths:
                if candidate.exists():
                    # QTWEBENGINEPROCESS_PATH (sem underscore) é o nome esperado pelo Qt.
                    os.environ.setdefault("QTWEBENGINEPROCESS_PATH", str(candidate))
                    # Também define QTWEBENGINE_PROCESS_PATH (com underscore) para
                    # máxima compatibilidade com diferentes versões do Qt.
                    os.environ.setdefault("QTWEBENGINE_PROCESS_PATH", str(candidate))
                    break

            # Definir QTWEBENGINE_RESOURCES_PATH para os arquivos .pak e icudtl.dat.
            # O QtWebEngine precisa desses arquivos para renderizar páginas web.
            resources_candidates = [
                meipass / "PySide6" / "Qt" / "lib" / "QtWebEngineCore.framework" / "Versions" / "Resources" / "Resources",
                meipass / "PySide6" / "QtWebEngineCore.framework" / "Versions" / "Resources" / "Resources",
            ]
            if sys.platform == "win32":
                # No Windows, os recursos do WebEngine (.pak / icudtl.dat) ficam em
                # pastas "resources" diretas do PySide6 (ou raiz do bundle congelado).
                resources_candidates.extend(
                    [
                        meipass / "PySide6" / "resources",
                        meipass / "PySide6" / "Qt" / "resources",
                        meipass / "resources",
                    ]
                )
            for resources_path in resources_candidates:
                if resources_path.exists() and (resources_path / "qtwebengine_resources.pak").exists():
                    os.environ.setdefault("QTWEBENGINE_RESOURCES_PATH", str(resources_path))
                    # Também definir QTWEBENGINE_LOCALES_PATH para as traduções de locale.
                    locales_path = resources_path / "qtwebengine_locales"
                    if locales_path.exists() and (locales_path / "en-US.pak").exists():
                        os.environ.setdefault("QTWEBENGINE_LOCALES_PATH", str(locales_path))
                    # No Windows, também buscar qtwebengine_locales em
                    # PySide6/translations/qtwebengine_locales (padrão da roda PySide6 no Windows).
                    if sys.platform == "win32":
                        translations_locales = meipass / "PySide6" / "translations" / "qtwebengine_locales"
                        if translations_locales.exists() and (translations_locales / "en-US.pak").exists():
                            os.environ.setdefault("QTWEBENGINE_LOCALES_PATH", str(translations_locales))
                    break


def run_self_test_ocr(pdf_path: str | Path | None = None) -> int:
    """Executar auto-teste headless de OCR (sem Qt/QApplication).

    :param pdf_path: caminho opcional de um PDF. Quando omitido, gera um PDF
                     100% imagem (sem camada de texto nativa) em diretorio
                     temporario com o texto "TOMUS OCR SMOKE CHECK 2026",
                     renderizado a 200 DPI, e verifica que "TOMUS" e "2026"
                     foram reconhecidos pelo OCR.
    :returns: codigo de saída 0 em sucesso, 1 em falha (PDF inexistente,
              OCR vazio ou palavras-chave nao reconhecidas no modo autogerado).
    """
    from tomus.extractors.ocr import ocr_scanned_pages

    tmp_dir: Path | None = None
    tmp_path: Path | None = None
    generated = pdf_path is None
    try:
        if generated:
            import fitz  # PyMuPDF (importacao lazy para nao exigir Qt)

            tmp_dir = Path(tempfile.mkdtemp(prefix="tomus_self_test_ocr_"))
            tmp_path = tmp_dir / "smoke_check.pdf"

            # Pagina com texto vetorial apenas para renderizar como imagem.
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "TOMUS OCR SMOKE CHECK 2026", fontsize=24)
            pix = page.get_pixmap(dpi=200)
            doc.close()

            # Novo PDF contendo APENAS a imagem renderizada (sem texto nativo).
            doc_img = fitz.open()
            page_img = doc_img.new_page(width=pix.width, height=pix.height)
            page_img.insert_image(page_img.rect, pixmap=pix)
            doc_img.save(str(tmp_path))
            doc_img.close()

            pdf_path = tmp_path

        texto = ocr_scanned_pages(Path(pdf_path))
        if not texto:
            print("FALHA: self-test OCR retornou texto vazio")
            return 1

        upper = texto.upper()
        if generated:
            # No modo autogerado exige-se reconhecimento de TOMUS e 2026.
            if "TOMUS" not in upper or "2026" not in upper:
                print(
                    "FALHA: self-test OCR nao reconheceu TOMUS/2026 "
                    f"(texto extraido: {texto!r})"
                )
                return 1

        print("OK: self-test OCR passou (TOMUS/2026 reconhecido)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA: self-test OCR excecao: {exc}")
        return 1
    finally:
        if tmp_dir is not None and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def launch_gui(
    config: AppConfig | None = None,
    source_dir: Path | str | None = None,
    target_dir: Path | str | None = None,
) -> int:
    """Inicializar a aplicação PySide6 e abrir a bancada principal.

    :param config: configuração ativa (criada por padrão se omitida).
    :param source_dir: diretório de origem pré-preenchido (opcional).
    :param target_dir: diretório de destino pré-preenchido (opcional).
    :returns: código de saída da aplicação Qt.
    """
    # Aplicar proteções defensivas do WebEngine ANTES de importar/criar qualquer
    # objeto Qt (especialmente QWebEnginePage usado pela visualização de PDF).
    _apply_webengine_defenses()

    # Inicializar o sistema de logs da GUI para que erros de OCR e runtime
    # nunca fiquem invisíveis no Windows/macOS (arquivo tomus.log na pasta do
    # usuário, evitando PermissionError em diretórios protegidos como '/' ou
    # 'Program Files').
    _log_dir = Path.home() / ".tomus"
    _log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(log_file=_log_dir / "tomus.log", verbose=False)

    from PySide6.QtGui import QColor, QIcon, QPalette
    from PySide6.QtWidgets import QApplication

    from tomus.gui.main_window import TomusMainWindow
    from tomus.gui.theme import EDITORIAL_PAPER_THEME, generate_qss

    if config is None:
        config = AppConfig()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    app.setApplicationName("Tomus")
    app.setApplicationDisplayName("Tomus — Organizador Acadêmico de PDFs")

    # --- Ícone oficial da aplicação (substitui o genérico do Python) ---
    if ICON_PATH.exists():
        app_icon = QIcon(str(ICON_PATH))
        app.setWindowIcon(app_icon)

    # Forçar paleta clara contra herança de tema escuro do OS
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F8FAFC"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#F8FAFC"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#DC2626"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1E3A8A"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)

    # Estilos globais para diálogos nativos (QMessageBox, QDialog, QMenu)
    app.setStyleSheet(
        generate_qss(EDITORIAL_PAPER_THEME)
        + """
        QDialog, QMessageBox {
            background-color: #FFFFFF;
            color: #0F172A;
        }
        QMessageBox QLabel {
            background-color: transparent;
            color: #0F172A;
            font-size: 13px;
        }
        QMessageBox QPushButton {
            background-color: #1E3A8A;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 6px 18px;
            font-weight: 600;
            font-size: 13px;
            min-width: 60px;
        }
        QMessageBox QPushButton:hover {
            background-color: #172554;
        }
        """
    )

    window = TomusMainWindow(
        config=config,
        source_dir=source_dir,
        target_dir=target_dir,
    )

    # Definir ícone também na janela principal (redundância por segurança).
    if ICON_PATH.exists():
        window.setWindowIcon(QIcon(str(ICON_PATH)))

    window.show()
    return app.exec()


def main() -> None:
    """Ponto de entrada do script GUI dedicado ``tomus-gui``.

    Intercepta ``--self-test-ocr [pdf]`` como primeiro argumento ANTES de
    qualquer importacao/instanciacao de QApplication ou QWebEngineView,
    permitindo auto-teste headless de OCR sem acionar o stack Qt.
    """
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test-ocr":
        pdf_path = sys.argv[2] if len(sys.argv) >= 3 else None
        sys.exit(run_self_test_ocr(pdf_path))
    sys.exit(launch_gui())


if __name__ == "__main__":
    main()
