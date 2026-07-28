from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from promptmeld.config import (
    CORRESPONDENCE_ACTION_IDS,
    LEGACY_NATURAL_VOICE_INSTRUCTION,
    ConfigurationError,
    ensure_user_configuration,
    load_actions,
    load_default_actions,
    load_settings,
    save_actions,
)
from promptmeld.paths import AppPaths


def test_load_actions(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "shorten",
                    "name": "Shorten",
                    "keywords": ["brief"],
                    "instruction": "Make it shorter.",
                    "hotkey": "Ctrl+Alt+2",
                    "enabled": True,
                    "folder": "Editing / Quick actions",
                }
            ]
        ),
        encoding="utf-8",
    )

    actions = load_actions(path)

    assert actions[0].id == "shorten"
    assert actions[0].keywords == ("brief",)
    assert actions[0].hotkey == "Ctrl+Alt+2"
    assert actions[0].icon == "lucide:scissors"
    assert actions[0].folder == "Editing/Quick actions"


def test_save_actions_round_trips_icon_and_order(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "first",
                    "name": "First",
                    "instruction": "First instruction.",
                    "icon": "lucide:pencil",
                    "folder": "First folder",
                },
                {
                    "id": "second",
                    "name": "Second",
                    "instruction": "Second instruction.",
                    "icon": "🙂",
                    "folder": "Second folder/Subfolder",
                },
            ]
        ),
        encoding="utf-8",
    )

    actions = load_actions(path)
    save_actions(path, list(reversed(actions)))
    reloaded = load_actions(path)

    assert [action.id for action in reloaded] == ["second", "first"]
    assert [action.icon for action in reloaded] == ["🙂", "lucide:pencil"]
    assert [action.folder for action in reloaded] == [
        "Second folder/Subfolder",
        "First folder",
    ]


def test_shipped_starter_set_contains_grouped_actions():
    actions = load_default_actions()

    assert len(actions) == 26
    assert {action.id for action in actions} >= {
        "edit-improve",
        "reply-comment",
        "fact-check",
        "troubleshooting-checklist",
        "improve-review",
        *CORRESPONDENCE_ACTION_IDS,
    }
    assert any("/" in action.folder for action in actions)
    assert sum(action.show_on_home for action in actions) == 3
    assert all(
        action.guided_drafting
        for action in actions
        if action.id in CORRESPONDENCE_ACTION_IDS
    )


def test_duplicate_action_ids_are_rejected(tmp_path):
    path = tmp_path / "actions.json"
    action = {"id": "same", "name": "Same", "instruction": "Do it."}
    path.write_text(json.dumps([action, action]), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Duplicate"):
        load_actions(path)


def test_load_settings_validates_timeouts(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"capture_timeout_ms": 25}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="capture_timeout_ms"):
        load_settings(path)


def test_load_settings_includes_home_and_folder_display_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    settings = load_settings(path)

    assert settings.project_name == "PromptMeld"
    assert settings.theme == "auto"
    assert settings.home_most_used_count == 3
    assert settings.folder_icons["Editing"] == "lucide:pencil"
    assert settings.natural_voice_enabled is False
    assert settings.auto_submit_enabled is False
    assert "individual voice" in settings.natural_voice_instruction
    assert settings.primary_language == "English (UK)"
    assert settings.guided_drafting_enabled is False
    assert settings.starter_action_version == 1


def test_load_settings_rejects_invalid_auto_submit_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"auto_submit_enabled": "sometimes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="auto_submit_enabled"):
        load_settings(path)


def test_load_settings_rejects_invalid_theme(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"theme": "midnight"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="theme"):
        load_settings(path)


def test_action_natural_voice_override_round_trips(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "edit",
                    "name": "Edit",
                    "instruction": "Improve this.",
                    "natural_voice": "always",
                }
            ]
        ),
        encoding="utf-8",
    )

    actions = load_actions(path)
    save_actions(path, actions)

    assert load_actions(path)[0].natural_voice == "always"


