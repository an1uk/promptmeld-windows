from __future__ import annotations

import json
from dataclasses import replace

import pytest

from promptmeld.action_packs import (
    ACTION_PACK_FORMAT,
    ActionPack,
    ActionPackError,
    action_pack_installation,
    detect_installed_applications,
    load_action_pack,
    load_builtin_action_packs,
    merge_action_pack,
    remove_builtin_action_pack,
    restore_builtin_action_pack,
    save_action_pack,
    update_builtin_action_pack,
)
from promptmeld.config import DEFAULT_FOLDER_ICONS, load_default_actions
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


def test_builtin_catalog_contains_twenty_one_intent_focused_starter_packs():
    packs = load_builtin_action_packs()

    assert len(packs) == 21
    assert {pack.pack_id for pack in packs} == {
        "editing",
        "customer-relations",
        "email",
        "complaints",
        "reports",
        "social-posts",
        "social-replies",
        "social-editing",
        "reviews-feedback",
        "meetings",
        "technical-communication",
        "learning",
        "career-writing",
        "tone-voice",
        "replies-arguments",
        "argument-editing",
        "summaries-extraction",
        "draft-from-selection",
        "decisions-planning",
        "authors-fiction",
        "authors-nonfiction",
    }
    assert all(len(pack.actions) == 4 for pack in packs)
    assert all(pack.category for pack in packs)
    assert all(pack.intended_use for pack in packs)
    assert all(pack.recommended_applications for pack in packs)

    pack_actions = [action for pack in packs for action in pack.actions]
    pack_action_ids = [action.id for action in pack_actions]
    core_action_ids = {action.id for action in load_default_actions()}

    assert all(action.enabled for action in pack_actions)
    assert all(action.hotkey is None for action in pack_actions)
    assert all(action.show_on_home is False for action in pack_actions)
    assert all(
        action.purpose in {"transform", "reply", "analyse", "extract", "develop"}
        for action in pack_actions
    )
    assert all(
        action.result_handling == "purpose_default"
        for action in pack_actions
    )
    assert all(
        action.recipient_audience
        in {
            "inherit",
            "unspecified",
            "friend_family",
            "colleague_peer",
            "manager_senior",
            "customer_client",
            "company_support",
            "public_online",
            "general_reader",
            "other",
        }
        for action in pack_actions
    )
    assert len(pack_action_ids) == len(set(pack_action_ids))
    assert set(pack_action_ids).isdisjoint(core_action_ids)
    represented_folders = {
        "/".join(action.folder.split("/")[:depth])
        for action in pack_actions
        for depth in range(1, len(action.folder.split("/")) + 1)
    }
    assert represented_folders <= set(DEFAULT_FOLDER_ICONS)
    replies = next(pack for pack in packs if pack.pack_id == "replies-arguments")
    assert replies.name == "Replies to selected text"
    assert {action.id for action in replies.actions} == {
        "reply-sarcastic",
        "reply-challenge-claim",
        "reply-polite-firm",
        "reply-steelman",
    }
    arguments = next(
        pack for pack in packs if pack.pack_id == "argument-editing"
    )
    assert arguments.name == "Arguments and evidence"
    assert {action.id for action in arguments.actions} == {
        "argument-strengthen",
        "argument-fact-check-response",
        "argument-test-reasoning",
        "argument-balanced-rewrite",
    }
    customer = next(
        pack for pack in packs if pack.pack_id == "customer-relations"
    )
    assert all(
        action.recipient_audience == "customer_client"
        for action in customer.actions
    )
    for pack_id in ("social-posts", "social-replies", "social-editing"):
        social = next(pack for pack in packs if pack.pack_id == pack_id)
        assert all(
            action.recipient_audience == "public_online"
            for action in social.actions
        )

    fiction = next(pack for pack in packs if pack.pack_id == "authors-fiction")
    assert {action.id for action in fiction.actions} == {
        "fiction-beta-reader",
        "fiction-deeper-questions",
        "fiction-continuity-pov",
        "fiction-scene-craft",
    }
    nonfiction = next(
        pack for pack in packs if pack.pack_id == "authors-nonfiction"
    )
    assert {action.id for action in nonfiction.actions} == {
        "nonfiction-critical-reader",
        "nonfiction-argument-evidence",
        "nonfiction-reader-journey",
        "nonfiction-deeper-questions",
    }
    author_actions = (*fiction.actions, *nonfiction.actions)
    assert all(
        action.folder.startswith("Review & develop/")
        for action in author_actions
    )
    assert all(
        "selected" in action.instruction.lower()
        for action in author_actions
    )
    assert {
        action.id: action.purpose for action in author_actions
    } == {
        "fiction-beta-reader": "analyse",
        "fiction-deeper-questions": "develop",
        "fiction-continuity-pov": "analyse",
        "fiction-scene-craft": "analyse",
        "nonfiction-critical-reader": "analyse",
        "nonfiction-argument-evidence": "analyse",
        "nonfiction-reader-journey": "analyse",
        "nonfiction-deeper-questions": "develop",
    }

    summaries = next(
        pack for pack in packs if pack.pack_id == "summaries-extraction"
    )
    assert all(action.purpose == "extract" for action in summaries.actions)
    decisions = next(
        pack for pack in packs if pack.pack_id == "decisions-planning"
    )
    assert all(action.purpose == "analyse" for action in decisions.actions)


