from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from .models import AppSettings, CapturedSelection

APPLICATION_RETURN_MODE_OPTIONS = (
    ("default", "Use overall defaults"),
    ("replace", "Replace the original selection"),
    ("copy", "Copy the result only"),
    ("leave", "Leave the result in ChatGPT"),
)
APPLICATION_RETURN_MODE_VALUES = tuple(
    value for value, _label in APPLICATION_RETURN_MODE_OPTIONS
)
COMMON_APPLICATIONS = (
    ("Microsoft Word", "winword.exe"),
    ("Microsoft Outlook", "outlook.exe"),
    ("New Microsoft Outlook", "olk.exe"),
    ("Microsoft Teams", "ms-teams.exe"),
    ("Microsoft Teams Classic", "teams.exe"),
    ("Google Chrome", "chrome.exe"),
    ("Microsoft Edge", "msedge.exe"),
    ("Mozilla Firefox", "firefox.exe"),
    ("Notepad", "notepad.exe"),
    ("Visual Studio Code", "code.exe"),
    ("Slack", "slack.exe"),
    ("Discord", "discord.exe"),
    ("Mozilla Thunderbird", "thunderbird.exe"),
)
_APPLICATION_LABELS = {
    executable: label for label, executable in COMMON_APPLICATIONS
}


def normalize_application_name(value: str) -> str:
    """Return a stable executable key without retaining a full local path."""

    cleaned = str(value or "").strip().strip('"').replace("\\", "/")
    if not cleaned:
        return ""
    return PurePath(cleaned).name.casefold()


def application_display_name(executable: str) -> str:
    normalized = normalize_application_name(executable)
    return _APPLICATION_LABELS.get(normalized, normalized or "this application")


@dataclass(frozen=True, slots=True)
class ReturnDecision:
    replace_selection: bool = False
    copy_result: bool = False
    requested_mode: str = "default"
    application: str = ""
    overridden: bool = False
    fallback_reason: str = ""

    @property
    def wants_generated_text(self) -> bool:
        return self.replace_selection or self.copy_result

    @property
    def summary(self) -> str:
        target = application_display_name(self.application)
        if self.replace_selection and self.copy_result:
            return f"Replace in {target} and copy the result"
        if self.replace_selection:
            return f"Replace the selection in {target}"
        if self.copy_result:
            return f"Copy the result for {target}"
        return "Leave the result in ChatGPT"


def resolve_return_decision(
    settings: AppSettings,
    selection: CapturedSelection | None,
) -> ReturnDecision:
    application = normalize_application_name(
        selection.source_app if selection is not None else ""
    )
    configured_mode = settings.application_return_policies.get(application)
    overridden = configured_mode in APPLICATION_RETURN_MODE_VALUES
    requested_mode = configured_mode if overridden else "default"

    if requested_mode == "replace":
        replace_selection = True
        copy_result = False
    elif requested_mode == "copy":
        replace_selection = False
        copy_result = True
    elif requested_mode == "leave":
        replace_selection = False
        copy_result = False
    else:
        replace_selection = settings.replace_selected_text_enabled
        copy_result = settings.copy_generated_text_enabled

    fallback_reason = ""
    if (replace_selection or copy_result) and not settings.auto_submit_enabled:
        replace_selection = False
        copy_result = False
        fallback_reason = (
            "Automatic submission is off, so PromptMeld will leave the prompt "
            "ready in ChatGPT. Result return begins only after PromptMeld "
            "submits the prompt itself."
        )
    elif replace_selection and (
        selection is None or not selection.source_is_editable
    ):
        replace_selection = False
        copy_result = True
        fallback_reason = (
            "The source did not expose an editable control, so PromptMeld will "
            "copy the generated result instead of attempting a replacement."
        )

    return ReturnDecision(
        replace_selection=replace_selection,
        copy_result=copy_result,
        requested_mode=requested_mode,
        application=application,
        overridden=overridden,
        fallback_reason=fallback_reason,
    )
