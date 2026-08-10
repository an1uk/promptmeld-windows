from __future__ import annotations

import json
import shutil
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from typing import Any

from .branding import DEFAULT_PROJECT_NAME
from .models import (
    ACTION_PURPOSE_VALUES,
    ACTION_RESULT_HANDLING_VALUES,
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    EDITING_STRENGTH_VALUES,
    NATURAL_VOICE_MODES,
    PROJECT_NAMING_VALUES,
    RECIPIENT_AUDIENCE_VALUES,
    RESULTING_TEXT_FORMATTING_VALUES,
    RESULTING_TEXT_LENGTH_VALUES,
    TITLE_SUBJECT_VALUES,
    AppSettings,
    ApplicationProfile,
    WritingAction,
)
from .returning import (
    APPLICATION_RESPONSE_WAIT_VALUES,
    APPLICATION_RETURN_MODE_VALUES,
    APPLICATION_TOGGLE_VALUES,
    LEGACY_RECOMMENDED_APPLICATION_PROFILES_V2,
    RECOMMENDED_APPLICATION_PROFILES,
    normalize_application_name,
)
from .paths import AppPaths

DEFAULT_ACTION_ICONS = {
    "edit-improve": "lucide:sparkles",
    "proofread": "lucide:spell-check-2",
    "draft-reply": "lucide:message-square-text",
    "improve": "lucide:sparkles",
    "shorten": "lucide:scissors",
    "expand-argument": "lucide:expand",
    "reply-comment": "lucide:message-square-text",
    "sarcastic-reply": "lucide:smile",
    "polite-firm-reply": "lucide:heart",
    "challenge-claim": "lucide:search-check",
    "fact-check": "lucide:book-open-check",
    "rough-notes-comment": "lucide:file-pen-line",
    "less-aggressive": "lucide:heart",
    "more-direct": "lucide:send",
    "explain-technical": "lucide:text-cursor-input",
    "troubleshooting-checklist": "lucide:list-checks",
    "compare-options": "lucide:search-check",
    "improve-review": "lucide:pencil",
    "clarify": "lucide:search-check",
    "professional": "lucide:briefcase-business",
    "friendly": "lucide:smile",
    "grammar": "lucide:spell-check-2",
    "formal": "lucide:landmark",
    "expand": "lucide:expand",
    "reply-email": "lucide:send",
    "formal-email-reply": "lucide:briefcase-business",
    "follow-up-reminder": "lucide:rotate-ccw",
    "reply-customer-message": "lucide:heart",
    "reply-marketplace-message": "lucide:message-square-text",
    "respond-complaint": "lucide:list-checks",
}

DEFAULT_FOLDER_ICONS = {
    "Essentials": "lucide:sparkles",
    "Reply": "lucide:message-square-text",
    "Reply/General replies": "lucide:send",
    "Reply/Complaints": "lucide:landmark",
    "Reply/Social": "lucide:message-square-text",
    "Reply/Social media": "lucide:message-square-text",
    "Reply/Customer relations": "lucide:heart",
    "Edit & revise": "lucide:pencil",
    "Edit & revise/Advanced editing": "lucide:file-pen-line",
    "Edit & revise/Tone & voice": "lucide:sparkles",
    "Edit & revise/Arguments & evidence": "lucide:search-check",
    "Edit & revise/Email": "lucide:send",
    "Edit & revise/Reviews": "lucide:heart",
    "Edit & revise/Social media": "lucide:pencil",
    "Draft & create": "lucide:file-pen-line",
    "Draft & create/General": "lucide:file-pen-line",
    "Draft & create/Email": "lucide:send",
    "Draft & create/Complaints": "lucide:landmark",
    "Draft & create/Reports": "lucide:list-checks",
    "Draft & create/Social": "lucide:message-square-text",
    "Draft & create/Social media": "lucide:message-square-text",
    "Draft & create/Reviews": "lucide:heart",
    "Draft & create/Meetings": "lucide:list-checks",
    "Draft & create/Technical": "lucide:text-cursor-input",
    "Draft & create/Career": "lucide:briefcase-business",
    "Summarise & understand": "lucide:shrink",
    "Summarise & understand/General": "lucide:shrink",
    "Summarise & understand/Complaints": "lucide:landmark",
    "Summarise & understand/Reports": "lucide:list-checks",
    "Summarise & understand/Meetings": "lucide:list-checks",
    "Explain & learn": "lucide:book-open-check",
    "Explain & learn/Technical": "lucide:text-cursor-input",
    "Explain & learn/Study": "lucide:book-open-check",
    "Plan & decide": "lucide:search-check",
    "Plan & decide/General": "lucide:search-check",
    "Plan & decide/Technical": "lucide:list-checks",
    "Review & develop": "lucide:book-open-check",
    "Review & develop/Fiction": "lucide:sparkles",
    "Review & develop/Non-fiction": "lucide:search-check",
    "Editing": "lucide:pencil",
    "Editing/Reviews": "lucide:heart",
    "Replies & arguments": "lucide:message-square-text",
    "Replies & arguments/Replies": "lucide:send",
    "Replies & arguments/Analysis": "lucide:search-check",
    "Tone & polish": "lucide:sparkles",
    "Technical help": "lucide:list-checks",
    "Correspondence": "lucide:send",
    "Correspondence/Email": "lucide:briefcase-business",
    "Correspondence/Customer & marketplace": "lucide:message-square-text",
    "Tone & voice": "lucide:sparkles",
    "Complaints": "lucide:landmark",
    "Reports": "lucide:file-pen-line",
    "Social writing": "lucide:message-square-text",
    "Reviews & feedback": "lucide:heart",
    "Meetings": "lucide:list-checks",
    "Study & learning": "lucide:book-open-check",
    "Career writing": "lucide:briefcase-business",
    "Summaries & extraction": "lucide:shrink",
    "Draft from selection": "lucide:file-pen-line",
    "Decisions & planning": "lucide:search-check",
}

