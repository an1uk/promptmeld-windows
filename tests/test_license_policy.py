from __future__ import annotations

from tools.check_licenses import (
    PROJECT_ROOT,
    audit_environment,
    check_bundle,
    load_policy,
)


def test_current_dependency_graph_matches_reviewed_license_policy():
    result = audit_environment()

    assert result.errors == []
    assert result.packages["pyside6"].scopes == {"runtime"}
    assert result.packages["pyinstaller"].scopes == {"dev"}


def _create_required_release_files(root, policy):
    for relative in policy["bundle_policy"]["required_release_files"]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")


def test_bundle_policy_rejects_gpl_only_qt_virtual_keyboard(tmp_path):
    policy = load_policy()
    _create_required_release_files(tmp_path, policy)
    forbidden = (
        tmp_path
        / "_internal"
        / "PySide6"
        / "Qt6VirtualKeyboard.dll"
    )
    forbidden.parent.mkdir(parents=True)
    forbidden.write_bytes(b"test")

    errors = check_bundle(tmp_path, policy)

    assert any("GPL-only" in error for error in errors)


def test_bundle_policy_accepts_reviewed_qt_framework_and_plugin(tmp_path):
    policy = load_policy()
    _create_required_release_files(tmp_path, policy)
    framework = tmp_path / "_internal" / "PySide6" / "Qt6Core.dll"
    plugin = (
        tmp_path
        / "_internal"
        / "PySide6"
        / "plugins"
        / "platforms"
        / "qwindows.dll"
    )
    framework.parent.mkdir(parents=True)
    plugin.parent.mkdir(parents=True)
    framework.write_bytes(b"test")
    plugin.write_bytes(b"test")

    assert check_bundle(tmp_path, policy) == []


def test_bundle_policy_rejects_unreviewed_native_dll(tmp_path):
    policy = load_policy()
    _create_required_release_files(tmp_path, policy)
    unreviewed = tmp_path / "_internal" / "new-native-library.dll"
    unreviewed.parent.mkdir(parents=True)
    unreviewed.write_bytes(b"test")

    errors = check_bundle(tmp_path, policy)

    assert any("native runtime DLL" in error for error in errors)


def test_reviewed_static_licence_files_are_present():
    policy = load_policy()

    for entry in policy["static_license_checks"]:
        assert (PROJECT_ROOT / entry["path"]).is_file()
