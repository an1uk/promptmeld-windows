from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import display_version
from .config import load_actions, load_settings
from .paths import AppPaths

BACKUP_FORMAT = "promptmeld-configuration-backup"
BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = "promptmeld-backup.json"
MAX_BACKUP_FILES = 512
MAX_BACKUP_BYTES = 50 * 1024 * 1024


class ConfigurationBackupError(ValueError):
    """Raised when a configuration backup is missing, unsafe, or invalid."""


@dataclass(frozen=True, slots=True)
class ConfigurationBackupSummary:
    created_at: str
    app_version: str
    action_count: int
    icon_count: int


@dataclass(frozen=True, slots=True)
class ConfigurationRestoreResult:
    summary: ConfigurationBackupSummary
    safety_backup: Path


@dataclass(frozen=True, slots=True)
class _BackupContents:
    summary: ConfigurationBackupSummary
    files: dict[str, bytes]


def _configuration_files(paths: AppPaths) -> list[tuple[Path, str]]:
    files = [
        (paths.actions_file, "actions.json"),
        (paths.settings_file, "settings.json"),
    ]
    icons_dir = paths.data_dir / "icons"
    if icons_dir.is_dir():
        for icon in sorted(icons_dir.rglob("*")):
            if icon.is_file() and not icon.is_symlink():
                relative = icon.relative_to(paths.data_dir).as_posix()
                files.append((icon, relative))
    return files


def create_configuration_backup(
    paths: AppPaths,
    destination: Path,
) -> ConfigurationBackupSummary:
    """Write a validated configuration archive without including user text."""

    paths.ensure()
    try:
        actions = load_actions(paths.actions_file)
        load_settings(paths.settings_file)
        sources = _configuration_files(paths)
        total_size = sum(source.stat().st_size for source, _name in sources)
    except (OSError, ValueError) as exc:
        raise ConfigurationBackupError(
            f"The saved configuration cannot be backed up: {exc}"
        ) from exc
    if len(sources) + 1 > MAX_BACKUP_FILES or total_size > MAX_BACKUP_BYTES:
        raise ConfigurationBackupError(
            "The configuration is too large to create a safe backup."
        )

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = ConfigurationBackupSummary(
        created_at=created_at,
        app_version=display_version(),
        action_count=len(actions),
        icon_count=sum(1 for _source, name in sources if name.startswith("icons/")),
    )
    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": summary.created_at,
        "app_version": summary.app_version,
        "files": [name for _source, name in sources],
    }

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".part",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, indent=2) + "\n",
            )
            for source, name in sources:
                archive.write(source, name)
        os.replace(temporary, destination)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ConfigurationBackupError(
            f"The configuration backup could not be created: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return summary


def _safe_archive_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and all(
            part
            and ":" not in part
            and not part.endswith((".", " "))
            for part in path.parts
        )
    )


def _load_backup(archive_path: Path) -> _BackupContents:
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_BACKUP_FILES:
                raise ConfigurationBackupError(
                    "The backup contains an unsafe number of files."
                )
            names = [info.filename for info in infos if not info.is_dir()]
            if len(names) != len({name.casefold() for name in names}):
                raise ConfigurationBackupError(
                    "The backup contains duplicate file names."
                )
            if any(not _safe_archive_name(name) for name in names):
                raise ConfigurationBackupError(
                    "The backup contains an unsafe file path."
                )
            allowed = {
                MANIFEST_NAME,
                "actions.json",
                "settings.json",
            }
            if any(
                name not in allowed and not name.startswith("icons/")
                for name in names
            ):
                raise ConfigurationBackupError(
                    "The backup contains files that PromptMeld does not restore."
                )
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_BACKUP_BYTES:
                raise ConfigurationBackupError(
                    "The backup is larger than the safe restore limit."
                )
            if not {MANIFEST_NAME, "actions.json", "settings.json"}.issubset(
                names
            ):
                raise ConfigurationBackupError(
                    "The backup is missing its manifest, actions, or settings."
                )
            files = {name: archive.read(name) for name in names}
    except ConfigurationBackupError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, KeyError) as exc:
        raise ConfigurationBackupError(
            "This is not a readable PromptMeld configuration backup."
        ) from exc

    try:
        manifest = json.loads(files[MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ConfigurationBackupError("The backup manifest is invalid.") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != BACKUP_FORMAT
        or manifest.get("format_version") != BACKUP_FORMAT_VERSION
    ):
        raise ConfigurationBackupError(
            "This backup format is not supported by this version of PromptMeld."
        )
    declared_files = manifest.get("files")
    if (
        not isinstance(declared_files, list)
        or any(not isinstance(name, str) for name in declared_files)
        or set(declared_files) != set(files) - {MANIFEST_NAME}
    ):
        raise ConfigurationBackupError(
            "The backup manifest does not match its configuration files."
        )

    with tempfile.TemporaryDirectory(prefix="promptmeld-restore-check-") as data:
        root = Path(data)
        actions_file = root / "actions.json"
        settings_file = root / "settings.json"
        actions_file.write_bytes(files["actions.json"])
        settings_file.write_bytes(files["settings.json"])
        try:
            actions = load_actions(actions_file)
            load_settings(settings_file)
        except (OSError, ValueError) as exc:
            raise ConfigurationBackupError(
                f"The backup contains invalid PromptMeld configuration: {exc}"
            ) from exc

    created_at = manifest.get("created_at", "")
    app_version = manifest.get("app_version", "")
    if not isinstance(created_at, str) or not isinstance(app_version, str):
        raise ConfigurationBackupError("The backup manifest metadata is invalid.")
    return _BackupContents(
        ConfigurationBackupSummary(
            created_at=created_at,
            app_version=app_version,
            action_count=len(actions),
            icon_count=sum(1 for name in files if name.startswith("icons/")),
        ),
        files,
    )


def inspect_configuration_backup(
    archive_path: Path,
) -> ConfigurationBackupSummary:
    return _load_backup(Path(archive_path)).summary


def _write_replacement(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.restore")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def restore_configuration_backup(
    paths: AppPaths,
    archive_path: Path,
) -> ConfigurationRestoreResult:
    """Restore validated configuration after saving an automatic rollback."""

    contents = _load_backup(Path(archive_path))
    paths.ensure()
    backups_dir = paths.data_dir / "backups"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safety_backup = backups_dir / f"PromptMeld-pre-restore-{stamp}.zip"
    create_configuration_backup(paths, safety_backup)

    original_actions = paths.actions_file.read_bytes()
    original_settings = paths.settings_file.read_bytes()
    icon_contents = {
        paths.data_dir / PurePosixPath(name): content
        for name, content in contents.files.items()
        if name.startswith("icons/")
    }
    original_icons = {
        target: target.read_bytes() if target.is_file() else None
        for target in icon_contents
    }
    try:
        _write_replacement(
            paths.actions_file,
            contents.files["actions.json"],
        )
        _write_replacement(
            paths.settings_file,
            contents.files["settings.json"],
        )
        for target, content in icon_contents.items():
            _write_replacement(target, content)
        load_actions(paths.actions_file)
        load_settings(paths.settings_file)
    except Exception as exc:
        _write_replacement(paths.actions_file, original_actions)
        _write_replacement(paths.settings_file, original_settings)
        for target, original in original_icons.items():
            if original is None:
                target.unlink(missing_ok=True)
            else:
                _write_replacement(target, original)
        raise ConfigurationBackupError(
            "The restore failed. The previous actions and settings were put back."
        ) from exc
    return ConfigurationRestoreResult(contents.summary, safety_backup)
