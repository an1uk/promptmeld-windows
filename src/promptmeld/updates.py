from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .branding import APP_NAME, REPOSITORY_URL

REPOSITORY_SLUG = "an1uk/promptmeld-windows"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{REPOSITORY_SLUG}/releases/latest"
)
RELEASES_URL = f"{REPOSITORY_URL}/releases"
UPDATE_CHECK_INTERVAL = timedelta(hours=24)
MAX_INSTALLER_BYTES = 250 * 1024 * 1024
MAX_RELEASE_RESPONSE_BYTES = 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 128 * 1024
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")
_SHA256_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class UpdateError(ValueError):
    """A GitHub release or downloaded installer was not safe to use."""


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    release_url: str
    installer_url: str | None = None
    installer_name: str | None = None
    installer_size: int | None = None
    sha256: str | None = None
    install_error: str = ""

    @property
    def installable(self) -> bool:
        return bool(
            self.installer_url
            and self.installer_name
            and self.installer_size
            and self.sha256
            and not self.install_error
        )


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    status: Literal["available", "current", "error"]
    release: ReleaseInfo | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path | None = None
    error: str = ""
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return self.path is not None and not self.error and not self.cancelled


@dataclass(frozen=True, slots=True)
class UpdateState:
    last_attempt_utc: str = ""
    last_notified_version: str = ""
    cached_release: ReleaseInfo | None = None

    def with_attempt(self, attempted_at: datetime | None = None) -> UpdateState:
        value = (attempted_at or datetime.now(UTC)).astimezone(UTC)
        return UpdateState(
            last_attempt_utc=value.isoformat().replace("+00:00", "Z"),
            last_notified_version=self.last_notified_version,
            cached_release=self.cached_release,
        )


def parse_version(value: str) -> tuple[int, int, int, int]:
    match = _VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise UpdateError(
            "Versions must contain three or four numeric components."
        )
    parts = [int(match.group(index) or 0) for index in range(1, 5)]
    return tuple(parts)  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def check_is_due(
    state: UpdateState,
    now: datetime | None = None,
) -> bool:
    if not state.last_attempt_utc:
        return True
    try:
        attempted_at = datetime.fromisoformat(
            state.last_attempt_utc.replace("Z", "+00:00")
        )
    except ValueError:
        return True
    if attempted_at.tzinfo is None:
        attempted_at = attempted_at.replace(tzinfo=UTC)
    elapsed = (now or datetime.now(UTC)).astimezone(UTC) - attempted_at
    return elapsed < timedelta(0) or elapsed >= UPDATE_CHECK_INTERVAL


def _valid_release_url(value: object, tag_name: str) -> str:
    if not isinstance(value, str):
        raise UpdateError("The GitHub release page URL is missing.")
    parsed = urlparse(value)
    expected_path = f"/{REPOSITORY_SLUG}/releases/tag/{tag_name}"
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "github.com"
        or parsed.path.casefold() != expected_path.casefold()
        or parsed.query
        or parsed.fragment
    ):
        raise UpdateError("The GitHub release page URL was not recognised.")
    return value


def _valid_installer_url(value: object, tag_name: str, name: str) -> str:
    if not isinstance(value, str):
        raise UpdateError("The installer download URL is missing.")
    parsed = urlparse(value)
    expected_path = f"/{REPOSITORY_SLUG}/releases/download/{tag_name}/{name}"
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "github.com"
        or parsed.path.casefold() != expected_path.casefold()
        or parsed.query
        or parsed.fragment
    ):
        raise UpdateError("The installer download URL was not recognised.")
    return value


