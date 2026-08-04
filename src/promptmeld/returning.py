from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from .models import AppSettings, ApplicationProfile, CapturedSelection

APPLICATION_RETURN_MODE_OPTIONS = (
    ("default", "Use overall defaults"),
    ("replace", "Replace the original selection"),
    ("copy", "Copy the result only"),
    ("leave", "Leave the result in ChatGPT"),
)
APPLICATION_RETURN_MODE_VALUES = tuple(
    value for value, _label in APPLICATION_RETURN_MODE_OPTIONS
)
APPLICATION_TOGGLE_OPTIONS = (
    ("inherit", "Use overall default"),
    ("on", "On"),
    ("off", "Off"),
)
APPLICATION_TOGGLE_VALUES = tuple(
    value for value, _label in APPLICATION_TOGGLE_OPTIONS
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
RECOMMENDED_APPLICATION_PROFILES = {
    # Native editors with dependable selection and paste behaviour.
    "winword.exe": ApplicationProfile(return_mode="replace"),
    "notepad.exe": ApplicationProfile(
        return_mode="replace",
        resulting_text_formatting="plain",
    ),
    # Email is safest as a copy operation. Plain text avoids Markdown markers
    # appearing in a composed message while leaving audience and tone personal.
    "outlook.exe": ApplicationProfile(
        return_mode="copy",
        resulting_text_formatting="plain",
    ),
    "olk.exe": ApplicationProfile(
        return_mode="copy",
        resulting_text_formatting="plain",
    ),
    # Messaging is normally concise, plain text, and aimed at colleagues.
    "ms-teams.exe": ApplicationProfile(
        return_mode="copy",
        recipient_audience="colleague_peer",
        resulting_text_length="short",
        resulting_text_formatting="plain",
    ),
    "slack.exe": ApplicationProfile(
        return_mode="copy",
        recipient_audience="colleague_peer",
        resulting_text_length="short",
        resulting_text_formatting="plain",
    ),
    # Browser fields can move focus or expose read-only content while ChatGPT
    # responds, so copying is the least surprising starter behaviour.
    "chrome.exe": ApplicationProfile(return_mode="copy"),
    "msedge.exe": ApplicationProfile(return_mode="copy"),
    "firefox.exe": ApplicationProfile(return_mode="copy"),
}
RECOMMENDED_APPLICATION_RETURN_POLICIES = {
    application: profile.return_mode
    for application, profile in RECOMMENDED_APPLICATION_PROFILES.items()
}
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


@dataclass(frozen=True, slots=True)
class EffectiveApplicationProfile:
    application: str
    configured: bool
    overridden_fields: frozenset[str]
    auto_submit_enabled: bool
    temporary_chat_enabled: bool
    natural_voice_enabled: bool
    guided_drafting_enabled: bool
    writing_block_enabled: bool
    primary_language: str
    resulting_text_length: str
    resulting_text_formatting: str
    editing_strength: str
    preserve_facts: bool
    recipient_audience: str
    project_name: str


def _profile_for_application(
    settings: AppSettings,
    application: str,
) -> ApplicationProfile:
    profile = settings.application_profiles.get(application)
    if profile is not None:
        return profile
    legacy_mode = settings.application_return_policies.get(application)
    if legacy_mode in APPLICATION_RETURN_MODE_VALUES:
        return ApplicationProfile(return_mode=legacy_mode)
    return ApplicationProfile()


def _toggle_value(value: str, inherited: bool) -> bool:
    if value == "on":
        return True
    if value == "off":
        return False
    return inherited


def resolve_application_profile(
    settings: AppSettings,
    selection: CapturedSelection | None,
) -> EffectiveApplicationProfile:
    application = normalize_application_name(
        selection.source_app if selection is not None else ""
    )
    profile = _profile_for_application(settings, application)
    configured = (
        application in settings.application_profiles
        or application in settings.application_return_policies
    )
    overridden_fields = frozenset(
        field
        for field, value in (
            ("return_mode", profile.return_mode),
            ("recipient_audience", profile.recipient_audience),
            ("primary_language", profile.primary_language),
            ("resulting_text_length", profile.resulting_text_length),
            ("resulting_text_formatting", profile.resulting_text_formatting),
            ("editing_strength", profile.editing_strength),
            ("preserve_facts", profile.preserve_facts),
            ("natural_voice", profile.natural_voice),
            ("guided_drafting", profile.guided_drafting),
            ("writing_block", profile.writing_block),
            ("auto_submit", profile.auto_submit),
            ("temporary_chat", profile.temporary_chat),
            ("project_name", profile.project_name),
        )
        if value not in {"", "default", "inherit"}
    )
    return EffectiveApplicationProfile(
        application=application,
        configured=configured,
        overridden_fields=overridden_fields,
        auto_submit_enabled=_toggle_value(
            profile.auto_submit,
            settings.auto_submit_enabled,
        ),
        temporary_chat_enabled=_toggle_value(
            profile.temporary_chat,
            settings.temporary_chat_enabled,
        ),
        natural_voice_enabled=_toggle_value(
            profile.natural_voice,
            settings.natural_voice_enabled,
        ),
        guided_drafting_enabled=_toggle_value(
            profile.guided_drafting,
            settings.guided_drafting_enabled,
        ),
        writing_block_enabled=_toggle_value(
            profile.writing_block,
            settings.writing_block_enabled,
        ),
        primary_language=(
            profile.primary_language or settings.primary_language
        ),
        resulting_text_length=(
            settings.resulting_text_length
            if profile.resulting_text_length == "inherit"
            else profile.resulting_text_length
        ),
        resulting_text_formatting=(
            settings.resulting_text_formatting
            if profile.resulting_text_formatting == "inherit"
            else profile.resulting_text_formatting
        ),
        editing_strength=(
            "default"
            if profile.editing_strength == "inherit"
            else profile.editing_strength
        ),
        preserve_facts=_toggle_value(profile.preserve_facts, True),
        recipient_audience=(
            "unspecified"
            if profile.recipient_audience == "inherit"
            else profile.recipient_audience
        ),
        project_name=profile.project_name or settings.project_name,
    )


def resolve_return_decision(
    settings: AppSettings,
    selection: CapturedSelection | None,
) -> ReturnDecision:
    application = normalize_application_name(
        selection.source_app if selection is not None else ""
    )
    configured_mode = _profile_for_application(
        settings,
        application,
    ).return_mode
    overridden = (
        configured_mode in APPLICATION_RETURN_MODE_VALUES
        and configured_mode != "default"
    )
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
