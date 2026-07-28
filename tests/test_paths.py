from __future__ import annotations

from writing_launcher.paths import AppPaths


def test_first_promptmeld_run_copies_legacy_data_without_removing_it(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "WritingLauncher"
    legacy.mkdir()
    (legacy / "settings.json").write_text(
        '{"project_name": "WritingLauncher"}',
        encoding="utf-8",
    )
    (legacy / "icons").mkdir()
    (legacy / "icons" / "custom.png").write_bytes(b"icon")

    paths = AppPaths.discover()
    paths.ensure()

    assert paths.data_dir == tmp_path / "PromptMeld"
    assert paths.log_file == paths.data_dir / "promptmeld.log"
    assert paths.settings_file.read_text(encoding="utf-8") == (
        '{"project_name": "WritingLauncher"}'
    )
    assert (paths.data_dir / "icons" / "custom.png").read_bytes() == b"icon"
    assert legacy.is_dir()
    assert (legacy / "settings.json").is_file()


def test_existing_promptmeld_data_is_not_overwritten_by_legacy_data(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "WritingLauncher"
    current = tmp_path / "PromptMeld"
    legacy.mkdir()
    current.mkdir()
    (legacy / "settings.json").write_text("legacy", encoding="utf-8")
    (current / "settings.json").write_text("current", encoding="utf-8")

    paths = AppPaths.discover()
    paths.ensure()

    assert paths.settings_file.read_text(encoding="utf-8") == "current"


def test_explicit_data_directory_does_not_enable_legacy_migration(tmp_path):
    paths = AppPaths.discover(tmp_path / "portable-data")

    paths.ensure()

    assert paths.data_dir.is_dir()
    assert paths.legacy_data_dir is None
