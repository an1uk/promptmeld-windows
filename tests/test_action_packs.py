from __future__ import annotations

import json

import pytest

from promptmeld.action_packs import (
    ACTION_PACK_FORMAT,
    ActionPack,
    ActionPackError,
    load_action_pack,
    load_builtin_action_packs,
    merge_action_pack,
    save_action_pack,
)
from promptmeld.models import WritingAction


def test_action_pack_round_trip_is_readable_json(tmp_path):
    path = tmp_path / "editing-pack.json"
    pack = ActionPack(
        name="My editing tools",
        description="Small, portable editing actions.",
        actions=(
            WritingAction(
                "make-clear",
                "Make clear",
                ("clarity", "edit"),
                "Improve clarity without changing the meaning.",
                icon="lucide:sparkles",
                folder="My editing",
            ),
        ),
    )

    save_action_pack(path, pack)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == ACTION_PACK_FORMAT
    assert payload["format_version"] == 1
    assert payload["actions"][0]["instruction"].startswith("Improve clarity")
    assert load_action_pack(path) == pack


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"format": "something-else", "format_version": 1},
        {
            "format": ACTION_PACK_FORMAT,
            "format_version": 99,
            "name": "Future",
            "actions": [{}],
        },
        {
            "format": ACTION_PACK_FORMAT,
            "format_version": 1,
            "name": "Empty",
            "actions": [],
        },
    ],
)
def test_invalid_action_pack_metadata_is_rejected(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ActionPackError):
        load_action_pack(path)


def test_merge_adapts_duplicate_ids_and_clashing_shortcuts():
    existing = [
        WritingAction(
            "reply",
            "Existing reply",
            (),
            "Reply.",
            "Ctrl+Alt+7",
        )
    ]
    pack = ActionPack(
        "Replies",
        "",
        (
            WritingAction(
                "reply",
                "Imported reply",
                (),
                "Reply differently.",
                "Alt+Ctrl+7",
            ),
            WritingAction(
                "follow-up",
                "Follow up",
                (),
                "Follow up.",
                "Ctrl+Alt+8",
            ),
        ),
    )

    result = merge_action_pack(existing, pack)

    assert [action.id for action in result.actions] == [
        "reply",
        "reply-2",
        "follow-up",
    ]
    assert result.actions[1].hotkey is None
    assert result.actions[2].hotkey == "Ctrl+Alt+8"
    assert result.added_count == 2
    assert result.renamed_count == 1
    assert result.cleared_hotkey_count == 1
    assert result.first_added_index == 1


def test_builtin_catalog_contains_five_personal_library_starter_packs():
    packs = load_builtin_action_packs()

    assert {pack.pack_id for pack in packs} == {
        "editing",
        "email",
        "complaints",
        "reports",
        "social-posts",
    }
    assert all(len(pack.actions) >= 4 for pack in packs)
    assert all(action.hotkey is None for pack in packs for action in pack.actions)
