from __future__ import annotations

import re
from dataclasses import dataclass


PRIVACY_PLACEHOLDER_INSTRUCTION = (
    "Privacy placeholders such as [EMAIL_1] represent details intentionally "
    "removed by the user. Preserve every placeholder exactly, including its "
    "square brackets, spelling, and number."
)


@dataclass(frozen=True, slots=True)
class SensitiveMatch:
    kind: str
    label: str
    value: str
    start: int
    end: int
    placeholder: str = ""


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    replacements: dict[str, str]
    selected_matches: tuple[SensitiveMatch, ...] = ()


_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,}"
    r"(?![\w-])",
    re.IGNORECASE,
)
_IBAN_PATTERN = re.compile(
    r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}(?![A-Z0-9])"
)
_LABELLED_ACCOUNT_PATTERN = re.compile(
    r"(?i)\b(?:account(?:\s+(?:number|no\.?))?|acct\.?|customer\s+(?:number|"
    r"reference)|membership\s+(?:number|no\.?))\s*[:#-]?\s*"
    r"(?:is\s+)?"
    r"(?P<value>[A-Z0-9][A-Z0-9 -]{4,}[A-Z0-9])\b"
)
_CARD_OR_LONG_NUMBER_PATTERN = re.compile(
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"
)
_PHONE_PATTERN = re.compile(
    r"(?<![\w])(?:\+?\d[\d ().-]{5,}\d)(?![\w])"
)
_TITLED_NAME_PATTERN = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?\s+"
    r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){0,2}\b"
)
_LABELLED_NAME_PATTERN = re.compile(
    r"(?im)\b(?:name|contact|account holder|customer|client)\s*:\s*"
    r"(?P<value>[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){0,2})\b"
)
_GREETING_NAME_PATTERN = re.compile(
    r"(?m)\b(?:Dear|Hello|Hi)\s+"
    r"(?P<value>[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)?)\b"
)
_SIGNATURE_NAME_PATTERN = re.compile(
    r"(?im)^(?:kind regards|regards|best regards|best|thanks),?\s*\n\s*"
    r"(?P<value>[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){0,2})\s*$"
)
_FULL_NAME_PATTERN = re.compile(
    r"\b[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+(?:[A-Z]\.\s+)?[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,2}\b"
)
_PRIVATE_TEXT_BLOCK_PATTERN = re.compile(
    r"(?s)<<<(?:SOURCE|USER CONTEXT)>>>\n(?P<value>.*?)\n"
    r"<<<END (?:SOURCE|USER CONTEXT)>>>",
)

_KIND_DETAILS = {
    "email": ("Email address", "EMAIL"),
    "phone": ("Phone number", "PHONE"),
    "account": ("Account number", "ACCOUNT"),
    "name": ("Possible name", "NAME"),
}


def _candidate(
    kind: str,
    match: re.Match[str],
    group: str | int = 0,
) -> SensitiveMatch:
    start, end = match.span(group)
    return SensitiveMatch(
        kind=kind,
        label=_KIND_DETAILS[kind][0],
        value=match.group(group),
        start=start,
        end=end,
    )


def _digit_count(value: str) -> int:
    return sum(character.isdigit() for character in value)


def detect_sensitive_text(text: str) -> tuple[SensitiveMatch, ...]:
    """Find likely personal details without sending text outside the app."""

    candidates: list[tuple[int, SensitiveMatch]] = []
    candidates.extend(
        (0, _candidate("email", match))
        for match in _EMAIL_PATTERN.finditer(text)
    )
    candidates.extend(
        (1, _candidate("account", match))
        for match in _IBAN_PATTERN.finditer(text)
    )
    candidates.extend(
        (1, _candidate("account", match, "value"))
        for match in _LABELLED_ACCOUNT_PATTERN.finditer(text)
    )
    candidates.extend(
        (1, _candidate("account", match))
        for match in _CARD_OR_LONG_NUMBER_PATTERN.finditer(text)
    )
    candidates.extend(
        (2, _candidate("phone", match))
        for match in _PHONE_PATTERN.finditer(text)
        if 7 <= _digit_count(match.group()) <= 15
    )
    for pattern, group in (
        (_TITLED_NAME_PATTERN, 0),
        (_LABELLED_NAME_PATTERN, "value"),
        (_GREETING_NAME_PATTERN, "value"),
        (_SIGNATURE_NAME_PATTERN, "value"),
    ):
        candidates.extend(
            (3, _candidate("name", match, group))
            for match in pattern.finditer(text)
        )
    private_ranges = [
        match.span("value") for match in _PRIVATE_TEXT_BLOCK_PATTERN.finditer(text)
    ]
    if not private_ranges:
        private_ranges = [(0, len(text))]
    candidates.extend(
        (4, _candidate("name", match))
        for match in _FULL_NAME_PATTERN.finditer(text)
        if any(
            start <= match.start() and match.end() <= end
            for start, end in private_ranges
        )
    )

    accepted: list[SensitiveMatch] = []
    occupied: list[tuple[int, int]] = []
    for _priority, candidate in sorted(
        candidates,
        key=lambda item: (
            item[0],
            item[1].start,
            -(item[1].end - item[1].start),
        ),
    ):
        if any(
            candidate.start < end and candidate.end > start
            for start, end in occupied
        ):
            continue
        accepted.append(candidate)
        occupied.append((candidate.start, candidate.end))

    counters: dict[str, int] = {}
    placeholders: dict[tuple[str, str], str] = {}
    numbered: list[SensitiveMatch] = []
    for candidate in sorted(accepted, key=lambda item: item.start):
        key = (candidate.kind, candidate.value.casefold())
        placeholder = placeholders.get(key)
        if placeholder is None:
            while True:
                counters[candidate.kind] = counters.get(candidate.kind, 0) + 1
                placeholder = (
                    f"[{_KIND_DETAILS[candidate.kind][1]}_"
                    f"{counters[candidate.kind]}]"
                )
                if placeholder not in text and placeholder not in placeholders.values():
                    break
            placeholders[key] = placeholder
        numbered.append(
            SensitiveMatch(
                kind=candidate.kind,
                label=candidate.label,
                value=candidate.value,
                start=candidate.start,
                end=candidate.end,
                placeholder=placeholder,
            )
        )
    return tuple(numbered)


def redact_sensitive_text(
    text: str,
    matches: tuple[SensitiveMatch, ...] | list[SensitiveMatch],
) -> RedactionResult:
    selected = tuple(sorted(matches, key=lambda item: item.start))
    redacted = text
    for match in reversed(selected):
        redacted = redacted[: match.start] + match.placeholder + redacted[match.end :]
    replacements: dict[str, str] = {}
    for match in selected:
        replacements.setdefault(match.placeholder, match.value)
    return RedactionResult(redacted, replacements, selected)


def restore_placeholders(text: str, replacements: dict[str, str]) -> str:
    restored = text
    for placeholder, original in sorted(
        replacements.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        restored = restored.replace(placeholder, original)
    return restored


def add_placeholder_instruction(text: str) -> str:
    return f"{text.rstrip()}\n\n{PRIVACY_PLACEHOLDER_INSTRUCTION}"