def test_action_guided_drafting_round_trips(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "reply",
                    "name": "Reply",
                    "instruction": "Draft a reply.",
                    "guided_drafting": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    actions = load_actions(path)
    save_actions(path, actions)

    assert load_actions(path)[0].guided_drafting is True


def test_invalid_action_guided_drafting_is_rejected(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "reply",
                    "name": "Reply",
                    "instruction": "Draft a reply.",
                    "guided_drafting": "sometimes",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="guided_drafting"):
        load_actions(path)


def test_invalid_action_natural_voice_override_is_rejected(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "edit",
                    "name": "Edit",
                    "instruction": "Improve this.",
                    "natural_voice": "sometimes",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="natural_voice"):
        load_actions(path)


def test_untouched_legacy_defaults_are_backed_up_and_migrated(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    legacy = Path(
        str(
            files("promptmeld").joinpath(
                "resources",
                "legacy_default_actions_v1.json",
            )
        )
    ).read_text(encoding="utf-8")
    paths.actions_file.write_text(legacy, encoding="utf-8")

    ensure_user_configuration(paths)

    actions = load_actions(paths.actions_file)
    backup = paths.data_dir / "actions.legacy-v1-backup.json"
    assert len(actions) == 26
    assert all(action.folder for action in actions)
    assert backup.read_text(encoding="utf-8") == legacy


def test_customized_legacy_configuration_is_preserved_during_additive_migration(
    tmp_path,
):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    legacy_path = Path(
        str(
            files("promptmeld").joinpath(
                "resources",
                "legacy_default_actions_v1.json",
            )
        )
    )
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    legacy[0]["name"] = "My customized action"
    paths.actions_file.write_text(json.dumps(legacy), encoding="utf-8")

    ensure_user_configuration(paths)

    actions = load_actions(paths.actions_file)
    assert len(actions) == 14
    assert actions[0].name == "My customized action"
    assert {action.id for action in actions} >= CORRESPONDENCE_ACTION_IDS
    assert not (paths.data_dir / "actions.legacy-v1-backup.json").exists()
    assert (
        paths.data_dir / "actions.pre-correspondence-v2-backup.json"
    ).exists()


def test_correspondence_actions_are_added_once_to_existing_configuration(
    tmp_path,
):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    old_actions = [
        action
        for action in load_default_actions()
        if action.id not in CORRESPONDENCE_ACTION_IDS
    ]
    save_actions(paths.actions_file, old_actions)
    paths.settings_file.write_text(
        json.dumps(
            {
                "folder_icons": {
                    "Editing": "lucide:sparkles",
                },
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    migrated = load_actions(paths.actions_file)
    settings = load_settings(paths.settings_file)
    assert len(migrated) == 26
    assert {action.id for action in migrated} >= CORRESPONDENCE_ACTION_IDS
    assert settings.folder_icons["Editing"] == "lucide:sparkles"
    assert (
        settings.folder_icons["Correspondence/Email"]
        == "lucide:briefcase-business"
    )
    assert settings.starter_action_version == 2
    assert (
        paths.data_dir / "actions.pre-correspondence-v2-backup.json"
    ).exists()

    save_actions(
        paths.actions_file,
        [action for action in migrated if action.id != "reply-email"],
    )
    ensure_user_configuration(paths)

    assert "reply-email" not in {
        action.id for action in load_actions(paths.actions_file)
    }


def test_earlier_launcher_defaults_are_migrated(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        json.dumps(
            {
                "project_name": "Writing Launcher",
                "natural_voice_instruction": (
                    LEGACY_NATURAL_VOICE_INSTRUCTION
                ),
                "starter_action_version": 2,
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    settings = load_settings(paths.settings_file)
    assert settings.project_name == "PromptMeld"
    assert settings.auto_submit_enabled is False
    assert "Do not use em dashes" in settings.natural_voice_instruction
    assert "standard dash (-)" in settings.natural_voice_instruction
    assert (
        json.loads(paths.settings_file.read_text(encoding="utf-8"))[
            "auto_submit_enabled"
        ]
        is False
    )


def test_custom_project_and_voice_wording_are_preserved(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        json.dumps(
            {
                "project_name": "My writing project",
                "natural_voice_instruction": "Keep my custom style.",
                "starter_action_version": 2,
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    settings = load_settings(paths.settings_file)
    assert settings.project_name == "My writing project"
    assert settings.natural_voice_instruction == "Keep my custom style."


@pytest.mark.parametrize(
    "legacy_name",
    ["Writing Launcher", "WritingAssistant", "WritingLauncher"],
)
def test_legacy_project_names_migrate_to_promptmeld(tmp_path, legacy_name):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        json.dumps(
            {
                "project_name": legacy_name,
                "starter_action_version": 2,
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    assert load_settings(paths.settings_file).project_name == "PromptMeld"
