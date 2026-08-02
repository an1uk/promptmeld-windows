from __future__ import annotations

import hashlib

import pytest

from promptmeld import app as app_module
from promptmeld.app import PromptMeld
from promptmeld.models import AppSettings
from promptmeld.updates import ReleaseInfo, UpdateCheckResult, UpdateState


def installable_release() -> ReleaseInfo:
    installer_content = b"verified"
    return ReleaseInfo(
        version="0.1.1",
        release_url=(
            "https://github.com/an1uk/promptmeld-windows/releases/tag/v0.1.1"
        ),
        installer_url=(
            "https://github.com/an1uk/promptmeld-windows/releases/download/"
            "v0.1.1/PromptMeld-Setup-v0.1.1.exe"
        ),
        installer_name="PromptMeld-Setup-v0.1.1.exe",
        installer_size=len(installer_content),
        sha256=hashlib.sha256(installer_content).hexdigest(),
    )


def bare_update_app() -> PromptMeld:
    app = object.__new__(PromptMeld)
    app.update_check_in_progress = True
    app.update_download_in_progress = False
    app.update_last_error = ""
    app.update_current_confirmed = False
    app.update_state = UpdateState()
    app.available_update = None
    app.settings_dialog = None
    app._save_update_state = lambda: None
    app._refresh_update_surfaces = lambda: None
    return app


def test_automatic_update_notification_is_shown_once_per_version():
    app = bare_update_app()
    notifications: list[tuple] = []
    app.notify = lambda *args: notifications.append(args)
    result = UpdateCheckResult(
        status="available",
        release=installable_release(),
    )

    app._update_check_finished(result, manual=False)
    app.update_check_in_progress = True
    app._update_check_finished(result, manual=False)

    assert len(notifications) == 1
    assert app.update_state.last_notified_version == "0.1.1"
    assert app.update_state.cached_release == result.release


def test_automatic_update_check_failure_is_silent():
    app = bare_update_app()
    notifications: list[tuple] = []
    app.notify = lambda *args: notifications.append(args)

    app._update_check_finished(
        UpdateCheckResult(status="error", error="offline"),
        manual=False,
    )

    assert notifications == []
    assert app.update_last_error == "offline"


def test_disabled_automatic_updates_do_not_schedule_network_check(monkeypatch):
    app = object.__new__(PromptMeld)
    app.settings = AppSettings(check_for_updates_enabled=False)
    app.update_check_in_progress = False
    app.update_download_in_progress = False
    app.update_state = UpdateState()
    calls: list[bool] = []
    app.check_for_updates = lambda *, manual: calls.append(manual)
    monkeypatch.setattr(app_module.sys, "frozen", True, raising=False)

    app._scheduled_update_check()

    assert calls == []


def test_manual_update_check_bypasses_automatic_update_setting():
    class ThreadPool:
        def __init__(self):
            self.workers = []

        def start(self, worker):
            self.workers.append(worker)

    app = object.__new__(PromptMeld)
    app.settings = AppSettings(check_for_updates_enabled=False)
    app.update_check_in_progress = False
    app.update_download_in_progress = False
    app.update_last_error = ""
    app.update_state = UpdateState()
    app.settings_dialog = None
    app.thread_pool = ThreadPool()
    app._save_update_state = lambda: None
    app._refresh_update_surfaces = lambda: None

    app.check_for_updates(manual=True)

    assert app.update_check_in_progress is True
    assert app.update_state.last_attempt_utc
    assert len(app.thread_pool.workers) == 1


def test_installer_launch_failure_restores_mutex_and_hotkeys(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []

    class Hotkeys:
        def unregister_all(self):
            events.append("unregister")

    class Instance:
        def release(self):
            events.append("release")

        def reacquire_mutex(self):
            events.append("reacquire")
            return True

    class Tray:
        def hide(self):
            events.append("hide")

    class Application:
        def quit(self):
            events.append("quit")

    app = object.__new__(PromptMeld)
    app.update_downloads_dir = tmp_path
    app.hotkeys = Hotkeys()
    app.single_instance = Instance()
    app.settings_dialog = None
    app.tray = Tray()
    app.qt_app = Application()
    app.register_hotkeys = lambda: events.append("register")
    installer = tmp_path / "PromptMeld-Setup-v0.1.1.exe"
    installer.write_bytes(b"verified")

    monkeypatch.setattr(app_module, "shutdown_automation_helper", lambda: None)
    monkeypatch.setattr(
        app_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("blocked")),
    )
    monkeypatch.setattr(
        app_module.QMessageBox,
        "critical",
        lambda *args, **kwargs: None,
    )

    app._launch_update_installer(installer, installable_release())

    assert events == ["unregister", "release", "reacquire", "register"]


def test_verified_installer_launch_releases_mutex_and_quits(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []

    class Hotkeys:
        def unregister_all(self):
            events.append("unregister")

    class Instance:
        def release(self):
            events.append("release")

    class Tray:
        def hide(self):
            events.append("hide")

    class Application:
        def quit(self):
            events.append("quit")

    app = object.__new__(PromptMeld)
    app.update_downloads_dir = tmp_path
    app.hotkeys = Hotkeys()
    app.single_instance = Instance()
    app.settings_dialog = None
    app.tray = Tray()
    app.qt_app = Application()
    installer = tmp_path / "PromptMeld-Setup-v0.1.1.exe"
    installer.write_bytes(b"verified")

    monkeypatch.setattr(app_module, "shutdown_automation_helper", lambda: None)
    monkeypatch.setattr(
        app_module.subprocess,
        "Popen",
        lambda *args, **kwargs: events.append("launch"),
    )

    app._launch_update_installer(installer, installable_release())

    assert events == ["unregister", "release", "launch", "hide", "quit"]


@pytest.mark.parametrize(
    ("choice", "expected", "expected_save_calls"),
    (
        ("Save changes and install", True, 1),
        ("Discard changes and install", True, 0),
        ("Cancel", False, 0),
    ),
)
def test_unsaved_configuration_update_choices(
    monkeypatch,
    choice,
    expected,
    expected_save_calls,
):
    class Roles:
        AcceptRole = 1
        DestructiveRole = 2
        RejectRole = 3

    class Icons:
        Warning = 1

    class FakeMessageBox:
        ButtonRole = Roles
        Icon = Icons

        def __init__(self, parent):
            self.buttons = {}

        def setWindowTitle(self, value):
            pass

        def setIcon(self, value):
            pass

        def setText(self, value):
            pass

        def addButton(self, text, role):
            button = object()
            self.buttons[text] = button
            return button

        def exec(self):
            pass

        def clickedButton(self):
            return self.buttons[choice]

    class SettingsDialog:
        def __init__(self):
            self.save_calls = 0

        def has_unsaved_changes(self):
            return True

        def save_changes(self):
            self.save_calls += 1
            return True

    app = object.__new__(PromptMeld)
    app.settings_dialog = SettingsDialog()
    monkeypatch.setattr(app_module, "QMessageBox", FakeMessageBox)

    result = app._resolve_unsaved_settings_before_update()

    assert result is expected
    assert app.settings_dialog.save_calls == expected_save_calls
