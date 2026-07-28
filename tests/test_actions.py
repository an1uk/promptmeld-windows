from __future__ import annotations

from datetime import UTC, datetime, timedelta

from writing_launcher.actions import ActionRegistry
from writing_launcher.models import WritingAction
from writing_launcher.usage import UsageTracker


def make_action(action_id: str, name: str, keywords=()):
    return WritingAction(
        id=action_id,
        name=name,
        keywords=tuple(keywords),
        instruction=f"Instruction for {name}",
    )


def test_search_matches_names_and_keywords(tmp_path):
    usage = UsageTracker(tmp_path / "usage.json")
    registry = ActionRegistry(
        [
            make_action("shorten", "Shorten", ("concise",)),
            make_action("friendly", "Friendly tone", ("warm",)),
        ],
        usage,
    )

    assert [item.id for item in registry.search("concise")] == ["shorten"]
    assert [item.id for item in registry.search("friendly")] == ["friendly"]


def test_usage_and_recency_rank_actions(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=UTC)
    usage = UsageTracker(tmp_path / "usage.json")
    usage.record("friendly", now=now - timedelta(days=2))
    usage.record("shorten", now=now - timedelta(days=1))
    usage.record("shorten", now=now)
    registry = ActionRegistry(
        [
            make_action("friendly", "Friendly"),
            make_action("shorten", "Shorten"),
        ],
        usage,
        now_provider=lambda: now,
    )

    assert [item.id for item in registry.all()] == ["shorten", "friendly"]


def test_disabled_actions_are_excluded(tmp_path):
    usage = UsageTracker(tmp_path / "usage.json")
    action = WritingAction("hidden", "Hidden", (), "No", enabled=False)

    assert ActionRegistry([action], usage).all() == []


def test_configuration_order_breaks_equal_ranking_ties(tmp_path):
    usage = UsageTracker(tmp_path / "usage.json")
    registry = ActionRegistry(
        [
            make_action("zebra", "Zebra"),
            make_action("apple", "Apple"),
        ],
        usage,
    )

    assert [item.id for item in registry.all()] == ["zebra", "apple"]


def test_search_matches_folder_names(tmp_path):
    usage = UsageTracker(tmp_path / "usage.json")
    action = WritingAction(
        "diagnose",
        "Diagnose",
        (),
        "Investigate it.",
        folder="Technical help/Troubleshooting",
    )
    registry = ActionRegistry([action], usage)

    assert [item.id for item in registry.search("technical")] == ["diagnose"]
