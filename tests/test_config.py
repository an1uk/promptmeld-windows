from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from promptmeld.config import (
    LEGACY_NATURAL_VOICE_INSTRUCTION,
    ConfigurationError,
    ensure_user_configuration,
    load_actions,
    load_default_actions,
    load_settings,
    save_actions,
    save_settings,
)
from promptmeld.models import AppSettings, WritingAction
from promptmeld.paths import AppPaths
from promptmeld.returning import (
    LEGACY_RECOMMENDED_APPLICATION_PROFILES_V2,
    RECOMMENDED_APPLICATION_PROFILES,
    RECOMMENDED_APPLICATION_RETURN_POLICIES,
)


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
    assert actions[0].recipient_audience == "inherit"
    assert actions[0].purpose == "transform"
    assert actions[0].result_handling == "purpose_default"


def test_action_purpose_and_result_handling_round_trip(tmp_path):
    path = tmp_path / "actions.json"
    action = WritingAction(
        "review",
        "Review",
        (),
        "Review the selected text.",
        purpose="analyse",
        result_handling="copy",
    )

    save_actions(path, [action])

    assert load_actions(path) == [action]
    payload = json.loads(path.read_text(encoding="utf-8"))[0]
    assert payload["purpose"] == "analyse"
    assert payload["result_handling"] == "copy"


def test_legacy_folder_purpose_migration_uses_safe_review_categories(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "summary",
                    "name": "Summary",
                    "instruction": "Summarise it.",
                    "folder": "Summarise & understand/General",
                },
                {
                    "id": "reply",
                    "name": "Reply",
                    "instruction": "Reply to it.",
                    "folder": "Reply/General replies",
                },
            ]
        ),
        encoding="utf-8",
    )

    actions = load_actions(path)

    assert actions[0].purpose == "extract"
    assert actions[1].purpose == "reply"


@pytest.mark.parametrize(
    ("field", "value"),
    (("purpose", "mystery"), ("result_handling", "unsafe-magic")),
)
def test_invalid_action_purpose_options_are_rejected(tmp_path, field, value):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "bad",
                    "name": "Bad",
                    "instruction": "Do it.",
                    field: value,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=field):
        load_actions(path)


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


def test_shipped_starter_set_contains_four_general_actions():
    actions = load_default_actions()

    assert [action.id for action in actions] == [
        "edit-improve",
        "proofread",
        "shorten",
        "draft-reply",
    ]
    assert [action.hotkey for action in actions] == [
        "Ctrl+Alt+1",
        "Ctrl+Alt+2",
        "Ctrl+Alt+3",
        "Ctrl+Alt+4",
    ]
    assert all(action.enabled for action in actions)
    assert all(action.show_on_home for action in actions)


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
    assert settings.project_naming_mode == "action"
    assert settings.theme == "auto"
    assert settings.home_most_used_count == 3
    assert settings.folder_icons["Editing"] == "lucide:pencil"
    assert settings.natural_voice_enabled is False
    # Existing configurations predate onboarding and must not be interrupted.
    assert settings.first_run_setup_completed is True
    assert settings.auto_submit_enabled is False
    assert settings.check_for_updates_enabled is True
    assert settings.replace_selected_text_enabled is False
    assert settings.copy_generated_text_enabled is False
    assert settings.application_return_policies == {}
    assert settings.starter_application_policy_version == 0
    assert settings.temporary_chat_enabled is False
    assert "individual voice" in settings.natural_voice_instruction
    assert settings.primary_language == "English (UK)"
    assert settings.guided_drafting_enabled is False
    assert settings.resulting_text_length == "default"
    assert settings.writing_block_enabled is False
    assert settings.resulting_text_formatting == "default"
    assert settings.title_subject == "none"
    assert settings.starter_action_version == 1


def test_load_settings_rejects_invalid_auto_submit_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"auto_submit_enabled": "sometimes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="auto_submit_enabled"):
        load_settings(path)


def test_load_settings_rejects_invalid_project_naming_mode(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"project_naming_mode": "random"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="project_naming_mode"):
        load_settings(path)


@pytest.mark.parametrize("mode", ["action", "single", "application"])
def test_project_naming_mode_round_trips(tmp_path, mode):
    path = tmp_path / "settings.json"

    save_settings(path, AppSettings(project_naming_mode=mode))

    assert load_settings(path).project_naming_mode == mode


def test_load_settings_rejects_invalid_update_check_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"check_for_updates_enabled": "sometimes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="check_for_updates_enabled"):
        load_settings(path)


@pytest.mark.parametrize(
    "key",
    ("replace_selected_text_enabled", "copy_generated_text_enabled"),
)
def test_load_settings_rejects_invalid_generated_output_value(tmp_path, key):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({key: "sometimes"}), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=key):
        load_settings(path)


