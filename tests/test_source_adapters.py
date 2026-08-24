from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QPlainTextEdit

from promptmeld import windows
from promptmeld.models import ApplyReceipt, CapturedSelection, SourceFingerprint


def test_current_process_identity_uses_stable_native_creation_time():
    process_id, process_started = windows.SelectionCapture._current_process_identity()

    assert process_id == os.getpid()
    assert process_started > 0


def verified_selection(
    text: str = "original",
    *,
    source_hwnd: int = 100,
    focused_hwnd: int = 101,
    selection_start: int = 0,
    selection_end: int | None = None,
) -> CapturedSelection:
    end = (
        selection_start + windows._utf16_units(text)
        if selection_end is None
        else selection_end
    )
    return CapturedSelection(
        text=text,
        source_hwnd=source_hwnd,
        source_title="not retained by recovery",
        source_is_editable=True,
        source_app="notepad.exe",
        source_fingerprint=SourceFingerprint(
            process_id=200,
            process_started=300,
            top_level_hwnd=source_hwnd,
            top_level_class="Notepad",
            focused_hwnd=focused_hwnd,
            focused_class="RichEditD2DPT",
            adapter_id=windows.VERIFIED_EDIT_ADAPTER,
            selection_start=selection_start,
            selection_end=end,
        ),
    )


def install_edit_state(monkeypatch, initial: str, selection: tuple[int, int]):
    state = {"text": initial, "selection": selection, "replacements": []}
    monkeypatch.setattr(windows, "_activate_verified_source", lambda *args: None)
    monkeypatch.setattr(
        windows,
        "_edit_selection_range",
        lambda hwnd: state["selection"],
    )
    monkeypatch.setattr(windows, "_edit_text", lambda hwnd: state["text"])
    monkeypatch.setattr(
        windows,
        "_set_edit_selection",
        lambda hwnd, start, end: state.update(selection=(start, end)),
    )

    def replace_selection(hwnd, value):
        start, end = state["selection"]
        text = state["text"]
        start_index = windows._utf16_offset_to_python_index(text, start)
        end_index = windows._utf16_offset_to_python_index(text, end)
        state["text"] = text[:start_index] + value + text[end_index:]
        caret = start + windows._utf16_units(value)
        state["selection"] = (caret, caret)
        state["replacements"].append(value)

    monkeypatch.setattr(windows, "_replace_edit_selection", replace_selection)
    return state


def test_verified_apply_reads_back_exact_unicode_range(monkeypatch):
    original = "A😀originalZ"
    start = windows._utf16_units("A😀")
    end = start + windows._utf16_units("original")
    selection = verified_selection(
        selection_start=start,
        selection_end=end,
    )
    state = install_edit_state(monkeypatch, original, (start, end))

    receipt = windows.apply_verified_source_selection(selection, "new🙂")

    assert state["text"] == "A😀new🙂Z"
    assert receipt.replacement_start == start
    assert receipt.replacement_end == start + windows._utf16_units("new🙂")
    assert receipt.original_text == "original"
    assert receipt.generated_text == "new🙂"


def test_verified_apply_comparison_does_not_discard_trailing_newlines():
    assert windows._normalise_selected_text("generated\n") != (
        windows._normalise_selected_text("generated")
    )


