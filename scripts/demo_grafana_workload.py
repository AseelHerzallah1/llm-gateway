"""Generate a real Grafana-friendly gateway workload for portfolio screenshots."""

from __future__ import annotations

import asyncio
import json
import random
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth.dependencies import resolve_project
from app.cache.persistence import clear_project_benchmark_state
from app.config import settings
from app.db.session import async_session_factory
from sqlalchemy import func, select

GATEWAY = "http://127.0.0.1:8001"
PROMETHEUS = "http://127.0.0.1:9090"
MODEL = "gpt-4o-mini"
BYPASS_HEADER = "X-Gateway-Bypass-Cache"
OUTPUT = ROOT / "docs" / "demo_grafana_workload.json"

SEMANTIC_PAIRS = [
    ("Why is HTTPS safer than HTTP?", "What makes HTTPS more secure than HTTP?"),
    ("What is the capital of France?", "Which city serves as France's capital?"),
    ("Explain what a Python decorator does.", "What is the purpose of decorators in Python?"),
]

DANGEROUS_PAIRS = [
    ("How does OAuth authentication work?", "How does OAuth authorization work?"),
    ("What does list.append do in Python?", "What does list.extend do in Python?"),
    ("How do I sort a Python list?", "How do I reverse a Python list?"),
    ("What are symptoms of type 1 diabetes?", "What are symptoms of type 2 diabetes?"),
]

MISS_PROMPTS = [
    "Explain why the sky appears blue during daytime.",
    "What is photosynthesis in simple terms?",
    "How do vaccines help prevent disease?",
    "Describe the difference between RAM and disk storage.",
    "What causes earthquakes?",
    "How does a combustion engine work?",
    "What is machine learning?",
]


@dataclass
class MetricsSnapshot:
    requests_total: dict[str, float] = field(default_factory=dict)
    cache_operations: dict[str, float] = field(default_factory=dict)
    provider_requests: float = 0.0
    provider_errors: float = 0.0
    request_errors: float = 0.0

    @classmethod
    def from_prometheus_text(cls, text: str) -> MetricsSnapshot:
        snap = cls()

        def counter(line_prefix: str) -> float:
            for line in text.splitlines():
                if line.startswith(line_prefix):
                    try:
                        return float(line.split()[-1])
                    except ValueError:
                        return 0.0
            return 0.0

        for cache_result in ("exact_hit", "semantic_hit", "miss", "bypass", "none"):
            val = counter(
                f'llmgateway_requests_total{{cache_result="{cache_result}",status="success",stream="false"}}'
            )
            if val:
                snap.requests_total[cache_result] = val
        err = 0.0
        for line in text.splitlines():
            if line.startswith('llmgateway_requests_total{') and 'status="error"' in line and 'stream="false"' in line:
                try:
                    err += float(line.split()[-1])
                except ValueError:
                    pass
        snap.request_errors = err

        for result in (
            "exact_hit",
            "semantic_hit",
            "semantic_reject",
            "semantic_miss",
            "store",
        ):
            val = counter(f'llmgateway_cache_operations_total{{result="{result}"}}')
            if val:
                snap.cache_operations[result] = val

        snap.provider_requests = counter(
            'llmgateway_provider_requests_total{provider="openai",status="success"}'
        )
        snap.provider_errors = counter(
            'llmgateway_provider_requests_total{provider="openai",status="error"}'
        )
        return snap

    def delta(self, other: MetricsSnapshot) -> dict[str, Any]:
        req_keys = set(self.requests_total) | set(other.requests_total)
        op_keys = set(self.cache_operations) | set(other.cache_operations)
        return {
            "requests_total": {
                k: self.requests_total.get(k, 0) - other.requests_total.get(k, 0)
                for k in req_keys
            },
            "cache_operations": {
                k: self.cache_operations.get(k, 0) - other.cache_operations.get(k, 0)
                for k in op_keys
            },
            "provider_requests": self.provider_requests - other.provider_requests,
            "provider_errors": self.provider_errors - other.provider_errors,
            "request_errors": self.request_errors - other.request_errors,
        }


async def fetch_gateway_metrics() -> MetricsSnapshot:
    async with httpx.AsyncClient() as client:
        text = (await client.get(f"{GATEWAY}/metrics", timeout=30)).text
    return MetricsSnapshot.from_prometheus_text(text)


async def pause() -> None:
    await asyncio.sleep(random.uniform(1.0, 3.0))


