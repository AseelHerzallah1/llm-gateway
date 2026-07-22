"""Offline tests for prompt text serialization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embeddings.prompt import messages_to_embed_text
from app.providers.base import ChatMessage


def main() -> None:
    text = messages_to_embed_text(
        [
            ChatMessage(role="user", content="  Hello  "),
            ChatMessage(role="assistant", content="Hi there"),
        ]
    )
    assert text == "user: Hello\nassistant: Hi there"

    print("Prompt serialization OK")


if __name__ == "__main__":
    main()
