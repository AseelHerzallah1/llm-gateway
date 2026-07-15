"""Verify provider timeout and hang handling (offline + connect timeout).

Usage:
    python scripts/test_provider_timeouts.py

No running gateway or valid OpenAI key required.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.errors import map_openai_provider_error
from app.providers.base import ChatMessage, CompletionRequest
from app.providers.exceptions import OpenAIProviderError
from app.providers.openai import OpenAIProvider


def test_timeout_maps_to_504() -> None:
    gateway = map_openai_provider_error(
        OpenAIProviderError("OpenAI stream idle for 30s", is_timeout=True)
    )
    assert gateway.status_code == 504, gateway.status_code
    assert gateway.body["error"]["code"] == "gateway_timeout"


async def test_connect_timeout() -> None:
    """Unreachable host with a short connect timeout should raise is_timeout."""
    provider = OpenAIProvider(
        api_key="sk-test",
        base_url="http://10.255.255.1:81/v1",
        connect_timeout=0.5,
        read_timeout=1.0,
        stream_idle_timeout=1.0,
        write_timeout=0.5,
        pool_timeout=0.5,
    )
    request = CompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=5,
    )

    try:
        try:
            await provider.complete(request)
        except OpenAIProviderError as exc:
            if not exc.is_timeout:
                raise AssertionError(f"expected timeout, got: {exc}") from exc
        else:
            raise AssertionError("expected OpenAIProviderError timeout")
    finally:
        await provider.aclose()


def main() -> None:
    test_timeout_maps_to_504()
    asyncio.run(test_connect_timeout())
    print("Provider timeout handling OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Test failed: {exc}", file=sys.stderr)
        sys.exit(1)
