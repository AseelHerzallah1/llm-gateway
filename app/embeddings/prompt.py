"""Build canonical prompt text for embedding."""

from __future__ import annotations

from app.providers.base import ChatMessage


def messages_to_embed_text(messages: list[ChatMessage]) -> str:
    """Serialize chat messages into stable text for embedding lookup."""
    return "\n".join(f"{message.role}: {message.content.strip()}" for message in messages)
