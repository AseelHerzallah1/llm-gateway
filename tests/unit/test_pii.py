"""Unit tests for PII redaction."""

from __future__ import annotations

import pytest

from app.security.pii import (
    PiiRedactionConfig,
    detokenize_text,
    redact_messages,
    redact_text,
)

VISA_TEST_CARD = "4111 1111 1111 1111"
GB_IBAN = "GB82 WEST 1234 5698 7654 32"
DE_IBAN = "DE89 3704 0044 0532 0130 00"


@pytest.mark.unit
def test_redacts_email() -> None:
    result = redact_text("Contact me at aseel@example.com please")

    assert result.text == "Contact me at [EMAIL_1] please"
    assert result.token_map == {"[EMAIL_1]": "aseel@example.com"}


@pytest.mark.unit
def test_same_email_reuses_token() -> None:
    result = redact_text("Email aseel@example.com or aseel@example.com again")

    assert result.text == "Email [EMAIL_1] or [EMAIL_1] again"
    assert len(result.token_map) == 1


@pytest.mark.unit
def test_redacts_us_phone_formats() -> None:
    cases = [
        ("Call (555) 123-4567 today", "Call [PHONE_1] today"),
        ("Call 555-123-4567 today", "Call [PHONE_1] today"),
        ("Call +1 555 123 4567 today", "Call [PHONE_1] today"),
    ]
    for original, expected in cases:
        result = redact_text(original)
        assert result.text == expected
        assert "[PHONE_1]" in result.token_map


@pytest.mark.unit
def test_email_not_double_matched_as_phone() -> None:
    result = redact_text("Reach user.name+tag@mail.co.uk for help")

    assert "[EMAIL_1]" in result.text
    assert "PHONE" not in result.text
    assert result.token_map["[EMAIL_1]"] == "user.name+tag@mail.co.uk"


@pytest.mark.unit
def test_credit_card_redacted_when_enabled() -> None:
    config = PiiRedactionConfig(redact_credit_card=True)
    result = redact_text(f"Card: {VISA_TEST_CARD}", config=config)

    assert result.text == "Card: [CREDIT_CARD_1]"
    assert result.token_map["[CREDIT_CARD_1]"] == VISA_TEST_CARD


@pytest.mark.unit
def test_credit_card_skipped_when_disabled() -> None:
    result = redact_text(f"Card: {VISA_TEST_CARD}")

    assert VISA_TEST_CARD in result.text
    assert result.token_map == {}


@pytest.mark.unit
def test_invalid_luhn_not_redacted() -> None:
    config = PiiRedactionConfig(redact_credit_card=True)
    result = redact_text("Order id 4111 1111 1111 1112", config=config)

    assert "4111 1111 1111 1112" in result.text
    assert result.token_map == {}


@pytest.mark.unit
def test_redact_messages_shared_token_map() -> None:
    messages = [
        {"role": "user", "content": "My email is aseel@example.com"},
        {"role": "user", "content": "Again: aseel@example.com"},
    ]
    redacted, token_map = redact_messages(messages)

    assert redacted[0]["content"] == "My email is [EMAIL_1]"
    assert redacted[1]["content"] == "Again: [EMAIL_1]"
    assert len(token_map) == 1


@pytest.mark.unit
def test_redact_messages_preserves_role() -> None:
    messages = [{"role": "system", "content": "plain text"}]
    redacted, token_map = redact_messages(messages)

    assert redacted[0]["role"] == "system"
    assert redacted[0]["content"] == "plain text"
    assert token_map == {}


@pytest.mark.unit
def test_selective_redaction_config() -> None:
    text = "Call 555-123-4567 or email help@example.com"
    phone_only = PiiRedactionConfig(redact_email=False, redact_phone=True)
    email_only = PiiRedactionConfig(redact_email=True, redact_phone=False)

    phone_result = redact_text(text, config=phone_only)
    email_result = redact_text(text, config=email_only)

    assert phone_result.text == "Call [PHONE_1] or email help@example.com"
    assert email_result.text == "Call 555-123-4567 or email [EMAIL_1]"


@pytest.mark.unit
def test_mixed_pii_in_one_string() -> None:
    result = redact_text(
        "Phone +44 20 7946 0958 and email team@example.org",
    )

    assert "[PHONE_1]" in result.text
    assert "[EMAIL_1]" in result.text
    assert len(result.token_map) == 2


