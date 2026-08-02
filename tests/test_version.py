from __future__ import annotations

import tomllib
from pathlib import Path

import promptmeld


def test_display_version_uses_packaged_version_file(monkeypatch, tmp_path):
    executable = tmp_path / "PromptMeld.exe"
    executable.touch()
    executable.with_name("VERSION").write_text("1.2.3.45\n", encoding="ascii")
    monkeypatch.setattr(promptmeld.sys, "frozen", True, raising=False)
    monkeypatch.setattr(promptmeld.sys, "executable", str(executable))

    assert promptmeld.display_version() == "1.2.3.45"


def test_release_version_is_tracked_semver_without_local_build_counter():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    build_script = (root / "scripts" / "build.ps1").read_text(
        encoding="utf-8"
    )

    assert metadata["project"]["version"] == "0.1.1"
    assert "build-number.txt" not in build_script
    assert "$buildVersion = $baseVersion" in build_script
