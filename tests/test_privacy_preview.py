from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QDialog

from promptmeld import privacy_preview as privacy_preview_module
from promptmeld.app import PromptMeld
from promptmeld.models import AppSettings
from promptmeld.privacy import detect_sensitive_text
from promptmeld.privacy_preview import PrivacyPreviewDialog


def test_privacy_preview_requires_an_explicit_redaction_choice(qtbot):
    text = "Email jane@example.com or call 020 7946 0958."
    dialog = PrivacyPreviewDialog(
        text,
        detect_sensitive_text(text),
        theme="light",
    )
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 2
    assert all(
        dialog.table.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(2)
    )
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)

    result = dialog.redaction_result()
    assert result.text == "Email [EMAIL_1] or call 020 7946 0958."
    assert result.replacements == {"[EMAIL_1]": "jane@example.com"}
    assert dialog.accessibleName() == (
        "Privacy preview before sending to ChatGPT"
    )


def test_privacy_preview_can_continue_completely_unchanged(qtbot):
    text = "Email jane@example.com."
    dialog = PrivacyPreviewDialog(text, detect_sensitive_text(text))
    qtbot.addWidget(dialog)
    accepted = QSignalSpy(dialog.accepted)

    qtbot.mouseClick(dialog.unchanged_button, Qt.MouseButton.LeftButton)

    assert accepted.count() == 1
    assert dialog.redaction_result().text == text
    assert dialog.redaction_result().replacements == {}


def test_privacy_preview_disables_redaction_when_nothing_is_selected(qtbot):
    text = "Email jane@example.com."
    dialog = PrivacyPreviewDialog(text, detect_sensitive_text(text))
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)

    assert dialog.redact_button.isEnabled() is False
    assert dialog.preview.toPlainText() == text


def test_cancelling_privacy_preview_stops_the_request(monkeypatch):
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(theme="dark")
    app.popup = None
    seen = []

    class CancelledPreview:
        def __init__(self, text, matches, **options):
            seen.extend(matches)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        privacy_preview_module,
        "PrivacyPreviewDialog",
        CancelledPreview,
    )

    result = app._review_prompt_privacy("Email jane@example.com")

    assert result is None
    assert seen[0].kind == "email"


def test_privacy_preview_uses_windows_high_contrast_palette(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(
        privacy_preview_module,
        "system_high_contrast_enabled",
        lambda: True,
    )
    text = "Email jane@example.com."

    dialog = PrivacyPreviewDialog(text, detect_sensitive_text(text))
    qtbot.addWidget(dialog)

    assert "palette(window-text)" in dialog.styleSheet()
