from __future__ import annotations

from writing_launcher.startup import StartupManager


def test_legacy_startup_registration_is_renamed(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    manager = StartupManager()
    registry_values = {manager.LEGACY_VALUE_NAME}
    writes = []
    deleted = []

    monkeypatch.setattr(
        manager,
        "_registry_value_exists",
        lambda name: name in registry_values,
    )
    monkeypatch.setattr(manager, "_write_registry_value", lambda: writes.append(True))
    monkeypatch.setattr(
        manager,
        "_delete_registry_value",
        lambda name: deleted.append(name),
    )

    manager.migrate_legacy_registration()

    assert writes == [True]
    assert deleted == [manager.LEGACY_VALUE_NAME]


def test_current_startup_registration_is_left_unchanged(monkeypatch):
    manager = StartupManager()
    monkeypatch.setattr(
        manager,
        "_registry_value_exists",
        lambda name: name == manager.VALUE_NAME,
    )
    writes = []
    deletes = []
    monkeypatch.setattr(manager, "_write_registry_value", lambda: writes.append(True))
    monkeypatch.setattr(
        manager,
        "_delete_registry_value",
        lambda name: deletes.append(name),
    )

    manager.migrate_legacy_registration()

    assert writes == []
    assert deletes == []