CURRENT_STARTER_ACTION_VERSION = 3
CURRENT_STARTER_APPLICATION_POLICY_VERSION = 3
LEGACY_PROJECT_NAMES = {
    "Writing Launcher",
    "WritingAssistant",
    "WritingLauncher",
}
LEGACY_NATURAL_VOICE_INSTRUCTION = (
    "Preserve the writer's individual voice, vocabulary, and level of formality. "
    "Make only the changes needed for the selected task. Avoid generic filler, "
    "stock transitions, excessive structure, and unnecessarily polished phrasing. "
    "Do not invent personal details or deliberately introduce errors."
)
class ConfigurationError(ValueError):
    """Raised when a user-editable configuration file is invalid."""


def _resource_path(name: str) -> Path:
    return Path(str(files("promptmeld").joinpath("resources", name)))


def ensure_user_configuration(paths: AppPaths) -> None:
    paths.ensure()
    actions_existed = paths.actions_file.exists()
    settings_existed = paths.settings_file.exists()
    if not paths.actions_file.exists():
        shutil.copyfile(_resource_path("default_actions.json"), paths.actions_file)
    elif _is_untouched_legacy_default(paths.actions_file):
        backup = paths.data_dir / "actions.legacy-v1-backup.json"
        if not backup.exists():
            shutil.copyfile(paths.actions_file, backup)
        shutil.copyfile(_resource_path("default_actions.json"), paths.actions_file)
    if not paths.settings_file.exists():
        shutil.copyfile(_resource_path("default_settings.json"), paths.settings_file)
    _migrate_starter_action_marker(
        paths,
        force=settings_existed is False and actions_existed,
    )
    _migrate_launcher_defaults(paths)
    _migrate_application_return_policies(paths)


def _migrate_application_return_policies(paths: AppPaths) -> None:
    """Install safe starter policies once without replacing user choices."""

    settings = load_settings(paths.settings_file)
    if (
        settings.starter_application_policy_version
        >= CURRENT_STARTER_APPLICATION_POLICY_VERSION
    ):
        return

    profiles = dict(settings.application_profiles)
    if (
        settings.starter_application_policy_version == 0
        and not profiles
    ):
        profiles.update(RECOMMENDED_APPLICATION_PROFILES)
    elif settings.starter_application_policy_version == 1:
        minimal_profiles = {
            application: ApplicationProfile(return_mode=profile.return_mode)
            for application, profile in profiles.items()
        }
        recommended_minimal = {
            application: ApplicationProfile(return_mode=profile.return_mode)
            for application, profile in RECOMMENDED_APPLICATION_PROFILES.items()
        }
        if profiles == minimal_profiles == recommended_minimal:
            # Enrich the exact v1 starter set. Any deletion or modification is
            # treated as a user choice and left untouched.
            profiles = dict(RECOMMENDED_APPLICATION_PROFILES)
    elif (
        settings.starter_application_policy_version == 2
        and profiles == LEGACY_RECOMMENDED_APPLICATION_PROFILES_V2
    ):
        profiles = dict(RECOMMENDED_APPLICATION_PROFILES)
    policies = {
        application: profile.return_mode
        for application, profile in profiles.items()
        if profile.return_mode != "default"
    }
    save_settings(
        paths.settings_file,
        replace(
            settings,
            application_return_policies=policies,
            application_profiles=profiles,
            starter_application_policy_version=(
                CURRENT_STARTER_APPLICATION_POLICY_VERSION
            ),
        ),
    )


