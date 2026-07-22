"""Offline tests for model → provider routing rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.router import resolve_provider_name


def main() -> None:
    assert resolve_provider_name("gpt-4o-mini") == "openai"
    assert resolve_provider_name("o4-mini") == "openai"
    assert resolve_provider_name("llama-3.3-70b-versatile") == "groq"
    assert resolve_provider_name("mixtral-8x7b-32768") == "groq"
    assert resolve_provider_name("claude-3-5-haiku-20241022") == "anthropic"

    try:
        resolve_provider_name("unknown-model-xyz")
        print("Expected ValueError for unknown model")
        sys.exit(1)
    except ValueError:
        pass

    print("Provider routing rules OK")


if __name__ == "__main__":
    main()
