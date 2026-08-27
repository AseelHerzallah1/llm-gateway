"""Semantic stability check before final benchmark — captures WiFi reject details."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth.dependencies import resolve_project
from app.cache.fingerprint import compute_fingerprint, messages_to_verifier_text
from app.cache.persistence import clear_project_benchmark_state
from app.cache.similarity import cosine_similarity
from app.cache.verifier import AnswerEquivalenceVerifier, create_verifier_client, parse_verifier_output
from app.config import settings
from app.db.models.cache_entry import CacheEntryRecord
from app.db.session import async_session_factory
from app.embeddings.openai import create_openai_embedding_provider
from app.embeddings.prompt import messages_to_embed_text
from app.providers.base import ChatMessage

GATEWAY = "http://127.0.0.1:8001"
MODEL = "gpt-4o-mini"
RUN = "stability"

ROBUST_SHORT_PAIRS = [
    ("Why is HTTPS safer than HTTP?", "What makes HTTPS more secure than HTTP?"),
    ("What is the capital of France?", "Which city serves as France's capital?"),
    ("Explain what a Python decorator does.", "What is the purpose of decorators in Python?"),
]

LONG_PAIR = (
    "In about 120-150 words, explain why HTTPS is safer than HTTP.",
    "In roughly 120-150 words, explain what makes HTTPS more secure than HTTP.",
)

WIFI_PAIR = (
    "How does WiFi work?",
    "Explain how wireless internet connectivity works.",
)

DANGEROUS_PAIRS = [
    ("How does OAuth authentication work?", "How does OAuth authorization work?"),
    ("What does list.append do in Python?", "What does list.extend do in Python?"),
    ("How do I sort a Python list?", "How do I reverse a Python list?"),
    ("What are symptoms of type 1 diabetes?", "What are symptoms of type 2 diabetes?"),
]


async def restart_and_clear(api_key: str) -> uuid.UUID:
    import subprocess

    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
    await clear_project_benchmark_state(project.id)
    subprocess.run(["docker", "compose", "restart", "app"], cwd=ROOT, check=True, capture_output=True)
    async with httpx.AsyncClient() as client:
        for _ in range(60):
            try:
                if (await client.get(f"{GATEWAY}/health", timeout=5)).status_code == 200:
                    return project.id
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise RuntimeError("gateway unhealthy")


async def fetch_metrics() -> str:
    async with httpx.AsyncClient() as client:
        return (await client.get(f"{GATEWAY}/metrics", timeout=30)).text


def metric_delta(before: str, after: str, key: str) -> float:
    needle = f'llmgateway_cache_operations_total{{result="{key}"}}'

    def read(text: str) -> float:
        for line in text.splitlines():
            if line.startswith(needle):
                return float(line.split()[-1])
        return 0.0

    return read(after) - read(before)


async def gateway_post(api_key: str, payload: dict) -> tuple[httpx.Response, dict[str, float]]:
    before = await fetch_metrics()
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{GATEWAY}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    after = await fetch_metrics()
    delta = {
        k: metric_delta(before, after, k)
        for k in ("exact_hit", "semantic_hit", "semantic_reject", "semantic_miss", "store")
    }
    prov_needle = 'llmgateway_provider_requests_total{provider="openai",status="success"}'

    def prov(text: str) -> float:
        for line in text.splitlines():
            if line.startswith(prov_needle):
                return float(line.split()[-1])
        return 0.0

    delta["provider"] = prov(after) - prov(before)
    return resp, delta


async def latest_cache_entry(project_id: uuid.UUID) -> CacheEntryRecord | None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(CacheEntryRecord)
            .where(CacheEntryRecord.project_id == project_id)
            .order_by(CacheEntryRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def inspect_wifi_reject(api_key: str, max_cycles: int = 5) -> dict | None:
    embedder = create_openai_embedding_provider()
    verifier = AnswerEquivalenceVerifier(create_verifier_client(), settings.cache_verifier_model)
    base_a, base_b = WIFI_PAIR

    try:
        for cycle in range(max_cycles):
            project_id = await restart_and_clear(api_key)
            suffix = uuid.uuid4().hex[:8]
            text_a = f"{base_a} [inspect-{RUN}-{suffix}]"
            text_b = f"{base_b} [inspect-{RUN}-{suffix}]"
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
            seed_resp, seed_delta = await gateway_post(api_key, seed)
            seed_data = seed_resp.json()
            hit_resp, hit_delta = await gateway_post(api_key, hit)
            hit_data = hit_resp.json()

            if hit_delta.get("semantic_reject", 0) < 1:
                continue

            record = await latest_cache_entry(project_id)
            if record is None:
                continue

            cached_response = record.cached_response
            cached_msgs = tuple(
                ChatMessage(role=m["role"], content=m["content"]) for m in (record.request_messages or [])
            )
            new_msgs = [ChatMessage(role="user", content=text_b)]
            embed_a = await embedder.embed(messages_to_embed_text(list(cached_msgs)))
            embed_b = await embedder.embed(messages_to_embed_text(new_msgs))
            similarity = cosine_similarity(embed_a, embed_b)

            cached_request_text = messages_to_verifier_text(list(cached_msgs))
            new_request_text = messages_to_verifier_text(new_msgs)
            reuse = await verifier.should_reuse(
                cached_request=cached_request_text,
                cached_response=cached_response,
                new_request=new_request_text,
            )

            return {
                "cycle": cycle + 1,
                "prompt_a": text_a,
                "prompt_b": text_b,
                "cached_response_a": cached_response,
                "similarity": round(similarity, 4),
                "verifier_result": reuse,
                "verifier_normalized": reuse,
                "seed_id": seed_data.get("id"),
                "hit_id": hit_data.get("id"),
                "hit_ops": hit_delta,
                "seed_response_preview": (seed_data.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")[:200],
            }
    finally:
        await embedder.aclose()
        await verifier._client.aclose()

    return None


async def run_semantic_cycle(
    api_key: str,
    base_a: str,
    base_b: str,
    *,
    max_tokens: int = 64,
    tag: str,
) -> tuple[bool, dict]:
    project_id = await restart_and_clear(api_key)
    suffix = uuid.uuid4().hex[:8]
    text_a = f"{base_a} [{tag}-{RUN}-{suffix}]"
    text_b = f"{base_b} [{tag}-{RUN}-{suffix}]"
    seed = {
        "model": MODEL,
        "messages": [{"role": "user", "content": text_a}],
        "stream": False,
        "max_tokens": max_tokens,
    }
    hit = {
        "model": MODEL,
        "messages": [{"role": "user", "content": text_b}],
        "stream": False,
        "max_tokens": max_tokens,
    }
    await gateway_post(api_key, seed)
    hit_resp, hit_delta = await gateway_post(api_key, hit)
    hit_data = hit_resp.json() if hit_resp.status_code == 200 else {}
    passed = (
        hit_delta.get("semantic_hit", 0) >= 1
        and hit_delta.get("provider", 0) == 0
        and (hit_data.get("id") or "").startswith("cache-")
    )
    return passed, {
        "pair": (base_a, base_b),
        "ops": hit_delta,
        "id": hit_data.get("id"),
        "project_id": str(project_id),
    }


async def run_dangerous_cycle(api_key: str, base_a: str, base_b: str) -> tuple[bool, dict]:
    await restart_and_clear(api_key)
    suffix = uuid.uuid4().hex[:8]
    text_a = f"{base_a} [neg-{RUN}-{suffix}]"
    text_b = f"{base_b} [neg-{RUN}-{suffix}]"
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
    await gateway_post(api_key, seed)
    hit_resp, hit_delta = await gateway_post(api_key, hit)
    hit_data = hit_resp.json() if hit_resp.status_code == 200 else {}
    passed = (
        hit_delta.get("semantic_reject", 0) >= 1
        and hit_delta.get("semantic_hit", 0) == 0
        and hit_delta.get("provider", 0) >= 1
        and (hit_data.get("id") or "").startswith("chatcmpl-")
    )
    return passed, {"pair": (base_a, base_b), "ops": hit_delta, "id": hit_data.get("id")}


async def main() -> None:
    api_key = settings.gateway_test_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("GATEWAY_TEST_API_KEY required")

    report: dict = {}

    print("=== 1. Inspect WiFi reject ===")
    wifi_detail = await inspect_wifi_reject(api_key)
    report["wifi_inspection"] = wifi_detail
    if wifi_detail:
        print(json.dumps(wifi_detail, indent=2))
    else:
        print("No WiFi reject captured in 5 cycles — checking cycle-2 from prior run pattern")
        # force one more isolated attempt
        wifi_detail = await inspect_wifi_reject(api_key, max_cycles=8)
        report["wifi_inspection"] = wifi_detail
        if wifi_detail:
            print(json.dumps(wifi_detail, indent=2))

    print("\n=== 2. Short stability (5 cycles, rotate robust pairs) ===")
    short_results = []
    short_abort = False
    for i in range(5):
        base_a, base_b = ROBUST_SHORT_PAIRS[i % len(ROBUST_SHORT_PAIRS)]
        ok, detail = await run_semantic_cycle(api_key, base_a, base_b, max_tokens=64, tag=f"short{i+1}")
        short_results.append({"cycle": i + 1, "passed": ok, **detail})
        print(f"  short cycle {i+1} ({base_a[:28]}...): {'PASS' if ok else 'FAIL'} ops={detail['ops']}")
        if not ok:
            short_abort = True
            break
    report["short_5"] = short_results

    print("\n=== 3. Long stability (5 cycles) ===")
    long_results = []
    long_abort = False
    if short_abort:
        print("  skipped due to short failure")
    else:
        for i in range(5):
            ok, detail = await run_semantic_cycle(
                api_key, LONG_PAIR[0], LONG_PAIR[1], max_tokens=180, tag=f"long{i+1}"
            )
            long_results.append({"cycle": i + 1, "passed": ok, **detail})
            print(f"  long cycle {i+1}: {'PASS' if ok else 'FAIL'} ops={detail['ops']}")
            if not ok:
                long_abort = True
                break
    report["long_5"] = long_results

    print("\n=== 4. Dangerous (4 cycles) ===")
    neg_results = []
    neg_abort = short_abort or long_abort
    if neg_abort:
        print("  skipped due to prior failure")
    else:
        for base_a, base_b in DANGEROUS_PAIRS:
            ok, detail = await run_dangerous_cycle(api_key, base_a, base_b)
            neg_results.append({"passed": ok, **detail})
            print(f"  {base_a[:30]}...: {'PASS' if ok else 'FAIL'} ops={detail['ops']}")
            if not ok:
                neg_abort = True
                break
    report["dangerous_4"] = neg_results

    short_ok = len(report.get("short_5", [])) == 5 and all(r["passed"] for r in report["short_5"])
    long_ok = len(report.get("long_5", [])) == 5 and all(r["passed"] for r in report["long_5"])
    neg_ok = len(report.get("dangerous_4", [])) == 4 and all(r["passed"] for r in report["dangerous_4"])
    report["ready"] = short_ok and long_ok and neg_ok

    out = ROOT / "docs" / "semantic_stability_check.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    print(f"READY={report['ready']}")


if __name__ == "__main__":
    asyncio.run(main())
