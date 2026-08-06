from promptmeld.privacy import (
    add_placeholder_instruction,
    detect_sensitive_text,
    redact_sensitive_text,
    restore_placeholders,
)


def test_detects_supported_private_information_with_distinct_placeholders():
    text = (
        "Dear Jane Smith, email jane@example.com or call +44 7700 900123. "
        "Account number: 1234-5678-9012."
    )

    matches = detect_sensitive_text(text)

    assert [(match.kind, match.value, match.placeholder) for match in matches] == [
        ("name", "Jane Smith", "[NAME_1]"),
        ("email", "jane@example.com", "[EMAIL_1]"),
        ("phone", "+44 7700 900123", "[PHONE_1]"),
        ("account", "1234-5678-9012", "[ACCOUNT_1]"),
    ]


def test_repeated_values_share_a_reversible_placeholder():
    text = "Email alex@example.com and copy alex@example.com."
    matches = detect_sensitive_text(text)

    result = redact_sensitive_text(text, matches)

    assert result.text.count("[EMAIL_1]") == 2
    assert result.replacements == {"[EMAIL_1]": "alex@example.com"}
    assert restore_placeholders(result.text, result.replacements) == text


def test_only_explicitly_selected_matches_are_redacted():
    text = "Email jane@example.com or phone 020 7946 0958."
    matches = detect_sensitive_text(text)

    result = redact_sensitive_text(
        text,
        [match for match in matches if match.kind == "email"],
    )

    assert result.text == "Email [EMAIL_1] or phone 020 7946 0958."
    assert result.replacements == {"[EMAIL_1]": "jane@example.com"}


def test_account_label_wins_over_phone_shape_and_supports_is_wording():
    matches = detect_sensitive_text("Account number is 1234567890")

    assert len(matches) == 1
    assert matches[0].kind == "account"
    assert matches[0].value == "1234567890"


def test_unstructured_capitalised_words_are_not_assumed_to_be_names():
    assert detect_sensitive_text(
        "Improve clarity and preserve the original meaning."
    ) == ()


def test_unlabelled_full_name_is_found_inside_prompt_source_block():
    prompt = (
        "Writing task:\nImprove clarity.\n\n"
        "Source text begins below:\n<<<SOURCE>>>\n"
        "John Smith asked for help.\n<<<END SOURCE>>>"
    )

    matches = detect_sensitive_text(prompt)

    assert [(match.kind, match.value) for match in matches] == [
        ("name", "John Smith")
    ]


def test_placeholder_instruction_requests_exact_tokens():
    prompt = add_placeholder_instruction("Rewrite [NAME_1].")

    assert prompt.startswith("Rewrite [NAME_1].")
    assert "Preserve every placeholder exactly" in prompt


def test_generated_placeholder_does_not_collide_with_existing_text():
    text = "Keep [EMAIL_1] and contact jane@example.com."

    matches = detect_sensitive_text(text)

    assert matches[0].placeholder == "[EMAIL_2]"