@pytest.mark.unit
def test_arabic_sentence_with_email() -> None:
    result = redact_text("راسلني على user@example.com من فضلك")

    assert "[EMAIL_1]" in result.text
    assert "user@example.com" not in result.text
    assert result.token_map["[EMAIL_1]"] == "user@example.com"


@pytest.mark.unit
def test_hebrew_sentence_with_israeli_phone() -> None:
    result = redact_text("הטלפון שלי הוא 050-1234567")

    assert "[PHONE_1]" in result.text
    assert "050-1234567" not in result.text
    assert result.token_map["[PHONE_1]"] == "050-1234567"


@pytest.mark.unit
def test_arabic_indic_digit_phone() -> None:
    result = redact_text("اتصل على ٠٥٠-١٢٣٤٥٦٧")

    assert "[PHONE_1]" in result.text
    assert "٠٥٠" not in result.text
    assert result.token_map["[PHONE_1]"] == "٠٥٠-١٢٣٤٥٦٧"


@pytest.mark.unit
def test_israeli_international_phone() -> None:
    result = redact_text("Call +972 50-123-4567 anytime")

    assert result.text == "Call [PHONE_1] anytime"
    assert result.token_map["[PHONE_1]"] == "+972 50-123-4567"


@pytest.mark.unit
def test_detokenize_text() -> None:
    token_map = {"[EMAIL_1]": "help@example.com"}
    restored = detokenize_text("Please write to [EMAIL_1] today.", token_map)

    assert restored == "Please write to help@example.com today."


@pytest.mark.unit
def test_detokenize_credit_card() -> None:
    token_map = {"[CREDIT_CARD_1]": VISA_TEST_CARD}
    restored = detokenize_text(f"Card on file: [CREDIT_CARD_1]", token_map)

    assert restored == f"Card on file: {VISA_TEST_CARD}"


@pytest.mark.unit
def test_iban_redacted_when_enabled() -> None:
    config = PiiRedactionConfig(redact_iban=True)
    result = redact_text(f"Pay to {GB_IBAN}", config=config)

    assert result.text == "Pay to [IBAN_1]"
    assert result.token_map["[IBAN_1]"] == GB_IBAN


@pytest.mark.unit
def test_iban_skipped_when_disabled() -> None:
    result = redact_text(f"Pay to {GB_IBAN}")

    assert GB_IBAN in result.text
    assert result.token_map == {}


@pytest.mark.unit
def test_iban_invalid_checksum_not_redacted() -> None:
    config = PiiRedactionConfig(redact_iban=True)
    invalid = "GB82 WEST 1234 5698 7654 33"
    result = redact_text(f"Pay to {invalid}", config=config)

    assert invalid in result.text
    assert result.token_map == {}


@pytest.mark.unit
def test_iban_normalizes_spaces_and_dashes() -> None:
    config = PiiRedactionConfig(redact_iban=True)
    dashed = "DE89-3704-0044-0532-0130-00"
    result = redact_text(f"Account {dashed}", config=config)

    assert result.text == "Account [IBAN_1]"
    assert result.token_map["[IBAN_1]"] == dashed


@pytest.mark.unit
def test_iban_same_value_reuses_token() -> None:
    config = PiiRedactionConfig(redact_iban=True)
    result = redact_text(f"{GB_IBAN} and {GB_IBAN}", config=config)

    assert result.text == "[IBAN_1] and [IBAN_1]"
    assert len(result.token_map) == 1


@pytest.mark.unit
def test_mixed_email_phone_iban_and_credit_card() -> None:
    config = PiiRedactionConfig(redact_credit_card=True, redact_iban=True)
    text = (
        f"Email help@example.com, phone 555-123-4567, "
        f"card {VISA_TEST_CARD}, iban {DE_IBAN}"
    )
    result = redact_text(text, config=config)

    assert "[EMAIL_1]" in result.text
    assert "[PHONE_1]" in result.text
    assert "[CREDIT_CARD_1]" in result.text
    assert "[IBAN_1]" in result.text
    assert "help@example.com" not in result.text
    assert VISA_TEST_CARD not in result.text
    assert DE_IBAN not in result.text
