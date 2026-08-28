"""Versioned deterministic request fingerprints for L1 exact cache lookup."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.providers.base import ChatMessage

FINGERPRINT_VERSION = 1


def _normalize_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [
        {"role": message.role.strip().lower(), "content": message.content.strip()}
        for message in messages
    ]


def pii_values_hash(token_map: dict[str, str]) -> str | None:
    """Hash redaction token values so distinct PII does not share an exact identity."""
    if not token_map:
        return None
    canonical = json.dumps(sorted(token_map.items()), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_fingerprint_payload(
    *,
    model: str,
    messages: list[ChatMessage],
    temperature: float | None,
    max_tokens: int | None,
    token_map: dict[str, str],
) -> dict[str, Any]:
    return {
        "v": FINGERPRINT_VERSION,
        "model": model,
        "messages": _normalize_messages(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "pii_values_hash": pii_values_hash(token_map),
    }


def compute_fingerprint(
    *,
    model: str,
    messages: list[ChatMessage],
    temperature: float | None,
    max_tokens: int | None,
    token_map: dict[str, str] | None = None,
) -> str:
    payload = build_fingerprint_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        token_map=token_map or {},
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def messages_to_verifier_text(messages: list[ChatMessage]) -> str:
    """Serialize messages for verifier input (matches embedding line format)."""
    return "\n".join(f"{message.role}: {message.content.strip()}" for message in messages)
