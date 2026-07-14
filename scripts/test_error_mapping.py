"""Verify provider error → gateway error mapping (no live API calls)."""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.errors import map_openai_provider_error
from app.providers.exceptions import OpenAIProviderError


def assert_mapping(
    exc: OpenAIProviderError,
    expected_status: int,
    expected_code: str,
) -> None:
    gateway = map_openai_provider_error(exc)
    assert gateway.status_code == expected_status, (
        f"expected status {expected_status}, got {gateway.status_code}"
    )
    assert gateway.body["error"]["code"] == expected_code, (
        f"expected code {expected_code}, got {gateway.body['error']['code']}"
    )


def main() -> None:
    assert_mapping(
        OpenAIProviderError("timed out", is_timeout=True),
        504,
        "gateway_timeout",
    )
    assert_mapping(
        OpenAIProviderError("too many requests", status_code=429),
        429,
        "rate_limit_exceeded",
    )
    assert_mapping(
        OpenAIProviderError("model not found", status_code=400),
        400,
        "invalid_request",
    )
    assert_mapping(
        OpenAIProviderError("invalid key", status_code=401),
        502,
        "provider_error",
    )
    assert_mapping(
        OpenAIProviderError("server error", status_code=503),
        502,
        "provider_error",
    )
    assert_mapping(
        OpenAIProviderError("connection reset"),
        502,
        "provider_error",
    )
    print("Error mapping OK")


if __name__ == "__main__":
    main()
