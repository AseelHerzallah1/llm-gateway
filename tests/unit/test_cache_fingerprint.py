"""Unit tests for L1 exact cache fingerprints."""

from __future__ import annotations

import pytest

from app.cache.fingerprint import compute_fingerprint, pii_values_hash
from app.providers.base import ChatMessage


def _messages(content: str = "Hello") -> list[ChatMessage]:
    return [ChatMessage(role="user", content=content)]


@pytest.mark.unit
def test_identical_requests_share_fingerprint() -> None:
    kwargs = {
        "model": "gpt-4o-mini",
        "messages": _messages("What is the capital of France?"),
        "temperature": 0.7,
        "max_tokens": 128,
        "token_map": {},
    }
    assert compute_fingerprint(**kwargs) == compute_fingerprint(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", 0.2),
        ("max_tokens", 256),
        ("model", "gpt-4o"),
    ],
)
def test_generation_field_changes_fingerprint(field: str, value: object) -> None:
    base = {
        "model": "gpt-4o-mini",
        "messages": _messages(),
        "temperature": 0.7,
        "max_tokens": 128,
        "token_map": {},
    }
    changed = dict(base)
    changed[field] = value
    assert compute_fingerprint(**base) != compute_fingerprint(**changed)


@pytest.mark.unit
def test_system_message_changes_fingerprint() -> None:
    base_kwargs = {
        "model": "gpt-4o-mini",
        "temperature": None,
        "max_tokens": None,
        "token_map": {},
    }
    with_system = [
        ChatMessage(role="system", content="Be concise."),
        ChatMessage(role="user", content="Hello"),
    ]
    without_system = [ChatMessage(role="user", content="Hello")]
    assert compute_fingerprint(messages=with_system, **base_kwargs) != compute_fingerprint(
        messages=without_system, **base_kwargs
    )


@pytest.mark.unit
def test_history_change_changes_fingerprint() -> None:
    base_kwargs = {
        "model": "gpt-4o-mini",
        "temperature": None,
        "max_tokens": None,
        "token_map": {},
    }
    history_a = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="Hello"),
        ChatMessage(role="user", content="Again"),
    ]
    history_b = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="Hello there"),
        ChatMessage(role="user", content="Again"),
    ]
    assert compute_fingerprint(messages=history_a, **base_kwargs) != compute_fingerprint(
        messages=history_b, **base_kwargs
    )


@pytest.mark.unit
def test_different_pii_values_do_not_collide() -> None:
    redacted = "Contact [EMAIL_1] about billing."
    kwargs = {
        "model": "gpt-4o-mini",
        "messages": _messages(redacted),
        "temperature": None,
        "max_tokens": None,
    }
    alice = compute_fingerprint(token_map={"[EMAIL_1]": "alice@example.com"}, **kwargs)
    bob = compute_fingerprint(token_map={"[EMAIL_1]": "bob@example.com"}, **kwargs)
    assert alice != bob
    assert pii_values_hash({"[EMAIL_1]": "alice@example.com"}) != pii_values_hash(
        {"[EMAIL_1]": "bob@example.com"}
    )


@pytest.mark.unit
def test_empty_token_map_has_no_pii_hash() -> None:
    assert pii_values_hash({}) is None
