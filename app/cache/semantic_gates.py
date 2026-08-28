"""Deterministic gates that skip L2 semantic reuse before embedding."""

from __future__ import annotations

import re

from app.providers.base import ChatMessage

_TIME_SENSITIVE_RE = re.compile(
    r"\b(latest|today|current|right now|this week|this month|as of now|202[0-9])\b",
    re.IGNORECASE,
)


def has_detected_pii(token_map: dict[str, str], *, pii_redaction_enabled: bool) -> bool:
    return bool(pii_redaction_enabled and token_map)


def is_multi_turn(messages: list[ChatMessage]) -> bool:
    """Multi-turn or assistant history is unsupported for L2 in v0.2."""
    if len(messages) != 1:
        return True
    return any(message.role.strip().lower() == "assistant" for message in messages)


def is_time_sensitive(messages: list[ChatMessage]) -> bool:
    for message in messages:
        if _TIME_SENSITIVE_RE.search(message.content):
            return True
    return False


def semantic_reuse_allowed(
    messages: list[ChatMessage],
    *,
    pii_redaction_enabled: bool,
    token_map: dict[str, str],
) -> bool:
    if has_detected_pii(token_map, pii_redaction_enabled=pii_redaction_enabled):
        return False
    if is_multi_turn(messages):
        return False
    if is_time_sensitive(messages):
        return False
    return True
