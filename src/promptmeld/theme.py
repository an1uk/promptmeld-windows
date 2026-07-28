from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

THEME_MODES = ("auto", "light", "dark")


def resolve_theme(mode: str) -> str:
    """Resolve an appearance preference to the light or dark colour scheme."""
    if mode in {"light", "dark"}:
        return mode
    app = QApplication.instance()
    if app is not None:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
    return "light"