def _migrate_launcher_defaults(paths: AppPaths) -> None:
    """Upgrade earlier shipped defaults while preserving user customisations."""

    raw_settings = _read_json(paths.settings_file)
    settings = load_settings(paths.settings_file)
    project_name = settings.project_name
    natural_voice_instruction = settings.natural_voice_instruction

    if project_name in LEGACY_PROJECT_NAMES:
        project_name = DEFAULT_PROJECT_NAME
    if natural_voice_instruction == LEGACY_NATURAL_VOICE_INSTRUCTION:
        natural_voice_instruction = DEFAULT_NATURAL_VOICE_INSTRUCTION

    if (
        project_name != settings.project_name
        or natural_voice_instruction != settings.natural_voice_instruction
        or (
            isinstance(raw_settings, dict)
            and "auto_submit_enabled" not in raw_settings
        )
    ):
        save_settings(
            paths.settings_file,
            replace(
                settings,
                project_name=project_name,
                natural_voice_instruction=natural_voice_instruction,
            ),
        )


def _migrate_starter_action_marker(
    paths: AppPaths,
    *,
    force: bool = False,
) -> None:
    """Advance the catalogue marker without changing an existing library."""

    settings = load_settings(paths.settings_file)
    current_version = 1 if force else settings.starter_action_version
    if current_version >= CURRENT_STARTER_ACTION_VERSION:
        return
    save_settings(
        paths.settings_file,
        replace(
            settings,
            starter_action_version=CURRENT_STARTER_ACTION_VERSION,
        ),
    )


def _is_untouched_legacy_default(path: Path) -> bool:
    try:
        return _read_json(path) == _read_json(
            _resource_path("legacy_default_actions_v1.json")
        )
    except ConfigurationError:
        return False


def load_default_actions() -> list[WritingAction]:
    return load_actions(_resource_path("default_actions.json"))


def load_default_settings() -> AppSettings:
    """Load the packaged settings used for a new PromptMeld installation."""

    return load_settings(_resource_path("default_settings.json"))


def normalize_folder(value: str) -> str:
    parts = tuple(
        part.strip()
        for part in value.replace("\\", "/").split("/")
        if part.strip()
    )
    if any(part in {".", ".."} for part in parts):
        raise ConfigurationError("Folder names cannot be '.' or '..'.")
    return "/".join(parts)


def _purpose_for_legacy_action(folder: str) -> str:
    """Choose a safe purpose for actions saved before purpose was explicit."""

    root = folder.partition("/")[0].casefold()
    if root == "reply":
        return "reply"
    if root == "summarise & understand":
        return "extract"
    if root in {"review & develop", "plan & decide", "explain & learn"}:
        return "analyse"
    return "transform"


_APPLICATION_PROFILE_KEYS = {
    "return_mode",
    "recipient_audience",
    "primary_language",
    "resulting_text_length",
    "resulting_text_formatting",
    "title_subject",
    "editing_strength",
    "preserve_facts",
    "natural_voice",
    "guided_drafting",
    "writing_block",
    "auto_submit",
    "temporary_chat",
    "privacy_preview",
    "response_wait",
    "project_name",
}


