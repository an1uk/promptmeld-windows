"""Small interactive source window used for manual selected-text smoke tests."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit


app = QApplication([])
editor = QLineEdit("Selected text for the PromptMeld smoke test.")
editor.setWindowTitle("PromptMeld Smoke Source")
editor.resize(520, 80)
editor.show()


def prepare_selection() -> None:
    editor.raise_()
    editor.activateWindow()
    editor.setFocus()
    editor.selectAll()


QTimer.singleShot(300, prepare_selection)
QTimer.singleShot(15_000, app.quit)
app.exec()
