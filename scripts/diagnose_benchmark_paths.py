"""Targeted diagnosis for v0.2 benchmark path D/E failures (no heavy rerun)."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth.dependencies import resolve_project
from app.cache.fingerprint import build_fingerprint_payload, compute_fingerprint
from app.cache.persistence import clear_project_benchmark_state
from app.config import settings
from app.db.session import async_session_factory
from app.providers.base import ChatMessage

GATEWAY = "http://127.0.0.1:8001"
MODEL = "gpt-4o-mini"
RUN_ID = "diag"


def _fp(payload: dict) -> tuple[str, dict]:
    msgs = [ChatMessage(role=m["role"], content=m["content"]) for m in payload["messages"]]
    canonical = build_fingerprint_payload(
        model=payload["model"],
        messages=msgs,
        temperature=payload.get("temperature"),
        max_tokens=payload.get("max_tokens"),
        token_map={},
    )
    return compute_fingerprint(
        model=payload["model"],
        messages=msgs,
        temperature=payload.get("temperature"),
        max_tokens=payload.get("max_tokens"),
        token_map={},
    ), canonical


async def fetch_metrics() -> dict[str, float]:
    async with httpx.AsyncClient() as client:
        text = (await client.get(f"{GATEWAY}/metrics", timeout=30)).text
    ops = {}
    for result in ("exact_hit", "semantic_hit", "semantic_reject", "store", "semantic_miss"):
        needle = f'llmgateway_cache_operations_total{{result="{result}"}}'
        for line in text.splitlines():
            if line.startswith(needle):
                ops[result] = float(line.split()[-1])
    return ops


async def gateway_post(api_key: str, payload: dict) -> tuple[httpx.Response, dict[str, float]]:
    before = await fetch_metrics()
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{GATEWAY}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    after = await fetch_metrics()
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in set(before) | set(after)}
    return resp, delta


async def diagnose_path_d(api_key: str, project_id) -> dict:
    """Reproduce Path D: two attempts without isolation — second should fail exact."""
    results = []
    for attempt in (1, 2):
        suffix = uuid.uuid4().hex[:8]
        prompt = f"Reply HELLO exactly. bench-d-{RUN_ID}-{suffix}"
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 5,
        }
        seed_fp, seed_canonical = _fp(payload)
        seed_resp, seed_delta = await gateway_post(api_key, payload)
        seed_data = seed_resp.json()
        repeat_resp, repeat_delta = await gateway_post(api_key, payload)
        repeat_data = repeat_resp.json()
        repeat_fp, _ = _fp(payload)
        results.append(
            {
                "attempt": attempt,
                "suffix": suffix,
                "seed_fingerprint": seed_fp,
                "repeat_fingerprint": repeat_fp,
                "fingerprints_match": seed_fp == repeat_fp,
                "seed_canonical": seed_canonical,
                "seed_cache_ops": seed_delta,
                "seed_completion_prefix": (seed_data.get("id") or "")[:12],
                "repeat_cache_ops": repeat_delta,
                "repeat_completion_prefix": (repeat_data.get("id") or "")[:12],
                "seed_stored": seed_delta.get("store", 0) > 0,
                "repeat_exact": repeat_delta.get("exact_hit", 0) > 0,
                "repeat_semantic": repeat_delta.get("semantic_hit", 0) > 0,
            }
        )
    return {"path_d": results, "project_id": str(project_id)}


async def diagnose_path_e_pair(api_key: str, base_a: str, base_b: str) -> dict:
    suffix = uuid.uuid4().hex[:8]
    text_a = f"{base_a} [bench-E-{RUN_ID}-{suffix}]"
    text_b = f"{base_b} [bench-E-{RUN_ID}-{suffix}]"
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
    hit_resp, hit_delta = await gateway_post(api_key, hit)
    return {
        "base_a": base_a,
        "base_b": base_b,
        "sent_a": text_a,
        "sent_b": text_b,
        "suffix": suffix,
        "seed_ops": seed_delta,
        "hit_ops": hit_delta,
        "hit_id_prefix": (hit_resp.json().get("id") or "")[:12],
        "semantic_hit": hit_delta.get("semantic_hit", 0) > 0,
        "semantic_reject": hit_delta.get("semantic_reject", 0) > 0,
        "provider_on_hit": hit_delta.get("store", 0) > 0 or hit_delta.get("semantic_reject", 0) > 0,
    }


async def main() -> None:
    api_key = settings.gateway_test_api_key.get_secret_value()
    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
    project_id = project.id

    await clear_project_benchmark_state(project_id)
    print("Cleared DB state; restart app manually if memory must be empty.")
    print("(Path D attempt 1 needs empty semantic cache — restart docker if prior entries exist)\n")

    d = await diagnose_path_d(api_key, project_id)
    print("=== Path D diagnosis ===")
    print(json.dumps(d, indent=2))

    await clear_project_benchmark_state(project_id)
    pairs = [
        ("Why is HTTPS safer than HTTP?", "What makes HTTPS more secure than HTTP?"),
        ("How does WiFi work?", "Explain how wireless networking works."),
    ]
    e_results = []
    for a, b in pairs:
        e_results.append(await diagnose_path_e_pair(api_key, a, b))
    print("\n=== Path E sample pairs (no restart between) ===")
    print(json.dumps(e_results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
