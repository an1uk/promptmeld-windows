from promptmeld.models import (
    AppSettings,
    ApplicationProfile,
    CapturedSelection,
    WritingAction,
)
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


def test_review_mode_waits_then_notifies_without_copying_or_replacing():
    settings = AppSettings(
        auto_submit_enabled=True,
        application_profiles={
            "chrome.exe": ApplicationProfile(return_mode="review")
        },
    )

    decision = resolve_return_decision(
        settings,
        selection(app="chrome.exe"),
    )

    assert decision.review_result is True
    assert decision.copy_result is False
    assert decision.replace_selection is False
    assert decision.wants_generated_text is True
    assert decision.summary == (
        "Notify when the result is ready for Google Chrome"
    )


def test_analysis_purpose_defaults_to_safe_review_over_application_replace():
    settings = AppSettings(
        auto_submit_enabled=True,
        application_profiles={
            "winword.exe": ApplicationProfile(return_mode="replace")
        },
    )
    action = WritingAction(
        "critical-review",
        "Critical review",
        (),
        "Analyse the selected text.",
        purpose="analyse",
    )

    decision = resolve_return_decision(settings, selection(), action)

    assert decision.review_result is True
    assert decision.replace_selection is False
    assert decision.copy_result is False
    assert decision.purpose_safe_review is True
    assert decision.action_policy_locked is True
    assert decision.allows_manual_apply is False
    assert "without replacing" in decision.summary


def test_action_can_explicitly_override_safe_purpose_result_handling():
    settings = AppSettings(auto_submit_enabled=True)
    action = WritingAction(
        "critical-review",
        "Critical review",
        (),
        "Analyse the selected text.",
        purpose="analyse",
        result_handling="replace",
    )

    decision = resolve_return_decision(settings, selection(), action)

    assert decision.replace_selection is True
    assert decision.review_result is False
    assert decision.action_overridden is True
    assert decision.purpose_safe_review is False
    assert decision.allows_manual_apply is True


def test_transform_purpose_keeps_application_result_policy():
    settings = AppSettings(
        auto_submit_enabled=True,
        application_profiles={
            "winword.exe": ApplicationProfile(return_mode="replace")
        },
    )
    action = WritingAction(
        "rewrite",
        "Rewrite",
        (),
        "Rewrite the selected text.",
        purpose="transform",
    )

    decision = resolve_return_decision(settings, selection(), action)

    assert decision.replace_selection is True
    assert decision.overridden is True
    assert decision.purpose_safe_review is False


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
        title_subject="automatic",
        application_profiles={
            "outlook.exe": ApplicationProfile(
                recipient_audience="customer_client",
                primary_language="English (US)",
                resulting_text_length="short",
                editing_strength="improve",
                preserve_facts="off",
                natural_voice="off",
                title_subject="subject",
                auto_submit="on",
                privacy_preview="off",
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
    assert effective.title_subject == "subject"
    assert effective.auto_submit_enabled is True
    assert effective.privacy_preview_enabled is False
    assert effective.project_name == "Email writing"
    assert "recipient_audience" in effective.overridden_fields


def test_application_profile_inherits_unspecified_overall_defaults():
    settings = AppSettings(
        primary_language="Preserve source language",
        guided_drafting_enabled=True,
        title_subject="title",
        application_profiles={
            "notepad.exe": ApplicationProfile(return_mode="replace")
        },
    )

    effective = resolve_application_profile(
        settings,
        selection(app="notepad.exe"),
    )

    assert effective.title_subject == "title"

    assert effective.primary_language == "Preserve source language"
    assert effective.guided_drafting_enabled is True
    assert effective.privacy_preview_enabled is True
    assert effective.recipient_audience == "unspecified"


def test_application_profile_resolves_custom_and_indefinite_waits():
    settings = AppSettings(
        application_profiles={
            "winword.exe": ApplicationProfile(
                response_wait="indefinite"
            ),
            "chrome.exe": ApplicationProfile(response_wait="600"),
        }
    )

    word = resolve_application_profile(settings, selection())
    browser = resolve_application_profile(
        settings,
        selection(app="chrome.exe"),
    )

    assert word.response_timeout_seconds is None
    assert browser.response_timeout_seconds == 600.0
    assert "response_wait" in word.overridden_fields