def test_verified_apply_rolls_back_post_insert_mismatch(monkeypatch):
    selection = verified_selection(
        text="old",
        selection_start=5,
        selection_end=8,
    )
    state = install_edit_state(monkeypatch, "left old right", (5, 8))
    real_replace = windows._replace_edit_selection
    calls = 0

    def mismatch_then_restore(hwnd, value):
        nonlocal calls
        calls += 1
        real_replace(hwnd, "BROKEN" if calls == 1 else value)

    monkeypatch.setattr(
        windows,
        "_replace_edit_selection",
        mismatch_then_restore,
    )

    with pytest.raises(windows.SourceRecoveryError, match="did not verify") as raised:
        windows.apply_verified_source_selection(selection, "new")

    assert raised.value.original_preserved is True
    assert state["text"] == "left old right"
    assert state["replacements"] == ["BROKEN", "old"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"source_hwnd": 999}, "top-level window"),
        ({"process_id": 999}, "reused"),
        ({"process_started": 999}, "process has been replaced"),
        ({"top_level_class": "Other"}, "window identity changed"),
        ({"focused_class": "Other"}, "editor identity changed"),
    ],
)
def test_source_fingerprint_rejects_reused_or_changed_identity(
    monkeypatch,
    change,
    message,
):
    selection = verified_selection()
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    source_hwnd = int(change.pop("source_hwnd", selection.source_hwnd))
    fingerprint = SourceFingerprint(
        **{
            "process_id": fingerprint.process_id,
            "process_started": fingerprint.process_started,
            "top_level_hwnd": fingerprint.top_level_hwnd,
            "top_level_class": fingerprint.top_level_class,
            "focused_hwnd": fingerprint.focused_hwnd,
            "focused_class": fingerprint.focused_class,
            "adapter_id": fingerprint.adapter_id,
            "selection_start": fingerprint.selection_start,
            "selection_end": fingerprint.selection_end,
            **change,
        }
    )
    monkeypatch.setattr(windows.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(windows.win32gui, "IsChild", lambda parent, child: True)
    monkeypatch.setattr(
        windows.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (1, 200),
    )
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_source_process_identity",
        staticmethod(lambda hwnd: (200, 300)),
    )
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_window_class",
        staticmethod(
            lambda hwnd: "Notepad" if hwnd == selection.source_hwnd else "RichEditD2DPT"
        ),
    )

    with pytest.raises(windows.SourceRecoveryError, match=message):
        windows._validate_source_fingerprint(source_hwnd, fingerprint)


def test_source_fingerprint_rejects_wrong_focused_child_with_identical_text(
    monkeypatch,
):
    selection = verified_selection()
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    monkeypatch.setattr(windows.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(windows.win32gui, "IsChild", lambda parent, child: False)

    with pytest.raises(windows.SourceRecoveryError, match="no longer belongs"):
        windows._validate_source_fingerprint(selection.source_hwnd, fingerprint)


def test_source_fingerprint_fails_closed_when_process_start_cannot_be_read(
    monkeypatch,
):
    selection = verified_selection()
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    monkeypatch.setattr(windows.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(windows.win32gui, "IsChild", lambda parent, child: True)
    monkeypatch.setattr(
        windows.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (1, fingerprint.process_id),
    )
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_source_process_identity",
        staticmethod(lambda hwnd: (fingerprint.process_id, 0)),
    )

    with pytest.raises(windows.SourceRecoveryError, match="could not be revalidated"):
        windows._validate_source_fingerprint(selection.source_hwnd, fingerprint)


def test_source_activation_requires_exact_focused_control(monkeypatch):
    selection = verified_selection()
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    ticks = iter((0.0, 2.0))
    monkeypatch.setattr(windows, "_validate_source_fingerprint", lambda *args: None)
    monkeypatch.setattr(windows.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(windows.win32gui, "BringWindowToTop", lambda hwnd: None)
    monkeypatch.setattr(windows.win32gui, "SetForegroundWindow", lambda hwnd: None)
    monkeypatch.setattr(
        windows.win32gui,
        "GetForegroundWindow",
        lambda: selection.source_hwnd,
    )
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_focused_hwnd",
        staticmethod(lambda: 999),
    )
    monkeypatch.setattr(windows.time, "monotonic", lambda: next(ticks))

    with pytest.raises(windows.SourceRecoveryError, match="exact captured focus"):
        windows._activate_verified_source(selection.source_hwnd, fingerprint)


def test_reversal_refuses_if_inserted_range_changed(monkeypatch):
    selection = verified_selection(text="old", selection_start=5, selection_end=8)
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    receipt = ApplyReceipt(
        adapter_id=windows.VERIFIED_EDIT_ADAPTER,
        source_fingerprint=fingerprint,
        original_text="old",
        generated_text="new",
        replacement_start=5,
        replacement_end=8,
    )
    state = install_edit_state(monkeypatch, "left NEW right", (8, 8))

    with pytest.raises(windows.SourceRecoveryError, match="changed"):
        windows.reverse_verified_source_replacement(receipt)

    assert state["replacements"] == []


def test_reversal_restores_and_reads_back_exact_range(monkeypatch):
    selection = verified_selection(text="old", selection_start=5, selection_end=8)
    fingerprint = selection.source_fingerprint
    assert fingerprint is not None
    receipt = ApplyReceipt(
        adapter_id=windows.VERIFIED_EDIT_ADAPTER,
        source_fingerprint=fingerprint,
        original_text="old",
        generated_text="new🙂",
        replacement_start=5,
        replacement_end=5 + windows._utf16_units("new🙂"),
    )
    state = install_edit_state(
        monkeypatch,
        "left new🙂 right",
        (receipt.replacement_end, receipt.replacement_end),
    )

    windows.reverse_verified_source_replacement(receipt)

    assert state["text"] == "left old right"
    assert state["replacements"] == ["old"]


def test_automatic_source_return_never_interrupts_third_application(monkeypatch):
    selection = verified_selection()
    monkeypatch.setattr(windows.win32gui, "GetForegroundWindow", lambda: 999)

    assert windows.automatic_source_return_is_allowed(selection, 500) is False

    monkeypatch.setattr(
        windows.win32gui,
        "GetForegroundWindow",
        lambda: selection.source_hwnd,
    )
    assert windows.automatic_source_return_is_allowed(selection, 500) is True

    monkeypatch.setattr(windows.win32gui, "GetForegroundWindow", lambda: 500)
    assert windows.automatic_source_return_is_allowed(selection, 500) is True


def test_promptmeld_scratch_adapter_applies_reads_back_and_reverses(
    monkeypatch,
    qtbot,
):
    scratch = QPlainTextEdit()
    qtbot.addWidget(scratch)
    scratch.setPlainText("PromptMeld canary source")
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_source_process_identity",
        staticmethod(lambda hwnd: (123, 456)),
    )
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_current_process_identity",
        staticmethod(lambda: (123, 456)),
    )
    monkeypatch.setattr(
        windows.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (1, 123),
    )
    monkeypatch.setattr(windows.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_window_class",
        staticmethod(lambda hwnd: "PromptMeldScratch"),
    )
    monkeypatch.setattr(
        windows,
        "_validate_source_fingerprint",
        lambda *args: None,
    )
    selection = windows.capture_promptmeld_scratch_selection(scratch)

    receipt = windows.apply_verified_source_selection(selection, "answer")

    assert scratch.toPlainText() == "answer"
    assert receipt.adapter_id == windows.PROMPTMELD_SCRATCH_ADAPTER
    windows.reverse_verified_source_replacement(receipt)
    assert scratch.toPlainText() == "PromptMeld canary source"
    windows.release_promptmeld_scratch_selection(selection)


