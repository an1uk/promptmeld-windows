from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QApplication,
)

from .theme import (
    high_contrast_stylesheet,
    resolve_theme,
    system_high_contrast_enabled,
)


class ResultReviewDialog(QDialog):
    """Let the user review and choose one generated alternative."""

    selected_result_changed = Signal(str)
    copy_result_requested = Signal()
    apply_result_requested = Signal()

    def __init__(self, theme: str = "auto"):
        super().__init__()
        self.theme = theme
        self.requested_count = 1
        self.results: list[str] = []
        self.setWindowTitle("Review generated alternatives")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setModal(False)
        self.resize(760, 520)
        self.setMinimumSize(620, 420)
        self.setAccessibleName("Review generated alternatives")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.title = QLabel("Choose a result")
        self.title.setObjectName("reviewTitle")
        layout.addWidget(self.title)
        self.explanation = QLabel()
        self.explanation.setObjectName("reviewExplanation")
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        self.parse_note = QLabel()
        self.parse_note.setObjectName("reviewWarning")
        self.parse_note.setWordWrap(True)
        self.parse_note.hide()
        layout.addWidget(self.parse_note)

        content = QHBoxLayout()
        self.options = QListWidget()
        self.options.setFixedWidth(165)
        self.options.setAccessibleName("Generated alternatives")
        self.options.currentRowChanged.connect(self._selection_changed)
        content.addWidget(self.options)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Selected generated result")
        content.addWidget(self.preview, 1)
        layout.addLayout(content, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.copy_button = QPushButton("Copy result")
        self.copy_button.clicked.connect(self.copy_result_requested.emit)
        buttons.addWidget(self.copy_button)
        self.apply_button = QPushButton("Apply now")
        self.apply_button.setToolTip(
            "Verify and replace the original selected text with this option."
        )
        self.apply_button.clicked.connect(self.apply_result_requested.emit)
        buttons.addWidget(self.apply_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.setTabOrder(self.options, self.preview)
        self.setTabOrder(self.preview, self.copy_button)
        self.setTabOrder(self.copy_button, self.apply_button)
        self.setTabOrder(self.apply_button, self.close_button)
        self._apply_style()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._system_appearance_changed)

    def set_results(
        self,
        results: list[str],
        *,
        requested_count: int,
        can_apply: bool,
    ) -> None:
        self.results = [value for value in results if value.strip()]
        self.requested_count = requested_count
        self.options.clear()
        self.preview.clear()
        self.copy_button.setText("Copy result")
        self.apply_button.setText("Apply now")
        self.apply_button.setEnabled(can_apply)
        self.apply_button.setVisible(can_apply)
        for index, _value in enumerate(self.results, start=1):
            self.options.addItem(f"Alternative {index}")
        parsed_all = len(self.results) == requested_count
        self.explanation.setText(
            f"ChatGPT generated {len(self.results)} alternative"
            f"{'s' if len(self.results) != 1 else ''}. Select one to review, "
            "copy, or apply to the original selection."
        )
        self.parse_note.setVisible(not parsed_all)
        if not parsed_all:
            self.parse_note.setText(
                f"PromptMeld requested {requested_count} alternatives but "
                "could not separate the response reliably. The complete "
                "response is shown as one option."
            )
        if self.results:
            self.options.setCurrentRow(0)

    def clear_results(self) -> None:
        self.results.clear()
        self.options.clear()
        self.preview.clear()
        self.hide()

    def selected_result(self) -> str:
        index = self.options.currentRow()
        if 0 <= index < len(self.results):
            return self.results[index]
        return ""

    def mark_result_copied(self) -> None:
        self.copy_button.setText("Copied")

    def mark_result_applied(self) -> None:
        self.apply_button.setText("Applied")
        self.apply_button.setEnabled(False)

    def _selection_changed(self, index: int) -> None:
        if not 0 <= index < len(self.results):
            return
        self.preview.setPlainText(self.results[index])
        self.copy_button.setText("Copy result")
        self.selected_result_changed.emit(self.results[index])

    def _apply_style(self) -> None:
        if system_high_contrast_enabled():
            self.setStyleSheet(high_contrast_stylesheet())
            return
        if resolve_theme(self.theme) == "light":
            self.setStyleSheet(
                """
                QDialog { color: #202631; background: #ffffff; }
                QLabel { color: #202631; }
                QLabel#reviewTitle { font-size: 19px; font-weight: 650; }
                QLabel#reviewExplanation { color: #596270; }
                QLabel#reviewWarning {
                    color: #7a4b00; background: #fff4d6;
                    border: 1px solid #e4c36f; border-radius: 7px;
                    padding: 8px;
                }
                QListWidget, QPlainTextEdit {
                    color: #202631; background: #f5f7fa;
                    border: 1px solid #c5ccd6; border-radius: 8px;
                    padding: 7px;
                    selection-background-color: #dce7ff;
                }
                QListWidget::item { padding: 9px; border-radius: 6px; }
                QListWidget::item:selected {
                    color: #173a87; background: #dce7ff;
                }
                QPushButton {
                    color: white; background: #315ecb; border: 0;
                    border-radius: 7px; padding: 8px 15px; font-weight: 600;
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
            QLabel#reviewTitle { color: #f4f5f7; font-size: 19px; font-weight: 650; }
            QLabel#reviewExplanation { color: #b8bec9; }
            QLabel#reviewWarning {
                color: #ffd98a; background: #3f3218;
                border: 1px solid #7b622d; border-radius: 7px;
                padding: 8px;
            }
            QListWidget, QPlainTextEdit {
                color: #f4f5f7; background: #23262d;
                border: 1px solid #3a3f4a; border-radius: 8px;
                padding: 7px;
                selection-background-color: #304a91;
            }
            QListWidget::item { padding: 9px; border-radius: 6px; }
            QListWidget::item:selected { color: white; background: #304a91; }
            QPushButton {
                color: white; background: #4f7cff; border: 0;
                border-radius: 7px; padding: 8px 15px; font-weight: 600;
            }
            QPushButton:hover { background: #6d8df2; }
            QPushButton:disabled { color: #858c98; background: #292d34; }
            """
        )

    def _system_appearance_changed(self, *args) -> None:
        self._apply_style()
