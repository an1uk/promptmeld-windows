from __future__ import annotations

import pytest

from writing_launcher.app import project_name_for_action
from writing_launcher.models import WritingAction


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
