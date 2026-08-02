"""PromptMeld application package."""

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path


try:
    __version__ = distribution_version("promptmeld")
except PackageNotFoundError:
    # Packaged releases use the generated VERSION file below. This fallback is
    # only for an unpackaged source tree that has not been installed.
    __version__ = "0.0.0"


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
