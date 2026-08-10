from promptmeld.selective_review import (
    SelectiveTextDiff,
    add_selective_review_output_rule,
    parse_selective_review_result,
    selective_review_output_rule,
)


def test_structured_review_parses_rewrite_feedback_and_linked_comments():
    response = """
<<<PROMPTMELD_REWRITE>>>
The revised opening is clearer.
<<<END_PROMPTMELD_REWRITE>>>
<<<PROMPTMELD_FEEDBACK>>>
The revision brings the central point forward.
<<<END_PROMPTMELD_FEEDBACK>>>
<<<PROMPTMELD_COMMENT>>>
<<<PROMPTMELD_SOURCE_PASSAGE>>>
The old opening
<<<END_PROMPTMELD_SOURCE_PASSAGE>>>
<<<PROMPTMELD_COMMENT_TEXT>>>
This delayed the main point.
<<<END_PROMPTMELD_COMMENT_TEXT>>>
<<<END_PROMPTMELD_COMMENT>>>
"""

    document = parse_selective_review_result(response)

    assert document.structured is True
    assert document.rewrite == "The revised opening is clearer."
    assert document.feedback.startswith("The revision brings")
    assert len(document.comments) == 1
    assert document.comments[0].source_passage == "The old opening"
    assert document.comments[0].comment == "This delayed the main point."
    assert document.primary_text == "The revised opening is clearer."


def test_unstructured_safe_result_is_treated_as_feedback_not_rewrite():
    document = parse_selective_review_result(
        "The scene loses tension in the middle.",
        prefer_feedback=True,
    )

    assert document.rewrite == ""
    assert document.feedback == "The scene loses tension in the middle."
    assert document.primary_text == document.feedback


def test_selective_diff_accepts_and_rejects_changes_losslessly():
    original = "The first sentence is rather long. Keep this sentence."
    revised = "The opening sentence is concise. Keep this sentence."
    difference = SelectiveTextDiff(original, revised)

    assert difference.change_count >= 1
    assert difference.selected_text() == revised

    difference.set_all(False)
    assert difference.selected_text() == original

    first_change = min(difference.accepted)
    difference.set_accepted(first_change, True)
    partly_accepted = difference.selected_text()
    assert partly_accepted != original
    assert partly_accepted != ""


def test_selective_diff_preserves_insertions_deletions_and_whitespace():
    original = "Heading\r\n\r\nA short paragraph.\r\n"
    revised = "Heading\r\n\r\nA concise paragraph with detail.\r\n"
    difference = SelectiveTextDiff(original, revised)

    assert difference.selected_text() == revised
    difference.set_all(False)
    assert difference.selected_text() == original


def test_selective_review_prompt_contract_distinguishes_rewrite_and_feedback():
    rewrite_rule = selective_review_output_rule("transform")
    analysis_rule = selective_review_output_rule("analyse")

    assert "<<<PROMPTMELD_REWRITE>>>" in rewrite_rule
    assert "complete finished rewrite" in rewrite_rule
    assert "Do not add a rewrite section" in analysis_rule
    assert "<<<PROMPTMELD_COMMENT>>>" in analysis_rule
    assert "Within each required PROMPTMELD_ALTERNATIVE block" in (
        selective_review_output_rule("transform", 2)
    )

    prompt = add_selective_review_output_rule(
        "Task.\n\nSource text begins below:\n<<<SOURCE>>>\nText\n<<<END SOURCE>>>",
        "transform",
    )
    assert prompt.index("Selective review output:") < prompt.index(
        "Source text begins below:"
    )
