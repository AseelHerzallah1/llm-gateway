"""Unit tests for provider error mapping."""

from __future__ import annotations

import pytest

from app.errors import map_openai_provider_error
from app.providers.exceptions import OpenAIProviderError


@pytest.mark.unit
@pytest.mark.parametrize(
    ("provider_error", "expected_status", "expected_code"),
    [
        (OpenAIProviderError("timed out", is_timeout=True), 504, "gateway_timeout"),
        (OpenAIProviderError("too many requests", status_code=429), 429, "rate_limit_exceeded"),
        (OpenAIProviderError("model not found", status_code=400), 400, "invalid_request"),
        (OpenAIProviderError("invalid key", status_code=401), 502, "provider_error"),
        (OpenAIProviderError("server error", status_code=503), 502, "provider_error"),
        (OpenAIProviderError("connection reset"), 502, "provider_error"),
    ],
)
def test_map_openai_provider_error(
    provider_error: OpenAIProviderError,
    expected_status: int,
    expected_code: str,
) -> None:
    gateway = map_openai_provider_error(provider_error)
    assert gateway.status_code == expected_status
    assert gateway.body["error"]["code"] == expected_code
