from promptmeld.models import AppSettings, ApplicationProfile, CapturedSelection
from promptmeld.returning import (
    application_display_name,
    normalize_application_name,
    resolve_application_profile,
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


def test_application_profile_resolves_writing_and_delivery_overrides():
    settings = AppSettings(
        project_name="PromptMeld",
        primary_language="English (UK)",
        auto_submit_enabled=False,
        natural_voice_enabled=True,
        application_profiles={
            "outlook.exe": ApplicationProfile(
                recipient_audience="customer_client",
                primary_language="English (US)",
                resulting_text_length="short",
                editing_strength="improve",
                preserve_facts="off",
                natural_voice="off",
                auto_submit="on",
                project_name="Email writing",
            )
        },
    )

    effective = resolve_application_profile(
        settings,
        selection(app="outlook.exe"),
    )

    assert effective.recipient_audience == "customer_client"
    assert effective.primary_language == "English (US)"
    assert effective.resulting_text_length == "short"
    assert effective.editing_strength == "improve"
    assert effective.preserve_facts is False
    assert effective.natural_voice_enabled is False
    assert effective.auto_submit_enabled is True
    assert effective.project_name == "Email writing"
    assert "recipient_audience" in effective.overridden_fields


def test_application_profile_inherits_unspecified_overall_defaults():
    settings = AppSettings(
        primary_language="Preserve source language",
        guided_drafting_enabled=True,
        application_profiles={
            "notepad.exe": ApplicationProfile(return_mode="replace")
        },
    )

    effective = resolve_application_profile(
        settings,
        selection(app="notepad.exe"),
    )

    assert effective.primary_language == "Preserve source language"
    assert effective.guided_drafting_enabled is True
    assert effective.recipient_audience == "unspecified"
