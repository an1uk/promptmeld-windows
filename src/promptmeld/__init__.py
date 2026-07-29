"""PromptMeld application package."""

import sys
from pathlib import Path

__version__ = "0.1.0"


def display_version() -> str:
    """Return the generated build version when running a packaged release."""
    if getattr(sys, "frozen", False):
        version_file = Path(sys.executable).with_name("VERSION")
        try:
            packaged_version = version_file.read_text(
                encoding="ascii"
            ).strip()
        except OSError:
            pass
        else:
            if packaged_version:
                return packaged_version
    return __version__
