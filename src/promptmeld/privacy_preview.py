from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .privacy import RedactionResult, SensitiveMatch, redact_sensitive_text
from .theme import (
    high_contrast_stylesheet,
    resolve_theme,
    system_high_contrast_enabled,
)


class PrivacyPreviewDialog(QDialog):
    """Require an explicit choice before replacing detected private details."""

    def __init__(
        self,
        text: str,
        matches: tuple[SensitiveMatch, ...],
        *,
        theme: str = "auto",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.original_text = text
        self.matches = matches
        self.theme = theme
        self.continue_unchanged = False
        self.setWindowTitle("Privacy preview")
        self.setAccessibleName("Privacy preview before sending to ChatGPT")
        self.setModal(True)
        self.resize(760, 590)
        self.setMinimumSize(650, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("Check possible private information")
        title.setObjectName("privacyTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "PromptMeld found details that may identify a person or account. "
            "Detection can be wrong. Choose exactly what to replace; nothing "
            "will be redacted unless you continue with selected items."
        )
        explanation.setObjectName("privacyExplanation")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(len(matches), 4)
        self.table.setHorizontalHeaderLabels(
            ("Replace", "Type", "Detected text", "Placeholder")
        )
        self.table.setAccessibleName("Detected private information")
        self.table.setAccessibleDescription(
            "Each row can be included in or excluded from redaction."
        )
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, match in enumerate(matches):
            choice = QTableWidgetItem()
            choice.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            choice.setCheckState(Qt.CheckState.Checked)
            choice.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, 0, choice)
            self.table.setItem(row, 1, QTableWidgetItem(match.label))
            self.table.setItem(row, 2, QTableWidgetItem(match.value))
            self.table.setItem(row, 3, QTableWidgetItem(match.placeholder))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.resizeSection(0, 72)
        header.resizeSection(1, 115)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(3, 120)
        layout.addWidget(self.table, 1)

        choice_row = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.clicked.connect(
            lambda: self._set_all_checked(True)
        )
        choice_row.addWidget(self.select_all_button)
        self.clear_button = QPushButton("Clear choices")
        self.clear_button.clicked.connect(
            lambda: self._set_all_checked(False)
        )
        choice_row.addWidget(self.clear_button)
        choice_row.addStretch(1)
        layout.addLayout(choice_row)

        preview_label = QLabel("Text that will be sent")
        preview_label.setObjectName("privacyPreviewLabel")
        layout.addWidget(preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Redacted prompt preview")
        self.preview.setMaximumHeight(155)
        layout.addWidget(self.preview)

        note = QLabel(
            "The replacement key stays in PromptMeld's memory only. When "
            "PromptMeld retrieves the result, it restores the original values "
            "before copying or applying it. If the result is left in ChatGPT, "
            "the placeholders remain there."
        )
        note.setObjectName("privacyNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        self.redact_button = buttons.addButton(
            "Redact selected and continue",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.redact_button.setDefault(True)
        self.unchanged_button = buttons.addButton(
            "Continue unchanged",
            QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        self.cancel_button = buttons.addButton(
            QDialogButtonBox.StandardButton.Cancel
        )
        self.redact_button.clicked.connect(self._accept_redaction)
        self.unchanged_button.clicked.connect(self._accept_unchanged)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.table.itemChanged.connect(self._update_preview)
        self._update_preview()
        self._apply_style()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._apply_style)

    def selected_matches(self) -> tuple[SensitiveMatch, ...]:
        return tuple(
            match
            for row, match in enumerate(self.matches)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        )

    def redaction_result(self) -> RedactionResult:
        if self.continue_unchanged:
            return RedactionResult(self.original_text, {})
        return redact_sensitive_text(self.original_text, self.selected_matches())

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_preview()

    def _update_preview(self, *args) -> None:
        result = redact_sensitive_text(
            self.original_text,
            self.selected_matches(),
        )
        self.preview.setPlainText(result.text)
        count = len(result.selected_matches)
        self.redact_button.setText(
            f"Redact {count} selected and continue"
            if count != 1
            else "Redact selected item and continue"
        )
        self.redact_button.setEnabled(count > 0)

    def _accept_redaction(self) -> None:
        if self.selected_matches():
            self.continue_unchanged = False
            self.accept()

    def _accept_unchanged(self) -> None:
        self.continue_unchanged = True
        self.accept()

    def _apply_style(self, *args) -> None:
        if system_high_contrast_enabled():
            self.setStyleSheet(high_contrast_stylesheet())
            return
        if resolve_theme(self.theme) == "light":
            self.setStyleSheet(
                """
                QDialog { color: #202631; background: #ffffff; }
                QLabel { color: #202631; }
                QLabel#privacyTitle { font-size: 19px; font-weight: 650; }
                QLabel#privacyExplanation, QLabel#privacyNote { color: #596270; }
                QLabel#privacyPreviewLabel { font-weight: 650; }
                QTableWidget, QPlainTextEdit {
                    color: #202631; background: #f5f7fa;
                    alternate-background-color: #edf1f5;
                    border: 1px solid #c5ccd6; border-radius: 7px;
                    selection-color: #173a87;
                    selection-background-color: #dce7ff;
                }
                QHeaderView::section {
                    color: #303846; background: #e8ecf2;
                    border: 0; border-bottom: 1px solid #c5ccd6;
                    padding: 7px; font-weight: 650;
                }
                QPushButton {
                    color: white; background: #315ecb; border: 0;
                    border-radius: 7px; padding: 8px 14px; font-weight: 600;
                }
                QPushButton:hover { background: #244fae; }
                QPushButton:disabled { color: #7a8491; background: #e5e9ef; }
                """
            )
            return
        self.setStyleSheet(
            """
            QDialog { color: #e9ebef; background: #1b1d23; }
            QLabel { color: #e9ebef; }
            QLabel#privacyTitle { font-size: 19px; font-weight: 650; }
            QLabel#privacyExplanation, QLabel#privacyNote { color: #b8bec9; }
            QLabel#privacyPreviewLabel { color: #f4f5f7; font-weight: 650; }
            QTableWidget, QPlainTextEdit {
                color: #f4f5f7; background: #23262d;
                alternate-background-color: #292d35;
                border: 1px solid #3a3f4a; border-radius: 7px;
                selection-color: white;
                selection-background-color: #304a91;
            }
            QHeaderView::section {
                color: #e9ebef; background: #30343d;
                border: 0; border-bottom: 1px solid #596273;
                padding: 7px; font-weight: 650;
            }
            QPushButton {
                color: white; background: #4f7cff; border: 0;
                border-radius: 7px; padding: 8px 14px; font-weight: 600;
            }
            QPushButton:hover { background: #6d8df2; }
            QPushButton:disabled { color: #858c98; background: #292d34; }
            """
        )
