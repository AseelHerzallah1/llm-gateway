"""Long provider baseline for Path G — gateway bypass, max_tokens=180."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.observability.cost import estimate_cost_usd
from app.observability.metrics import percentile

GATEWAY = "http://127.0.0.1:8001"
MODEL = "gpt-4o-mini"
MAX_TOKENS = 180
ITERATIONS = 30
BYPASS_HEADER = "X-Gateway-Bypass-Cache"
OUTPUT = ROOT / "docs" / "benchmark_v2_long_provider_validation.json"
FINAL_BENCHMARK = ROOT / "docs" / "benchmark_v2_final_validation.json"

# Same long workload family as G_long_semantic_hit (Path G seed side).
LONG_PROMPT_TEMPLATE = (
    "In about 120-150 words, explain why HTTPS is safer than HTTP. bench-long-prov-{suffix}"
)


@dataclass
class MetricsSnapshot:
    provider_requests: float = 0.0
    cache_operations: dict[str, float] | None = None
    requests_total: dict[str, float] | None = None

    @classmethod
    def from_prometheus(cls, text: str) -> MetricsSnapshot:
        snap = cls(cache_operations={}, requests_total={})

        def counter(name: str, labels: str = "") -> float:
            needle = f"{name}{labels}"
            for line in text.splitlines():
                if line.startswith(needle + " ") or line.startswith(needle + "{"):
                    try:
                        return float(line.split()[-1])
                    except ValueError:
                        return 0.0
            return 0.0

        snap.provider_requests = counter(
            "llmgateway_provider_requests_total", '{provider="openai",status="success"}'
        )
        for result in ("exact_hit", "semantic_hit", "semantic_reject", "store"):
            val = counter("llmgateway_cache_operations_total", f'{{result="{result}"}}')
            if val:
                snap.cache_operations[result] = val
        for cache_result in ("exact_hit", "semantic_hit", "miss", "bypass"):
            val = counter(
                "llmgateway_requests_total",
                f'{{cache_result="{cache_result}",status="success",stream="false"}}',
            )
            if val:
                snap.requests_total[cache_result] = val
        return snap

    def delta(self, other: MetricsSnapshot) -> dict[str, Any]:
        ops = set(self.cache_operations or {}) | set(other.cache_operations or {})
        reqs = set(self.requests_total or {}) | set(other.requests_total or {})
        return {
            "provider_requests": self.provider_requests - other.provider_requests,
            "cache_operations": {
                k: (self.cache_operations or {}).get(k, 0) - (other.cache_operations or {}).get(k, 0)
                for k in ops
            },
            "requests_total": {
                k: (self.requests_total or {}).get(k, 0) - (other.requests_total or {}).get(k, 0)
                for k in reqs
            },
        }


async def fetch_metrics() -> MetricsSnapshot:
    async with httpx.AsyncClient() as client:
        text = (await client.get(f"{GATEWAY}/metrics", timeout=30)).text
    return MetricsSnapshot.from_prometheus(text)


def parse_git_commit() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


async def run_baseline(api_key: str) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:10]
    valid_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []
    attempt = 0

    while len(valid_records) < ITERATIONS and attempt < ITERATIONS * 3:
        attempt += 1
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": LONG_PROMPT_TEMPLATE.format(suffix=f"{run_id}-{suffix}"),
                }
            ],
            "stream": False,
            "max_tokens": MAX_TOKENS,
        }
        before = await fetch_metrics()
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{GATEWAY}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    BYPASS_HEADER: "true",
                },
                json=payload,
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        after = await fetch_metrics()
        delta = after.delta(before)
        data = response.json() if response.status_code == 200 else {}
        usage = data.get("usage") or {}
        inp = int(usage.get("prompt_tokens") or 0)
        out_tok = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or inp + out_tok)
        cid = data.get("id") or ""
        ops = delta.get("cache_operations", {})
        reqs = delta.get("requests_total", {})

        cache_result = "bypass"
        if reqs.get("exact_hit", 0) > 0 or ops.get("exact_hit", 0) > 0:
            cache_result = "exact_hit"
        elif reqs.get("semantic_hit", 0) > 0 or ops.get("semantic_hit", 0) > 0:
            cache_result = "semantic_hit"
        elif reqs.get("bypass", 0) > 0:
            cache_result = "bypass"
        elif cid.startswith("cache-"):
            cache_result = "cache_hit_unknown"

        valid = (
            response.status_code == 200
            and cache_result == "bypass"
            and delta["provider_requests"] >= 1
            and total > 0
            and cid.startswith("chatcmpl-")
            and ops.get("exact_hit", 0) == 0
            and ops.get("semantic_hit", 0) == 0
        )
        rec = {
            "iteration": len(valid_records) + 1 if valid else -1,
            "attempt": attempt,
            "latency_ms": latency_ms,
            "valid": valid,
            "invalid_reason": None
            if valid
            else (
                f"cache_result={cache_result} provider={delta['provider_requests']} "
                f"tokens={total} ops={ops}"
            ),
            "completion_id": cid,
            "input_tokens": inp,
            "output_tokens": out_tok,
            "total_tokens": total,
            "cost_usd": estimate_cost_usd(MODEL, inp, out_tok),
            "cache_result": cache_result,
            "metrics_delta": delta,
        }
        if valid:
            valid_records.append(rec)
        else:
            invalid_records.append(rec)

    lats = [r["latency_ms"] for r in valid_records]
    ordered = sorted(lats)
    total_in = sum(r["input_tokens"] for r in valid_records)
    total_out = sum(r["output_tokens"] for r in valid_records)
    total_cost = sum(r["cost_usd"] for r in valid_records)

    stats = {
        "path": "G_long_provider_bypass_baseline",
        "valid_count": len(valid_records),
        "invalid_count": len(invalid_records),
        "retried_count": len(invalid_records),
        "min_ms": min(lats) if lats else 0,
        "mean_ms": statistics.mean(lats) if lats else 0,
        "p50_ms": float(percentile(ordered, 50)) if lats else 0,
        "p95_ms": float(percentile(ordered, 95)) if lats else 0,
        "p99_ms": float(percentile(ordered, 99)) if lats else 0,
        "max_ms": max(lats) if lats else 0,
        "stdev_ms": statistics.pstdev(lats) if len(lats) > 1 else 0,
        "mean_input_tokens": total_in / len(valid_records) if valid_records else 0,
        "mean_output_tokens": total_out / len(valid_records) if valid_records else 0,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "estimated_cost_usd": round(total_cost, 6),
        "mean_cost_usd": round(total_cost / len(valid_records), 6) if valid_records else 0,
    }

    g_semantic_p50 = 1195.0
    if FINAL_BENCHMARK.exists():
        final = json.loads(FINAL_BENCHMARK.read_text(encoding="utf-8"))
        g_semantic_p50 = final["path_statistics"]["G_long_semantic_hit"]["p50_ms"]

    provider_p50 = stats["p50_ms"]
    latency_saved_ms = provider_p50 - g_semantic_p50
    pct_saved = (latency_saved_ms / provider_p50 * 100) if provider_p50 else None

    comparison = {
        "long_provider_bypass_p50_ms": provider_p50,
        "long_verified_semantic_hit_p50_ms": g_semantic_p50,
        "latency_saved_by_semantic_hit_ms": latency_saved_ms,
        "latency_saved_pct": pct_saved,
        "provider_calls_avoided_per_semantic_hit": 1,
        "estimated_cost_saved_per_hit_usd": round(stats["mean_cost_usd"], 6),
        "estimated_cost_saved_30_hits_usd": round(stats["mean_cost_usd"] * 30, 6),
    }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": parse_git_commit(),
        "methodology": (
            "Gateway bypass baseline for Path G long workload: max_tokens=180, "
            "120-150 word HTTPS prompt, unique suffix per request, no cache reuse"
        ),
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "iterations_target": ITERATIONS,
        "run_id": run_id,
        "reference_artifact": str(FINAL_BENCHMARK.relative_to(ROOT)),
        "path_statistics": stats,
        "comparative_metrics": comparison,
        "raw_iterations": valid_records,
        "invalid_iterations": invalid_records,
    }


async def main() -> None:
    api_key = settings.gateway_test_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("GATEWAY_TEST_API_KEY required")

    report = await run_baseline(api_key)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"statistics": report["path_statistics"], "comparison": report["comparative_metrics"]}, indent=2))
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
