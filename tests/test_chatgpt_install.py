from __future__ import annotations

from promptmeld.chatgpt_install import chatgpt_desktop_app_installed


class _Key:
    def __init__(self, location):
        self.location = location

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Registry:
    HKEY_CLASSES_ROOT = "classes"
    HKEY_CURRENT_USER = "user"

    def __init__(self, keys=(), values=None, children=None):
        self.keys = set(keys)
        self.values = values or {}
        self.children = children or {}

    def OpenKey(self, root, path):
        location = (root, path)
        if location not in self.keys:
            raise OSError("missing")
        return _Key(location)

    def QueryValueEx(self, key, name):
        try:
            return self.values[(*key.location, name)], 1
        except KeyError as exc:
            raise OSError("missing") from exc

    def EnumKey(self, key, index):
        try:
            return self.children[key.location][index]
        except (KeyError, IndexError) as exc:
            raise OSError("end") from exc


def test_chatgpt_install_detection_accepts_registered_protocol():
    registry = _Registry(
        keys={("classes", "codex")},
        values={("classes", "codex", "URL Protocol"): ""},
    )

    assert chatgpt_desktop_app_installed(registry) is True


def test_chatgpt_install_detection_accepts_store_package_registration():
    package_path = (
        r"Software\Classes\Local Settings\Software\Microsoft\Windows"
        r"\CurrentVersion\AppModel\Repository\Packages"
    )
    location = ("user", package_path)
    registry = _Registry(
        keys={location},
        children={
            location: [
                "Microsoft.WindowsCalculator_1.0_x64",
                "OpenAI.Codex_2.0_x64",
            ]
        },
    )

    assert chatgpt_desktop_app_installed(registry) is True


def test_chatgpt_install_detection_rejects_classic_package():
    package_path = (
        r"Software\Classes\Local Settings\Software\Microsoft\Windows"
        r"\CurrentVersion\AppModel\Repository\Packages"
    )
    location = ("user", package_path)
    registry = _Registry(
        keys={location},
        children={location: ["OpenAI.ChatGPT-Desktop_2.0_x64"]},
    )

    assert chatgpt_desktop_app_installed(registry) is False


def test_chatgpt_install_detection_returns_false_when_not_registered():
    assert chatgpt_desktop_app_installed(_Registry()) is False
