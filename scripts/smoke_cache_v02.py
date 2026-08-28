"""Focused v0.2 cache smoke test — exact, verified semantic, dangerous reject.

Uses deterministic provider/embeddings/verifier (no external LLM API calls).
Run: python scripts/smoke_cache_v02.py
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import bcrypt
from httpx import ASGITransport, AsyncClient

from app.auth.api_keys import generate_api_key, prepare_stored_api_key
from app.auth.dependencies import get_current_project
from app.cache.fingerprint import FINGERPRINT_VERSION, compute_fingerprint, pii_values_hash
from app.cache.memory import GatewayCache
from app.cache.types import new_cache_entry
from app.config import settings
from app.db.models.project import Project
from app.db.models.user import User
from app.db.session import async_session_factory
from app.main import app
from app.providers.base import ChatMessage
from tests.fakes.embeddings import _CLUSTER_VECTORS, _cluster_for_text
from tests.fakes.providers import RetryOnlyRouter, SuccessProvider
from tests.fakes.verifier import DeterministicVerifier


def _cluster_vector(prompt: str) -> list[float]:
    return list(_CLUSTER_VECTORS[_cluster_for_text(prompt)])


async def _post(client: AsyncClient, api_key: str, content: str) -> None:
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        },
    )
    response.raise_for_status()


def _seed(cache: GatewayCache, project_id: uuid.UUID, prompt: str, response: str) -> None:
    messages = (ChatMessage(role="user", content=prompt),)
    cache.load_entry(
        new_cache_entry(
            project_id,
            "gpt-4o-mini",
            _cluster_vector(prompt),
            response,
            fingerprint=compute_fingerprint(
                model="gpt-4o-mini",
                messages=list(messages),
                temperature=None,
                max_tokens=None,
                token_map={},
            ),
            fingerprint_version=FINGERPRINT_VERSION,
            request_messages=messages,
            pii_values_hash=pii_values_hash({}),
        )
    )


async def main() -> None:
    api_key = generate_api_key()
    lookup, key_hash = prepare_stored_api_key(api_key)

    async with async_session_factory() as db:
        user = User(
            email=f"smoke-{uuid.uuid4()}@local.dev",
            password_hash=bcrypt.hashpw(b"smoke", bcrypt.gensalt()).decode("utf-8"),
        )
        db.add(user)
        await db.flush()
        project = Project(
            user_id=user.id,
            name="smoke-cache",
            api_key_lookup=lookup,
            api_key_hash=key_hash,
            active=True,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)

    cache = GatewayCache(candidate_threshold=settings.cache_candidate_threshold)
    from tests.fakes.embeddings import DeterministicEmbeddingProvider

    embedding = DeterministicEmbeddingProvider()
    provider = SuccessProvider("openai", content="from-provider")
    verifier = DeterministicVerifier()

    app.state.semantic_cache = cache
    app.state.embedding_provider = embedding
    app.state.cache_verifier = verifier
    app.state.cache_verifier_client = AsyncMock()
    app.state.provider_router = RetryOnlyRouter(provider)

    async def override_project() -> Project:
        return project

    app.dependency_overrides[get_current_project] = override_project

    with patch("app.config.settings.semantic_cache_enabled", True), patch(
        "app.config.settings.request_log_async", False
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            exact_prompt = f"smoke exact {uuid.uuid4().hex[:8]}"
            provider.attempts = 0
            embedding.calls.clear()
            verifier.calls.clear()
            await _post(client, api_key, exact_prompt)
            provider_before = provider.attempts
            embed_before = len(embedding.calls)
            verifier_before = len(verifier.calls)
            await _post(client, api_key, exact_prompt)
            exact_ok = (
                provider.attempts == provider_before
                and len(embedding.calls) == embed_before
                and len(verifier.calls) == verifier_before
            )
            print(
                "exact_hit: provider_delta=0 embed_delta=0 verifier_delta=0 -> "
                f"{'PASS' if exact_ok else 'FAIL'}"
            )

            cache.clear()
            _seed(cache, project.id, "What is the capital of France?", "The capital of France is Paris.")
            provider.attempts = 0
            embedding.calls.clear()
            verifier.calls.clear()
            await _post(client, api_key, "Which city serves as France's capital?")
            semantic_ok = provider.attempts == 0 and len(embedding.calls) == 1 and len(verifier.calls) == 1
            print(
                "semantic_hit: provider_delta=0 embed_delta=1 verifier_delta=1 -> "
                f"{'PASS' if semantic_ok else 'FAIL'}"
            )

            cache.clear()
            _seed(cache, project.id, "How does OAuth authentication work?", "OAuth authentication details.")
            provider.attempts = 0
            embedding.calls.clear()
            verifier.calls.clear()
            await _post(client, api_key, "How does OAuth authorization work?")
            reject_ok = provider.attempts == 1 and len(verifier.calls) == 1
            print(f"dangerous_pair: verifier_reject provider_called -> {'PASS' if reject_ok else 'FAIL'}")

            if not (exact_ok and semantic_ok and reject_ok):
                raise SystemExit(1)

    app.dependency_overrides.clear()


if __name__ == "__main__":
    asyncio.run(main())