def test_promptmeld_scratch_adapter_creates_a_real_hidden_native_window(qtbot):
    if windows.QApplication.platformName().casefold() != "windows":
        pytest.skip("requires the native Windows Qt platform plugin")
    scratch = QPlainTextEdit()
    qtbot.addWidget(scratch)
    scratch.setPlainText("PromptMeld canary source")

    selection = windows.capture_promptmeld_scratch_selection(scratch)
    fingerprint = selection.source_fingerprint

    assert fingerprint is not None
    assert fingerprint.process_id
    assert fingerprint.process_started
    assert fingerprint.top_level_hwnd
    assert fingerprint.top_level_class
    assert fingerprint.selection_start == 0
    assert fingerprint.selection_end == len("PromptMeld canary source")
    assert scratch.testAttribute(
        windows.Qt.WidgetAttribute.WA_DontShowOnScreen
    )
    assert scratch.isVisible() is True
    windows.release_promptmeld_scratch_selection(selection)


def test_promptmeld_scratch_reversal_refuses_changed_result(
    monkeypatch,
    qtbot,
):
    scratch = QPlainTextEdit()
    qtbot.addWidget(scratch)
    scratch.setPlainText("PromptMeld canary source")
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_source_process_identity",
        staticmethod(lambda hwnd: (123, 456)),
    )
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_current_process_identity",
        staticmethod(lambda: (123, 456)),
    )
    monkeypatch.setattr(
        windows.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (1, 123),
    )
    monkeypatch.setattr(windows.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(
        windows.SelectionCapture,
        "_window_class",
        staticmethod(lambda hwnd: "PromptMeldScratch"),
    )
    monkeypatch.setattr(
        windows,
        "_validate_source_fingerprint",
        lambda *args: None,
    )
    selection = windows.capture_promptmeld_scratch_selection(scratch)
    receipt = windows.apply_verified_source_selection(selection, "answer")
    scratch.setPlainText("changed")

    with pytest.raises(windows.SourceRecoveryError, match="changed"):
        windows.reverse_verified_source_replacement(receipt)

    windows.release_promptmeld_scratch_selection(selection)
