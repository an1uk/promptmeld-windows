from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .branding import (
    DATA_DIRECTORY_NAME,
    LEGACY_DATA_DIRECTORY_NAME,
    LOG_FILE_NAME,
)


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_dir: Path
    actions_file: Path
    settings_file: Path
    usage_file: Path
    log_file: Path
    legacy_data_dir: Path | None = None

    @classmethod
    def discover(cls, override: Path | None = None) -> "AppPaths":
        if override is not None:
            data_dir = Path(override)
            legacy_data_dir = None
        else:
            local_app_data = os.environ.get("LOCALAPPDATA")
            base_dir = (
                Path(local_app_data)
                if local_app_data
                else Path.home() / "AppData" / "Local"
            )
            data_dir = base_dir / DATA_DIRECTORY_NAME
            legacy_data_dir = base_dir / LEGACY_DATA_DIRECTORY_NAME
        return cls(
            data_dir=data_dir,
            actions_file=data_dir / "actions.json",
            settings_file=data_dir / "settings.json",
            usage_file=data_dir / "usage.json",
            log_file=data_dir / LOG_FILE_NAME,
            legacy_data_dir=legacy_data_dir,
        )

    def ensure(self) -> None:
        if (
            not self.data_dir.exists()
            and self.legacy_data_dir is not None
            and self.legacy_data_dir.is_dir()
        ):
            shutil.copytree(self.legacy_data_dir, self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
