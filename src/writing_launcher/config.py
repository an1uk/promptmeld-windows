from __future__ import annotations

import json
import shutil
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from typing import Any

from .branding import DEFAULT_PROJECT_NAME
from .models import (
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    NATURAL_VOICE_MODES,
    AppSettings,
    WritingAction,
)
from .paths import AppPaths

DEFAULT_ACTION_ICONS = {
    "edit-improve": "lucide:sparkles",
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
}

CURRENT_STARTER_ACTION_VERSION = 2
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
CORRESPONDENCE_ACTION_IDS = {
    "reply-email",
    "formal-email-reply",
    "follow-up-reminder",
    "reply-customer-message",
    "reply-marketplace-message",
    "respond-complaint",
}


class ConfigurationError(ValueError):
    """Raised when a user-editable configuration file is invalid."""


def _resource_path(name: str) -> Path:
    return Path(str(files("writing_launcher").joinpath("resources", name)))


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
    _migrate_correspondence_actions(
        paths,
        force=settings_existed is False and actions_existed,
    )
    _migrate_launcher_defaults(paths)


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


def _migrate_correspondence_actions(
    paths: AppPaths,
    *,
    force: bool = False,
) -> None:
    """Add the V2 correspondence starter actions once without replacing edits."""

    settings = load_settings(paths.settings_file)
    current_version = 1 if force else settings.starter_action_version
    if current_version >= CURRENT_STARTER_ACTION_VERSION:
        return

    actions = load_actions(paths.actions_file)
    existing_ids = {action.id for action in actions}
    additions = [
        action
        for action in load_default_actions()
        if action.id in CORRESPONDENCE_ACTION_IDS
        and action.id not in existing_ids
    ]
    if additions:
        backup = paths.data_dir / "actions.pre-correspondence-v2-backup.json"
        if not backup.exists():
            shutil.copyfile(paths.actions_file, backup)
        save_actions(paths.actions_file, [*actions, *additions])

    folder_icons = dict(settings.folder_icons)
    for folder in (
        "Correspondence",
        "Correspondence/Email",
        "Correspondence/Customer & marketplace",
    ):
        folder_icons.setdefault(folder, DEFAULT_FOLDER_ICONS[folder])
    save_settings(
        paths.settings_file,
        replace(
            settings,
            folder_icons=folder_icons,
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


def normalize_folder(value: str) -> str:
    parts = tuple(
        part.strip()
        for part in value.replace("\\", "/").split("/")
        if part.strip()
    )
    if any(part in {".", ".."} for part in parts):
        raise ConfigurationError("Folder names cannot be '.' or '..'.")
    return "/".join(parts)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {path.name} at line {exc.lineno}, column {exc.colno}."
        ) from exc


def load_actions(path: Path) -> list[WritingAction]:
    data = _read_json(path)
    if not isinstance(data, list):
        raise ConfigurationError("actions.json must contain a JSON list.")

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
                folder=normalize_folder(folder or ""),
                show_on_home=bool(raw.get("show_on_home", False)),
                natural_voice=natural_voice,
                guided_drafting=guided_drafting,
            )
        )
    return actions


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
    popup_hotkey = str(raw.get("popup_hotkey", "Ctrl+Alt+Space")).strip()
    if not project_name:
        raise ConfigurationError("project_name cannot be empty.")
    if not popup_hotkey:
        raise ConfigurationError("popup_hotkey cannot be empty.")

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
    auto_submit_enabled = raw.get("auto_submit_enabled", False)
    if not isinstance(auto_submit_enabled, bool):
        raise ConfigurationError("auto_submit_enabled must be true or false.")
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

    known = {
        "project_name",
        "popup_hotkey",
        "capture_timeout_ms",
        "automation_timeout_seconds",
        "startup_enabled",
        "chatgpt_uri",
        "app_names",
        "project_uri",
        "home_most_used_count",
        "folder_icons",
        "natural_voice_enabled",
        "natural_voice_instruction",
        "auto_submit_enabled",
        "primary_language",
        "guided_drafting_enabled",
        "starter_action_version",
    }
    return AppSettings(
        project_name=project_name,
        popup_hotkey=popup_hotkey,
        capture_timeout_ms=capture_timeout_ms,
        automation_timeout_seconds=automation_timeout_seconds,
        startup_enabled=bool(raw.get("startup_enabled", False)),
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
        primary_language=primary_language,
        guided_drafting_enabled=guided_drafting_enabled,
        starter_action_version=starter_action_version,
        extra={key: value for key, value in raw.items() if key not in known},
    )


def settings_to_dict(settings: AppSettings) -> dict[str, object]:
    return {
        **settings.extra,
        "project_name": settings.project_name,
        "popup_hotkey": settings.popup_hotkey,
        "capture_timeout_ms": settings.capture_timeout_ms,
        "automation_timeout_seconds": settings.automation_timeout_seconds,
        "startup_enabled": settings.startup_enabled,
        "chatgpt_uri": settings.chatgpt_uri,
        "app_names": list(settings.app_names),
        "project_uri": settings.project_uri,
        "home_most_used_count": settings.home_most_used_count,
        "folder_icons": settings.folder_icons,
        "natural_voice_enabled": settings.natural_voice_enabled,
        "natural_voice_instruction": settings.natural_voice_instruction,
        "auto_submit_enabled": settings.auto_submit_enabled,
        "primary_language": settings.primary_language,
        "guided_drafting_enabled": settings.guided_drafting_enabled,
        "starter_action_version": settings.starter_action_version,
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
