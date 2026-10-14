import pytest

from app.security.guards import (
    contains_card_number,
    is_payment_action,
    is_secret_field,
    is_send_action,
    luhn_valid,
)
from app.security.redaction import redact_args, redact_text


def test_luhn():
    assert luhn_valid("4111 1111 1111 1111")
    assert not luhn_valid("4111 1111 1111 1112")
    assert not luhn_valid("1234")


def test_card_numbers_detected_in_text():
    assert contains_card_number("my card is 4111-1111-1111-1111 thanks")
    assert not contains_card_number("call me on 08012345678")


@pytest.mark.parametrize("label", ["Pay now", "Place order", "Buy Now", "Proceed to checkout", "Confirm payment"])
def test_payment_labels(label):
    assert is_payment_action(label)


@pytest.mark.parametrize("label", ["Search", "Next page", "Sign in", "Open settings"])
def test_non_payment_labels(label):
    assert not is_payment_action(label)


def test_send_labels():
    assert is_send_action("Send")
    assert is_send_action("Post comment")
    assert not is_send_action("Search")


@pytest.mark.parametrize("attrs", [
    {"type": "password"},
    {"autocomplete": "cc-number"},
    {"autocomplete": "current-password"},
    {"name": "cvv"},
    {"placeholder": "Card number"},
    {"aria-label": "Enter PIN"},
])
def test_secret_fields(attrs):
    assert is_secret_field(attrs)


@pytest.mark.parametrize("attrs", [{"type": "search", "name": "q"}, {"type": "text", "placeholder": "Your name"},
                                   {"name": "spinner"}])
def test_ordinary_fields(attrs):
    assert not is_secret_field(attrs)


def test_redaction_removes_keys_and_card_numbers():
    text = "key gsk_abcdefghijklmnopqrstuvwxyz123 and AIzaSyA1234567890abcdefghijklmnopqrstuv card 4111111111111111"
    out = redact_text(text)
    assert "gsk_" not in out and "AIza" not in out and "4111111111111111" not in out
    assert redact_text("api_key=supersecret") == "api_key=[redacted]"


def test_redact_args_truncates_long_content():
    out = redact_args({"content": "x" * 500, "title": "ok"})
    assert out["title"] == "ok"
    assert len(out["content"]) < 120
