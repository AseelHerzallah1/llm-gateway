"""Measure gateway proxy overhead vs direct OpenAI calls.

Usage:
    python scripts/benchmark_latency.py
    python scripts/benchmark_latency.py gw-sk-your-key --iterations 10

Requires:
    - Gateway running locally (default http://127.0.0.1:8001)
    - OPENAI_API_KEY in .env
    - GATEWAY_TEST_API_KEY in .env or pass gateway key as first argument

Each iteration uses a unique prompt suffix so semantic cache does not skew results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.observability.metrics import percentile


DEFAULT_GATEWAY_URL = "http://127.0.0.1:8001"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_ITERATIONS = 10
DEFAULT_MAX_TOKENS = 10
BYPASS_CACHE_HEADER = "X-Gateway-Bypass-Cache"


@dataclass(frozen=True)
class BenchmarkSample:
    target: str
    iteration: int
    latency_ms: int
    status_code: int


@dataclass(frozen=True)
class BenchmarkSummary:
    target: str
    samples: int
    p50_ms: int
    p95_ms: int
    p99_ms: int
    errors: int


@dataclass(frozen=True)
class BenchmarkReport:
    model: str
    iterations: int
    gateway_url: str
    direct: BenchmarkSummary
    gateway: BenchmarkSummary
    overhead_p50_ms: int
    overhead_p95_ms: int
    overhead_p50_pct: float


def build_payload(model: str, iteration: int) -> dict:
    """Unique prompt per iteration to avoid semantic cache hits."""
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": f"Reply with one short greeting word. benchmark-{iteration}-{uuid.uuid4().hex[:8]}",
            }
        ],
        "stream": False,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }


async def time_request(
    client: httpx.AsyncClient,
    *,
    target: str,
    url: str,
    headers: dict[str, str],
    payload: dict,
    iteration: int,
) -> BenchmarkSample:
    started = time.perf_counter()
    try:
        response = await client.post(url, json=payload, headers=headers)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return BenchmarkSample(
            target=target,
            iteration=iteration,
            latency_ms=latency_ms,
            status_code=response.status_code,
        )
    except httpx.HTTPError:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return BenchmarkSample(
            target=target,
            iteration=iteration,
            latency_ms=latency_ms,
            status_code=0,
        )


def summarize(target: str, samples: list[BenchmarkSample]) -> BenchmarkSummary:
    latencies = [sample.latency_ms for sample in samples if sample.status_code == 200]
    errors = sum(1 for sample in samples if sample.status_code != 200)
    return BenchmarkSummary(
        target=target,
        samples=len(samples),
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        errors=errors,
    )


def overhead_pct(base_ms: int, total_ms: int) -> float:
    if base_ms <= 0:
        return 0.0
    return round(((total_ms - base_ms) / base_ms) * 100, 2)


async def run_benchmark(
    *,
    gateway_url: str,
    gateway_api_key: str,
    openai_api_key: str,
    model: str,
    iterations: int,
) -> BenchmarkReport:
    direct_url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    gateway_chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"

    direct_headers = {"Authorization": f"Bearer {openai_api_key}"}
    gateway_headers = {
        "Authorization": f"Bearer {gateway_api_key}",
        BYPASS_CACHE_HEADER: "true",
    }

    timeout = httpx.Timeout(settings.openai_read_timeout_s)
    direct_samples: list[BenchmarkSample] = []
    gateway_samples: list[BenchmarkSample] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        warmup_payload = build_payload(model, 0)
        await time_request(
            client,
            target="direct",
            url=direct_url,
            headers=direct_headers,
            payload=warmup_payload,
            iteration=0,
        )
        await time_request(
            client,
            target="gateway",
            url=gateway_chat_url,
            headers=gateway_headers,
            payload=build_payload(model, 0),
            iteration=0,
        )

        for iteration in range(1, iterations + 1):
            payload = build_payload(model, iteration)
            direct_samples.append(
                await time_request(
                    client,
                    target="direct",
                    url=direct_url,
                    headers=direct_headers,
                    payload=payload,
                    iteration=iteration,
                )
            )
            gateway_samples.append(
                await time_request(
                    client,
                    target="gateway",
                    url=gateway_chat_url,
                    headers=gateway_headers,
                    payload=build_payload(model, iteration),
                    iteration=iteration,
                )
            )

    direct = summarize("direct_openai", direct_samples)
    gateway = summarize("llm_gateway", gateway_samples)

    return BenchmarkReport(
        model=model,
        iterations=iterations,
        gateway_url=gateway_url,
        direct=direct,
        gateway=gateway,
        overhead_p50_ms=gateway.p50_ms - direct.p50_ms,
        overhead_p95_ms=gateway.p95_ms - direct.p95_ms,
        overhead_p50_pct=overhead_pct(direct.p50_ms, gateway.p50_ms),
    )


def print_report(report: BenchmarkReport) -> None:
    print("Benchmark latency report")
    print("Model:", report.model)
    print("Gateway URL:", report.gateway_url)
    print("Iterations (excluding warmup):", report.iterations)
    print()
    print(f"{'Target':<16} {'p50':>8} {'p95':>8} {'p99':>8} {'errors':>8}")
    print(f"{report.direct.target:<16} {report.direct.p50_ms:>7}ms {report.direct.p95_ms:>7}ms {report.direct.p99_ms:>7}ms {report.direct.errors:>8}")
    print(
        f"{report.gateway.target:<16} {report.gateway.p50_ms:>7}ms {report.gateway.p95_ms:>7}ms {report.gateway.p99_ms:>7}ms {report.gateway.errors:>8}"
    )
    print()
    print(f"Gateway overhead p50: {report.overhead_p50_ms} ms ({report.overhead_p50_pct}%)")
    print(f"Gateway overhead p95: {report.overhead_p95_ms} ms")
    if report.gateway.p50_ms < report.direct.p50_ms:
        print()
        print(
            "WARNING: Gateway faster than direct — likely semantic cache hits skewing results."
        )
        print(f"  Re-run with {BYPASS_CACHE_HEADER}: true on gateway requests (script does this")
        print("  automatically after the latest fix) or set SEMANTIC_CACHE_ENABLED=false.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark gateway vs direct OpenAI latency")
    parser.add_argument("gateway_api_key", nargs="?", default="")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument(
        "--output",
        default="docs/benchmark_results.json",
        help="Write JSON results to this path",
    )
    return parser.parse_args()


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    args = parse_args()

    gateway_api_key = args.gateway_api_key or os.getenv("GATEWAY_TEST_API_KEY", "")
    openai_api_key = settings.openai_api_key.get_secret_value()

    if not gateway_api_key:
        print("Set GATEWAY_TEST_API_KEY in .env or pass gateway key as first argument.")
        sys.exit(1)
    if not openai_api_key:
        print("Set OPENAI_API_KEY in .env before running the benchmark.")
        sys.exit(1)

    report = await run_benchmark(
        gateway_url=args.gateway_url,
        gateway_api_key=gateway_api_key,
        openai_api_key=openai_api_key,
        model=args.model,
        iterations=args.iterations,
    )

    print_report(report)

    if report.direct.errors or report.gateway.errors:
        print()
        print("Benchmark completed with errors — check gateway/OpenAI connectivity.")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print()
    print("Wrote:", output_path)


if __name__ == "__main__":
    asyncio.run(main())