async def wait_for_gateway(timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get(f"{GATEWAY}/health", timeout=5)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise RuntimeError("Gateway not healthy")


def restart_app() -> None:
    subprocess.run(["docker", "compose", "restart", "app"], cwd=ROOT, check=True, capture_output=True)


async def setup_clean(api_key: str) -> uuid.UUID:
    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
    await clear_project_benchmark_state(project.id)
    print(f"Cleared project cache/logs for {project.id}")
    restart_app()
    await wait_for_gateway()
    print("App restarted and healthy")
    return project.id


@dataclass
class RequestOutcome:
    phase: str
    cache_result: str
    completion_id: str
    provider_delta: float
    ops_delta: dict[str, float]
    latency_ms: float


class DemoWorkload:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.outcomes: list[RequestOutcome] = []
        self.safety_stop = False

    async def _post(
        self,
        payload: dict[str, Any],
        *,
        bypass: bool = False,
        phase: str,
    ) -> RequestOutcome:
        before = await fetch_gateway_metrics()
        started = time.perf_counter()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if bypass:
            headers[BYPASS_HEADER] = "true"
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{GATEWAY}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        after = await fetch_gateway_metrics()
        delta = after.delta(before)
        data = resp.json() if resp.status_code == 200 else {}
        cid = data.get("id") or ""
        ops = delta.get("cache_operations", {})
        reqs = delta.get("requests_total", {})

        if bypass:
            cache_result = "bypass"
        elif reqs.get("exact_hit", 0) > 0 or ops.get("exact_hit", 0) > 0:
            cache_result = "exact_hit"
        elif reqs.get("semantic_hit", 0) > 0 or ops.get("semantic_hit", 0) > 0:
            cache_result = "semantic_hit"
        elif ops.get("semantic_reject", 0) > 0:
            cache_result = "miss"
        elif reqs.get("miss", 0) > 0:
            cache_result = "miss"
        elif cid.startswith("cache-"):
            cache_result = "cache_unknown"
        else:
            cache_result = "unknown"

        outcome = RequestOutcome(
            phase=phase,
            cache_result=cache_result,
            completion_id=cid,
            provider_delta=delta.get("provider_requests", 0),
            ops_delta=ops,
            latency_ms=latency_ms,
        )
        self.outcomes.append(outcome)
        print(
            f"  [{phase}] {cache_result} id={cid[:18]} provider+={outcome.provider_delta:.0f} "
            f"ops={ops} {latency_ms:.0f}ms"
        )
        return outcome

    def _payload(self, content: str, *, max_tokens: int = 64) -> dict[str, Any]:
        return {
            "model": MODEL,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "max_tokens": max_tokens,
        }

    async def run_exact(self, repeats: int = 14) -> None:
        print("\n=== Exact cache (L1) ===")
        prompt = "Reply HELLO exactly."
        seed = self._payload(prompt, max_tokens=8)
        await self._post(seed, phase="exact_seed")
        await pause()
        for i in range(repeats):
            await self._post(seed, phase=f"exact_hit_{i+1}")
            await pause()

    async def run_semantic(self, cycles_per_pair: int = 3) -> None:
        print("\n=== Verified semantic cache (L2) ===")
        for pair_idx, (a, b) in enumerate(SEMANTIC_PAIRS):
            for cycle in range(cycles_per_pair):
                await self._post(self._payload(a), phase=f"sem{pair_idx}_seed_{cycle}")
                await pause()
                outcome = await self._post(self._payload(b), phase=f"sem{pair_idx}_hit_{cycle}")
                if outcome.cache_result != "semantic_hit":
                    print(f"WARNING: expected semantic_hit got {outcome.cache_result}")
                await pause()

    async def run_dangerous(self) -> None:
        print("\n=== Semantic rejects (dangerous neighbors) ===")
        for idx, (a, b) in enumerate(DANGEROUS_PAIRS):
            await self._post(self._payload(a), phase=f"dang{idx}_seed")
            await pause()
            outcome = await self._post(self._payload(b), phase=f"dang{idx}_reject")
            if outcome.cache_result == "semantic_hit" or outcome.ops_delta.get("semantic_hit", 0) > 0:
                self.safety_stop = True
                print(f"SAFETY STOP: dangerous pair {idx} became semantic_hit!")
                return
            await pause()

    async def run_misses(self, count: int = 7) -> None:
        print("\n=== Cache misses ===")
        for i, prompt in enumerate(MISS_PROMPTS[:count]):
            await self._post(self._payload(prompt), phase=f"miss_{i}")
            await pause()

    async def run_bypass(self, count: int = 5) -> None:
        print("\n=== Cache bypass ===")
        for i in range(count):
            prompt = f"Say hello in one short word. demo-bypass-{i}"
            await self._post(self._payload(prompt, max_tokens=8), bypass=True, phase=f"bypass_{i}")
            await pause()


async def cross_check_db(api_key: str) -> dict[str, Any]:
    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
        from app.db.models.cache_entry import CacheEntryRecord
        from app.db.models.request import RequestLog

        cache_count = await db.scalar(
            select(func.count()).select_from(CacheEntryRecord).where(CacheEntryRecord.project_id == project.id)
        )
        req_count = await db.scalar(
            select(func.count()).select_from(RequestLog).where(RequestLog.project_id == project.id)
        )
        cache_hits = await db.scalar(
            select(func.count())
            .select_from(RequestLog)
            .where(RequestLog.project_id == project.id, RequestLog.cache_hit.is_(True))
        )
    async with httpx.AsyncClient() as client:
        reqs = await client.get(
            f"{GATEWAY}/v1/requests",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 200},
            timeout=30,
        )
        reqs.raise_for_status()
        req_api = reqs.json()
    return {
        "project_id": str(project.id),
        "cache_entries": cache_count,
        "request_logs": req_count,
        "cache_hit_rows": cache_hits,
        "requests_api_total": req_api.get("total"),
    }


