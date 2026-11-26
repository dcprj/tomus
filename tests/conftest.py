"""Fixtures compartilhadas para a suíte de testes do Tomus.

Garante teardown deterministico do QApplication/QWebEngineView para prevenir
segfaults intermitentes (exit 139) em macOS offscreen, decorrentes de race
conditions entre o encerro do QApplication e widgets Qt ainda vivos.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.hookimpl(hookwrapper=True)
def pytest_sessionfinish(session, exitstatus):
    """Flush final de eventos do Qt antes de encerrar a sessao de testes.

    Processa eventos pendentes do QApplication antes de finalizar, permitindo
    que deleteLater e callbacks do QWebEngineView sejam executados e evitando
    segfault no teardown quando a QApplication e destruida com widgets ainda
    vivos no macOS offscreen.
    """
    yield
    app = QApplication.instance()
    if app is not None:
        try:
            app.processEvents()
            app.processEvents()
        except Exception as exc:  # noqa: S110 - teardown defensivo, ignorar falha de eventos Qt
            import logging

            logging.getLogger("tomus.tests").debug("Teardown Qt ignorou excecao: %s", exc)


@pytest.fixture
def project_root() -> Path:
    """Diretorio raiz do repositorio Tomus."""
    return Path(__file__).resolve().parents[1]
