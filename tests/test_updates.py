from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from promptmeld.updates import (
    MAX_INSTALLER_BYTES,
    DownloadResult,
    ReleaseInfo,
    UpdateError,
    UpdateState,
    check_is_due,
    check_latest_release,
    download_installer,
    is_newer_version,
    load_update_state,
    parse_version,
    release_from_payload,
    save_update_state,
)


INSTALLER_CONTENT = b"verified PromptMeld installer"
INSTALLER_SHA256 = (
    "12d5e8cb390ea9cbec3cee9e0cab0068b98865ad5dad7d44492097c3fa61f768"
)


class FakeResponse:
    def __init__(self, content: bytes, url: str = "https://github.com"):
        self.stream = io.BytesIO(content)
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def geturl(self) -> str:
        return self.url


def release_payload(
    version: str = "0.1.1",
    *,
    draft: bool = False,
    prerelease: bool = False,
    digest: str | None = f"sha256:{INSTALLER_SHA256}",
    size: int = len(INSTALLER_CONTENT),
    installer_url: str | None = None,
) -> dict:
    tag = f"v{version}"
    name = f"PromptMeld-Setup-v{version}.exe"
    return {
        "tag_name": tag,
        "html_url": (
            f"https://github.com/an1uk/promptmeld-windows/releases/tag/{tag}"
        ),
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": size,
                "digest": digest,
                "browser_download_url": installer_url
                or (
                    "https://github.com/an1uk/promptmeld-windows/releases/"
                    f"download/{tag}/{name}"
                ),
            }
        ],
    }


def test_version_comparison_supports_semver_and_legacy_builds():
    assert parse_version("v0.1.1") == (0, 1, 1, 0)
    assert parse_version("0.1.0.56") == (0, 1, 0, 56)
    assert is_newer_version("0.1.1", "0.1.0.56") is True
    assert is_newer_version("0.1.0.56", "0.1.1") is False


@pytest.mark.parametrize(
    "value",
    ("0.1", "0.1.1.2.3", "0.1.beta", "v01.1.0"),
)
def test_invalid_or_noncanonical_versions_are_rejected(value):
    if value == "v01.1.0":
        with pytest.raises(UpdateError):
            release_from_payload(release_payload("01.1.0"))
    else:
        with pytest.raises(UpdateError):
            parse_version(value)


def test_release_payload_exposes_verified_installer():
    release = release_from_payload(release_payload())

    assert release.version == "0.1.1"
    assert release.installer_name == "PromptMeld-Setup-v0.1.1.exe"
    assert release.installer_size == len(INSTALLER_CONTENT)
    assert release.sha256 == INSTALLER_SHA256
    assert release.installable is True


@pytest.mark.parametrize(
    "changes",
    (
        {"digest": None},
        {"size": MAX_INSTALLER_BYTES + 1},
        {"installer_url": "https://example.com/PromptMeld.exe"},
    ),
)
def test_unsafe_installer_metadata_allows_release_page_only(changes):
    release = release_from_payload(release_payload(**changes))

    assert release.installable is False
    assert release.release_url.endswith("/releases/tag/v0.1.1")
    assert release.install_error


def test_wrong_installer_name_allows_release_page_only():
    payload = release_payload()
    payload["assets"][0]["name"] = "PromptMeld.exe"

    release = release_from_payload(payload)

    assert release.installable is False
    assert "exactly one" in release.install_error


@pytest.mark.parametrize(
    "changes",
    ({"draft": True}, {"prerelease": True}),
)
def test_nonstable_releases_are_rejected(changes):
    with pytest.raises(UpdateError):
        release_from_payload(release_payload(**changes))


def test_update_check_reports_available_and_current_releases():
    raw = json.dumps(release_payload()).encode("utf-8")
    opener = lambda request, timeout: FakeResponse(raw)

    available = check_latest_release("0.1.0.56", opener=opener)
    current = check_latest_release("0.1.1", opener=opener)

    assert available.status == "available"
    assert available.release is not None
    assert current.status == "current"


def test_update_state_round_trip_and_daily_schedule(tmp_path):
    release = release_from_payload(release_payload())
    attempted = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    state = UpdateState(
        last_notified_version="0.1.1",
        cached_release=release,
    ).with_attempt(attempted)
    path = tmp_path / "update-state.json"

    save_update_state(path, state)
    loaded = load_update_state(path)

    assert loaded == state
    assert check_is_due(loaded, attempted + timedelta(hours=23)) is False
    assert check_is_due(loaded, attempted + timedelta(hours=24)) is True


def test_corrupt_update_state_is_ignored(tmp_path):
    path = tmp_path / "update-state.json"
    path.write_text("not json", encoding="utf-8")

    assert load_update_state(path) == UpdateState()


def test_download_verifies_size_and_sha256(tmp_path):
    release = release_from_payload(release_payload())
    progress: list[tuple[int, int]] = []
    opener = lambda request, timeout: FakeResponse(
        INSTALLER_CONTENT,
        "https://release-assets.githubusercontent.com/verified",
    )

    result = download_installer(
        release,
        tmp_path,
        current_version="0.1.0.56",
        report_progress=lambda downloaded, total: progress.append(
            (downloaded, total)
        ),
        opener=opener,
    )

    assert result.succeeded is True
    assert result.path is not None
    assert result.path.read_bytes() == INSTALLER_CONTENT
    assert progress[-1] == (len(INSTALLER_CONTENT), len(INSTALLER_CONTENT))


def test_download_removes_partial_file_after_digest_failure(tmp_path):
    release = release_from_payload(release_payload())
    opener = lambda request, timeout: FakeResponse(
        b"x" * len(INSTALLER_CONTENT),
        "https://release-assets.githubusercontent.com/invalid",
    )

    result = download_installer(
        release,
        tmp_path,
        current_version="0.1.0.56",
        opener=opener,
    )

    assert isinstance(result, DownloadResult)
    assert result.succeeded is False
    assert "digest" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_removes_partial_file_after_size_mismatch(tmp_path):
    release = release_from_payload(release_payload())
    opener = lambda request, timeout: FakeResponse(
        INSTALLER_CONTENT[:-1],
        "https://release-assets.githubusercontent.com/incomplete",
    )

    result = download_installer(
        release,
        tmp_path,
        current_version="0.1.0.56",
        opener=opener,
    )

    assert result.succeeded is False
    assert "incomplete" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_can_be_cancelled_without_leaving_partial_file(tmp_path):
    release = release_from_payload(release_payload())
    opener = lambda request, timeout: FakeResponse(
        INSTALLER_CONTENT,
        "https://release-assets.githubusercontent.com/cancelled",
    )

    result = download_installer(
        release,
        tmp_path,
        current_version="0.1.0.56",
        is_cancelled=lambda: True,
        opener=opener,
    )

    assert result.cancelled is True
    assert list(tmp_path.iterdir()) == []
