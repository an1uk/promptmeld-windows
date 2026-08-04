from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .models import SubmissionResult
from .theme import resolve_theme


class AutomationProgressWindow(QWidget):
    """A non-focus-stealing history of the current ChatGPT automation."""

    cancel_requested = Signal()

    def __init__(self, theme: str = "auto"):
        super().__init__()
        self.theme = theme
        self.operation_labels: list[QLabel] = []
        self.current_operation: QLabel | None = None
        self.last_operation: tuple[str, str] | None = None
        self.scroll_animation: QPropertyAnimation | None = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

        self.setWindowTitle("PromptMeld automation")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("automationProgress")
        self.setAccessibleName("PromptMeld automation progress")
        self.setAccessibleDescription(
            "Shows each automation stage without displaying selected text or prompts."
        )
        self.setFixedWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(9)

        self.title = QLabel("Working with ChatGPT")
        self.title.setObjectName("progressTitle")
        self.title.setAccessibleName("Automation status")
        layout.addWidget(self.title)

        self.project = QLabel()
        self.project.setObjectName("progressProject")
        self.project.setAccessibleName("ChatGPT destination")
        self.project.setWordWrap(True)
        layout.addWidget(self.project)

        self.history = QScrollArea()
        self.history.setObjectName("progressHistory")
        self.history.setWidgetResizable(True)
        self.history.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.history.setFixedHeight(244)
        self.history.setAccessibleName("Automation stage history")

        self.history_content = QWidget()
        self.history_content.setObjectName("progressHistoryContent")
        self.history_layout = QVBoxLayout(self.history_content)
        # The breathing room lets the active card settle near the centre even
        # for the first and last operation in a short run.
        self.history_layout.setContentsMargins(8, 94, 8, 94)
        self.history_layout.setSpacing(8)
        self.history.setWidget(self.history_content)
        layout.addWidget(self.history)

        self.privacy_note = QLabel(
            "Only stage names are shown here; selected text and prompts are not."
        )
        self.privacy_note.setObjectName("progressNote")
        self.privacy_note.setWordWrap(True)
        layout.addWidget(self.privacy_note)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAccessibleName("Cancel ChatGPT automation")
        self.cancel_button.setToolTip(
            "Stop waiting for ChatGPT. ChatGPT may continue if the prompt was "
            "already submitted."
        )
        self.cancel_button.clicked.connect(self._request_cancel)
        button_row.addWidget(self.cancel_button)
        self.close_button = QPushButton("Close")
        self.close_button.setAccessibleName("Close automation progress")
        self.close_button.clicked.connect(self.hide)
        self.close_button.hide()
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)
        self.setTabOrder(self.cancel_button, self.close_button)

        self._apply_progress_style()

    def begin(
        self,
        project_name: str,
        *,
        temporary_chat: bool = False,
    ) -> None:
        self.hide_timer.stop()
        if self.scroll_animation is not None:
            self.scroll_animation.stop()
        self._clear_history()
        self.title.setText("Working with ChatGPT")
        self.project.setText(
            "Temporary Chat (outside Projects)"
            if temporary_chat
            else f"Project: {project_name}"
        )
        self.close_button.hide()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.update_stage("preparing", "Preparing the writing request")
        self._show_on_cursor_screen()

    def update_stage(self, stage: str, message: str) -> None:
        operation = (stage.strip(), message.strip())
        if not operation[1] or operation == self.last_operation:
            return
        self._complete_current_operation()
        self._append_operation(*operation, state="current")

    def finish(self, result: SubmissionResult) -> None:
        self.cancel_button.hide()
        if result.cancelled:
            self.title.setText("Cancelled")
            self._complete_current_operation()
            self._append_operation(
                "cancelled",
                result.message or "Automation was cancelled.",
                state="error",
            )
            self.close_button.show()
            return

        if result.output_failed:
            self.title.setText("Result needs attention")
            self._complete_current_operation()
            self._append_operation(
                "output-failed",
                result.message or "The generated result could not be returned.",
                state="error",
            )
            self.close_button.show()
            return

        if result.submitted:
            self.title.setText("Complete")
            self._complete_current_operation()
            self._append_operation(
                "complete",
                "Prompt submitted to ChatGPT",
                state="success",
            )
            self.hide_timer.start(3500)
            return

        if result.prepared:
            self.title.setText("Ready in ChatGPT")
            self._complete_current_operation()
            self._append_operation(
                "ready",
                "The verified prompt is ready for your review",
                state="success",
            )
            self.close_button.show()
            self.hide_timer.start(6000)
            return

        self.title.setText("ChatGPT needs attention")
        self._complete_current_operation()
        self._append_operation(
            "error",
            result.message
            or "The prompt could not be completed automatically.",
            state="error",
        )
        self.close_button.show()

    def _request_cancel(self) -> None:
        if not self.cancel_button.isEnabled():
            return
        self.cancel_button.setEnabled(False)
        self.title.setText("Cancelling")
        self.update_stage(
            "cancelling",
            "Stopping the automation safely",
        )
        self.cancel_requested.emit()

    def _append_operation(
        self,
        stage: str,
        message: str,
        *,
        state: str,
    ) -> None:
        label = QLabel()
        label.setObjectName("progressOperation")
        label.setWordWrap(True)
        label.setAccessibleName("Automation stage")
        label.setProperty("operationText", message)
        self.history_layout.addWidget(label)
        self.operation_labels.append(label)
        self.current_operation = label
        self.last_operation = (stage, message)
        self._set_operation_state(label, state)
        QTimer.singleShot(0, self._centre_current_operation)

    def _complete_current_operation(self) -> None:
        if (
            self.current_operation is not None
            and self.current_operation.property("state") == "current"
        ):
            self._set_operation_state(self.current_operation, "complete")

    def _set_operation_state(self, label: QLabel, state: str) -> None:
        marker = {
            "current": "●",
            "complete": "✓",
            "success": "✓",
            "error": "!",
        }[state]
        label.setProperty("state", state)
        label.setText(f"{marker}  {label.property('operationText')}")
        label.style().unpolish(label)
        label.style().polish(label)

    def _clear_history(self) -> None:
        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.operation_labels.clear()
        self.current_operation = None
        self.last_operation = None
        self.history_content.setMinimumHeight(0)
        self.history.verticalScrollBar().setValue(0)

    def _centre_current_operation(self) -> None:
        if self.current_operation is None:
            return
        self.history_content.setMinimumHeight(
            max(
                self.history.viewport().height(),
                self.history_layout.sizeHint().height(),
            )
        )
        self.history_layout.activate()
        scrollbar = self.history.verticalScrollBar()
        operation_center = self.current_operation.geometry().center().y()
        target = operation_center - self.history.viewport().height() // 2
        target = max(scrollbar.minimum(), min(scrollbar.maximum(), target))

        if self.scroll_animation is not None:
            self.scroll_animation.stop()
        animation = QPropertyAnimation(scrollbar, b"value", self)
        animation.setDuration(280)
        animation.setStartValue(scrollbar.value())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.scroll_animation = animation
        animation.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.cancel_button.isVisible() and self.cancel_button.isEnabled():
                self._request_cancel()
            else:
                self.hide()
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_W
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_on_cursor_screen(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        self.adjustSize()
        self.move(
            geometry.right() - self.width() - 24,
            geometry.bottom() - self.height() - 24,
        )
        self.show()

    def _apply_progress_style(self) -> None:
        if resolve_theme(self.theme) == "light":
            self.setStyleSheet(
                """
                QWidget#automationProgress {
                    color: #202631;
                    background: #ffffff;
                }
                QLabel { color: #202631; }
                QLabel#progressTitle {
                    color: #171c25;
                    font-size: 18px;
                    font-weight: 650;
                }
                QLabel#progressProject { color: #365fc7; font-weight: 600; }
                QScrollArea#progressHistory {
                    background: transparent;
                    border: 0;
                }
                QWidget#progressHistoryContent { background: transparent; }
                QLabel#progressOperation {
                    color: #596270;
                    background: #f5f7fa;
                    border: 1px solid #e1e6ed;
                    border-radius: 8px;
                    padding: 9px 11px;
                }
                QLabel#progressOperation[state="current"] {
                    color: #173a87;
                    background: #dce7ff;
                    border-color: #8fabef;
                    font-weight: 650;
                }
                QLabel#progressOperation[state="success"] {
                    color: #145c31;
                    background: #e6f5eb;
                    border-color: #94cdaa;
                    font-weight: 650;
                }
                QLabel#progressOperation[state="error"] {
                    color: #8f1f1f;
                    background: #fdeaea;
                    border-color: #e2a3a3;
                    font-weight: 650;
                }
                QLabel#progressNote { color: #697381; font-size: 10px; }
                QScrollBar:vertical {
                    background: transparent;
                    width: 8px;
                    margin: 0;
                }
                QScrollBar::handle:vertical {
                    background: #c1c8d2;
                    border-radius: 4px;
                    min-height: 24px;
                }
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical {
                    height: 0;
                }
                QScrollBar::add-page:vertical,
                QScrollBar::sub-page:vertical {
                    background: transparent;
                }
                QPushButton {
                    color: white;
                    background: #315ecb;
                    border: 0;
                    border-radius: 7px;
                    padding: 7px 15px;
                    font-weight: 600;
                }
                QPushButton:hover { background: #244fae; }
                """
            )
            return

        self.setStyleSheet(
            """
            QWidget#automationProgress {
                color: #e9ebef;
                background: #1b1d23;
            }
            QLabel { color: #e9ebef; }
            QLabel#progressTitle {
                color: #f4f5f7;
                font-size: 18px;
                font-weight: 650;
            }
            QLabel#progressProject { color: #b8c8ff; font-weight: 600; }
            QScrollArea#progressHistory {
                background: transparent;
                border: 0;
            }
            QWidget#progressHistoryContent { background: transparent; }
            QLabel#progressOperation {
                color: #b8bec9;
                background: #23262d;
                border: 1px solid #343842;
                border-radius: 8px;
                padding: 9px 11px;
            }
            QLabel#progressOperation[state="current"] {
                color: #ffffff;
                background: #304a91;
                border-color: #6d8df2;
                font-weight: 650;
            }
            QLabel#progressOperation[state="success"] {
                color: #9be7b9;
                background: #173725;
                border-color: #43825c;
                font-weight: 650;
            }
            QLabel#progressOperation[state="error"] {
                color: #ff9d9d;
                background: #4a2528;
                border-color: #9b5358;
                font-weight: 650;
            }
            QLabel#progressNote { color: #9298a5; font-size: 10px; }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #505661;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QPushButton {
                color: white;
                background: #4f7cff;
                border: 0;
                border-radius: 7px;
                padding: 7px 15px;
                font-weight: 600;
            }
            QPushButton:hover { background: #6d8df2; }
            """
        )
