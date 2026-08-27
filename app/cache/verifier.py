"""Answer-equivalence verifier for L2 verified semantic cache."""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the cache reuse safety gate for an LLM API gateway. "
    "This is NOT a semantic similarity or topical overlap task.\n\n"
    "Return true ONLY when ALL are true:\n"
    "1. Request A and Request B share the same PRIMARY user intent and underlying task.\n"
    "2. Any differences are wording, phrasing, or harmless specificity only.\n"
    "3. The cached response directly answers Request B as written, without repurposing "
    "incidental content.\n"
    "4. Request B does not shift to a neighboring concept, operation, subtype, comparison, "
    "direction, or requested task.\n\n"
    "Return false when A and B differ in PRIMARY INTENT — even if the cached response "
    "incidentally mentions information relevant to B. Incidental coverage is NOT sufficient.\n\n"
    "Examples that MUST be false (different primary intent, not paraphrases):\n"
    "- authentication vs authorization\n"
    "- append vs extend (Python lists)\n"
    "- sort vs reverse (Python lists)\n"
    "- Type 1 vs Type 2 diabetes\n\n"
    "When uncertain, return false."
)

USER_TEMPLATE = """ORIGINAL REQUEST (cached):
{request_a}

CACHED RESPONSE (produced for the original request):
{cached_response}

NEW REQUEST:
{request_b}

Answer with exactly one word: true or false"""


def parse_verifier_output(content: str) -> bool | None:
    """Strict parser — only literal true/false accepted."""
    normalized = content.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


class AnswerEquivalenceVerifier:
    """Calls gpt-4o-mini (configurable) for boolean reuse decisions."""

    def __init__(self, client: httpx.AsyncClient, model: str) -> None:
        self._client = client
        self._model = model

    async def should_reuse(
        self,
        *,
        cached_request: str,
        cached_response: str,
        new_request: str,
    ) -> bool | None:
        """Return True/False on valid output, None on failure or malformed output."""
        user_prompt = USER_TEMPLATE.format(
            request_a=cached_request,
            cached_response=cached_response,
            request_b=new_request,
        )
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": settings.cache_verifier_max_tokens,
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Verifier request failed: %s", exc)
            return None

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = parse_verifier_output(content)
        if parsed is None:
            logger.warning("Verifier returned malformed output: %r", content[:80])
        return parsed


def create_verifier_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.openai_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(settings.cache_verifier_timeout_s),
    )
