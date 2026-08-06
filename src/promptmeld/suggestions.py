from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

from .models import WritingAction


@dataclass(frozen=True, slots=True)
class SuggestionContext:
    source_application: str
    source_label: str
    word_count: int
    length_band: str
    text_types: tuple[str, ...]

    @property
    def summary(self) -> str:
        parts = [self.source_label] if self.source_label else []
        parts.extend(
            text_type.replace("_", " ").title()
            for text_type in self.text_types[:2]
        )
        parts.append(f"{self.word_count} word{'s' if self.word_count != 1 else ''}")
        return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class ActionSuggestion:
    action: WritingAction
    score: float
    reasons: tuple[str, ...]


_APPLICATION_LABELS = {
    "winword.exe": "Microsoft Word",
    "outlook.exe": "Microsoft Outlook",
    "olk.exe": "New Outlook",
    "thunderbird.exe": "Thunderbird",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
    "code.exe": "Visual Studio Code",
    "notepad.exe": "Notepad",
}
_EMAIL_APPLICATIONS = {"outlook.exe", "olk.exe", "thunderbird.exe"}
_BROWSER_APPLICATIONS = {"chrome.exe", "msedge.exe", "firefox.exe"}
_MESSAGE_APPLICATIONS = {
    "ms-teams.exe",
    "teams.exe",
    "slack.exe",
    "discord.exe",
}
_DOCUMENT_APPLICATIONS = {"winword.exe", "notepad.exe"}
_CODE_APPLICATIONS = {"code.exe"}


def _normalise_application(value: str) -> str:
    cleaned = str(value or "").strip().strip('"').replace("\\", "/")
    return PurePath(cleaned).name.casefold() if cleaned else ""


def classify_suggestion_context(
    text: str,
    source_application: str = "",
) -> SuggestionContext:
    """Reduce selected text to non-content features for local ranking."""

    application = _normalise_application(source_application)
    words = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    word_count = len(words)
    length_band = (
        "short" if word_count <= 40 else "medium" if word_count <= 180 else "long"
    )
    lowered = text.casefold()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text_types: list[str] = []

    def add(value: str) -> None:
        if value not in text_types:
            text_types.append(value)

    looks_like_email = bool(
        application in _EMAIL_APPLICATIONS
        or re.search(r"(?im)^(?:from|to|subject|cc):\s*\S", text)
        or re.search(r"(?im)^(?:dear|hello|hi)\b", text)
        and re.search(
            r"(?im)^(?:kind regards|regards|best|thanks)[,\s]*$",
            text,
        )
    )
    if looks_like_email:
        add("email")
    if "?" in text or re.search(
        r"(?i)\b(?:how|why|what|when|where|which|can|could|would|should)\b[^.?!]{0,80}\?",
        text,
    ):
        add("question")
    if re.search(
        r"(?i)\b(?:complaint|unhappy|disappointed|refund|faulty|damaged|"
        r"unacceptable|not working|not arrived|late delivery|delayed|"
        r"problem with|poor service)\b",
        text,
    ):
        add("complaint")
    if re.search(
        r"(?i)\b(?:error|exception|traceback|failed|failure|bug|crash|"
        r"driver|install|server|database|api|usb|network|windows)\b",
        text,
    ) or re.search(
        r"\b[A-Z][A-Za-z]+(?:Error|Exception)\b",
        text,
    ) or re.search(
        r"(?m)^\s*(?:```|def\s+|class\s+|import\s+|from\s+\S+\s+import\s+|"
        r"return\s+|const\s+|let\s+|function\s+|"
        r"[A-Za-z_][\w.]*\([^)]*\)\s*$)",
        text,
    ):
        add("technical")
    bullet_lines = sum(
        bool(re.match(r"^(?:[-*•]|\d+[.)])\s+", line)) for line in lines
    )
    if bullet_lines >= 2 or (
        not looks_like_email
        and "technical" not in text_types
        and len(lines) >= 3
        and sum(len(line.split()) <= 8 for line in lines) >= len(lines) - 1
    ):
        add("notes")
    if re.search(
        r"(?i)\b(?:review|rating|stars?|product|purchase|bought|seller|buyer)\b",
        text,
    ):
        add("review")
    if re.search(
        r"(?i)\b(?:claim|argument|evidence|because|disagree|misleading|"
        r"therefore|however|policy|opinion)\b",
        text,
    ):
        add("argument")
    if application in _BROWSER_APPLICATIONS | _MESSAGE_APPLICATIONS and word_count <= 180:
        add("online_message")

    source_label = _APPLICATION_LABELS.get(
        application,
        application or "Selected text",
    )
    return SuggestionContext(
        source_application=application,
        source_label=source_label,
        word_count=word_count,
        length_band=length_band,
        text_types=tuple(text_types),
    )