def test_application_return_policies_are_normalized_and_saved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "application_return_policies": {
                    r"C:\Program Files\Word\WINWORD.EXE": "replace",
                    "chrome.exe": "copy",
                }
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(path)
    save_settings(path, settings)

    assert load_settings(path).application_return_policies == {
        "chrome.exe": "copy",
        "winword.exe": "replace",
    }


def test_invalid_application_return_policy_is_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"application_return_policies": {"word.exe": "guess"}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="return policies"):
        load_settings(path)


def test_application_profile_writing_defaults_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "application_profiles": {
                    "OUTLOOK.EXE": {
                        "return_mode": "copy",
                        "recipient_audience": "customer_client",
                        "primary_language": "English (US)",
                        "resulting_text_length": "short",
                        "resulting_text_formatting": "plain",
                        "title_subject": "subject",
                        "editing_strength": "improve",
                        "preserve_facts": "on",
                        "natural_voice": "off",
                        "guided_drafting": "on",
                        "writing_block": "off",
                        "auto_submit": "on",
                        "temporary_chat": "off",
                        "privacy_preview": "off",
                        "response_wait": "600",
                        "project_name": "Email writing",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(path)
    profile = settings.application_profiles["outlook.exe"]
    assert profile.recipient_audience == "customer_client"
    assert profile.primary_language == "English (US)"
    assert profile.auto_submit == "on"
    assert profile.privacy_preview == "off"
    assert profile.response_wait == "600"
    assert profile.title_subject == "subject"
    assert profile.project_name == "Email writing"

    save_settings(path, settings)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["application_profiles"]["outlook.exe"][
        "editing_strength"
    ] == "improve"
    assert saved["application_return_policies"]["outlook.exe"] == "copy"


def test_privacy_preview_defaults_to_enabled_and_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    assert load_settings(path).privacy_preview_enabled is True

    save_settings(path, AppSettings(privacy_preview_enabled=False))

    assert load_settings(path).privacy_preview_enabled is False


def test_invalid_privacy_preview_values_are_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"privacy_preview_enabled": "sometimes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="privacy_preview_enabled"):
        load_settings(path)

    path.write_text(
        json.dumps(
            {
                "application_profiles": {
                    "outlook.exe": {"privacy_preview": "sometimes"}
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="privacy_preview"):
        load_settings(path)


def test_invalid_application_response_wait_is_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "application_profiles": {
                    "outlook.exe": {"response_wait": "forever-ish"}
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="response_wait"):
        load_settings(path)


def test_invalid_application_profile_option_is_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "application_profiles": {
                    "outlook.exe": {"recipient_audience": "everyone"}
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="recipient_audience"):
        load_settings(path)


def test_new_configuration_contains_recommended_application_policies(
    tmp_path,
):
    paths = AppPaths.discover(tmp_path)

    ensure_user_configuration(paths)

    settings = load_settings(paths.settings_file)
    assert (
        settings.application_return_policies
        == RECOMMENDED_APPLICATION_RETURN_POLICIES
    )
    assert settings.application_profiles == RECOMMENDED_APPLICATION_PROFILES
    assert settings.starter_action_version == 3
    assert settings.starter_application_policy_version == 3
    assert settings.first_run_setup_completed is False
    assert settings.folder_icons == {"Essentials": "lucide:sparkles"}


def test_first_run_setup_state_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    settings = AppSettings(first_run_setup_completed=False)

    save_settings(path, settings)

    assert load_settings(path).first_run_setup_completed is False


def test_load_settings_rejects_invalid_first_run_setup_state(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"first_run_setup_completed": "yes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="first_run_setup_completed"):
        load_settings(path)


def test_empty_application_policies_receive_recommendations_only_once(
    tmp_path,
):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        json.dumps(
            {
                "application_return_policies": {},
                "starter_action_version": 2,
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    migrated = load_settings(paths.settings_file)
    assert (
        migrated.application_return_policies
        == RECOMMENDED_APPLICATION_RETURN_POLICIES
    )
    assert migrated.application_profiles == RECOMMENDED_APPLICATION_PROFILES
    assert migrated.starter_application_policy_version == 3

    save_settings(
        paths.settings_file,
        replace(
            migrated,
            application_return_policies={},
            application_profiles={},
        ),
    )
    ensure_user_configuration(paths)

    assert load_settings(paths.settings_file).application_return_policies == {}


def test_v1_starter_policies_are_enriched_with_writing_defaults(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        json.dumps(
            {
                "application_return_policies": (
                    RECOMMENDED_APPLICATION_RETURN_POLICIES
                ),
                "starter_application_policy_version": 1,
                "starter_action_version": 2,
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    settings = load_settings(paths.settings_file)
    assert settings.application_profiles == RECOMMENDED_APPLICATION_PROFILES
    assert (
        settings.application_profiles["outlook.exe"].resulting_text_formatting
        == "plain"
    )
    assert settings.application_profiles["ms-teams.exe"].recipient_audience == (
        "colleague_peer"
    )


def test_v2_starter_profiles_receive_per_application_wait_defaults(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    save_settings(
        paths.settings_file,
        AppSettings(
            application_profiles=(
                LEGACY_RECOMMENDED_APPLICATION_PROFILES_V2
            ),
            starter_application_policy_version=2,
        ),
    )

    ensure_user_configuration(paths)

    settings = load_settings(paths.settings_file)
    assert settings.application_profiles == RECOMMENDED_APPLICATION_PROFILES
    assert settings.application_profiles["winword.exe"].response_wait == (
        "indefinite"
    )
    assert settings.application_profiles["chrome.exe"].response_wait == "600"
    assert settings.starter_application_policy_version == 3


def test_existing_application_policies_are_preserved_during_migration(
    tmp_path,
):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    paths.settings_file.write_text(
        json.dumps(
            {
                "application_return_policies": {"thunderbird.exe": "copy"},
                "starter_action_version": 2,
            }
        ),
        encoding="utf-8",
    )

    ensure_user_configuration(paths)

    settings = load_settings(paths.settings_file)
    assert settings.application_return_policies == {
        "thunderbird.exe": "copy"
    }
    assert settings.application_profiles["thunderbird.exe"].return_mode == (
        "copy"
    )
    assert settings.starter_application_policy_version == 3


def test_load_settings_rejects_invalid_temporary_chat_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"temporary_chat_enabled": "sometimes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="temporary_chat_enabled"):
        load_settings(path)


def test_load_settings_validates_resulting_text_length(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"resulting_text_length": "enormous"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="resulting_text_length"):
        load_settings(path)


def test_load_settings_rejects_invalid_writing_block_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"writing_block_enabled": "sometimes"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="writing_block_enabled"):
        load_settings(path)


def test_load_settings_validates_resulting_text_formatting(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"resulting_text_formatting": "elaborate"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="resulting_text_formatting"):
        load_settings(path)


def test_load_settings_validates_title_or_subject_mode(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"title_subject": "headline-ish"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="title_subject"):
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


def test_action_default_audience_round_trips(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "social-reply",
                    "name": "Social reply",
                    "instruction": "Draft a reply.",
                    "recipient_audience": "public_online",
                }
            ]
        ),
        encoding="utf-8",
    )

    actions = load_actions(path)
    save_actions(path, actions)

    assert load_actions(path)[0].recipient_audience == "public_online"


def test_invalid_action_default_audience_is_rejected(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "reply",
                    "name": "Reply",
                    "instruction": "Draft a reply.",
                    "recipient_audience": "everyone-on-earth",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="recipient_audience"):
        load_actions(path)


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
    assert [action.id for action in actions] == [
        "edit-improve",
        "proofread",
        "shorten",
        "draft-reply",
    ]
    assert backup.read_text(encoding="utf-8") == legacy


def test_customized_legacy_configuration_is_preserved_during_version_migration(
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
    paths.settings_file.write_text(
        json.dumps({"starter_action_version": 2}),
        encoding="utf-8",
    )
    before = load_actions(paths.actions_file)
    before_json = paths.actions_file.read_text(encoding="utf-8")

    ensure_user_configuration(paths)

    actions = load_actions(paths.actions_file)
    settings = load_settings(paths.settings_file)
    assert actions == before
    assert paths.actions_file.read_text(encoding="utf-8") == before_json
    assert settings.starter_action_version == 3
    assert not (paths.data_dir / "actions.legacy-v1-backup.json").exists()
    assert not list(paths.data_dir.glob("actions.*-backup.json"))


def test_action_catalogue_version_migration_only_updates_settings(tmp_path):
    paths = AppPaths.discover(tmp_path)
    paths.ensure()
    custom_actions = [
        WritingAction(
            id="my-action",
            name="My action",
            keywords=("custom",),
            instruction="Keep this action exactly as configured.",
            hotkey="Ctrl+Alt+9",
            folder="My tools",
        ),
    ]
    save_actions(paths.actions_file, custom_actions)
    before_json = paths.actions_file.read_text(encoding="utf-8")
    paths.settings_file.write_text(
        json.dumps(
            {
                "starter_action_version": 2,
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
    assert migrated == custom_actions
    assert paths.actions_file.read_text(encoding="utf-8") == before_json
    assert settings.folder_icons["Editing"] == "lucide:sparkles"
    assert settings.starter_action_version == 3
    assert not list(paths.data_dir.glob("actions.*-backup.json"))


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
