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
