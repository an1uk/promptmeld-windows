from __future__ import annotations

from promptmeld.app import PromptMeld
from promptmeld.models import (
    AppSettings,
    ApplicationProfile,
    CapturedSelection,
    WritingAction,
)


class RecordingPromptBuilder:
    def __init__(self) -> None:
        self.options = {}

    def build(self, action, selection, **options):
        self.options = options
        return "built prompt"


class RecordingUsage:
    def __init__(self) -> None:
        self.action_ids: list[str] = []

    def record(self, action_id: str) -> None:
        self.action_ids.append(action_id)


def test_action_submission_uses_source_application_profile_defaults():
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(
        primary_language="English (UK)",
        application_profiles={
            "outlook.exe": ApplicationProfile(
                recipient_audience="customer_client",
                primary_language="English (US)",
                resulting_text_length="short",
                resulting_text_formatting="plain",
                editing_strength="improve",
                preserve_facts="on",
                natural_voice="on",
                project_name="Client correspondence",
            )
        },
    )
    app.prompt_builder = RecordingPromptBuilder()
    app.usage = RecordingUsage()
    app._confirm_automatic_replacement = lambda selection: True
    submissions = []
    app._submit_prompt = lambda prompt, **options: submissions.append(
        (prompt, options)
    )
    selection = CapturedSelection(
        "Original message",
        42,
        "Reply",
        source_is_editable=True,
        source_app="OUTLOOK.EXE",
    )
    action = WritingAction(
        id="reply-email",
        name="Reply to email",
        keywords=(),
        instruction="Draft a reply.",
        folder="Correspondence/Email",
    )

    app._submit_action(action, selection)

    assert app.prompt_builder.options["recipient_audience"] == (
        "customer_client"
    )
    assert app.prompt_builder.options["primary_language"] == "English (US)"
    assert app.prompt_builder.options["resulting_text_length"] == "short"
    assert app.prompt_builder.options["resulting_text_formatting"] == "plain"
    assert app.prompt_builder.options["editing_strength"] == "improve"
    assert app.prompt_builder.options["preserve_facts"] is True
    assert app.prompt_builder.options["natural_voice_enabled"] is True
    assert app.usage.action_ids == ["reply-email"]
    prompt, options = submissions[0]
    assert prompt == "built prompt"
    assert options["project_name"] == (
        "Client correspondence - Correspondence - Email"
    )
    assert options["selection"] == selection


def test_action_submission_can_name_project_for_source_application():
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(
        project_naming_mode="application",
        application_profiles={
            "outlook.exe": ApplicationProfile(
                project_name="Client correspondence"
            )
        },
    )
    app.prompt_builder = RecordingPromptBuilder()
    app.usage = RecordingUsage()
    app._confirm_automatic_replacement = lambda selection: True
    submissions = []
    app._submit_prompt = lambda prompt, **options: submissions.append(options)
    selection = CapturedSelection(
        "Original message",
        42,
        "Reply",
        source_app="outlook.exe",
    )
    action = WritingAction(
        "reply-email",
        "Reply to email",
        (),
        "Draft a reply.",
        folder="Correspondence/Email",
    )

    app._submit_action(action, selection)

    assert submissions[0]["project_name"] == (
        "Client correspondence - Microsoft Outlook"
    )


def test_single_project_mode_ignores_application_project_base_override():
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(
        project_name="PromptMeld",
        project_naming_mode="single",
        application_profiles={
            "outlook.exe": ApplicationProfile(
                project_name="Client correspondence"
            )
        },
    )
    app.prompt_builder = RecordingPromptBuilder()
    app.usage = RecordingUsage()
    app._confirm_automatic_replacement = lambda selection: True
    submissions = []
    app._submit_prompt = lambda prompt, **options: submissions.append(options)

    app._submit_action(
        WritingAction("reply", "Reply", (), "Draft a reply."),
        CapturedSelection("Message", 42, "Mail", source_app="outlook.exe"),
    )

    assert submissions[0]["project_name"] == "PromptMeld"
