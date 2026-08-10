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
PROJECT_NAMING_OPTIONS = (
    ("action", "Writing action or folder (current behaviour)"),
    ("single", "One project for everything"),
    ("application", "Application the text came from"),
)
PROJECT_NAMING_VALUES = tuple(
    value for value, _label in PROJECT_NAMING_OPTIONS
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
TITLE_SUBJECT_OPTIONS = (
    ("none", "Do not add one"),
    ("automatic", "Choose title or subject automatically"),
    ("title", "Generate a title"),
    ("subject", "Generate a subject line"),
)
TITLE_SUBJECT_VALUES = tuple(
    value for value, _label in TITLE_SUBJECT_OPTIONS
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
ACTION_PURPOSE_OPTIONS = (
    ("transform", "Edit or replace selected text"),
    ("reply", "Draft a reply to selected text"),
    ("analyse", "Analyse or review selected text"),
    ("extract", "Extract or summarise information"),
    ("develop", "Develop ideas or ask useful questions"),
)
ACTION_PURPOSE_VALUES = tuple(
    value for value, _label in ACTION_PURPOSE_OPTIONS
)
ACTION_RESULT_HANDLING_OPTIONS = (
    ("purpose_default", "Use the safe recommendation for this purpose"),
    ("inherit", "Use application or overall defaults"),
    ("replace", "Apply automatically when safe"),
    ("review", "Open a review window"),
    ("copy", "Copy to the clipboard"),
    ("leave", "Leave the result in ChatGPT"),
)
ACTION_RESULT_HANDLING_VALUES = tuple(
    value for value, _label in ACTION_RESULT_HANDLING_OPTIONS
)
SAFE_REVIEW_ACTION_PURPOSES = frozenset({"analyse", "extract", "develop"})


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
    recipient_audience: str = "inherit"
    purpose: str = "transform"
    result_handling: str = "purpose_default"


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
    generated_text: str = ""


@dataclass(frozen=True, slots=True)
class ApplicationProfile:
    """Writing and delivery defaults for one source executable."""

    return_mode: str = "default"
    recipient_audience: str = "inherit"
    primary_language: str = ""
    resulting_text_length: str = "inherit"
    resulting_text_formatting: str = "inherit"
    title_subject: str = "inherit"
    editing_strength: str = "inherit"
    preserve_facts: str = "inherit"
    natural_voice: str = "inherit"
    guided_drafting: str = "inherit"
    writing_block: str = "inherit"
    auto_submit: str = "inherit"
    temporary_chat: str = "inherit"
    privacy_preview: str = "inherit"
    response_wait: str = "inherit"
    project_name: str = ""


@dataclass(frozen=True, slots=True)
class AppSettings:
    project_name: str = DEFAULT_PROJECT_NAME
    project_naming_mode: str = "action"
    theme: str = "auto"
    popup_hotkey: str = "Ctrl+Alt+Space"
    capture_timeout_ms: int = 1000
    automation_timeout_seconds: float = 8.0
    first_run_setup_completed: bool = True
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
    privacy_preview_enabled: bool = True
    replace_selected_text_enabled: bool = False
    copy_generated_text_enabled: bool = False
    application_return_policies: dict[str, str] = field(default_factory=dict)
    application_profiles: dict[str, ApplicationProfile] = field(
        default_factory=dict
    )
    temporary_chat_enabled: bool = False
    primary_language: str = "English (UK)"
    guided_drafting_enabled: bool = False
    resulting_text_length: str = "default"
    writing_block_enabled: bool = False
    resulting_text_formatting: str = "default"
    title_subject: str = "none"
    starter_action_version: int = 3
    starter_application_policy_version: int = 0
    extra: dict[str, object] = field(default_factory=dict)