def release_from_payload(payload: object) -> ReleaseInfo:
    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an invalid release description.")
    if payload.get("draft") is not False:
        raise UpdateError("GitHub returned a draft release.")
    if payload.get("prerelease") is not False:
        raise UpdateError("GitHub returned a prerelease.")

    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str):
        raise UpdateError("The GitHub release tag is missing.")
    version_match = _VERSION_PATTERN.fullmatch(tag_name.strip())
    parsed_version = parse_version(tag_name)
    component_count = 4 if version_match and version_match.group(4) else 3
    version = ".".join(str(part) for part in parsed_version[:component_count])
    # The public release contract requires a canonical v-prefixed tag.
    if tag_name != f"v{version}":
        raise UpdateError("The GitHub release tag is not canonical.")
    release_url = _valid_release_url(payload.get("html_url"), tag_name)
    expected_name = f"PromptMeld-Setup-v{version}.exe"

    assets = payload.get("assets")
    if not isinstance(assets, list):
        assets = []
    matches = [
        asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name") == expected_name
    ]
    if len(matches) != 1:
        issue = (
            f"The release must contain exactly one {expected_name} installer."
        )
        return ReleaseInfo(version, release_url, install_error=issue)

    asset = matches[0]
    try:
        if asset.get("state") not in {None, "uploaded"}:
            raise UpdateError("The installer upload is not complete.")
        size = asset.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise UpdateError("The installer size is invalid.")
        if size > MAX_INSTALLER_BYTES:
            raise UpdateError("The installer is larger than the safety limit.")
        digest = asset.get("digest")
        digest_match = (
            _SHA256_PATTERN.fullmatch(digest)
            if isinstance(digest, str)
            else None
        )
        if digest_match is None:
            raise UpdateError("The installer has no valid GitHub SHA-256 digest.")
        installer_url = _valid_installer_url(
            asset.get("browser_download_url"),
            tag_name,
            expected_name,
        )
    except UpdateError as exc:
        return ReleaseInfo(version, release_url, install_error=str(exc))

    return ReleaseInfo(
        version=version,
        release_url=release_url,
        installer_url=installer_url,
        installer_name=expected_name,
        installer_size=size,
        sha256=digest_match.group(1).lower(),
    )


def _request_headers(current_version: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{APP_NAME}/{current_version}",
    }


