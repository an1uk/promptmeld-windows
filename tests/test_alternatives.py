from __future__ import annotations

import pytest

from promptmeld.alternatives import (
    alternative_output_rule,
    parse_generated_alternatives,
    validate_alternative_count,
)


def test_marker_protocol_parses_three_alternatives():
    response = """
<<<PROMPTMELD_ALTERNATIVE_1>>>
First version.
<<<END_PROMPTMELD_ALTERNATIVE_1>>>
<<<PROMPTMELD_ALTERNATIVE_2>>>
Second version with two paragraphs.

Still second.
<<<END_PROMPTMELD_ALTERNATIVE_2>>>
<<<PROMPTMELD_ALTERNATIVE_3>>>
Third version.
<<<END_PROMPTMELD_ALTERNATIVE_3>>>
"""

    assert parse_generated_alternatives(response, 3) == [
        "First version.",
        "Second version with two paragraphs.\n\nStill second.",
        "Third version.",
    ]


def test_markdown_headings_are_a_tolerant_fallback():
    response = """
### Alternative 1
First version.

### Alternative 2
Second version.
"""

    assert parse_generated_alternatives(response, 2) == [
        "First version.",
        "Second version.",
    ]


def test_unseparated_response_remains_available_as_one_option():
    assert parse_generated_alternatives("A combined response", 3) == [
        "A combined response"
    ]


def test_alternative_prompt_rule_uses_exact_markers():
    rule = alternative_output_rule(2)

    assert "exactly 2 distinct" in rule
    assert "<<<PROMPTMELD_ALTERNATIVE_1>>>" in rule
    assert "<<<END_PROMPTMELD_ALTERNATIVE_2>>>" in rule


@pytest.mark.parametrize("value", (0, 4, "many"))
def test_invalid_alternative_counts_are_rejected(value):
    with pytest.raises(ValueError, match="one, two, or three"):
        validate_alternative_count(value)
