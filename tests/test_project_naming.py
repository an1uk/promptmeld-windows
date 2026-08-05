from __future__ import annotations

import pytest

from promptmeld.app import project_name_for_action, project_name_for_request
from promptmeld.models import WritingAction


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("", "PromptMeld"),
        ("Editing", "PromptMeld - Editing"),
        (
            "Correspondence/Email",
            "PromptMeld - Correspondence - Email",
        ),
        (
            r"Replies & arguments\Analysis",
            "PromptMeld - Replies & arguments - Analysis",
        ),
    ],
)
def test_project_name_is_based_on_configured_action_folder(folder, expected):
    action = WritingAction(
        id="example",
        name="Example",
        keywords=(),
        instruction="Transform the text.",
        folder=folder,
    )

    assert project_name_for_action("PromptMeld", action) == expected


@pytest.mark.parametrize(
    ("mode", "source_application", "expected"),
    [
        ("single", "outlook.exe", "PromptMeld"),
        (
            "application",
            "outlook.exe",
            "PromptMeld - Microsoft Outlook",
        ),
        (
            "application",
            "chrome.exe",
            "PromptMeld - Google Chrome",
        ),
        ("application", "custom-editor.exe", "PromptMeld - custom-editor.exe"),
        ("application", "", "PromptMeld"),
    ],
)
def test_project_name_can_use_one_project_or_the_source_application(
    mode,
    source_application,
    expected,
):
    action = WritingAction(
        "edit",
        "Edit",
        (),
        "Edit this.",
        folder="Editing",
    )

    assert project_name_for_action(
        "PromptMeld",
        action,
        mode,
        source_application,
    ) == expected


def test_custom_instruction_uses_application_strategy_without_an_action():
    assert project_name_for_request(
        "PromptMeld",
        "application",
        "outlook.exe",
    ) == "PromptMeld - Microsoft Outlook"