def _action_text(action: WritingAction) -> str:
    return " ".join(
        (
            action.id,
            action.name,
            *action.keywords,
            action.folder,
            action.instruction,
        )
    ).casefold()


def contextual_action_score(
    action: WritingAction,
    context: SuggestionContext,
) -> tuple[float, tuple[str, ...]]:
    """Score one action using application, length, and detected text type."""

    searchable = _action_text(action)
    score = 0.0
    reasons: list[str] = []

    def contains(term: str) -> bool:
        return bool(
            re.search(
                rf"(?<![\w]){re.escape(term)}(?![\w])",
                searchable,
            )
        )

    def reward(weight: float, reason: str, terms: tuple[str, ...]) -> None:
        nonlocal score
        if any(contains(term) for term in terms):
            score += weight
            if reason not in reasons:
                reasons.append(reason)

    application = context.source_application
    if application in _EMAIL_APPLICATIONS:
        reward(
            62,
            f"email action for {context.source_label}",
            ("email", "correspondence", "follow up"),
        )
        reward(
            28,
            f"reply action for {context.source_label}",
            ("reply", "customer", "complaint"),
        )
    elif application in _BROWSER_APPLICATIONS:
        reward(
            34,
            f"suited to {context.source_label}",
            ("comment", "review", "fact-check", "challenge", "marketplace"),
        )
        reward(
            16,
            f"reply action for {context.source_label}",
            ("reply",),
        )
    elif application in _MESSAGE_APPLICATIONS:
        reward(
            30,
            f"suited to {context.source_label}",
            ("reply", "friendly", "shorten", "direct", "polite", "message"),
        )
    elif application in _DOCUMENT_APPLICATIONS:
        reward(
            24,
            f"suited to {context.source_label}",
            (
                "edit",
                "editing",
                "revise",
                "clarity",
                "grammar",
                "proofread",
                "shorten",
            ),
        )
    elif application in _CODE_APPLICATIONS:
        reward(
            50,
            f"suited to {context.source_label}",
            (
                "technical",
                "troubleshoot",
                "diagnose",
                "diagnosis",
                "checklist",
            ),
        )
        reward(
            12,
            f"can explain text from {context.source_label}",
            ("explain",),
        )

    type_rules = {
        "email": (
            56,
            "looks like email",
            ("email", "follow up", "reminder"),
        ),
        "question": (
            24,
            "contains a question",
            ("reply", "explain", "compare", "troubleshoot", "answer"),
        ),
        "complaint": (
            52,
            "looks like a complaint",
            ("complaint", "customer", "polite", "firm", "problem"),
        ),
        "technical": (
            56,
            "looks technical",
            (
                "technical",
                "troubleshoot",
                "diagnose",
                "diagnosis",
                "checklist",
            ),
        ),
        "notes": (
            50,
            "looks like notes",
            ("rough notes", "notes", "shape"),
        ),
        "review": (
            46,
            "looks like a review",
            ("review", "product", "marketplace", "ebay"),
        ),
        "argument": (
            38,
            "contains an argument",
            ("argument", "challenge", "claim", "fact-check", "reply"),
        ),
        "online_message": (
            24,
            "looks like an online message",
            ("comment", "reply", "friendly", "direct", "marketplace"),
        ),
    }
    for text_type in context.text_types:
        weight, reason, terms = type_rules[text_type]
        reward(weight, reason, terms)
    if "technical" in context.text_types:
        reward(10, "can explain technical text", ("explain",))

    if context.length_band == "long":
        reward(
            28,
            "useful for long text",
            ("shorten", "concise", "clarity", "edit", "revise", "grammar"),
        )
    elif context.length_band == "short":
        reward(
            14,
            "useful for short text",
            ("reply", "expand", "friendly", "direct", "comment"),
        )
    else:
        reward(
            9,
            "suited to this text length",
            ("edit", "clarity", "professional", "grammar"),
        )
    return score, tuple(reasons)
