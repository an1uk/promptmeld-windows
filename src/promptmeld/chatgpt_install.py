from __future__ import annotations

try:
    import winreg
except ImportError:  # pragma: no cover - PromptMeld is Windows-only.
    winreg = None  # type: ignore[assignment]


CHATGPT_DOWNLOAD_URL = "https://chatgpt.com/download/"
_CHATGPT_PROTOCOL = "chatgpt"
_APPX_REPOSITORY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppModel\Repository\Packages"
)


def chatgpt_desktop_app_installed(registry=None) -> bool:
    """Return whether Windows exposes the installed ChatGPT desktop app.

    PromptMeld opens ChatGPT through its ``chatgpt:`` protocol, so protocol
    registration is the most useful readiness check. The package repository is
    also inspected to handle a newly installed Store package whose protocol has
    not yet been materialised in the merged Classes view.
    """

    registry = winreg if registry is None else registry
    if registry is None:
        return False

    protocol_locations = (
        (registry.HKEY_CLASSES_ROOT, _CHATGPT_PROTOCOL),
        (
            registry.HKEY_CURRENT_USER,
            rf"Software\Classes\{_CHATGPT_PROTOCOL}",
        ),
    )
    for root, path in protocol_locations:
        if _protocol_registered(registry, root, path):
            return True

    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            _APPX_REPOSITORY,
        ) as packages:
            index = 0
            while True:
                try:
                    package_name = registry.EnumKey(packages, index)
                except OSError:
                    break
                if "chatgpt" in package_name.casefold():
                    return True
                index += 1
    except OSError:
        pass
    return False


def _protocol_registered(registry, root, path: str) -> bool:
    try:
        with registry.OpenKey(root, path) as key:
            try:
                registry.QueryValueEx(key, "URL Protocol")
                return True
            except OSError:
                pass
        with registry.OpenKey(root, rf"{path}\shell\open\command"):
            return True
    except OSError:
        return False
