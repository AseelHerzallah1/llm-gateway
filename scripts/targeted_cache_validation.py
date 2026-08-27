"""Cheap targeted validation before heavy benchmark rerun (section 6)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth.dependencies import resolve_project
from app.cache.persistence import clear_project_benchmark_state
from app.config import settings
from app.db.session import async_session_factory

GATEWAY = "http://127.0.0.1:8001"
MODEL = "gpt-4o-mini"
RUN = "targeted"

SEMANTIC_PAIRS = [
    ("Why is HTTPS safer than HTTP?", "What makes HTTPS more secure than HTTP?"),
    ("What is the capital of France?", "Which city serves as France's capital?"),
    ("Explain what a Python decorator does.", "What is the purpose of decorators in Python?"),
    ("How does WiFi work?", "Explain how wireless internet connectivity works."),
]

DANGEROUS_PAIRS = [
    ("How does OAuth authentication work?", "How does OAuth authorization work?"),
    ("What does list.append do in Python?", "What does list.extend do in Python?"),
    ("How do I sort a Python list?", "How do I reverse a Python list?"),
    ("What are symptoms of type 1 diabetes?", "What are symptoms of type 2 diabetes?"),
]


async def metrics_delta(before: str, after: str) -> dict[str, float]:
    def read(text: str, result: str) -> float:
        needle = f'llmgateway_cache_operations_total{{result="{result}"}}'
        for line in text.splitlines():
            if line.startswith(needle):
                return float(line.split()[-1])
        return 0.0

    keys = (
        "exact_hit",
        "semantic_hit",
        "semantic_reject",
        "semantic_miss",
        "store",
    )
    return {k: read(after, k) - read(before, k) for k in keys}


async def fetch_metrics() -> str:
    async with httpx.AsyncClient() as client:
        return (await client.get(f"{GATEWAY}/metrics", timeout=30)).text


async def post(api_key: str, payload: dict) -> tuple[httpx.Response, dict[str, float], dict[str, float]]:
    before = await fetch_metrics()
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{GATEWAY}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    after = await fetch_metrics()
    provider_before = 0.0
    provider_after = 0.0
    for line in after.splitlines():
        if line.startswith('llmgateway_provider_requests_total{provider="openai",status="success"}'):
            provider_after = float(line.split()[-1])
    for line in before.splitlines():
        if line.startswith('llmgateway_provider_requests_total{provider="openai",status="success"}'):
            provider_before = float(line.split()[-1])
    delta = await metrics_delta(before, after)
    delta["provider"] = provider_after - provider_before
    return resp, delta, resp.json() if resp.status_code == 200 else {}


async def restart_and_clear(api_key: str) -> None:
    import subprocess

    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
    await clear_project_benchmark_state(project.id)
    subprocess.run(
        ["docker", "compose", "restart", "app"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    deadline = asyncio.get_event_loop().time() + 120
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                if (await client.get(f"{GATEWAY}/health", timeout=5)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise RuntimeError("gateway not healthy")


async def validate_exact(api_key: str) -> tuple[int, int]:
    await restart_and_clear(api_key)
    ok = 0
    for i in range(10):
        suffix = uuid.uuid4().hex[:8]
        prompt = f"Reply HELLO exactly. val-exact-{RUN}-{suffix}"
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 5,
        }
        await post(api_key, payload)
        _, delta, data = await post(api_key, payload)
        passed = (
            delta.get("exact_hit", 0) >= 1
            and delta.get("provider", 0) == 0
            and delta.get("semantic_hit", 0) == 0
            and delta.get("semantic_reject", 0) == 0
            and (data.get("usage") or {}).get("total_tokens", -1) == 0
            and (data.get("id") or "").startswith("cache-")
        )
        if passed:
            ok += 1
        else:
            print(f"  exact cycle {i+1} FAIL ops={delta} id={data.get('id')}")
    return ok, 10


async def validate_semantic_positives(api_key: str) -> tuple[int, int]:
    ok = 0
    total = 0
    for base_a, base_b in SEMANTIC_PAIRS:
        for cycle in range(3):
            total += 1
            await restart_and_clear(api_key)
            suffix = uuid.uuid4().hex[:8]
            text_a = f"{base_a} [val-sem-{RUN}-{suffix}]"
            text_b = f"{base_b} [val-sem-{RUN}-{suffix}]"
            seed = {
                "model": MODEL,
                "messages": [{"role": "user", "content": text_a}],
                "stream": False,
                "max_tokens": 64,
            }
            hit = {
                "model": MODEL,
                "messages": [{"role": "user", "content": text_b}],
                "stream": False,
                "max_tokens": 64,
            }
            await post(api_key, seed)
            _, delta, data = await post(api_key, hit)
            passed = (
                delta.get("semantic_hit", 0) >= 1
                and delta.get("provider", 0) == 0
                and (data.get("usage") or {}).get("total_tokens", -1) == 0
                and (data.get("id") or "").startswith("cache-")
            )
            if passed:
                ok += 1
            else:
                print(
                    f"  semantic FAIL pair={base_a[:30]!r} cycle={cycle+1} "
                    f"ops={delta} id={data.get('id')}"
                )
    return ok, total


async def validate_dangerous(api_key: str) -> tuple[int, int]:
    ok = 0
    for base_a, base_b in DANGEROUS_PAIRS:
        await restart_and_clear(api_key)
        suffix = uuid.uuid4().hex[:8]
        text_a = f"{base_a} [val-neg-{RUN}-{suffix}]"
        text_b = f"{base_b} [val-neg-{RUN}-{suffix}]"
        seed = {
            "model": MODEL,
            "messages": [{"role": "user", "content": text_a}],
            "stream": False,
            "max_tokens": 64,
        }
        hit = {
            "model": MODEL,
            "messages": [{"role": "user", "content": text_b}],
            "stream": False,
            "max_tokens": 64,
        }
        await post(api_key, seed)
        _, delta, data = await post(api_key, hit)
        passed = (
            delta.get("semantic_reject", 0) >= 1
            and delta.get("semantic_hit", 0) == 0
            and delta.get("provider", 0) >= 1
            and (data.get("usage") or {}).get("total_tokens", 0) > 0
            and (data.get("id") or "").startswith("chatcmpl-")
        )
        if passed:
            ok += 1
        else:
            print(f"  dangerous FAIL pair={base_a[:30]!r} ops={delta} id={data.get('id')}")
    return ok, len(DANGEROUS_PAIRS)


async def main() -> None:
    api_key = settings.gateway_test_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("GATEWAY_TEST_API_KEY required")

    print("=== Targeted exact (10 cycles, no isolation between cycles) ===")
    exact_ok, exact_total = await validate_exact(api_key)
    print(f"exact: {exact_ok}/{exact_total}")

    print("\n=== Targeted semantic positives (4 pairs x 3 cycles) ===")
    sem_ok, sem_total = await validate_semantic_positives(api_key)
    print(f"semantic: {sem_ok}/{sem_total}")

    print("\n=== Targeted dangerous negatives (4 pairs) ===")
    neg_ok, neg_total = await validate_dangerous(api_key)
    print(f"dangerous: {neg_ok}/{neg_total}")

    all_pass = exact_ok == exact_total and sem_ok == sem_total and neg_ok == neg_total
    print(f"\nREADY_FOR_HEAVY_RERUN={all_pass}")


if __name__ == "__main__":
    asyncio.run(main())
