from __future__ import annotations

import re

ALTERNATIVE_COUNTS = (1, 2, 3)

_MARKED_ALTERNATIVE = re.compile(
    r"(?ms)^[ \t]*<<<PROMPTMELD_ALTERNATIVE_(\d+)>>>[ \t]*\r?\n"
    r"(.*?)"
    r"(?:\r?\n)?^[ \t]*<<<END_PROMPTMELD_ALTERNATIVE_\1>>>[ \t]*$"
)
_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*)?"
    r"Alternative[ \t]+(\d+)(?:\*\*)?[ \t]*(?::|-)?[ \t]*$"
)


def validate_alternative_count(value: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Number of alternatives must be one, two, or three.") from exc
    if count not in ALTERNATIVE_COUNTS:
        raise ValueError("Number of alternatives must be one, two, or three.")
    return count


def alternative_output_rule(value: int) -> str:
    count = validate_alternative_count(value)
    if count == 1:
        return ""
    blocks = "\n".join(
        (
            f"<<<PROMPTMELD_ALTERNATIVE_{index}>>>\n"
            f"[alternative {index} text]\n"
            f"<<<END_PROMPTMELD_ALTERNATIVE_{index}>>>"
        )
        for index in range(1, count + 1)
    )
    return (
        f"Produce exactly {count} distinct, complete alternatives that each "
        "satisfy the writing task. Make the differences genuinely useful, "
        "such as varying wording, structure, or emphasis without changing "
        "the supplied facts.\n"
        "Return only the alternatives, using these exact marker lines and "
        "putting no commentary outside them:\n"
        f"{blocks}"
    )


def parse_generated_alternatives(text: str, requested_count: int) -> list[str]:
    """Extract marked alternatives, with a heading fallback for model drift."""

    count = validate_alternative_count(requested_count)
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    if count == 1:
        return [cleaned]

    marked: dict[int, str] = {}
    for match in _MARKED_ALTERNATIVE.finditer(cleaned):
        index = int(match.group(1))
        value = match.group(2).strip()
        if 1 <= index <= count and value and index not in marked:
            marked[index] = value
    if list(sorted(marked)) == list(range(1, count + 1)):
        return [marked[index] for index in range(1, count + 1)]

    headings = list(_HEADING.finditer(cleaned))
    headed: dict[int, str] = {}
    for position, match in enumerate(headings):
        index = int(match.group(1))
        start = match.end()
        end = (
            headings[position + 1].start()
            if position + 1 < len(headings)
            else len(cleaned)
        )
        value = cleaned[start:end].strip()
        if 1 <= index <= count and value and index not in headed:
            headed[index] = value
    if list(sorted(headed)) == list(range(1, count + 1)):
        return [headed[index] for index in range(1, count + 1)]

    return [cleaned]