def _application_profile_from_dict(
    application: str,
    raw_profile: object,
) -> ApplicationProfile:
    if not isinstance(raw_profile, dict):
        raise ConfigurationError(
            f"Application profile for {application} must be an object."
        )
    unknown = set(raw_profile) - _APPLICATION_PROFILE_KEYS
    if unknown:
        raise ConfigurationError(
            f"Application profile for {application} contains unknown options: "
            + ", ".join(sorted(str(key) for key in unknown))
        )

    def enum_value(key: str, default: str, allowed: tuple[str, ...]) -> str:
        value = raw_profile.get(key, default)
        if not isinstance(value, str):
            raise ConfigurationError(
                f"Application profile option {key} for {application} must be text."
            )
        normalized = value.strip().casefold()
        if normalized not in allowed:
            raise ConfigurationError(
                f"Application profile option {key} for {application} is invalid."
            )
        return normalized

    def text_value(key: str) -> str:
        value = raw_profile.get(key, "")
        if not isinstance(value, str):
            raise ConfigurationError(
                f"Application profile option {key} for {application} must be text."
            )
        return value.strip()

    return ApplicationProfile(
        return_mode=enum_value(
            "return_mode",
            "default",
            APPLICATION_RETURN_MODE_VALUES,
        ),
        recipient_audience=enum_value(
            "recipient_audience",
            "inherit",
            ("inherit", *RECIPIENT_AUDIENCE_VALUES),
        ),
        primary_language=text_value("primary_language"),
        resulting_text_length=enum_value(
            "resulting_text_length",
            "inherit",
            ("inherit", *RESULTING_TEXT_LENGTH_VALUES),
        ),
        resulting_text_formatting=enum_value(
            "resulting_text_formatting",
            "inherit",
            ("inherit", *RESULTING_TEXT_FORMATTING_VALUES),
        ),
        title_subject=enum_value(
            "title_subject",
            "inherit",
            ("inherit", *TITLE_SUBJECT_VALUES),
        ),
        editing_strength=enum_value(
            "editing_strength",
            "inherit",
            ("inherit", *EDITING_STRENGTH_VALUES),
        ),
        preserve_facts=enum_value(
            "preserve_facts",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        natural_voice=enum_value(
            "natural_voice",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        guided_drafting=enum_value(
            "guided_drafting",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        writing_block=enum_value(
            "writing_block",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        auto_submit=enum_value(
            "auto_submit",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        temporary_chat=enum_value(
            "temporary_chat",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        privacy_preview=enum_value(
            "privacy_preview",
            "inherit",
            APPLICATION_TOGGLE_VALUES,
        ),
        response_wait=enum_value(
            "response_wait",
            "inherit",
            APPLICATION_RESPONSE_WAIT_VALUES,
        ),
        project_name=text_value("project_name"),
    )


def _application_profile_to_dict(
    profile: ApplicationProfile,
) -> dict[str, str]:
    return {
        "return_mode": profile.return_mode,
        "recipient_audience": profile.recipient_audience,
        "primary_language": profile.primary_language,
        "resulting_text_length": profile.resulting_text_length,
        "resulting_text_formatting": profile.resulting_text_formatting,
        "title_subject": profile.title_subject,
        "editing_strength": profile.editing_strength,
        "preserve_facts": profile.preserve_facts,
        "natural_voice": profile.natural_voice,
        "guided_drafting": profile.guided_drafting,
        "writing_block": profile.writing_block,
        "auto_submit": profile.auto_submit,
        "temporary_chat": profile.temporary_chat,
        "privacy_preview": profile.privacy_preview,
        "response_wait": profile.response_wait,
        "project_name": profile.project_name,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {path.name} at line {exc.lineno}, column {exc.colno}."
        ) from exc


def actions_from_data(
    data: object,
    source_name: str = "actions.json",
) -> list[WritingAction]:
    """Validate and convert a decoded action list."""

    if not isinstance(data, list):
        raise ConfigurationError(f"{source_name} must contain a JSON list.")

    actions: list[WritingAction] = []
    seen: set[str] = set()
    required = ("id", "name", "instruction")
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"Action {index + 1} must be an object.")
        missing = [key for key in required if not str(raw.get(key, "")).strip()]
        if missing:
            raise ConfigurationError(
                f"Action {index + 1} is missing: {', '.join(missing)}."
            )
        action_id = str(raw["id"]).strip()
        if action_id in seen:
            raise ConfigurationError(f"Duplicate action id: {action_id}")
        seen.add(action_id)
        keywords = raw.get("keywords", [])
        if not isinstance(keywords, list) or not all(
            isinstance(item, str) for item in keywords
        ):
            raise ConfigurationError(
                f"Action '{action_id}' keywords must be a list of strings."
            )
        hotkey = raw.get("hotkey")
        if hotkey is not None and not isinstance(hotkey, str):
            raise ConfigurationError(
                f"Action '{action_id}' hotkey must be a string or null."
            )
        folder = raw.get("folder", "")
        if folder is not None and not isinstance(folder, str):
            raise ConfigurationError(
                f"Action '{action_id}' folder must be a string or null."
            )
        normalized_folder = normalize_folder(folder or "")
        natural_voice = str(raw.get("natural_voice", "inherit")).strip().casefold()
        if natural_voice not in NATURAL_VOICE_MODES:
            raise ConfigurationError(
                f"Action '{action_id}' natural_voice must be one of: "
                f"{', '.join(NATURAL_VOICE_MODES)}."
            )
        guided_drafting = raw.get("guided_drafting", False)
        if not isinstance(guided_drafting, bool):
            raise ConfigurationError(
                f"Action '{action_id}' guided_drafting must be true or false."
            )
        recipient_audience = str(
            raw.get("recipient_audience", "inherit")
        ).strip().casefold()
        if recipient_audience not in ("inherit", *RECIPIENT_AUDIENCE_VALUES):
            raise ConfigurationError(
                f"Action '{action_id}' recipient_audience must be one of: "
                f"inherit, {', '.join(RECIPIENT_AUDIENCE_VALUES)}."
            )
        purpose = str(
            raw.get("purpose", _purpose_for_legacy_action(normalized_folder))
        ).strip().casefold()
        if purpose not in ACTION_PURPOSE_VALUES:
            raise ConfigurationError(
                f"Action '{action_id}' purpose must be one of: "
                f"{', '.join(ACTION_PURPOSE_VALUES)}."
            )
        result_handling = str(
            raw.get("result_handling", "purpose_default")
        ).strip().casefold()
        if result_handling not in ACTION_RESULT_HANDLING_VALUES:
            raise ConfigurationError(
                f"Action '{action_id}' result_handling must be one of: "
                f"{', '.join(ACTION_RESULT_HANDLING_VALUES)}."
            )
        actions.append(
            WritingAction(
                id=action_id,
                name=str(raw["name"]).strip(),
                keywords=tuple(item.strip() for item in keywords if item.strip()),
                instruction=str(raw["instruction"]).strip(),
                hotkey=hotkey.strip() if hotkey else None,
                enabled=bool(raw.get("enabled", True)),
                icon=str(
                    raw.get("icon", DEFAULT_ACTION_ICONS.get(action_id, ""))
                ).strip(),
                folder=normalized_folder,
                show_on_home=bool(raw.get("show_on_home", False)),
                natural_voice=natural_voice,
                guided_drafting=guided_drafting,
                recipient_audience=recipient_audience,
                purpose=purpose,
                result_handling=result_handling,
            )
        )
    return actions


def load_actions(path: Path) -> list[WritingAction]:
    return actions_from_data(_read_json(path), path.name)


def action_to_dict(action: WritingAction) -> dict[str, object]:
    return {
        "id": action.id,
        "name": action.name,
        "keywords": list(action.keywords),
        "instruction": action.instruction,
        "hotkey": action.hotkey,
        "enabled": action.enabled,
        "icon": action.icon,
        "folder": action.folder,
        "show_on_home": action.show_on_home,
        "natural_voice": action.natural_voice,
        "guided_drafting": action.guided_drafting,
        "recipient_audience": action.recipient_audience,
        "purpose": action.purpose,
        "result_handling": action.result_handling,
    }


def save_actions(path: Path, actions: list[WritingAction]) -> None:
    # Reuse the loader's validation rules before replacing user configuration.
    payload = [action_to_dict(action) for action in actions]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        load_actions(temp_path)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def load_settings(path: Path) -> AppSettings:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ConfigurationError("settings.json must contain a JSON object.")

    project_name = str(raw.get("project_name", DEFAULT_PROJECT_NAME)).strip()
    project_naming_mode = str(
        raw.get("project_naming_mode", "action")
    ).strip().casefold()
    popup_hotkey = str(raw.get("popup_hotkey", "Ctrl+Alt+Space")).strip()
    if not project_name:
        raise ConfigurationError("project_name cannot be empty.")
    if project_naming_mode not in PROJECT_NAMING_VALUES:
        raise ConfigurationError(
            "project_naming_mode must be action, single, or application."
        )
    if not popup_hotkey:
        raise ConfigurationError("popup_hotkey cannot be empty.")
    theme = str(raw.get("theme", "auto")).strip().casefold()
    if theme not in {"auto", "light", "dark"}:
        raise ConfigurationError("theme must be auto, light, or dark.")

    try:
        capture_timeout_ms = int(raw.get("capture_timeout_ms", 1000))
        automation_timeout_seconds = float(
            raw.get("automation_timeout_seconds", 8.0)
        )
        home_most_used_count = int(raw.get("home_most_used_count", 3))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Timeout settings must be numbers.") from exc
    if not 100 <= capture_timeout_ms <= 10_000:
        raise ConfigurationError("capture_timeout_ms must be between 100 and 10000.")
    if not 1 <= automation_timeout_seconds <= 60:
        raise ConfigurationError(
            "automation_timeout_seconds must be between 1 and 60."
        )
    if not 0 <= home_most_used_count <= 10:
        raise ConfigurationError(
            "home_most_used_count must be between 0 and 10."
        )

    app_names = raw.get("app_names", ["ChatGPT"])
    if not isinstance(app_names, list) or not all(
        isinstance(item, str) and item.strip() for item in app_names
    ):
        raise ConfigurationError("app_names must be a non-empty list of strings.")
    folder_icons = raw.get("folder_icons", DEFAULT_FOLDER_ICONS)
    if not isinstance(folder_icons, dict) or not all(
        isinstance(folder, str)
        and isinstance(icon, str)
        for folder, icon in folder_icons.items()
    ):
        raise ConfigurationError(
            "folder_icons must be an object mapping folder paths to icon values."
        )
    natural_voice_enabled = raw.get("natural_voice_enabled", False)
    if not isinstance(natural_voice_enabled, bool):
        raise ConfigurationError("natural_voice_enabled must be true or false.")
    # A missing key identifies an existing pre-onboarding configuration. Only
    # the bundled defaults explicitly opt a new installation into the wizard.
    first_run_setup_completed = raw.get("first_run_setup_completed", True)
    if not isinstance(first_run_setup_completed, bool):
        raise ConfigurationError(
            "first_run_setup_completed must be true or false."
        )
    check_for_updates_enabled = raw.get("check_for_updates_enabled", True)
    if not isinstance(check_for_updates_enabled, bool):
        raise ConfigurationError(
            "check_for_updates_enabled must be true or false."
        )
    auto_submit_enabled = raw.get("auto_submit_enabled", False)
    if not isinstance(auto_submit_enabled, bool):
        raise ConfigurationError("auto_submit_enabled must be true or false.")
    privacy_preview_enabled = raw.get("privacy_preview_enabled", True)
    if not isinstance(privacy_preview_enabled, bool):
        raise ConfigurationError(
            "privacy_preview_enabled must be true or false."
        )
    replace_selected_text_enabled = raw.get(
        "replace_selected_text_enabled",
        False,
    )
    if not isinstance(replace_selected_text_enabled, bool):
        raise ConfigurationError(
            "replace_selected_text_enabled must be true or false."
        )
    copy_generated_text_enabled = raw.get(
        "copy_generated_text_enabled",
        False,
    )
    if not isinstance(copy_generated_text_enabled, bool):
        raise ConfigurationError(
            "copy_generated_text_enabled must be true or false."
        )
    raw_application_policies = raw.get("application_return_policies", {})
    if not isinstance(raw_application_policies, dict):
        raise ConfigurationError(
            "application_return_policies must be an object."
        )
    application_return_policies: dict[str, str] = {}
    for application, mode in raw_application_policies.items():
        if not isinstance(application, str) or not isinstance(mode, str):
            raise ConfigurationError(
                "Application return policies must map executable names to text."
            )
        normalized_application = normalize_application_name(application)
        normalized_mode = mode.strip().casefold()
        if not normalized_application or normalized_mode not in (
            APPLICATION_RETURN_MODE_VALUES
        ):
            raise ConfigurationError(
                "Application return policies must use default, replace, copy, "
                "or leave."
            )
        if normalized_mode != "default":
            application_return_policies[normalized_application] = (
                normalized_mode
            )
    raw_application_profiles = raw.get("application_profiles", {})
    if not isinstance(raw_application_profiles, dict):
        raise ConfigurationError("application_profiles must be an object.")
    application_profiles: dict[str, ApplicationProfile] = {}
    for application, raw_profile in raw_application_profiles.items():
        if not isinstance(application, str):
            raise ConfigurationError(
                "Application profile executable names must be text."
            )
        normalized_application = normalize_application_name(application)
        if not normalized_application:
            raise ConfigurationError(
                "Application profile executable names cannot be empty."
            )
        application_profiles[normalized_application] = (
            _application_profile_from_dict(
                normalized_application,
                raw_profile,
            )
        )
    for application, mode in tuple(application_return_policies.items()):
        application_profiles.setdefault(
            application,
            ApplicationProfile(return_mode=mode),
        )
    for application, profile in application_profiles.items():
        if profile.return_mode == "default":
            application_return_policies.pop(application, None)
        else:
            application_return_policies[application] = profile.return_mode
    temporary_chat_enabled = raw.get("temporary_chat_enabled", False)
    if not isinstance(temporary_chat_enabled, bool):
        raise ConfigurationError(
            "temporary_chat_enabled must be true or false."
        )
    natural_voice_instruction_value = raw.get(
        "natural_voice_instruction",
        DEFAULT_NATURAL_VOICE_INSTRUCTION,
    )
    if not isinstance(natural_voice_instruction_value, str):
        raise ConfigurationError("natural_voice_instruction must be text.")
    natural_voice_instruction = natural_voice_instruction_value.strip()
    if not natural_voice_instruction:
        raise ConfigurationError("natural_voice_instruction cannot be empty.")
    primary_language_value = raw.get("primary_language", "English (UK)")
    if not isinstance(primary_language_value, str):
        raise ConfigurationError("primary_language must be text.")
    primary_language = primary_language_value.strip()
    if not primary_language:
        raise ConfigurationError("primary_language cannot be empty.")
    guided_drafting_enabled = raw.get("guided_drafting_enabled", False)
    if not isinstance(guided_drafting_enabled, bool):
        raise ConfigurationError(
            "guided_drafting_enabled must be true or false."
        )
    resulting_text_length_value = raw.get(
        "resulting_text_length",
        "default",
    )
    if not isinstance(resulting_text_length_value, str):
        raise ConfigurationError("resulting_text_length must be text.")
    resulting_text_length = (
        resulting_text_length_value.strip().casefold().replace(" ", "_")
    )
    if resulting_text_length not in RESULTING_TEXT_LENGTH_VALUES:
        raise ConfigurationError(
            "resulting_text_length must be one of: "
            f"{', '.join(RESULTING_TEXT_LENGTH_VALUES)}."
        )
    writing_block_enabled = raw.get("writing_block_enabled", False)
    if not isinstance(writing_block_enabled, bool):
        raise ConfigurationError(
            "writing_block_enabled must be true or false."
        )
    resulting_text_formatting_value = raw.get(
        "resulting_text_formatting",
        "default",
    )
    if not isinstance(resulting_text_formatting_value, str):
        raise ConfigurationError("resulting_text_formatting must be text.")
    resulting_text_formatting = (
        resulting_text_formatting_value.strip().casefold().replace(" ", "_")
    )
    if resulting_text_formatting not in RESULTING_TEXT_FORMATTING_VALUES:
        raise ConfigurationError(
            "resulting_text_formatting must be one of: "
            f"{', '.join(RESULTING_TEXT_FORMATTING_VALUES)}."
        )
    title_subject_value = raw.get("title_subject", "none")
    if not isinstance(title_subject_value, str):
        raise ConfigurationError("title_subject must be text.")
    title_subject = (
        title_subject_value.strip().casefold().replace(" ", "_")
    )
    if title_subject not in TITLE_SUBJECT_VALUES:
        raise ConfigurationError(
            "title_subject must be one of: "
            f"{', '.join(TITLE_SUBJECT_VALUES)}."
        )
    try:
        starter_action_version = int(raw.get("starter_action_version", 1))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "starter_action_version must be a whole number."
        ) from exc
    if starter_action_version < 1:
        raise ConfigurationError(
            "starter_action_version must be at least 1."
        )
    try:
        starter_application_policy_version = int(
            raw.get("starter_application_policy_version", 0)
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "starter_application_policy_version must be a whole number."
        ) from exc
    if starter_application_policy_version < 0:
        raise ConfigurationError(
            "starter_application_policy_version cannot be negative."
        )

    known = {
        "project_name",
        "project_naming_mode",
        "theme",
        "popup_hotkey",
        "capture_timeout_ms",
        "automation_timeout_seconds",
        "first_run_setup_completed",
        "startup_enabled",
        "check_for_updates_enabled",
        "chatgpt_uri",
        "app_names",
        "project_uri",
        "home_most_used_count",
        "folder_icons",
        "natural_voice_enabled",
        "natural_voice_instruction",
        "auto_submit_enabled",
        "privacy_preview_enabled",
        "replace_selected_text_enabled",
        "copy_generated_text_enabled",
        "application_return_policies",
        "application_profiles",
        "temporary_chat_enabled",
        "primary_language",
        "guided_drafting_enabled",
        "resulting_text_length",
        "writing_block_enabled",
        "resulting_text_formatting",
        "title_subject",
        "starter_action_version",
        "starter_application_policy_version",
    }
    return AppSettings(
        project_name=project_name,
        project_naming_mode=project_naming_mode,
        theme=theme,
        popup_hotkey=popup_hotkey,
        capture_timeout_ms=capture_timeout_ms,
        automation_timeout_seconds=automation_timeout_seconds,
        first_run_setup_completed=first_run_setup_completed,
        startup_enabled=bool(raw.get("startup_enabled", False)),
        check_for_updates_enabled=check_for_updates_enabled,
        chatgpt_uri=str(raw.get("chatgpt_uri", "chatgpt:")).strip() or "chatgpt:",
        app_names=tuple(item.strip() for item in app_names),
        project_uri=str(raw.get("project_uri", "")).strip(),
        home_most_used_count=home_most_used_count,
        folder_icons={
            normalize_folder(folder): icon.strip()
            for folder, icon in folder_icons.items()
            if normalize_folder(folder)
        },
        natural_voice_enabled=natural_voice_enabled,
        natural_voice_instruction=natural_voice_instruction,
        auto_submit_enabled=auto_submit_enabled,
        privacy_preview_enabled=privacy_preview_enabled,
        replace_selected_text_enabled=replace_selected_text_enabled,
        copy_generated_text_enabled=copy_generated_text_enabled,
        application_return_policies=application_return_policies,
        application_profiles=application_profiles,
        temporary_chat_enabled=temporary_chat_enabled,
        primary_language=primary_language,
        guided_drafting_enabled=guided_drafting_enabled,
        resulting_text_length=resulting_text_length,
        writing_block_enabled=writing_block_enabled,
        resulting_text_formatting=resulting_text_formatting,
        title_subject=title_subject,
        starter_action_version=starter_action_version,
        starter_application_policy_version=(
            starter_application_policy_version
        ),
        extra={key: value for key, value in raw.items() if key not in known},
    )


def settings_to_dict(settings: AppSettings) -> dict[str, object]:
    return {
        **settings.extra,
        "project_name": settings.project_name,
        "project_naming_mode": settings.project_naming_mode,
        "theme": settings.theme,
        "popup_hotkey": settings.popup_hotkey,
        "capture_timeout_ms": settings.capture_timeout_ms,
        "automation_timeout_seconds": settings.automation_timeout_seconds,
        "first_run_setup_completed": settings.first_run_setup_completed,
        "startup_enabled": settings.startup_enabled,
        "check_for_updates_enabled": settings.check_for_updates_enabled,
        "chatgpt_uri": settings.chatgpt_uri,
        "app_names": list(settings.app_names),
        "project_uri": settings.project_uri,
        "home_most_used_count": settings.home_most_used_count,
        "folder_icons": settings.folder_icons,
        "natural_voice_enabled": settings.natural_voice_enabled,
        "natural_voice_instruction": settings.natural_voice_instruction,
        "auto_submit_enabled": settings.auto_submit_enabled,
        "privacy_preview_enabled": settings.privacy_preview_enabled,
        "replace_selected_text_enabled": settings.replace_selected_text_enabled,
        "copy_generated_text_enabled": settings.copy_generated_text_enabled,
        "application_return_policies": dict(
            sorted(settings.application_return_policies.items())
        ),
        "application_profiles": {
            application: _application_profile_to_dict(profile)
            for application, profile in sorted(
                settings.application_profiles.items()
            )
        },
        "temporary_chat_enabled": settings.temporary_chat_enabled,
        "primary_language": settings.primary_language,
        "guided_drafting_enabled": settings.guided_drafting_enabled,
        "resulting_text_length": settings.resulting_text_length,
        "writing_block_enabled": settings.writing_block_enabled,
        "resulting_text_formatting": settings.resulting_text_formatting,
        "title_subject": settings.title_subject,
        "starter_action_version": settings.starter_action_version,
        "starter_application_policy_version": (
            settings.starter_application_policy_version
        ),
    }


def save_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(settings_to_dict(settings), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        load_settings(temp_path)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