def test_pack_installation_reports_missing_installed_and_modified_states():
    pack = ActionPack(
        "Editing",
        "Editing actions.",
        (
            WritingAction("one", "One", (), "First."),
            WritingAction("two", "Two", (), "Second."),
        ),
        "editing",
    )

    assert action_pack_installation([], pack).status == "not_installed"
    partial = action_pack_installation([pack.actions[0]], pack)
    assert partial.status == "partial"
    assert partial.missing_count == 1
    assert action_pack_installation(list(pack.actions), pack).status == (
        "installed"
    )

    personalised = [
        replace(pack.actions[0], folder="My folder"),
        pack.actions[1],
    ]
    personalised_state = action_pack_installation(personalised, pack)
    assert personalised_state.status == "modified"
    assert personalised_state.label == "Installed — personalised settings"
    content_changed = [
        replace(pack.actions[0], instruction="My custom instruction."),
        pack.actions[1],
    ]
    state = action_pack_installation(content_changed, pack)
    assert state.status == "update_available"
    assert state.label == "Content differs from catalogue"
    assert state.update_count == 1


def test_pack_update_preserves_personal_library_choices_and_adds_missing():
    pack = ActionPack(
        "Editing",
        "Editing actions.",
        (
            WritingAction(
                "one",
                "Current name",
                ("current",),
                "Current instruction.",
                folder="Shipped folder",
                icon="lucide:sparkles",
            ),
            WritingAction("two", "Second", (), "Second instruction."),
        ),
        "editing",
    )
    existing = [
        WritingAction(
            "one",
            "Old name",
            ("old",),
            "Old instruction.",
            hotkey="Ctrl+Alt+8",
            enabled=False,
            folder="My folder",
            show_on_home=True,
            natural_voice="always",
        )
    ]

    result = update_builtin_action_pack(existing, pack)

    assert result.added_count == 1
    assert result.updated_count == 1
    updated = result.actions[0]
    assert updated.name == "Current name"
    assert updated.instruction == "Current instruction."
    assert updated.icon == "lucide:sparkles"
    assert updated.hotkey == "Ctrl+Alt+8"
    assert updated.enabled is False
    assert updated.folder == "My folder"
    assert updated.show_on_home is True
    assert updated.natural_voice == "always"
    assert result.actions[1].id == "two"


def test_pack_restore_and_remove_affect_only_canonical_pack_ids():
    pack = ActionPack(
        "Editing",
        "Editing actions.",
        (
            WritingAction("one", "One", (), "First."),
            WritingAction("two", "Two", (), "Second."),
        ),
        "editing",
    )
    unrelated = WritingAction("mine", "Mine", (), "Keep me.")
    existing = [
        unrelated,
        replace(pack.actions[0], name="Changed"),
    ]

    restored = restore_builtin_action_pack(existing, pack)

    assert [action.id for action in restored.actions] == [
        "mine",
        "one",
        "two",
    ]
    assert restored.actions[1:] == list(pack.actions)

    removed = remove_builtin_action_pack(restored.actions, pack)
    assert removed.actions == [unrelated]
    assert removed.removed_count == 2


def test_installed_application_detection_uses_local_executable_lookup(
    monkeypatch,
):
    monkeypatch.setattr(
        "promptmeld.action_packs.shutil.which",
        lambda executable: (
            f"C:/Apps/{executable}" if executable == "outlook.exe" else None
        ),
    )
    monkeypatch.setattr("promptmeld.action_packs.os.name", "posix")

    detected = detect_installed_applications(
        ("OUTLOOK.EXE", "winword.exe", "")
    )

    assert detected == frozenset({"outlook.exe"})
