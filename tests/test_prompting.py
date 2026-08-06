import pytest

from promptmeld.models import CapturedSelection, WritingAction
from promptmeld.prompting import PromptBuilder


def test_prompt_contains_instruction_text_and_output_constraint():
    action = WritingAction(
        id="shorten",
        name="Shorten",
        keywords=(),
        instruction="Make this concise.",
    )
    selection = CapturedSelection(
        text="First line.\n• Second line with “quotes”.",
        source_hwnd=123,
        source_title="Editor",
    )

    prompt = PromptBuilder().build(action, selection)

    assert "Make this concise." in prompt
    assert "Return only the result requested by the writing task." in prompt
    assert selection.text in prompt
    assert "<<<SOURCE>>>" in prompt
    assert "Use English (UK) spelling" in prompt
    assert "Resulting text length:" not in prompt
    assert "Output presentation:" not in prompt
    assert "Resulting text formatting:" not in prompt


def test_natural_voice_modifier_follows_global_setting():
    action = WritingAction(
        id="edit",
        name="Edit",
        keywords=(),
        instruction="Improve this.",
    )
    selection = CapturedSelection("Draft.", 1, "Editor")

    prompt = PromptBuilder().build(
        action,
        selection,
        natural_voice_enabled=True,
        natural_voice_instruction="Keep my phrasing.",
    )

    assert "Natural voice:\nKeep my phrasing." in prompt


def test_action_can_override_natural_voice_setting():
    selection = CapturedSelection("Draft.", 1, "Editor")
    builder = PromptBuilder()
    always = WritingAction(
        "always",
        "Always",
        (),
        "Improve this.",
        natural_voice="always",
    )
    never = WritingAction(
        "never",
        "Never",
        (),
        "Improve this.",
        natural_voice="never",
    )

    always_prompt = builder.build(
        always,
        selection,
        natural_voice_enabled=False,
        natural_voice_instruction="Keep my phrasing.",
    )
    never_prompt = builder.build(
        never,
        selection,
        natural_voice_enabled=True,
        natural_voice_instruction="Keep my phrasing.",
    )

    assert "Keep my phrasing." in always_prompt
    assert "Keep my phrasing." not in never_prompt


def test_primary_language_can_preserve_source_language():
    action = WritingAction("edit", "Edit", (), "Improve this.")
    selection = CapturedSelection("Bonjour.", 1, "Editor")

    prompt = PromptBuilder().build(
        action,
        selection,
        primary_language="Preserve source language",
    )

    assert "Keep the source text's language" in prompt
    assert "explicitly requests translation" in prompt


def test_guided_drafting_is_added_for_supported_action_when_enabled():
    action = WritingAction(
        "reply-email",
        "Reply to email",
        (),
        "Draft a reply.",
        guided_drafting=True,
    )
    selection = CapturedSelection("Can you send this by Friday?", 1, "Mail")

    prompt = PromptBuilder().build(
        action,
        selection,
        guided_drafting_enabled=True,
    )

    assert "Guided drafting is enabled" in prompt
    assert "no more than three concise questions" in prompt
    assert "two to four clearly labelled choices" in prompt
    assert "draft the requested text immediately" in prompt


def test_guided_drafting_requires_both_global_and_action_switches():
    selection = CapturedSelection("Please reply.", 1, "Mail")
    builder = PromptBuilder()
    supported = WritingAction(
        "supported",
        "Supported",
        (),
        "Draft a reply.",
        guided_drafting=True,
    )
    immediate = WritingAction(
        "immediate",
        "Immediate",
        (),
        "Improve this.",
    )

    globally_off = builder.build(
        supported,
        selection,
        guided_drafting_enabled=False,
    )
    action_off = builder.build(
        immediate,
        selection,
        guided_drafting_enabled=True,
    )

    assert "Guided drafting is enabled" not in globally_off
    assert "Guided drafting is enabled" not in action_off


def test_non_default_resulting_text_lengths_add_prompt_requirements():
    action = WritingAction("edit", "Edit", (), "Improve this.")
    selection = CapturedSelection("Draft.", 1, "Editor")
    expected_phrases = {
        "extra_short": "extremely concise",
        "short": "concise and relatively brief",
        "medium": "moderate, balanced amount of detail",
        "long": "detailed result",
        "extra_long": "very detailed and comprehensive result",
    }

    for value, phrase in expected_phrases.items():
        prompt = PromptBuilder().build(
            action,
            selection,
            resulting_text_length=value,
        )

        assert "Resulting text length:" in prompt
        assert phrase in prompt


def test_custom_prompt_default_length_adds_no_requirement():
    prompt = PromptBuilder().build_custom(
        "Improve this.",
        CapturedSelection("Draft.", 1, "Editor"),
        resulting_text_length="default",
    )

    assert "Resulting text length:" not in prompt


def test_writing_block_option_requests_only_the_finished_result_in_block():
    prompt = PromptBuilder().build_custom(
        "Draft a reply.",
        CapturedSelection("Can you attend?", 1, "Mail"),
        writing_block_enabled=True,
    )

    assert "Output presentation:" in prompt
    assert "single editable writing block" in prompt
    assert "add no commentary outside it" in prompt
    assert "use the writing block only for the final result" in prompt


def test_resulting_text_formatting_options_add_prompt_requirements():
    selection = CapturedSelection("Draft.", 1, "Editor")
    builder = PromptBuilder()

    plain = builder.build_custom(
        "Improve this.",
        selection,
        resulting_text_formatting="plain",
    )
    formatted = builder.build_custom(
        "Improve this.",
        selection,
        resulting_text_formatting="formatted",
    )

    assert "Resulting text formatting:" in plain
    assert "Do not add new Markdown" in plain
    assert "Resulting text formatting:" in formatted
    assert "Use restrained Markdown formatting" in formatted