def check_latest_release(
    current_version: str,
    *,
    opener: Callable[..., object] = urlopen,
    timeout_seconds: float = 15.0,
) -> UpdateCheckResult:
    try:
        parse_version(current_version)
        request = Request(
            LATEST_RELEASE_API,
            headers=_request_headers(current_version),
        )
        response_context = opener(request, timeout=timeout_seconds)
        with response_context as response:  # type: ignore[attr-defined]
            raw = response.read(MAX_RELEASE_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RELEASE_RESPONSE_BYTES:
            raise UpdateError(
                "The GitHub release response was unexpectedly large."
            )
        release = release_from_payload(json.loads(raw.decode("utf-8")))
        return UpdateCheckResult(
            status=(
                "available"
                if is_newer_version(release.version, current_version)
                else "current"
            ),
            release=release,
        )
    except HTTPError as exc:
        error = (
            "GitHub has no published stable PromptMeld release yet."
            if exc.code == 404
            else f"GitHub returned HTTP {exc.code} while checking for updates."
        )
    except (URLError, TimeoutError):
        error = "PromptMeld could not reach GitHub. Check your internet connection."
    except (UnicodeError, json.JSONDecodeError, UpdateError) as exc:
        error = str(exc)
    except OSError as exc:
        error = f"The update check failed: {exc}"
    except Exception as exc:
        # A worker must always return a result so an unusual network response
        # cannot leave the UI permanently showing "Checking for updates".
        error = f"The update check failed unexpectedly: {exc}"
    return UpdateCheckResult(status="error", error=error)


def _release_from_state(value: object) -> ReleaseInfo | None:
    if not isinstance(value, dict):
        return None
    try:
        release = ReleaseInfo(
            version=str(value["version"]),
            release_url=str(value["release_url"]),
            installer_url=(
                str(value["installer_url"])
                if value.get("installer_url")
                else None
            ),
            installer_name=(
                str(value["installer_name"])
                if value.get("installer_name")
                else None
            ),
            installer_size=(
                int(value["installer_size"])
                if value.get("installer_size") is not None
                else None
            ),
            sha256=(str(value["sha256"]) if value.get("sha256") else None),
            install_error=str(value.get("install_error", "")),
        )
        parse_version(release.version)
        _valid_release_url(value.get("release_url"), f"v{release.version}")
        if release.installable:
            expected_name = f"PromptMeld-Setup-v{release.version}.exe"
            if release.installer_name != expected_name:
                return None
            _valid_installer_url(
                release.installer_url,
                f"v{release.version}",
                release.installer_name or "",
            )
            if not _SHA256_PATTERN.fullmatch(f"sha256:{release.sha256}"):
                return None
            if not 0 < int(release.installer_size or 0) <= MAX_INSTALLER_BYTES:
                return None
        return release
    except (KeyError, TypeError, ValueError, UpdateError):
        return None


def load_update_state(path: Path) -> UpdateState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return UpdateState()
    if not isinstance(raw, dict):
        return UpdateState()
    last_attempt = raw.get("last_attempt_utc", "")
    last_notified = raw.get("last_notified_version", "")
    return UpdateState(
        last_attempt_utc=(last_attempt if isinstance(last_attempt, str) else ""),
        last_notified_version=(
            last_notified if isinstance(last_notified, str) else ""
        ),
        cached_release=_release_from_state(raw.get("cached_release")),
    )


def save_update_state(path: Path, state: UpdateState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_attempt_utc": state.last_attempt_utc,
        "last_notified_version": state.last_notified_version,
        "cached_release": (
            asdict(state.cached_release) if state.cached_release else None
        ),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _trusted_download_response_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (
        host == "github.com" or host.endswith(".githubusercontent.com")
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installer_file(release: ReleaseInfo, path: Path) -> str:
    """Return an error message when a release installer is no longer valid."""

    if not release.installable:
        return release.install_error or "No safe installer was supplied."
    if path.name != release.installer_name:
        return "The installer filename did not match the GitHub release."
    try:
        if path.stat().st_size != release.installer_size:
            return "The installer size did not match the GitHub release."
        if _file_sha256(path) != release.sha256:
            return "The installer SHA-256 digest did not match GitHub."
    except OSError as exc:
        return f"The installer could not be read: {exc}"
    return ""


def download_installer(
    release: ReleaseInfo,
    directory: Path,
    *,
    current_version: str,
    report_progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    opener: Callable[..., object] = urlopen,
    timeout_seconds: float = 30.0,
) -> DownloadResult:
    if not release.installable:
        return DownloadResult(error=release.install_error or "No safe installer found.")
    assert release.installer_name is not None
    assert release.installer_url is not None
    assert release.installer_size is not None
    assert release.sha256 is not None

    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / release.installer_name
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        if destination.is_file():
            if not verify_installer_file(release, destination):
                if report_progress:
                    report_progress(release.installer_size, release.installer_size)
                return DownloadResult(path=destination)
            destination.unlink()
        partial.unlink(missing_ok=True)
        if report_progress:
            report_progress(0, release.installer_size)
        request = Request(
            release.installer_url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": f"{APP_NAME}/{current_version}",
            },
        )
        digest = hashlib.sha256()
        downloaded = 0
        response_context = opener(request, timeout=timeout_seconds)
        with response_context as response:  # type: ignore[attr-defined]
            final_url = (
                response.geturl()
                if callable(getattr(response, "geturl", None))
                else release.installer_url
            )
            if not _trusted_download_response_url(str(final_url)):
                raise UpdateError("GitHub redirected the installer unexpectedly.")
            with partial.open("wb") as stream:
                while True:
                    if is_cancelled and is_cancelled():
                        raise InterruptedError
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if (
                        downloaded > release.installer_size
                        or downloaded > MAX_INSTALLER_BYTES
                    ):
                        raise UpdateError("The installer exceeded its advertised size.")
                    stream.write(chunk)
                    digest.update(chunk)
                    if report_progress:
                        report_progress(downloaded, release.installer_size)
        if downloaded != release.installer_size:
            raise UpdateError("The installer download was incomplete.")
        if digest.hexdigest() != release.sha256:
            raise UpdateError("The installer SHA-256 digest did not match GitHub.")
        partial.replace(destination)
        return DownloadResult(path=destination)
    except InterruptedError:
        partial.unlink(missing_ok=True)
        return DownloadResult(cancelled=True)
    except (HTTPError, URLError, TimeoutError, OSError, UpdateError) as exc:
        partial.unlink(missing_ok=True)
        return DownloadResult(error=f"The installer could not be downloaded: {exc}")
    except Exception as exc:
        # As above, always complete the worker and remove an untrusted partial
        # file even if the HTTP implementation fails in an unexpected way.
        partial.unlink(missing_ok=True)
        return DownloadResult(
            error=f"The installer download failed unexpectedly: {exc}"
        )


def cleanup_update_downloads(directory: Path) -> None:
    if not directory.is_dir():
        return
    for pattern in ("PromptMeld-Setup-v*.exe", "PromptMeld-Setup-v*.exe.part"):
        for path in directory.glob(pattern):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                continue