def summarize_outcomes(outcomes: list[RequestOutcome]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.cache_result] = counts.get(o.cache_result, 0) + 1
    return counts


async def main() -> None:
    api_key = settings.gateway_test_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("GATEWAY_TEST_API_KEY required")

    started_at = datetime.now(timezone.utc)
    print("=== Grafana demo workload setup ===")
    await setup_clean(api_key)
    baseline = await fetch_gateway_metrics()
    workload_started = time.time()

    runner = DemoWorkload(api_key)
    await runner.run_exact(repeats=14)
    if not runner.safety_stop:
        await runner.run_semantic(cycles_per_pair=3)
    if not runner.safety_stop:
        await runner.run_dangerous()
    if not runner.safety_stop:
        await runner.run_misses(count=7)
    if not runner.safety_stop:
        await runner.run_bypass(count=5)

    final = await fetch_gateway_metrics()
    delta = final.delta(baseline)
    reqs = delta["requests_total"]
    ops = delta["cache_operations"]
    exact_hit = int(reqs.get("exact_hit", 0))
    semantic_hit = int(reqs.get("semantic_hit", 0))
    miss = int(reqs.get("miss", 0))
    bypass = int(reqs.get("bypass", 0))
    semantic_reject = int(ops.get("semantic_reject", 0))
    total_non_stream = int(sum(reqs.values()))
    errors = int(delta.get("request_errors", 0))
    provider_attempts = int(delta.get("provider_requests", 0))

    cache_hit_rate = (
        100.0 * (exact_hit + semantic_hit) / (exact_hit + semantic_hit + miss)
        if (exact_hit + semantic_hit + miss) > 0
        else 0.0
    )

    report = {
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.time() - workload_started, 1),
        "safety_stop": runner.safety_stop,
        "request_count": len(runner.outcomes),
        "prometheus_delta": delta,
        "summary": {
            "total_requests_non_stream": total_non_stream,
            "exact_hit": exact_hit,
            "semantic_hit": semantic_hit,
            "miss": miss,
            "bypass": bypass,
            "semantic_reject": semantic_reject,
            "provider_attempts": provider_attempts,
            "errors": errors,
            "cache_hit_rate_pct": round(cache_hit_rate, 1),
        },
        "outcome_counts_by_inferred_result": summarize_outcomes(runner.outcomes),
        "cross_check": await cross_check_db(api_key),
        "grafana": {
            "url": "http://127.0.0.1:3000/d/llm-gateway-overview/llm-gateway-overview",
            "recommended_time_range": "Last 15 minutes",
            "screenshot_ready": not runner.safety_stop and exact_hit >= 10 and semantic_hit >= 6,
        },
    }

    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== Workload summary ===")
    print(json.dumps(report["summary"], indent=2))
    print(f"\nWrote {OUTPUT}")

    if runner.safety_stop:
        raise SystemExit("SAFETY STOP — do not screenshot")


if __name__ == "__main__":
    asyncio.run(main())