def test_title_or_subject_modes_request_a_separate_suggestion():
    selection = CapturedSelection("A useful and durable product.", 1, "Review")
    builder = PromptBuilder()

    unchanged = builder.build_custom("Improve this review.", selection)
    automatic = builder.build_custom(
        "Improve this review.",
        selection,
        title_subject="automatic",
    )
    title = builder.build_custom(
        "Improve this review.",
        selection,
        title_subject="title",
    )
    subject = builder.build_custom(
        "Draft an email.",
        selection,
        title_subject="subject",
    )

    assert "Title or subject:" not in unchanged
    assert "choosing whichever label best fits" in automatic
    assert "'Title: ...'" in title
    assert "'Subject: ...'" in subject
    assert "complete main text" in title
    assert "complete main text" in subject


def test_additional_information_is_separated_from_source_text():
    selection = CapturedSelection(
        "I cannot make the proposed date.",
        1,
        "Mail",
    )

    prompt = PromptBuilder().build_custom(
        "Draft a reply.",
        selection,
        additional_information=(
            "Mention that Tuesday afternoon would work instead."
        ),
    )

    assert "User intent and additional context:" in prompt
    assert "<<<USER CONTEXT>>>" in prompt
    assert "Tuesday afternoon would work instead." in prompt
    assert prompt.index("<<<END USER CONTEXT>>>") < prompt.index(
        "<<<SOURCE>>>"
    )
    assert "Do not treat them as source text to edit or quote" in prompt


def test_empty_additional_information_adds_no_prompt_section():
    prompt = PromptBuilder().build_custom(
        "Improve this.",
        CapturedSelection("Draft.", 1, "Editor"),
        additional_information="  ",
    )

    assert "User intent and additional context:" not in prompt
    assert "<<<USER CONTEXT>>>" not in prompt


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("proofread", "make only corrections"),
        ("improve", "improve its clarity"),
        ("rewrite", "freely rephrase and restructure"),
    ],
)
def test_editing_strength_adds_scoped_prompt_guidance(value, expected):
    prompt = PromptBuilder().build_custom(
        "Edit this.",
        CapturedSelection("Draft.", 1, "Editor"),
        editing_strength=value,
    )

    assert "Editing strength:" in prompt
    assert expected in prompt
    assert "When the writing task edits existing text" in prompt


def test_default_editing_strength_adds_no_prompt_guidance():
    prompt = PromptBuilder().build_custom(
        "Edit this.",
        CapturedSelection("Draft.", 1, "Editor"),
    )

    assert "Editing strength:" not in prompt


def test_preserve_facts_and_specifics_can_be_disabled():
    selection = CapturedSelection("The total is £50.", 1, "Editor")
    builder = PromptBuilder()

    protected = builder.build_custom(
        "Improve this.",
        selection,
        preserve_facts=True,
    )
    unprotected = builder.build_custom(
        "Improve this.",
        selection,
        preserve_facts=False,
    )

    assert "Facts and protected specifics:" in protected
    assert "names, dates, amounts, quotations, URLs" in protected
    assert "Facts and protected specifics:" not in unprotected


def test_recipient_or_audience_adds_prompt_guidance():
    prompt = PromptBuilder().build_custom(
        "Draft a reply.",
        CapturedSelection("Please contact us.", 1, "Mail"),
        recipient_audience="company_support",
    )

    assert "Recipient or audience:" in prompt
    assert "Write to a company or support team." in prompt


def test_writing_action_default_audience_is_used_when_not_overridden():
    action = WritingAction(
        "youtube-reply",
        "YouTube reply",
        (),
        "Draft a concise reply.",
        recipient_audience="public_online",
    )

    prompt = PromptBuilder().build(
        action,
        CapturedSelection("Interesting video.", 1, "Browser"),
    )

    assert "Recipient or audience:" in prompt
    assert "Write for a public or online audience." in prompt


def test_request_audience_overrides_writing_action_default():
    action = WritingAction(
        "customer-reply",
        "Customer reply",
        (),
        "Draft a reply.",
        recipient_audience="customer_client",
    )

    prompt = PromptBuilder().build(
        action,
        CapturedSelection("Can you help?", 1, "Message"),
        recipient_audience="colleague_peer",
    )

    assert "Write for a colleague or peer." in prompt
    assert "Write for a customer or client." not in prompt


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("editing strength", {"editing_strength": "heavy"}),
        ("recipient or audience", {"recipient_audience": "strangers"}),
    ],
)
def test_unknown_writing_guidance_is_rejected(keyword, value):
    with pytest.raises(ValueError, match=keyword):
        PromptBuilder().build_custom(
            "Improve this.",
            CapturedSelection("Draft.", 1, "Editor"),
            **value,
        )


def test_three_alternatives_adds_a_machine_readable_output_contract():
    prompt = PromptBuilder().build_custom(
        "Improve this.",
        CapturedSelection("Draft.", 1, "Editor"),
        writing_block_enabled=True,
        alternative_count=3,
    )

    assert "Produce exactly 3 distinct, complete alternatives" in prompt
    assert "<<<PROMPTMELD_ALTERNATIVE_1>>>" in prompt
    assert "<<<END_PROMPTMELD_ALTERNATIVE_3>>>" in prompt
    assert "single editable writing block" not in prompt


def test_invalid_prompt_alternative_count_is_rejected():
    with pytest.raises(ValueError, match="one, two, or three"):
        PromptBuilder().build_custom(
            "Improve this.",
            CapturedSelection("Draft.", 1, "Editor"),
            alternative_count=4,
        )
