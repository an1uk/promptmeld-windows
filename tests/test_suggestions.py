from __future__ import annotations

from datetime import UTC, datetime, timedelta

from promptmeld.actions import ActionRegistry
from promptmeld.models import WritingAction
from promptmeld.suggestions import classify_suggestion_context
from promptmeld.usage import UsageTracker


def make_action(
    action_id: str,
    name: str,
    *,
    keywords: tuple[str, ...] = (),
    instruction: str = "Improve the selected text.",
) -> WritingAction:
    return WritingAction(
        id=action_id,
        name=name,
        keywords=keywords,
        instruction=instruction,
    )


def test_context_classification_keeps_features_not_selected_text():
    private_text = (
        "From: alex@example.com\nSubject: Server problem\n"
        "Can you explain this database error?"
    )

    context = classify_suggestion_context(private_text, "OUTLOOK.EXE")

    assert context.source_application == "outlook.exe"
    assert context.source_label == "Microsoft Outlook"
    assert context.length_band == "short"
    assert context.text_types == ("email", "question", "technical")
    assert private_text not in repr(context)
    assert not hasattr(context, "text")


def test_short_code_is_technical_instead_of_notes():
    context = classify_suggestion_context(
        "def save(value):\n    return client.write(value)\n"
        "TypeError: expected str, got None",
        "Code.exe",
    )

    assert "technical" in context.text_types
    assert "notes" not in context.text_types


def test_code_context_favours_explicit_technical_actions(tmp_path):
    registry = ActionRegistry(
        [
            make_action("clarify", "Improve clarity", keywords=("explain",)),
            make_action(
                "troubleshoot",
                "Troubleshooting checklist",
                keywords=("technical", "diagnose"),
            ),
        ],
        UsageTracker(tmp_path / "usage.json"),
    )
    context = classify_suggestion_context(
        "TypeError: expected str, got None",
        "Code.exe",
    )

    assert registry.suggest(context)[0].action.id == "troubleshoot"


def test_outlook_favours_email_reply_despite_moderate_other_usage(tmp_path):
    now = datetime(2026, 8, 6, tzinfo=UTC)
    usage = UsageTracker(tmp_path / "usage.json")
    for offset in range(4):
        usage.record("technical", now=now - timedelta(days=offset + 1))
    registry = ActionRegistry(
        [
            make_action("technical", "Explain technical issue"),
            make_action(
                "email",
                "Reply to email",
                keywords=("email", "reply",),
            ),
        ],
        usage,
        now_provider=lambda: now,
    )
    context = classify_suggestion_context(
        "From: Pat\nSubject: Delivery\nCan you confirm the delivery date?",
        "outlook.exe",
    )

    suggestions = registry.suggest(context)

    assert suggestions[0].action.id == "email"
    assert "email action for Microsoft Outlook" in suggestions[0].reasons


def test_recent_use_breaks_a_contextual_tie(tmp_path):
    now = datetime(2026, 8, 6, tzinfo=UTC)
    usage = UsageTracker(tmp_path / "usage.json")
    usage.record("follow-up", now=now)
    registry = ActionRegistry(
        [
            make_action("reply", "Reply to email", keywords=("email",)),
            make_action(
                "follow-up",
                "Follow up by email",
                keywords=("reply", "email"),
            ),
        ],
        usage,
        now_provider=lambda: now,
    )
    context = classify_suggestion_context("Can you send an update?", "outlook.exe")

    suggestions = registry.suggest(context)

    assert [item.action.id for item in suggestions] == ["follow-up", "reply"]
    assert "used recently" in suggestions[0].reasons


def test_long_text_and_notes_change_action_ranking(tmp_path):
    registry = ActionRegistry(
        [
            make_action("expand", "Expand this"),
            make_action("shorten", "Shorten and clarify"),
            make_action("notes", "Shape rough notes"),
        ],
        UsageTracker(tmp_path / "usage.json"),
    )

    long_context = classify_suggestion_context("word " * 220, "notepad.exe")
    note_context = classify_suggestion_context(
        "- delayed launch\n- supplier has not replied\n- update the team",
        "notepad.exe",
    )

    assert registry.suggest(long_context)[0].action.id == "shorten"
    assert registry.suggest(note_context)[0].action.id == "notes"


def test_search_uses_context_after_text_match_relevance(tmp_path):
    registry = ActionRegistry(
        [
            make_action("comment", "Reply to comment"),
            make_action("email", "Reply to email"),
        ],
        UsageTracker(tmp_path / "usage.json"),
    )
    context = classify_suggestion_context("Can you reply today?", "outlook.exe")

    assert [item.id for item in registry.search("reply", context=context)] == [
        "email",
        "comment",
    ]
