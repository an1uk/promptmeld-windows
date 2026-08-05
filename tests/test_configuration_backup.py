from __future__ import annotations

import json
import zipfile
from dataclasses import replace

import pytest

from promptmeld.config import (
    load_actions,
    load_settings,
    save_actions,
    save_settings,
)
from promptmeld.configuration_backup import (
    ConfigurationBackupError,
    create_configuration_backup,
    inspect_configuration_backup,
    restore_configuration_backup,
)
from promptmeld.models import AppSettings, ApplicationProfile, WritingAction
from promptmeld.paths import AppPaths


def configured_paths(tmp_path) -> AppPaths:
    paths = AppPaths.discover(tmp_path / "data")
    paths.ensure()
    save_actions(
        paths.actions_file,
        [
            WritingAction(
                "reply",
                "Reply",
                ("answer",),
                "Draft a useful reply.",
                "Ctrl+Alt+7",
                icon="icons/reply.png",
            )
        ],
    )
    save_settings(
        paths.settings_file,
        AppSettings(
            primary_language="English (US)",
            application_profiles={
                "outlook.exe": ApplicationProfile(
                    recipient_audience="customer_client",
                    resulting_text_formatting="plain",
                )
            },
        ),
    )
    icons = paths.data_dir / "icons"
    icons.mkdir()
    (icons / "reply.png").write_bytes(b"custom-icon")
    return paths


def test_backup_is_one_file_with_configuration_and_icons(tmp_path):
    paths = configured_paths(tmp_path)
    backup = tmp_path / "PromptMeld-backup.zip"

    summary = create_configuration_backup(paths, backup)

    assert backup.is_file()
    assert summary.action_count == 1
    assert summary.icon_count == 1
    assert summary.format_version == 1
    with zipfile.ZipFile(backup) as archive:
        assert set(archive.namelist()) == {
            "promptmeld-backup.json",
            "actions.json",
            "settings.json",
            "icons/reply.png",
        }
        manifest = json.loads(
            archive.read("promptmeld-backup.json").decode("utf-8")
        )
    assert manifest["format"] == "promptmeld-configuration-backup"


def test_restore_replaces_configuration_and_creates_safety_backup(tmp_path):
    paths = configured_paths(tmp_path)
    backup = tmp_path / "PromptMeld-backup.zip"
    create_configuration_backup(paths, backup)
    save_actions(
        paths.actions_file,
        [WritingAction("changed", "Changed", (), "Changed.")],
    )
    save_settings(
        paths.settings_file,
        replace(load_settings(paths.settings_file), primary_language="German"),
    )
    (paths.data_dir / "icons" / "reply.png").write_bytes(b"changed-icon")

    result = restore_configuration_backup(paths, backup)

    assert [action.id for action in load_actions(paths.actions_file)] == [
        "reply"
    ]
    assert load_settings(paths.settings_file).primary_language == "English (US)"
    assert (paths.data_dir / "icons" / "reply.png").read_bytes() == b"custom-icon"
    assert result.safety_backup.is_file()
    safety = inspect_configuration_backup(result.safety_backup)
    assert safety.action_count == 1
    assert safety.format_version == 1


def test_unsafe_archive_path_is_rejected(tmp_path):
    backup = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("../settings.json", "{}")

    with pytest.raises(ConfigurationBackupError, match="unsafe file path"):
        inspect_configuration_backup(backup)


def test_case_insensitive_duplicate_archive_paths_are_rejected(tmp_path):
    backup = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("icons/Example.png", b"one")
        archive.writestr("icons/example.png", b"two")

    with pytest.raises(ConfigurationBackupError, match="duplicate file names"):
        inspect_configuration_backup(backup)


def test_invalid_configuration_is_rejected_before_restore(tmp_path):
    paths = configured_paths(tmp_path)
    valid = tmp_path / "valid.zip"
    invalid = tmp_path / "invalid.zip"
    create_configuration_backup(paths, valid)
    with zipfile.ZipFile(valid) as source, zipfile.ZipFile(invalid, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "settings.json":
                content = b"not json"
            target.writestr(name, content)
    original_actions = paths.actions_file.read_bytes()
    original_settings = paths.settings_file.read_bytes()

    with pytest.raises(ConfigurationBackupError, match="invalid PromptMeld"):
        restore_configuration_backup(paths, invalid)

    assert paths.actions_file.read_bytes() == original_actions
    assert paths.settings_file.read_bytes() == original_settings
