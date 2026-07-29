from __future__ import annotations

import promptmeld


def test_display_version_uses_packaged_version_file(monkeypatch, tmp_path):
    executable = tmp_path / "PromptMeld.exe"
    executable.touch()
    executable.with_name("VERSION").write_text("1.2.3.45\n", encoding="ascii")
    monkeypatch.setattr(promptmeld.sys, "frozen", True, raising=False)
    monkeypatch.setattr(promptmeld.sys, "executable", str(executable))

    assert promptmeld.display_version() == "1.2.3.45"
