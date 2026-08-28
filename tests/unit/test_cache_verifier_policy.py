"""Regression tests for hardened verifier decision policy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.cache.verifier import (
    SYSTEM_PROMPT,
    AnswerEquivalenceVerifier,
    parse_verifier_output,
)
from tests.helpers import skip_unless_live_openai_key

# Broad provider-style answer: covers authentication AND authorization incidentally.
BROAD_OAUTH_AUTHENTICATION_RESPONSE = (
    "OAuth (Open Authorization) is widely used on the internet. "
    "Authentication confirms who a user is — typically via login, tokens, or identity "
    "providers. Authorization determines what an authenticated user is allowed to access — "
    "scopes, permissions, and consent govern which resources a client may use. "
    "In OAuth 2.0 flows, authentication often precedes authorization: the user signs in, "
    "then grants authorization for specific scopes. "
    "Access tokens represent delegated authorization; refresh tokens can obtain new access "
    "tokens. Common flows include authorization code, client credentials, and implicit "
    "(legacy). Both authentication and authorization are central to OAuth's security model."
)

BROAD_APPEND_RESPONSE = (
    "In Python, list.append(x) adds a single element to the end of a list in place. "
    "list.extend(iterable) adds each element from an iterable — useful when merging lists. "
    "append returns None; extend also returns None. Both mutate the original list."
)

BROAD_SORT_RESPONSE = (
    "To sort a Python list in place, use list.sort() or sorted(list) for a new list. "
    "To reverse order, use list.reverse() or list[::-1]. sort orders elements; "
    "reverse flips the current sequence without comparing elements."
)

BROAD_TYPE1_DIABETES_RESPONSE = (
    "Type 1 diabetes is an autoimmune condition where the pancreas produces little or no "
    "insulin. Type 2 diabetes involves insulin resistance and often develops later in life. "
    "Type 1 symptoms can include excessive thirst and weight loss; Type 2 may present with "
    "fatigue and blurred vision. Management differs between the two types."
)


@pytest.mark.unit
def test_system_prompt_requires_primary_intent_match() -> None:
    assert "PRIMARY user intent" in SYSTEM_PROMPT
    assert "Incidental coverage is NOT sufficient" in SYSTEM_PROMPT
    assert "authentication vs authorization" in SYSTEM_PROMPT
    assert "When uncertain, return false" in SYSTEM_PROMPT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verifier_request_uses_hardened_system_prompt() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "false"}}],
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    verifier = AnswerEquivalenceVerifier(mock_client, "gpt-4o-mini")
    result = await verifier.should_reuse(
        cached_request="How does OAuth authentication work?",
        cached_response=BROAD_OAUTH_AUTHENTICATION_RESPONSE,
        new_request="How does OAuth authorization work?",
    )

    assert result is False
    call_kwargs = mock_client.post.call_args.kwargs
    messages = call_kwargs["json"]["messages"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert BROAD_OAUTH_AUTHENTICATION_RESPONSE in messages[1]["content"]
    assert "How does OAuth authorization work?" in messages[1]["content"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cached_request", "new_request", "cached_response"),
    [
        (
            "How does OAuth authentication work?",
            "How does OAuth authorization work?",
            BROAD_OAUTH_AUTHENTICATION_RESPONSE,
        ),
        (
            "What does list.append do in Python?",
            "What does list.extend do in Python?",
            BROAD_APPEND_RESPONSE,
        ),
        (
            "How do I sort a Python list?",
            "How do I reverse a Python list?",
            BROAD_SORT_RESPONSE,
        ),
        (
            "What are symptoms of type 1 diabetes?",
            "What are symptoms of type 2 diabetes?",
            BROAD_TYPE1_DIABETES_RESPONSE,
        ),
    ],
)
@pytest.mark.asyncio
async def test_broad_cached_responses_rejected_by_live_verifier(
    cached_request: str,
    new_request: str,
    cached_response: str,
) -> None:
    skip_unless_live_openai_key()

    from app.cache.verifier import create_verifier_client

    client = create_verifier_client()
    try:
        verifier = AnswerEquivalenceVerifier(client, "gpt-4o-mini")
        result = await verifier.should_reuse(
            cached_request=cached_request,
            cached_response=cached_response,
            new_request=new_request,
        )
    finally:
        await client.aclose()

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_https_paraphrase_still_accepted_by_live_verifier() -> None:
    skip_unless_live_openai_key()

    from app.cache.verifier import create_verifier_client

    cached_response = (
        "HTTPS encrypts traffic between browser and server using TLS, preventing "
        "eavesdropping and tampering. HTTP sends data in plain text."
    )
    client = create_verifier_client()
    try:
        verifier = AnswerEquivalenceVerifier(client, "gpt-4o-mini")
        result = await verifier.should_reuse(
            cached_request="Why is HTTPS safer than HTTP?",
            cached_response=cached_response,
            new_request="What makes HTTPS more secure than HTTP?",
        )
    finally:
        await client.aclose()

    assert result is True
    assert parse_verifier_output("true") is True
