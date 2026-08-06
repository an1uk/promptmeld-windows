from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

THEME_MODES = ("auto", "light", "dark")

SPI_GETHIGHCONTRAST = 0x0042
SPI_GETCLIENTAREAANIMATION = 0x1042
HCF_HIGHCONTRASTON = 0x00000001


class _HighContrast(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("dwFlags", wintypes.DWORD),
        ("lpszDefaultScheme", wintypes.LPWSTR),
    )


def system_high_contrast_enabled() -> bool:
    """Return whether Windows High Contrast is currently enabled."""

    if sys.platform != "win32":
        return False
    value = _HighContrast()
    value.cbSize = ctypes.sizeof(value)
    try:
        succeeded = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST,
            value.cbSize,
            ctypes.byref(value),
            0,
        )
    except (AttributeError, OSError):
        return False
    return bool(succeeded and value.dwFlags & HCF_HIGHCONTRASTON)


def system_reduced_motion_enabled() -> bool:
    """Respect Windows' 'Show animations' accessibility preference."""

    if sys.platform != "win32":
        return False
    animations_enabled = wintypes.BOOL(True)
    try:
        succeeded = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION,
            0,
            ctypes.byref(animations_enabled),
            0,
        )
    except (AttributeError, OSError):
        return False
    return bool(succeeded and not animations_enabled.value)


def high_contrast_stylesheet() -> str:
    """Use the active Windows palette instead of fixed application colours."""

    return """
        QWidget, QDialog, QWizard, QWizardPage {
            color: palette(window-text);
            background-color: palette(window);
        }
        QLabel {
            color: palette(window-text);
            background-color: transparent;
        }
        QFrame#launcherFrame, QGroupBox, QScrollArea, QMenu {
            color: palette(window-text);
            background-color: palette(window);
            border: 2px solid palette(window-text);
        }
        QGroupBox { margin-top: 10px; padding-top: 10px; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox,
        QListWidget, QTreeWidget, QTableWidget {
            color: palette(text);
            background-color: palette(base);
            border: 2px solid palette(window-text);
            border-radius: 0;
            selection-color: palette(highlighted-text);
            selection-background-color: palette(highlight);
        }
        QListWidget::item:selected, QTreeWidget::item:selected,
        QTableWidget::item:selected, QMenu::item:selected {
            color: palette(highlighted-text);
            background-color: palette(highlight);
        }
        QPushButton, QToolButton {
            color: palette(button-text);
            background-color: palette(button);
            border: 2px solid palette(window-text);
            border-radius: 0;
            padding: 7px 12px;
        }
        QPushButton:focus, QToolButton:focus, QLineEdit:focus,
        QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
        QListWidget:focus, QTreeWidget:focus, QTableWidget:focus {
            border: 3px solid palette(highlight);
        }
        QPushButton:disabled, QToolButton:disabled {
            color: palette(mid);
            background-color: palette(window);
        }
        QCheckBox, QRadioButton {
            color: palette(window-text);
            background-color: palette(window);
        }
        QCheckBox::indicator, QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 2px solid palette(window-text);
            background-color: palette(base);
        }
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {
            border: 3px solid palette(highlight);
            background-color: palette(highlight);
        }
        QScrollBar:vertical, QScrollBar:horizontal {
            background: palette(window);
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: palette(window-text);
            min-height: 24px;
            min-width: 24px;
        }
        QToolTip {
            color: palette(tool-tip-text);
            background-color: palette(tool-tip-base);
            border: 2px solid palette(tool-tip-text);
        }
    """


def message_box_stylesheet(mode: str) -> str:
    """Return complete, scoped styling for every QMessageBox."""

    if system_high_contrast_enabled():
        return """
            QMessageBox {
                color: palette(window-text);
                background-color: palette(window);
            }
            QMessageBox QLabel {
                color: palette(window-text);
                background-color: transparent;
            }
            QMessageBox QTextEdit {
                color: palette(text);
                background-color: palette(base);
                border: 2px solid palette(window-text);
            }
            QMessageBox QPushButton {
                color: palette(button-text);
                background-color: palette(button);
                border: 2px solid palette(window-text);
                border-radius: 0;
                min-width: 96px;
                padding: 7px 12px;
            }
            QMessageBox QPushButton:focus {
                border: 3px solid palette(highlight);
            }
        """
    if resolve_theme(mode) == "light":
        return """
            QMessageBox {
                color: #202631;
                background-color: #ffffff;
            }
            QMessageBox QLabel {
                color: #202631;
                background-color: transparent;
            }
            QMessageBox QLabel#qt_msgbox_label {
                color: #111827;
                font-size: 14px;
                font-weight: 650;
            }
            QMessageBox QLabel#qt_msgbox_informativelabel {
                color: #344052;
                font-size: 13px;
            }
            QMessageBox QTextEdit {
                color: #202631;
                background-color: #f8fafc;
                border: 1px solid #aeb8c5;
            }
            QMessageBox QPushButton {
                color: #ffffff;
                background-color: #315ecb;
                border: 1px solid #244fae;
                border-radius: 6px;
                min-width: 96px;
                padding: 7px 12px;
                font-weight: 600;
            }
            QMessageBox QPushButton:hover { background-color: #244fae; }
            QMessageBox QPushButton:focus { border: 2px solid #102e70; }
            QMessageBox QPushButton:disabled {
                color: #596273;
                background-color: #e5e9ef;
                border-color: #c5ccd6;
            }
            QMessageBox QPushButton#resetConfigurationButton {
                background-color: #a32626;
                border-color: #7f1d1d;
            }
            QMessageBox QPushButton#resetConfigurationButton:hover {
                background-color: #7f1d1d;
            }
        """
    return """
        QMessageBox {
            color: #f4f5f7;
            background-color: #17191e;
        }
        QMessageBox QLabel {
            color: #f4f5f7;
            background-color: transparent;
        }
        QMessageBox QLabel#qt_msgbox_label {
            color: #ffffff;
            font-size: 14px;
            font-weight: 650;
        }
        QMessageBox QLabel#qt_msgbox_informativelabel {
            color: #e1e5ee;
            font-size: 13px;
        }
        QMessageBox QTextEdit {
            color: #f4f5f7;
            background-color: #22252c;
            border: 1px solid #646b77;
        }
        QMessageBox QPushButton {
            color: #ffffff;
            background-color: #315ecb;
            border: 1px solid #6d8df2;
            border-radius: 6px;
            min-width: 96px;
            padding: 7px 12px;
            font-weight: 600;
        }
        QMessageBox QPushButton:hover { background-color: #4f7cff; }
        QMessageBox QPushButton:focus { border: 2px solid #ffffff; }
        QMessageBox QPushButton:disabled {
            color: #9ca3af;
            background-color: #292d34;
            border-color: #505661;
        }
        QMessageBox QPushButton#resetConfigurationButton {
            background-color: #a32626;
            border-color: #ff9d9d;
        }
        QMessageBox QPushButton#resetConfigurationButton:hover {
            background-color: #c43d45;
        }
    """


def apply_message_box_theme(mode: str) -> None:
    """Apply only QMessageBox rules globally so static dialogs stay readable."""

    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(message_box_stylesheet(mode))


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
