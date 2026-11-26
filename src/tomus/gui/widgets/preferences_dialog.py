"""Modal de Preferências e Chaves de API (Seção 3.3 do gui_spec.md).

Lê e grava ``~/.config/tomus/config.toml`` (ou ``./tomus.toml``)
preservando permissão restrita ``0600``. Respeita a precedência
``ENV > Local TOML > Global TOML``.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tomus.core.config import (
    GEMINI_ENV_KEYS,
    LOCAL_CONFIG_FILENAME,
    ApiKeysConfig,
    AppConfig,
    GeneralConfig,
    LLMConfig,
    mask_key,
)
from tomus.core.key_validator import (
    _normalize_field_name,
    validate_provider_key_live,
)
from tomus.core.key_validator import (
    validate_key_format as _validate_key_format,
)
from tomus.core.key_validator import (
    validate_key_syntax as _validate_single_key,
)

__all__ = ["PreferencesDialog", "KeyPoolDialog"]

_CHECKMARK_PATH = str(Path(__file__).parent.parent / "resources" / "checkmark.svg").replace("\\", "/")

_PREFERENCES_STYLE = f"""
QDialog {{
    background-color: #FFFFFF;
    color: #0F172A;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
QTabWidget::pane {{
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    background-color: #FFFFFF;
    top: -1px;
}}
QTabBar::tab {{
    background: #F8FAFC;
    color: #64748B;
    border: 1px solid #E2E8F0;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 4px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: #FFFFFF;
    color: #1E3A8A;
    border-bottom: 2px solid #1E3A8A;
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: #F1F5F9;
    color: #0F172A;
}}
QLabel {{
    color: #0F172A;
    font-size: 13px;
}}
QLineEdit {{
    background-color: #F8FAFC;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}
QLineEdit:focus {{
    border: 1px solid #1E3A8A;
    background-color: #FFFFFF;
}}
QComboBox {{
    background-color: #F8FAFC;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #E2E8F0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #F1F5F9;
}}
QComboBox QAbstractItemView {{
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    selection-background-color: #1E3A8A;
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 6px 10px;
    color: #0F172A;
    background-color: #FFFFFF;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: #1E3A8A;
    color: #FFFFFF;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: #F1F5F9;
    color: #0F172A;
}}
QCheckBox {{
    color: #0F172A;
    font-size: 13px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #94A3B8;
    border-radius: 4px;
    background-color: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background-color: #1E3A8A;
    border: 1px solid #1E3A8A;
    image: url({_CHECKMARK_PATH});
}}
QCheckBox::indicator:hover {{
    border: 1px solid #1E3A8A;
}}
QListView {{
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}}
QListView::item {{
    min-height: 30px;
    padding: 4px 8px;
    border-radius: 4px;
    color: #0F172A;
}}
QListView::item:hover {{
    background-color: #F8FAFC;
}}
QListView::item:selected {{
    background-color: #EFF6FF;
    color: #1E3A8A;
    font-weight: 500;
}}
QPushButton {{
    background-color: #F1F5F9;
    color: #1E293B;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #E2E8F0;
}}
QPushButton:checked {{
    background-color: #1E3A8A;
    color: #FFFFFF;
    border-color: #1E3A8A;
}}
"""

PROVIDER_INFO = {
    "gemini": {
        "title": "Google Gemini",
        "default_model": "gemini-3.5-flash",
        "key_field": "gemini_api_key",
        "env_keys": list(GEMINI_ENV_KEYS),
    },
    "groq": {
        "title": "Groq Cloud",
        "default_model": "openai/gpt-oss-120b",
        "key_field": "groq_api_key",
        "env_keys": ["TOMUS_GROQ_API_KEY", "GROQ_API_KEY"],
    },
    "claude": {
        "title": "Anthropic Claude",
        "default_model": "claude-haiku-5-5",
        "key_field": "claude_api_key",
        "env_keys": ["TOMUS_CLAUDE_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_API_KEY"],
    },
    "deepseek": {
        "title": "DeepSeek",
        "default_model": "deepseek-flash",
        "key_field": "deepseek_api_key",
        "env_keys": ["TOMUS_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"],
    },
    "nvidia": {
        "title": "NVIDIA NIM",
        "default_model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "key_field": "nvidia_api_key",
        "env_keys": ["TOMUS_NVIDIA_API_KEY", "NVIDIA_API_KEY"],
    },
}

API_KEY_FIELDS = [
    ("gemini_api_key", "Google Gemini API Key", list(GEMINI_ENV_KEYS), True),
    ("groq_api_key", "Groq Cloud API Key", ["TOMUS_GROQ_API_KEY", "GROQ_API_KEY"], True),
    ("nvidia_api_key", "NVIDIA NIM API Key", ["TOMUS_NVIDIA_API_KEY", "NVIDIA_API_KEY"], True),
    ("deepseek_api_key", "DeepSeek API Key", ["TOMUS_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"], True),
    ("claude_api_key", "Anthropic Claude API Key", ["TOMUS_CLAUDE_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_API_KEY"], True),
]

ENRICHMENT_FIELDS = [
    ("openalex_polite_email", "OpenAlex Polite Email", []),
    ("google_books_api_key", "Google Books API Key", ["TOMUS_GOOGLE_BOOKS_API_KEY", "GOOGLE_BOOKS_API_KEY"]),
]


def _env_active(env_names: list[str]) -> bool:
    return any(os.environ.get(env) for env in env_names)


# --------------------------------------------------------------------------- #
# Sub-Diálogo de Gerenciamento do Pool de Chaves com Teste Ativo
# --------------------------------------------------------------------------- #

class KeyPoolDialog(QDialog):
    """Sub-diálogo modal para visualização, validação ativa e gerenciamento do pool de múltiplas chaves."""

    def __init__(
        self,
        provider_title: str,
        field_name: str,
        initial_keys: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Pool de Chaves — {provider_title}")
        self.setModal(True)
        self.resize(640, 500)
        self.setStyleSheet(_PREFERENCES_STYLE)

        self._provider_title = provider_title
        # Validação e normalização defensiva do nome do campo ou título do provedor
        normalized = _normalize_field_name(field_name) if isinstance(field_name, str) and field_name else _normalize_field_name(provider_title)
        self._field_name = normalized or "gemini_api_key"
        self._keys: list[str] = [k.strip() for k in initial_keys if k.strip()]

        self._build_ui()
        self._render_keys()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        lbl_title = QLabel(f"Gerenciar Pool de Chaves — {self._provider_title}")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #0F172A;")
        layout.addWidget(lbl_title)

        banner = QLabel(
            "O Tomus realiza rotação e fallback automático entre as chaves deste pool. "
            "Se uma chave atingir o limite de cota (HTTP 429) ou sofrer instabilidade temporária, "
            "a próxima chave válida do pool é acionada automaticamente."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; "
            "padding: 10px 12px; color: #475569; font-size: 12px; line-height: 1.4;"
        )
        layout.addWidget(banner)

        lbl_sec1 = QLabel("Chaves Cadastradas no Pool:")
        lbl_sec1.setStyleSheet("font-weight: 600; color: #1E293B; font-size: 13px; margin-top: 4px;")
        layout.addWidget(lbl_sec1)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(180)
        self.scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #CBD5E1; border-radius: 6px; background-color: #FFFFFF; }"
        )
        self.keys_container = QWidget()
        self.keys_layout = QVBoxLayout(self.keys_container)
        self.keys_layout.setContentsMargins(8, 8, 8, 8)
        self.keys_layout.setSpacing(6)
        self.keys_layout.addStretch(1)
        self.scroll.setWidget(self.keys_container)
        layout.addWidget(self.scroll)

        lbl_sec2 = QLabel("Adicionar Nova Chave ao Pool:")
        lbl_sec2.setStyleSheet("font-weight: 600; color: #1E293B; font-size: 13px; margin-top: 6px;")
        layout.addWidget(lbl_sec2)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)

        self.edit_new_key = QLineEdit()
        self.edit_new_key.setPlaceholderText("Cole aqui a nova chave de API...")
        self.edit_new_key.setEchoMode(QLineEdit.EchoMode.Password)
        add_row.addWidget(self.edit_new_key, 1)

        self.btn_reveal = QPushButton("Mostrar")
        self.btn_reveal.setFixedWidth(68)
        self.btn_reveal.setCheckable(True)
        self.btn_reveal.toggled.connect(
            lambda checked: (
                self.edit_new_key.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                self.btn_reveal.setText("Ocultar" if checked else "Mostrar"),
            )
        )
        add_row.addWidget(self.btn_reveal)

        self.btn_add = QPushButton("＋ Adicionar ao Pool")
        self.btn_add.setFixedWidth(145)
        self.btn_add.setStyleSheet(
            "QPushButton { background-color: #1E3A8A; color: #FFFFFF; border: none; "
            "border-radius: 6px; padding: 7px 12px; font-weight: 600; font-size: 12px; }"
            "QPushButton:hover { background-color: #172554; }"
        )
        self.btn_add.clicked.connect(self._add_key)
        add_row.addWidget(self.btn_add)

        layout.addLayout(add_row)

        self.lbl_add_err = QLabel("")
        self.lbl_add_err.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 500;")
        self.lbl_add_err.hide()
        layout.addWidget(self.lbl_add_err)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #475569; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 7px 16px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background-color: #F1F5F9; color: #0F172A; }"
        )
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton("Salvar Pool")
        btn_save.setStyleSheet(
            "QPushButton { background-color: #1E3A8A; color: #FFFFFF; border: none; "
            "border-radius: 6px; padding: 7px 20px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background-color: #172554; }"
        )
        btn_save.clicked.connect(self.accept)
        footer.addWidget(btn_save)

        layout.addLayout(footer)

    def _render_keys(self) -> None:
        while self.keys_layout.count() > 1:
            child = self.keys_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self._keys:
            empty = QLabel("Nenhuma chave no pool. Cole uma chave abaixo e clique em '＋ Adicionar ao Pool'.")
            empty.setStyleSheet("color: #94A3B8; font-style: italic; font-size: 12px; padding: 12px;")
            self.keys_layout.insertWidget(0, empty)
            return

        for idx, key in enumerate(self._keys):
            row_w = QWidget()
            row_w.setStyleSheet(
                "background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px;"
            )
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(10, 5, 10, 5)
            row_lay.setSpacing(8)

            idx_lbl = QLabel(f"#{idx + 1}")
            idx_lbl.setStyleSheet("font-weight: 700; color: #1E3A8A; min-width: 24px; border: none; background: transparent;")
            row_lay.addWidget(idx_lbl)

            key_lbl = QLabel(mask_key(key))
            key_lbl.setStyleSheet("font-family: monospace; font-size: 12px; color: #0F172A; border: none; background: transparent;")
            row_lay.addWidget(key_lbl, 1)

            ok, err = _validate_single_key(self._field_name, key)
            status_lbl = QLabel("✓ Formato Válido" if ok else f"⚠️ {err}")
            status_color = "#16A34A" if ok else "#DC2626"
            status_lbl.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 600; border: none; background: transparent;")
            row_lay.addWidget(status_lbl)

            # Botão Testar Ativo para cada chave individual
            btn_test = QPushButton("Testar")
            btn_test.setFixedWidth(64)
            btn_test.setStyleSheet(
                "QPushButton { background-color: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; "
                "border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 500; }"
                "QPushButton:hover { background-color: #DBEAFE; }"
            )

            def _make_test_single(k_str: str, s_lbl: QLabel, b_t: QPushButton):
                def _do_test(_checked: bool = False):
                    b_t.setEnabled(False)
                    b_t.setText("...")
                    s_lbl.setText("Testando...")
                    s_lbl.setStyleSheet("color: #2563EB; font-size: 11px; font-weight: 600; border: none; background: transparent;")
                    ok_live, msg = validate_provider_key_live(self._field_name, k_str)
                    b_t.setEnabled(True)
                    b_t.setText("Testar")
                    if ok_live:
                        s_lbl.setText("✓ Autenticada")
                        s_lbl.setStyleSheet("color: #16A34A; font-size: 11px; font-weight: 600; border: none; background: transparent;")
                    else:
                        s_lbl.setText("✗ Recusada")
                        s_lbl.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 600; border: none; background: transparent;")
                        QMessageBox.warning(self, "Chave Recusada", f"Falha na validação desta chave com a API:\n\n{msg}")
                return _do_test

            btn_test.clicked.connect(_make_test_single(key, status_lbl, btn_test))
            row_lay.addWidget(btn_test)

            btn_del = QPushButton("Remover")
            btn_del.setFixedWidth(66)
            btn_del.setStyleSheet(
                "QPushButton { background-color: #FEF2F2; color: #DC2626; border: 1px solid #FCA5A5; "
                "border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 500; }"
                "QPushButton:hover { background-color: #FEE2E2; border-color: #B91C1C; }"
            )
            btn_del.clicked.connect(lambda _, i=idx: self._remove_key(i))
            row_lay.addWidget(btn_del)

            self.keys_layout.insertWidget(self.keys_layout.count() - 1, row_w)

    def _remove_key(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self._keys.pop(index)
            self._render_keys()

    def _add_key(self) -> None:
        raw = self.edit_new_key.text().strip()
        if not raw:
            self.lbl_add_err.setText("Digite ou cole a chave de API antes de adicionar.")
            self.lbl_add_err.show()
            return

        tokens = [t.strip() for line in raw.splitlines() for t in line.split(",") if t.strip()]
        for t in tokens:
            ok, err = _validate_single_key(self._field_name, t)
            if not ok:
                self.lbl_add_err.setText(f"Chave inválida: {err}")
                self.lbl_add_err.show()
                return

        for t in tokens:
            if t not in self._keys:
                self._keys.append(t)

        self.edit_new_key.clear()
        self.lbl_add_err.hide()
        self._render_keys()

    def get_keys(self) -> list[str]:
        return list(self._keys)


# --------------------------------------------------------------------------- #
# Delegates Customizados para Provedores e Fallback
# --------------------------------------------------------------------------- #

class ProviderComboDelegate(QStyledItemDelegate):
    """Delegate para renderizar nomes amigáveis no QComboBox de Provedores."""

    def displayText(self, value, locale):
        val = str(value)
        info = PROVIDER_INFO.get(val)
        if info:
            return f"{info['title']} ({val})"
        return val


class FallbackItemDelegate(QStyledItemDelegate):
    """Delegate editorial para renderizar provedores de fallback com modelo e status de chave."""

    def __init__(self, dialog: PreferencesDialog, parent=None) -> None:
        super().__init__(parent)
        self._dlg = dialog

    def displayText(self, value, locale):
        val = str(value)
        info = PROVIDER_INFO.get(val, {"title": val.title(), "default_model": ""})
        title = info["title"]
        model = info.get("default_model", "")
        has_key = self._dlg._provider_has_key(val)
        status_text = "✓ Chave Configurada" if has_key else "○ Sem chave de API"
        if model:
            return f"{title} ({model})  —  {status_text}"
        return f"{title}  —  {status_text}"


# --------------------------------------------------------------------------- #
# Diálogo Principal de Preferências
# --------------------------------------------------------------------------- #

class PreferencesDialog(QDialog):
    """Diálogo modal de edição do config.toml e chaves de API."""

    def __init__(self, config: AppConfig, parent=None, config_path: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._config = config

        if config_path is not None:
            self._config_path = Path(config_path)
        else:
            local = Path.cwd() / LOCAL_CONFIG_FILENAME
            global_path = Path.home() / ".config" / "tomus" / "config.toml"
            self._config_path = local if local.exists() else global_path

        self.setWindowTitle("Preferências e Credenciais — Tomus")
        self.setModal(True)
        self.resize(880, 630)
        self.setStyleSheet(_PREFERENCES_STYLE)

        self._fields: dict[str, QLineEdit] = {}
        self._env_labels: dict[str, QLabel] = {}
        self._error_labels: dict[str, QLabel] = {}
        self._pool_buttons: dict[str, QPushButton] = {}
        self._test_buttons: dict[str, QPushButton] = {}

        self._build_ui()
        self._load_config_into_ui()

    # ------------------------------------------------------------------ #
    # Construção da UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_credentials(), "Credenciais e Chaves de API")
        self.tabs.addTab(self._tab_fallback(), "Provedores LLM & Fallback".replace("&", "&&"))
        self.tabs.addTab(self._tab_pipeline(), "Pipeline, OCR & Cache".replace("&", "&&"))
        layout.addWidget(self.tabs)

        self.path_lbl = QLabel()
        self.path_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-family: monospace; padding-top: 4px;")
        layout.addWidget(self.path_lbl)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 8, 0, 0)

        self.btn_restore = QPushButton("Restaurar Padrões", self)
        self.btn_restore.setFixedWidth(130)
        self.btn_restore.setStyleSheet(
            "QPushButton { background-color: #F8FAFC; color: #475569; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 7px 12px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background-color: #F1F5F9; color: #0F172A; border-color: #94A3B8; }"
        )
        self.btn_restore.clicked.connect(self._restore_defaults)
        footer_layout.addWidget(self.btn_restore)
        footer_layout.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.btn_save = btns.button(QDialogButtonBox.StandardButton.Save)
        self.btn_save.setText("Salvar Configuração")
        self.btn_save.setStyleSheet(
            "QPushButton { background-color: #1E3A8A; color: #FFFFFF; border: none; "
            "border-radius: 6px; padding: 8px 20px; font-weight: 600; font-size: 13px; }"
            "QPushButton:hover { background-color: #172554; }"
        )
        self.btn_cancel = btns.button(QDialogButtonBox.StandardButton.Cancel)
        self.btn_cancel.setText("Cancelar")
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #475569; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 8px 16px; font-weight: 500; font-size: 13px; }"
            "QPushButton:hover { background-color: #F1F5F9; color: #0F172A; }"
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        footer_layout.addWidget(btns)

        layout.addLayout(footer_layout)

    def _provider_has_key(self, prov: str) -> bool:
        """Verifica se um provedor possui chave configurada e com formato sintático válido."""
        field_name = f"{prov}_api_key"
        edit = self._fields.get(field_name)
        if edit and edit.text().strip():
            first = edit.text().strip().split(",")[0].strip()
            ok, _ = _validate_single_key(prov, first)
            return ok
        info = PROVIDER_INFO.get(prov)
        if info and _env_active(info.get("env_keys", [])):
            return True
        return False

    def _update_primary_status(self) -> None:
        if not hasattr(self, "lbl_primary_key_status") or not hasattr(self, "cmb_primary"):
            return
        prov = self.cmb_primary.currentText()
        field_name = f"{prov}_api_key"
        edit = self._fields.get(field_name)
        txt = edit.text().strip() if edit else ""
        if txt:
            first = txt.split(",")[0].strip()
            ok, _ = _validate_single_key(prov, first)
            if ok:
                self.lbl_primary_key_status.setText("✓ Chave Configurada")
                self.lbl_primary_key_status.setStyleSheet("color: #16A34A; font-weight: 600; font-size: 11px;")
            else:
                self.lbl_primary_key_status.setText("⚠️ Formato Inválido")
                self.lbl_primary_key_status.setStyleSheet("color: #DC2626; font-weight: 600; font-size: 11px;")
        elif self._provider_has_key(prov):
            self.lbl_primary_key_status.setText("✓ Chave Ativa (ENV)")
            self.lbl_primary_key_status.setStyleSheet("color: #0284C7; font-weight: 600; font-size: 11px;")
        else:
            self.lbl_primary_key_status.setText("⚠️ Sem chave cadastrada")
            self.lbl_primary_key_status.setStyleSheet("color: #D97706; font-weight: 500; font-size: 11px;")

    def _restore_defaults(self) -> None:
        """Restaurar configurações padrão de fábrica (preservando chaves de API já cadastradas)."""
        reply = QMessageBox.question(
            self,
            "Restaurar Padrões",
            "Deseja redefinir os modelos, provedores e parâmetros do pipeline para as configurações padrão de fábrica?\n\n"
            "Nota: Suas chaves de API cadastradas serão preservadas com segurança.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._config.general.confidence_min = 0.70
        self._config.general.workers = 1
        self._config.general.use_cache = True
        self._config.llm.provider = "gemini"
        self._config.llm.model = "gemini-3.5-flash"
        self._config.llm.fallback_chain = ["groq", "nvidia", "claude", "deepseek"]

        self.edit_conf.setText("0.70")
        self.edit_workers.setText("1")
        self.chk_use_cache.setChecked(True)
        idx = self.cmb_primary.findText("gemini")
        if idx >= 0:
            self.cmb_primary.setCurrentIndex(idx)
        self.edit_model.setText("gemini-3.5-flash")
        self._populate_fallback_list()
        self._update_primary_status()

    def _tab_credentials(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_lbl = QLabel("Credenciais dos provedores de classificação (Stage 4)")
        header_lbl.setStyleSheet("font-weight: 600; color: #0F172A; font-size: 13px;")
        layout.addWidget(header_lbl)

        sub_lbl = QLabel(
            "Suporta validação ativa e múltiplas chaves por provedor. "
            "Clique em 'Testar' para validar a chave na API oficial ou em 'Pool de Chaves' para gerenciar."
        )
        sub_lbl.setStyleSheet("color: #64748B; font-size: 12px; margin-bottom: 2px;")
        layout.addWidget(sub_lbl)

        form = QFormLayout()
        form.setSpacing(10)
        for field_name, _label, _env_names, _multi_keys in API_KEY_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(8)
            edit = QLineEdit()
            edit.setPlaceholderText("Cole sua chave aqui...")
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setFixedWidth(210)
            edit.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

            reveal = QPushButton("Mostrar")
            reveal.setFixedWidth(64)
            reveal.setCheckable(True)
            reveal.toggled.connect(
                lambda checked, e=edit, b=reveal: (
                    e.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                    b.setText("Ocultar" if checked else "Mostrar"),
                )
            )

            btn_test = QPushButton("Testar")
            btn_test.setFixedWidth(64)
            btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_test.setStyleSheet(
                "QPushButton { background-color: #F8FAFC; color: #1E293B; border: 1px solid #CBD5E1; "
                "border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: 500; }"
                "QPushButton:hover { background-color: #E2E8F0; color: #0F172A; }"
            )

            btn_pool = QPushButton("＋ Pool de Chaves")
            btn_pool.setFixedWidth(126)
            btn_pool.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_pool.setStyleSheet(
                "QPushButton { background-color: #F8FAFC; color: #334155; border: 1px solid #CBD5E1; "
                "border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: 500; }"
                "QPushButton:hover { background-color: #F1F5F9; color: #0F172A; }"
            )

            def _make_pool_opener(f_name: str, prov_lbl: str, edit_w: QLineEdit):
                def _open_pool(_checked: bool = False):
                    raw = edit_w.text().strip()
                    keys = [k.strip() for k in raw.split(",") if k.strip()]
                    dlg = KeyPoolDialog(prov_lbl, f_name, keys, parent=self)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        new_keys = dlg.get_keys()
                        edit_w.setText(", ".join(new_keys))
                return _open_pool

            btn_pool.clicked.connect(_make_pool_opener(field_name, _label, edit))
            self._pool_buttons[field_name] = btn_pool
            self._test_buttons[field_name] = btn_test

            env_lbl = QLabel("(Não configurado)")
            env_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic;")
            env_lbl.setMinimumWidth(160)

            error_lbl = QLabel("")
            error_lbl.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 500;")
            error_lbl.setMinimumWidth(180)
            error_lbl.hide()
            self._error_labels[field_name] = error_lbl

            # Ação de teste ativo com o provedor
            def _make_test_action(f_name: str, p_lbl: str, edit_w: QLineEdit, env_l: QLabel, b_t: QPushButton):
                def _do_test(_checked: bool = False):
                    raw = edit_w.text().strip()
                    if not raw:
                        env_l.setText("Informe a chave para testar")
                        env_l.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 500;")
                        return

                    tokens = [t.strip() for t in raw.split(",") if t.strip()]
                    first_k = tokens[0]

                    # Validar sintaxe primeiro
                    ok_fmt, err_fmt = _validate_single_key(f_name, first_k)
                    if not ok_fmt:
                        env_l.setText("Formato Inválido")
                        env_l.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 600;")
                        edit_w.setStyleSheet(
                            "QLineEdit { background-color: #FEF2F2; border: 1px solid #DC2626; border-radius: 6px; padding: 6px 10px; font-size: 13px; }"
                        )
                        QMessageBox.warning(
                            self,
                            "Formato de Chave Inválido",
                            f"A chave informada não atende aos requisitos sintáticos do provedor:\n\n{err_fmt}\n\n"
                            "Corrija o formato antes de testar a conexão com a API.",
                        )
                        return

                    b_t.setEnabled(False)
                    b_t.setText("...")
                    env_l.setText("Validando na API...")
                    env_l.setStyleSheet("color: #2563EB; font-size: 11px; font-weight: 500;")

                    ok_live, msg_live = validate_provider_key_live(f_name, first_k)
                    b_t.setEnabled(True)
                    b_t.setText("Testar")

                    if ok_live:
                        env_l.setText("✓ Chave Autenticada")
                        env_l.setStyleSheet("color: #16A34A; font-size: 11px; font-weight: 600;")
                        QMessageBox.information(
                            self,
                            "Chave Autenticada com Sucesso",
                            f"A chave do provedor {p_lbl} foi verificada e aceita pela API oficial:\n\n{msg_live}",
                        )
                    else:
                        env_l.setText("✗ Chave Recusada na API")
                        env_l.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 600;")
                        edit_w.setStyleSheet(
                            "QLineEdit { background-color: #FEF2F2; border: 1px solid #DC2626; border-radius: 6px; padding: 6px 10px; font-size: 13px; }"
                        )
                        QMessageBox.critical(
                            self,
                            "Chave Recusada pela API",
                            f"A API oficial do provedor rejeitou a chave:\n\n{msg_live}\n\n"
                            "Verifique se a chave informada está ativa, sem caracteres extras e vinculada a um projeto com cota.",
                        )
                return _do_test

            btn_test.clicked.connect(_make_test_action(field_name, _label, edit, env_lbl, btn_test))

            def _make_validator(edit_obj: QLineEdit, f_name: str, env_l: QLabel, err_l: QLabel, env_n: list[str], pool_b: QPushButton):
                def _on_change(_text: str) -> None:
                    txt = edit_obj.text().strip()
                    tokens = [k.strip() for k in txt.split(",") if k.strip()]

                    valid, err_msg = _validate_key_format(f_name, txt)

                    if _env_active(env_n):
                        env_l.setText("(Ativo via Variável de Ambiente)")
                        env_l.setStyleSheet("color: #0284C7; font-size: 11px; font-weight: 500;")
                    elif tokens:
                        if not valid:
                            env_l.setText("Formato Inválido")
                            env_l.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 600;")
                        elif len(tokens) > 1:
                            env_l.setText(f"✓ {len(tokens)} chaves no Pool")
                            env_l.setStyleSheet("color: #16A34A; font-size: 11px; font-weight: 600;")
                        else:
                            env_l.setText("✓ Configurado")
                            env_l.setStyleSheet("color: #16A34A; font-size: 11px; font-weight: 600;")
                    else:
                        env_l.setText("(Não configurado)")
                        env_l.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic;")

                    if len(tokens) > 1:
                        pool_b.setText(f"🔑 Pool ({len(tokens)} chaves)")
                        pool_b.setStyleSheet(
                            "QPushButton { background-color: #EFF6FF; color: #1D4ED8; border: 1px solid #93C5FD; "
                            "border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: 600; }"
                            "QPushButton:hover { background-color: #DBEAFE; }"
                        )
                    else:
                        pool_b.setText("＋ Pool de Chaves")
                        pool_b.setStyleSheet(
                            "QPushButton { background-color: #F8FAFC; color: #334155; border: 1px solid #CBD5E1; "
                            "border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: 500; }"
                            "QPushButton:hover { background-color: #F1F5F9; color: #0F172A; }"
                        )

                    if not txt:
                        err_l.hide()
                        edit_obj.setStyleSheet("")
                    elif valid:
                        err_l.hide()
                        edit_obj.setStyleSheet(
                            "QLineEdit { background-color: #F0FDF4; border: 1px solid #16A34A; border-radius: 6px; padding: 6px 10px; font-size: 13px; }"
                        )
                    else:
                        err_l.setText(err_msg)
                        err_l.show()
                        edit_obj.setStyleSheet(
                            "QLineEdit { background-color: #FEF2F2; border: 1px solid #DC2626; border-radius: 6px; padding: 6px 10px; font-size: 13px; }"
                        )

                    if hasattr(self, "lbl_primary_key_status"):
                        self._update_primary_status()
                    if hasattr(self, "fallback_list"):
                        self.fallback_list.viewport().update()

                edit_obj.textChanged.connect(_on_change)

            row.addWidget(edit)
            row.addWidget(reveal)
            row.addWidget(btn_test)
            row.addWidget(btn_pool)
            row.addSpacing(8)
            row.addWidget(env_lbl)
            row.addWidget(error_lbl)
            row.addStretch(1)

            lbl = QLabel(_label)
            lbl.setStyleSheet("font-weight: 500; color: #1E293B;")
            form.addRow(lbl, row)
            self._fields[field_name] = edit
            self._env_labels[field_name] = env_lbl
            _make_validator(edit, field_name, env_lbl, error_lbl, _env_names, btn_pool)

        layout.addLayout(form)
        layout.addSpacing(8)

        header_enrich = QLabel("Serviços de enriquecimento acadêmico (Stage 3 — OpenAlex & Google Books)")
        header_enrich.setStyleSheet("font-weight: 600; color: #0F172A; font-size: 13px;")
        layout.addWidget(header_enrich)

        form_enrich = QFormLayout()
        form_enrich.setSpacing(10)
        for field_name, label, _env_names in ENRICHMENT_FIELDS:
            edit = QLineEdit()
            edit.setFixedWidth(210)
            edit.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
            if "key" in field_name:
                edit.setPlaceholderText("Cole sua chave aqui...")
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            else:
                edit.setPlaceholderText("pesquisador@instituicao.edu.br")

            env_lbl = QLabel("(Não configurado)")
            env_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic;")
            env_lbl.setMinimumWidth(160)

            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(edit)

            if "key" in field_name:
                reveal = QPushButton("Mostrar")
                reveal.setFixedWidth(64)
                reveal.setCheckable(True)
                reveal.toggled.connect(
                    lambda checked, e=edit, b=reveal: (
                        e.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                        b.setText("Ocultar" if checked else "Mostrar"),
                    )
                )
                row.addWidget(reveal)

                btn_test_enrich = QPushButton("Testar")
                btn_test_enrich.setFixedWidth(64)
                btn_test_enrich.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_test_enrich.setStyleSheet(
                    "QPushButton { background-color: #F8FAFC; color: #1E293B; border: 1px solid #CBD5E1; "
                    "border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: 500; }"
                    "QPushButton:hover { background-color: #E2E8F0; color: #0F172A; }"
                )

                def _make_enrich_test(f_n: str, l_n: str, e_w: QLineEdit, s_l: QLabel, b_e: QPushButton):
                    def _do_enrich_test(_checked: bool = False):
                        raw_k = e_w.text().strip()
                        if not raw_k:
                            s_l.setText("Informe a chave para testar")
                            return
                        ok_fmt, err_fmt = _validate_single_key(f_n, raw_k)
                        if not ok_fmt:
                            s_l.setText("Formato Inválido")
                            QMessageBox.warning(self, "Chave Inválida", f"Formato inválido:\n\n{err_fmt}")
                            return
                        b_e.setEnabled(False)
                        b_e.setText("...")
                        s_l.setText("Validando...")
                        ok_l, msg_l = validate_provider_key_live(f_n, raw_k)
                        b_e.setEnabled(True)
                        b_e.setText("Testar")
                        if ok_l:
                            s_l.setText("✓ Chave Autenticada")
                            s_l.setStyleSheet("color: #16A34A; font-size: 11px; font-weight: 600;")
                            QMessageBox.information(self, "Chave Autenticada", f"Chave validada:\n\n{msg_l}")
                        else:
                            s_l.setText("✗ Chave Recusada")
                            s_l.setStyleSheet("color: #DC2626; font-size: 11px; font-weight: 600;")
                            QMessageBox.critical(self, "Chave Recusada", f"Chave rejeitada pela API:\n\n{msg_l}")
                    return _do_enrich_test

                btn_test_enrich.clicked.connect(_make_enrich_test(field_name, label, edit, env_lbl, btn_test_enrich))
                row.addWidget(btn_test_enrich)
            else:
                spacer = QWidget()
                spacer.setFixedWidth(64 + 8 + 64)
                row.addWidget(spacer)

            spacer_pool = QWidget()
            spacer_pool.setFixedWidth(126)
            row.addWidget(spacer_pool)

            def _on_enrich_change(_text, e=edit, _lbl_env=env_lbl, ev=_env_names, fn=field_name):
                if _env_active(ev):
                    _lbl_env.setText("(Ativo via Variável de Ambiente)")
                    _lbl_env.setStyleSheet("color: #0284C7; font-size: 11px; font-weight: 500;")
                elif e.text().strip():
                    if fn == "openalex_polite_email":
                        _lbl_env.setText("✓ Polite Pool Ativo (10 req/s)")
                    else:
                        _lbl_env.setText("✓ Configurado")
                    _lbl_env.setStyleSheet("color: #16A34A; font-size: 11px; font-weight: 600;")
                else:
                    _lbl_env.setText("(Não configurado)")
                    _lbl_env.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic;")

            edit.textChanged.connect(_on_enrich_change)

            row.addSpacing(8)
            row.addWidget(env_lbl)
            row.addStretch(1)
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: 500; color: #1E293B;")
            form_enrich.addRow(lbl, row)
            self._fields[field_name] = edit
            self._env_labels[field_name] = env_lbl

        layout.addLayout(form_enrich)
        layout.addStretch(1)
        return widget

    def _tab_fallback(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Card do Provedor Principal
        card1 = QFrame()
        card1.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; }"
        )
        card1_lay = QVBoxLayout(card1)
        card1_lay.setContentsMargins(14, 12, 14, 12)
        card1_lay.setSpacing(8)

        card1_title = QLabel("1. Provedor Principal de Classificação (Execução Primária)")
        card1_title.setStyleSheet("font-weight: 700; color: #0F172A; font-size: 13px; border: none; background: transparent;")
        card1_lay.addWidget(card1_title)

        card1_sub = QLabel("Provedor utilizado inicialmente pelo pipeline para categorizar e enriquecer as obras.")
        card1_sub.setStyleSheet("color: #64748B; font-size: 12px; border: none; background: transparent;")
        card1_lay.addWidget(card1_sub)

        row_prim = QHBoxLayout()
        row_prim.setSpacing(10)

        lbl_p = QLabel("Provedor:")
        lbl_p.setStyleSheet("font-weight: 500; color: #1E293B; border: none; background: transparent;")
        row_prim.addWidget(lbl_p)

        self.cmb_primary = QComboBox(self)
        self.cmb_primary.addItems(["gemini", "groq", "claude", "deepseek", "nvidia"])
        self.cmb_primary.setItemDelegate(ProviderComboDelegate(self.cmb_primary))
        self.cmb_primary.setFixedWidth(180)
        row_prim.addWidget(self.cmb_primary)

        lbl_m = QLabel("Modelo Padrão:")
        lbl_m.setStyleSheet("font-weight: 500; color: #1E293B; border: none; background: transparent;")
        row_prim.addWidget(lbl_m)

        self.edit_model = QLineEdit("gemini-3.5-flash")
        self.edit_model.setFixedWidth(220)
        self.edit_model.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        row_prim.addWidget(self.edit_model)

        self.lbl_primary_key_status = QLabel("")
        self.lbl_primary_key_status.setStyleSheet("border: none; background: transparent; font-size: 11px;")
        row_prim.addWidget(self.lbl_primary_key_status)
        row_prim.addStretch(1)

        card1_lay.addLayout(row_prim)
        layout.addWidget(card1)

        def _on_provider_change(prov: str) -> None:
            info = PROVIDER_INFO.get(prov)
            if info:
                self.edit_model.setText(info["default_model"])
            self._update_primary_status()
            if hasattr(self, "fallback_list"):
                self.fallback_list.viewport().update()

        self.cmb_primary.currentTextChanged.connect(_on_provider_change)

        # 2. Card da Cadeia de Fallback (Reserva)
        card2 = QFrame()
        card2.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }"
        )
        card2_lay = QVBoxLayout(card2)
        card2_lay.setContentsMargins(14, 12, 14, 12)
        card2_lay.setSpacing(8)

        card2_title = QLabel("2. Cadeia de Fallback Automático (Provedores de Reserva)")
        card2_title.setStyleSheet("font-weight: 700; color: #0F172A; font-size: 13px; border: none; background: transparent;")
        card2_lay.addWidget(card2_title)

        card2_sub = QLabel(
            "Quando o provedor primário esgota sua cota (HTTP 429) ou sofre timeout, "
            "o Tomus aciona sequencialmente os provedores marcados abaixo na ordem especificada:"
        )
        card2_sub.setWordWrap(True)
        card2_sub.setStyleSheet("color: #64748B; font-size: 12px; border: none; background: transparent; line-height: 1.4;")
        card2_lay.addWidget(card2_sub)

        self.fallback_list = QListView(self)
        self.fallback_list.setFixedHeight(140)
        self.fallback_model = QStandardItemModel(self)
        self.fallback_list.setModel(self.fallback_model)
        self.fallback_list.setItemDelegate(FallbackItemDelegate(self, self.fallback_list))
        self.fallback_list.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        card2_lay.addWidget(self.fallback_list)

        ctrl_lay = QHBoxLayout()
        ctrl_lay.setSpacing(8)

        self.btn_move_up = QPushButton("▲ Subir", self)
        self.btn_move_up.setFixedWidth(84)
        self.btn_move_up.clicked.connect(self._move_fallback_up)
        ctrl_lay.addWidget(self.btn_move_up)

        self.btn_move_down = QPushButton("▼ Descer", self)
        self.btn_move_down.setFixedWidth(84)
        self.btn_move_down.clicked.connect(self._move_fallback_down)
        ctrl_lay.addWidget(self.btn_move_down)

        ctrl_lay.addSpacing(12)

        self.btn_check_all = QPushButton("Marcar Todos", self)
        self.btn_check_all.setFixedWidth(110)
        self.btn_check_all.clicked.connect(self._check_all_fallbacks)
        ctrl_lay.addWidget(self.btn_check_all)

        self.btn_only_keys = QPushButton("Apenas com Chave", self)
        self.btn_only_keys.setFixedWidth(130)
        self.btn_only_keys.clicked.connect(self._check_only_keyed_fallbacks)
        ctrl_lay.addWidget(self.btn_only_keys)

        ctrl_lay.addStretch(1)
        card2_lay.addLayout(ctrl_lay)

        tip_lbl = QLabel(
            "Dica: Provedores desmarcados ou sem chave de API configurada são ignorados automaticamente durante o processamento."
        )
        tip_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-style: italic; border: none; background: transparent;")
        card2_lay.addWidget(tip_lbl)

        layout.addWidget(card2)
        layout.addStretch(1)
        return widget

    def _check_all_fallbacks(self) -> None:
        for i in range(self.fallback_model.rowCount()):
            item = self.fallback_model.item(i)
            item.setCheckState(Qt.CheckState.Checked)

    def _check_only_keyed_fallbacks(self) -> None:
        for i in range(self.fallback_model.rowCount()):
            item = self.fallback_model.item(i)
            has_key = self._provider_has_key(item.text())
            item.setCheckState(Qt.CheckState.Checked if has_key else Qt.CheckState.Unchecked)

    def _populate_fallback_list(self) -> None:
        """Preencher a lista de fallback com base na configuração atual."""
        self.fallback_model.clear()
        primary = self.cmb_primary.currentText() if hasattr(self, "cmb_primary") else (self._config.llm.provider or "gemini")
        fallback = list(self._config.llm.fallback_chain or [])
        if not fallback:
            fallback = ["groq", "nvidia", "claude", "deepseek"]

        added = set()
        for prov in fallback:
            item = QStandardItem(prov)
            item.setEditable(False)
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Checked)
            self.fallback_model.appendRow(item)
            added.add(prov)

        for prov in ("gemini", "groq", "claude", "deepseek", "nvidia"):
            if prov != primary and prov not in added:
                item = QStandardItem(prov)
                item.setEditable(False)
                item.setCheckable(True)
                has_key = self._provider_has_key(prov)
                item.setCheckState(Qt.CheckState.Checked if has_key else Qt.CheckState.Unchecked)
                self.fallback_model.appendRow(item)
                added.add(prov)

    def _move_fallback_up(self) -> None:
        idx = self.fallback_list.currentIndex()
        if not idx.isValid() or idx.row() <= 0:
            return
        row = idx.row()
        item = self.fallback_model.takeRow(row)
        self.fallback_model.insertRow(row - 1, item)
        self.fallback_list.setCurrentIndex(self.fallback_model.index(row - 1, 0))

    def _move_fallback_down(self) -> None:
        idx = self.fallback_list.currentIndex()
        if not idx.isValid() or idx.row() >= self.fallback_model.rowCount() - 1:
            return
        row = idx.row()
        item = self.fallback_model.takeRow(row)
        self.fallback_model.insertRow(row + 1, item)
        self.fallback_list.setCurrentIndex(self.fallback_model.index(row + 1, 0))

    def _tab_pipeline(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header2 = QLabel("Limiar de qualidade e concorrência (Stage 1 a Stage 5)")
        header2.setStyleSheet("font-weight: 600; color: #0F172A; font-size: 13px;")
        layout.addWidget(header2)

        form = QFormLayout()
        form.setSpacing(10)
        self.edit_conf = QLineEdit("0.70")
        self.edit_conf.setFixedWidth(70)
        self.edit_conf.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        lbl_conf = QLabel("Confiança Mínima (confidence_min):")
        lbl_conf.setStyleSheet("font-weight: 500; color: #1E293B;")
        form.addRow(lbl_conf, self.edit_conf)
        self.edit_workers = QLineEdit("1")
        self.edit_workers.setFixedWidth(70)
        self.edit_workers.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        lbl_work = QLabel("Workers de Rede:")
        lbl_work.setStyleSheet("font-weight: 500; color: #1E293B;")
        form.addRow(lbl_work, self.edit_workers)
        layout.addLayout(form)

        layout.addSpacing(14)
        header3 = QLabel("Cache Local de Classificação (Stage 1)")
        header3.setStyleSheet("font-weight: 600; color: #0F172A; font-size: 13px;")
        layout.addWidget(header3)

        self.chk_use_cache = QCheckBox("Utilizar Cache Local SQLite (evita reprocessamento de PDFs já classificados)", self)
        self.chk_use_cache.setChecked(self._config.general.use_cache)
        layout.addWidget(self.chk_use_cache)

        layout.addStretch(1)
        return widget

    # ------------------------------------------------------------------ #
    # Carregar / Salvar
    # ------------------------------------------------------------------ #

    def _load_config_into_ui(self) -> None:
        modo = " (Permissão 0600 Segura)" if self._config_path.exists() else ""
        self.path_lbl.setText(f"ARQUIVO DE CONFIGURAÇÃO ATIVO: {self._config_path}{modo}")

        for field_name, _label, _env_names, _multi_keys in API_KEY_FIELDS:
            value = getattr(self._config.api_keys, field_name, "")
            if isinstance(value, list):
                value = ", ".join(value)
            if field_name in self._fields:
                self._fields[field_name].setText(value)

        for field_name, _label, _env in ENRICHMENT_FIELDS:
            value = getattr(self._config.api_keys, field_name, "")
            if field_name in self._fields:
                self._fields[field_name].setText(value)

        curr_provider = self._config.llm.provider or "gemini"
        idx = self.cmb_primary.findText(curr_provider)
        if idx >= 0:
            self.cmb_primary.setCurrentIndex(idx)
        else:
            self.cmb_primary.setCurrentText(curr_provider)

        self.edit_model.setText(self._config.llm.model or "gemini-3.5-flash")

        self.edit_conf.setText(f"{self._config.general.confidence_min:.2f}")
        self.edit_workers.setText(str(self._config.general.workers))
        self.chk_use_cache.setChecked(self._config.general.use_cache)
        self._populate_fallback_list()
        self._update_primary_status()

    def _save(self) -> None:
        """Serializar as seções em config.toml com permissão 0600 e atualizar self._config in-place."""
        import tomli_w

        api_updates = {}
        for field_name, _label, _env_names, _multi_keys in API_KEY_FIELDS:
            edit = self._fields.get(field_name)
            if edit is None:
                continue
            val = edit.text().strip()
            if hasattr(self._config.api_keys, field_name):
                setattr(self._config.api_keys, field_name, val)
                api_updates[field_name] = val

        try:
            conf = float(self.edit_conf.text())
        except ValueError:
            conf = 0.70
        try:
            workers = int(self.edit_workers.text())
        except ValueError:
            workers = 1

        use_cache = self.chk_use_cache.isChecked()
        self._config.general.use_cache = use_cache
        self._config.general.confidence_min = conf
        self._config.general.workers = workers

        primary_prov = self.cmb_primary.currentText()
        model_name = self.edit_model.text().strip() or "gemini-3.5-flash"
        fallback = [
            self.fallback_model.item(i).text()
            for i in range(self.fallback_model.rowCount())
            if self.fallback_model.item(i).checkState() != Qt.CheckState.Unchecked
        ]
        if not fallback:
            fallback = [self.fallback_model.item(i).text() for i in range(self.fallback_model.rowCount())]

        self._config.llm.provider = primary_prov
        self._config.llm.model = model_name
        self._config.llm.fallback_chain = fallback

        new_config = AppConfig(
            general=GeneralConfig(
                **{
                    **self._config.general.model_dump(),
                    "confidence_min": conf,
                    "workers": workers,
                    "use_cache": use_cache,
                }
            ),
            llm=LLMConfig(
                provider=primary_prov,
                default_provider=primary_prov,
                model=model_name,
                fallback_chain=fallback,
                providers=self._config.llm.providers,
            ),
            api_keys=ApiKeysConfig(
                **{**self._config.api_keys.model_dump(), **api_updates}
            ),
        )

        config_dir = self._config_path.parent
        config_dir.mkdir(parents=True, exist_ok=True)
        toml_data = {
            "general": {
                "recursive": new_config.general.recursive,
                "file_operation": new_config.general.file_operation,
                "confidence_min": new_config.general.confidence_min,
                "workers": new_config.general.workers,
                "use_cache": new_config.general.use_cache,
            },
            "llm": {
                "provider": new_config.llm.provider,
                "default_provider": new_config.llm.provider,
                "fallback_chain": new_config.llm.fallback_chain,
                "model": new_config.llm.model,
            },
            "api_keys": {k: v for k, v in new_config.api_keys.model_dump().items() if v},
        }
        text = tomli_w.dumps(toml_data)
        self._config_path.write_text(text, encoding="utf-8")
        try:
            from tomus.gui.os_integration import secure_chmod_600

            secure_chmod_600(self._config_path)
        except OSError:
            pass

        self.accept()
