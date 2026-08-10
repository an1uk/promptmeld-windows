from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


_REWRITE_BLOCK = re.compile(
    r"(?ms)^[ \t]*<<<PROMPTMELD_REWRITE>>>[ \t]*\r?\n"
    r"(.*?)"
    r"(?:\r?\n)?^[ \t]*<<<END_PROMPTMELD_REWRITE>>>[ \t]*$"
)
_FEEDBACK_BLOCK = re.compile(
    r"(?ms)^[ \t]*<<<PROMPTMELD_FEEDBACK>>>[ \t]*\r?\n"
    r"(.*?)"
    r"(?:\r?\n)?^[ \t]*<<<END_PROMPTMELD_FEEDBACK>>>[ \t]*$"
)
_COMMENT_BLOCK = re.compile(
    r"(?ms)^[ \t]*<<<PROMPTMELD_COMMENT>>>[ \t]*\r?\n"
    r"(.*?)"
    r"(?:\r?\n)?^[ \t]*<<<END_PROMPTMELD_COMMENT>>>[ \t]*$"
)
_SOURCE_PASSAGE = re.compile(
    r"(?ms)^[ \t]*<<<PROMPTMELD_SOURCE_PASSAGE>>>[ \t]*\r?\n"
    r"(.*?)"
    r"(?:\r?\n)?^[ \t]*<<<END_PROMPTMELD_SOURCE_PASSAGE>>>[ \t]*$"
)
_COMMENT_TEXT = re.compile(
    r"(?ms)^[ \t]*<<<PROMPTMELD_COMMENT_TEXT>>>[ \t]*\r?\n"
    r"(.*?)"
    r"(?:\r?\n)?^[ \t]*<<<END_PROMPTMELD_COMMENT_TEXT>>>[ \t]*$"
)
_TOKEN = re.compile(r"\s+|[\w]+(?:[\-'\u2019][\w]+)*|[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class EditorialComment:
    source_passage: str
    comment: str


@dataclass(frozen=True, slots=True)
class ReviewDocument:
    rewrite: str = ""
    feedback: str = ""
    comments: tuple[EditorialComment, ...] = ()
    structured: bool = False

    @property
    def primary_text(self) -> str:
        return self.rewrite or self.feedback


@dataclass(frozen=True, slots=True)
class DiffSegment:
    original: str
    revised: str
    changed: bool
    change_index: int = -1


class SelectiveTextDiff:
    """A lossless token diff whose changed spans can be accepted separately."""

    def __init__(self, original: str, revised: str):
        self.original = str(original or "")
        self.revised = str(revised or "")
        self.segments = self._build_segments(self.original, self.revised)
        self.accepted = {
            segment.change_index: True
            for segment in self.segments
            if segment.changed
        }

    @property
    def change_count(self) -> int:
        return len(self.accepted)

    @property
    def accepted_count(self) -> int:
        return sum(self.accepted.values())

    def set_accepted(self, change_index: int, accepted: bool) -> None:
        if change_index in self.accepted:
            self.accepted[change_index] = bool(accepted)

    def set_all(self, accepted: bool) -> None:
        for change_index in self.accepted:
            self.accepted[change_index] = bool(accepted)

    def selected_text(self) -> str:
        return "".join(
            (
                segment.revised
                if self.accepted.get(segment.change_index, True)
                else segment.original
            )
            if segment.changed
            else segment.original
            for segment in self.segments
        )

    @classmethod
    def _build_segments(
        cls,
        original: str,
        revised: str,
    ) -> tuple[DiffSegment, ...]:
        original_tokens = _TOKEN.findall(original)
        revised_tokens = _TOKEN.findall(revised)
        matcher = SequenceMatcher(
            lambda token: token.isspace(),
            original_tokens,
            revised_tokens,
            autojunk=True,
        )
        opcodes = matcher.get_opcodes()
        grouped: list[tuple[str, int, int, int, int]] = []
        position = 0
        while position < len(opcodes):
            tag, i1, i2, j1, j2 = opcodes[position]
            if tag == "equal":
                grouped.append((tag, i1, i2, j1, j2))
                position += 1
                continue
            end_i, end_j = i2, j2
            lookahead = position + 1
            while lookahead + 1 < len(opcodes):
                equal = opcodes[lookahead]
                following = opcodes[lookahead + 1]
                equal_text = "".join(original_tokens[equal[1] : equal[2]])
                equal_words = sum(
                    bool(token.strip())
                    for token in original_tokens[equal[1] : equal[2]]
                )
                if (
                    equal[0] != "equal"
                    or following[0] == "equal"
                    or "\n" in equal_text
                    or equal_words > 3
                ):
                    break
                end_i, end_j = following[2], following[4]
                lookahead += 2
            grouped.append(("change", i1, end_i, j1, end_j))
            position = lookahead

        segments: list[DiffSegment] = []
        change_index = 0
        for tag, i1, i2, j1, j2 in grouped:
            changed = tag != "equal"
            segments.append(
                DiffSegment(
                    original="".join(original_tokens[i1:i2]),
                    revised="".join(revised_tokens[j1:j2]),
                    changed=changed,
                    change_index=change_index if changed else -1,
                )
            )
            if changed:
                change_index += 1
        return tuple(segments)


def selective_review_output_rule(
    purpose: str,
    alternative_count: int = 1,
) -> str:
    """Return the response contract used by the selective review window."""

    normalized = str(purpose or "transform").strip().casefold()
    produces_rewrite = normalized in {"transform", "reply"}
    rewrite_section = (
        "Put the complete finished rewrite between the rewrite markers. It "
        "must stand alone and include unchanged material needed for a complete "
        "result.\n"
        "<<<PROMPTMELD_REWRITE>>>\n"
        "[complete rewritten text]\n"
        "<<<END_PROMPTMELD_REWRITE>>>\n"
        if produces_rewrite
        else (
            "Do not add a rewrite section because this action produces "
            "supporting material rather than replacement prose.\n"
        )
    )
    alternative_note = (
        "Within each required PROMPTMELD_ALTERNATIVE block, use all of the "
        "following selective-review sections. Keep the alternative wrapper "
        "markers exactly as already specified.\n"
        if alternative_count > 1
        else ""
    )
    ending = (
        "Apart from the required alternative wrapper markers, put nothing "
        "outside the marked selective-review sections."
        if alternative_count > 1
        else "Put nothing outside the marked sections."
    )
    return (
        "Format the completed response for PromptMeld's selective review "
        "window. This output format overrides any earlier instruction to put "
        "only the finished text in a writing block or to omit commentary.\n"
        f"{alternative_note}"
        f"{rewrite_section}"
        "Put the requested editorial feedback, analysis, extracted material, "
        "or development notes between these markers. For a straightforward "
        "rewrite, give a concise overview of the most material changes.\n"
        "<<<PROMPTMELD_FEEDBACK>>>\n"
        "[editorial feedback or supporting result]\n"
        "<<<END_PROMPTMELD_FEEDBACK>>>\n"
        "When a comment relates to a specific source passage, add a separate "
        "comment block using an exact, short quote from the source. Use no more "
        "than eight high-value comments and omit these blocks when no precise "
        "passage applies. Repeat this complete block as needed:\n"
        "<<<PROMPTMELD_COMMENT>>>\n"
        "<<<PROMPTMELD_SOURCE_PASSAGE>>>\n"
        "[exact short source quote]\n"
        "<<<END_PROMPTMELD_SOURCE_PASSAGE>>>\n"
        "<<<PROMPTMELD_COMMENT_TEXT>>>\n"
        "[comment linked to that passage]\n"
        "<<<END_PROMPTMELD_COMMENT_TEXT>>>\n"
        "<<<END_PROMPTMELD_COMMENT>>>\n"
        f"{ending}"
    )


def add_selective_review_output_rule(
    prompt: str,
    purpose: str,
    alternative_count: int = 1,
) -> str:
    rule = selective_review_output_rule(purpose, alternative_count)
    marker = "\n\nSource text begins below:"
    if marker in prompt:
        return prompt.replace(
            marker,
            f"\n\nSelective review output:\n{rule}{marker}",
            1,
        )
    return f"{prompt.rstrip()}\n\nSelective review output:\n{rule}"


def parse_selective_review_result(
    text: str,
    *,
    prefer_feedback: bool = False,
) -> ReviewDocument:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ReviewDocument()
    rewrite_match = _REWRITE_BLOCK.search(cleaned)
    feedback_match = _FEEDBACK_BLOCK.search(cleaned)
    comments: list[EditorialComment] = []
    for comment_match in _COMMENT_BLOCK.finditer(cleaned):
        block = comment_match.group(1)
        passage_match = _SOURCE_PASSAGE.search(block)
        text_match = _COMMENT_TEXT.search(block)
        if passage_match is None or text_match is None:
            continue
        passage = passage_match.group(1).strip()
        comment = text_match.group(1).strip()
        if passage and comment:
            comments.append(EditorialComment(passage, comment))
    structured = bool(rewrite_match or feedback_match or comments)
    rewrite = rewrite_match.group(1).strip() if rewrite_match else ""
    feedback = feedback_match.group(1).strip() if feedback_match else ""
    if not structured:
        if prefer_feedback:
            feedback = cleaned
        else:
            rewrite = cleaned
    elif not rewrite and not feedback:
        feedback = cleaned
    return ReviewDocument(
        rewrite=rewrite,
        feedback=feedback,
        comments=tuple(comments),
        structured=structured,
    )
