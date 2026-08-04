from promptmeld.models import AppSettings, CapturedSelection
from promptmeld.returning import (
    application_display_name,
    normalize_application_name,
    resolve_return_decision,
)


def selection(*, app: str = "winword.exe", editable: bool = True):
    return CapturedSelection(
        "Original",
        123,
        "Document",
        source_is_editable=editable,
        source_app=app,
    )


def test_application_policy_overrides_global_result_defaults():
    settings = AppSettings(
        auto_submit_enabled=True,
        replace_selected_text_enabled=True,
        application_return_policies={"chrome.exe": "copy"},
    )

    decision = resolve_return_decision(settings, selection(app="CHROME.EXE"))

    assert decision.replace_selection is False
    assert decision.copy_result is True
    assert decision.overridden is True


def test_uneditable_replacement_falls_back_to_copy():
    settings = AppSettings(
        auto_submit_enabled=True,
        application_return_policies={"chrome.exe": "replace"},
    )

    decision = resolve_return_decision(
        settings,
        selection(app="chrome.exe", editable=False),
    )

    assert decision.replace_selection is False
    assert decision.copy_result is True
    assert "editable control" in decision.fallback_reason


def test_result_return_waits_for_automatic_submission():
    settings = AppSettings(
        auto_submit_enabled=False,
        application_return_policies={"winword.exe": "replace"},
    )

    decision = resolve_return_decision(settings, selection())

    assert decision.wants_generated_text is False
    assert "Automatic submission is off" in decision.fallback_reason


def test_application_names_are_path_free_and_human_readable():
    assert normalize_application_name(r"C:\Program Files\Word\WINWORD.EXE") == (
        "winword.exe"
    )
    assert application_display_name("winword.exe") == "Microsoft Word"
