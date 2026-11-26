"""Widgets da bancada do Tomus (Seção 3.2 do gui_spec.md).

Exporta os componentes da interface ainda em uso:
``PreferencesDialog`` (diálogo de preferências e gerenciador de pool de chaves
de API). Os painéis legados da bancada de 3 painéis
(``OperationalToolbar``, ``SessionResumeBanner``, ``CapesSidebarPanel``,
``DocumentTablePanel``, ``DocumentInspectorPanel``, ``ABNTReferenceCard``,
``ManualTriageBox``, ``TelemetryStatusBar``, ``LogCacheDrawer``) foram
removidos neste refator (branch refactor/remove-legacy-qtwidgets-gui).
"""

from __future__ import annotations

from tomus.gui.widgets.preferences_dialog import PreferencesDialog

__all__ = ["PreferencesDialog"]
