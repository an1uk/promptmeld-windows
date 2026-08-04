from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .branding import DEFAULT_PROJECT_NAME

DEFAULT_NATURAL_VOICE_INSTRUCTION = (
    "Preserve the writer's individual voice, vocabulary, and level of formality. "
    "Make only the changes needed for the selected task. Avoid generic filler, "
    "stock transitions, excessive structure, and unnecessarily polished phrasing. "
    "Do not use em dashes (\u2014). Use a standard dash (-), comma, colon, "
    "semicolon, brackets, or a separate sentence instead. Do not invent personal "
    "details or deliberately introduce errors."
)
NATURAL_VOICE_MODES = ("inherit", "always", "never")
PRIMARY_LANGUAGE_OPTIONS = (
    "English (UK)",
    "English (US)",
    "Preserve source language",
)
RESULTING_TEXT_LENGTH_OPTIONS = (
    ("default", "Default"),
    ("extra_short", "Extra short"),
    ("short", "Short"),
    ("medium", "Medium"),
    ("long", "Long"),
    ("extra_long", "Extra long"),
)
RESULTING_TEXT_LENGTH_VALUES = tuple(
    value for value, _label in RESULTING_TEXT_LENGTH_OPTIONS
)
RESULTING_TEXT_FORMATTING_OPTIONS = (
    ("default", "Default"),
    ("plain", "Do not add formatting"),
    ("formatted", "Add helpful formatting"),
)
RESULTING_TEXT_FORMATTING_VALUES = tuple(
    value for value, _label in RESULTING_TEXT_FORMATTING_OPTIONS
)
EDITING_STRENGTH_OPTIONS = (
    ("default", "Default"),
    ("proofread", "Proofread"),
    ("improve", "Improve"),
    ("rewrite", "Rewrite"),
)
EDITING_STRENGTH_VALUES = tuple(
    value for value, _label in EDITING_STRENGTH_OPTIONS
)
RECIPIENT_AUDIENCE_OPTIONS = (
    ("unspecified", "Not specified"),
    ("friend_family", "Friend or family"),
    ("colleague_peer", "Colleague or peer"),
    ("manager_senior", "Manager or senior colleague"),
    ("customer_client", "Customer or client"),
    ("company_support", "Company or support team"),
    ("public_online", "Public or online audience"),
    ("general_reader", "General reader"),
    ("other", "Other (describe in context)"),
)
RECIPIENT_AUDIENCE_VALUES = tuple(
    value for value, _label in RECIPIENT_AUDIENCE_OPTIONS
)


@dataclass(frozen=True, slots=True)
class WritingAction:
    id: str
    name: str
    keywords: tuple[str, ...]
    instruction: str
    hotkey: str | None = None
    enabled: bool = True
    icon: str = ""
    folder: str = ""
    show_on_home: bool = False
    natural_voice: str = "inherit"
    guided_drafting: bool = False


@dataclass(frozen=True, slots=True)
class CapturedSelection:
    text: str
    source_hwnd: int
    source_title: str
    source_is_editable: bool = False
    source_app: str = ""


@dataclass(frozen=True, slots=True)
class UsageRecord:
    count: int = 0
    last_used: datetime | None = None


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    submitted: bool
    prepared: bool = False
    fallback_copied: bool = False
    generated_text_copied: bool = False
    selection_replaced: bool = False
    output_failed: bool = False
    cancelled: bool = False
    message: str = ""


@dataclass(frozen=True, slots=True)
class AppSettings:
    project_name: str = DEFAULT_PROJECT_NAME
    theme: str = "auto"
    popup_hotkey: str = "Ctrl+Alt+Space"
    capture_timeout_ms: int = 1000
    automation_timeout_seconds: float = 8.0
    startup_enabled: bool = False
    check_for_updates_enabled: bool = True
    chatgpt_uri: str = "chatgpt:"
    app_names: tuple[str, ...] = ("ChatGPT",)
    project_uri: str = ""
    home_most_used_count: int = 3
    folder_icons: dict[str, str] = field(default_factory=dict)
    natural_voice_enabled: bool = False
    natural_voice_instruction: str = DEFAULT_NATURAL_VOICE_INSTRUCTION
    auto_submit_enabled: bool = False
    replace_selected_text_enabled: bool = False
    copy_generated_text_enabled: bool = False
    application_return_policies: dict[str, str] = field(default_factory=dict)
    temporary_chat_enabled: bool = False
    primary_language: str = "English (UK)"
    guided_drafting_enabled: bool = False
    resulting_text_length: str = "default"
    writing_block_enabled: bool = False
    resulting_text_formatting: str = "default"
    starter_action_version: int = 2
    starter_application_policy_version: int = 0
    extra: dict[str, object] = field(default_factory=dict)
