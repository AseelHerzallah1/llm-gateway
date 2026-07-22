"""Decompose gateway latency into direct OpenAI, embedding, and gateway paths.

Usage:
    python scripts/benchmark_decompose.py gw-sk-your-key --iterations 5

Measures:
    - direct_chat: OpenAI chat/completions only
    - direct_embed: OpenAI embeddings only (same text shape as cache lookup)
    - gateway_chat: full gateway path (cache miss with unique prompts)

Restart the gateway after code changes before comparing gateway numbers.
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
from app.embeddings.prompt import messages_to_embed_text
from app.observability.metrics import percentile
from app.providers.base import ChatMessage


DEFAULT_GATEWAY_URL = "http://127.0.0.1:8001"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_ITERATIONS = 5


@dataclass(frozen=True)
class TargetSummary:
    name: str
    p50_ms: int
    p95_ms: int
    errors: int


@dataclass(frozen=True)
class DecomposeReport:
    model: str
    iterations: int
    gateway_url: str
    direct_chat: TargetSummary
    direct_embed: TargetSummary
    gateway_chat: TargetSummary
    estimated_embed_share_ms: int
    gateway_overhead_p50_ms: int


def build_chat_payload(model: str, iteration: int) -> dict:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": f"Reply with one short greeting word. benchmark-{iteration}-{uuid.uuid4().hex[:8]}",
            }
        ],
        "stream": False,
        "max_tokens": 10,
    }


def embed_text_for_iteration(iteration: int) -> str:
    messages = [
        ChatMessage(
            role="user",
            content=f"Reply with one short greeting word. benchmark-{iteration}-{uuid.uuid4().hex[:8]}",
        )
    ]
    return messages_to_embed_text(messages)


async def time_chat(client: httpx.AsyncClient, url: str, headers: dict[str, str], payload: dict) -> tuple[int, int]:
    started = time.perf_counter()
    response = await client.post(url, json=payload, headers=headers)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return latency_ms, response.status_code


async def time_embed(client: httpx.AsyncClient, base_url: str, headers: dict[str, str], text: str) -> tuple[int, int]:
    started = time.perf_counter()
    response = await client.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": settings.openai_embedding_model, "input": text},
        headers=headers,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return latency_ms, response.status_code


def summarize(name: str, latencies: list[int], errors: int) -> TargetSummary:
    return TargetSummary(
        name=name,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        errors=errors,
    )


async def run_decompose(
    *,
    gateway_url: str,
    gateway_api_key: str,
    openai_api_key: str,
    model: str,
    iterations: int,
) -> DecomposeReport:
    openai_base = settings.openai_base_url.rstrip("/")
    direct_chat_url = f"{openai_base}/chat/completions"
    gateway_chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    openai_headers = {"Authorization": f"Bearer {openai_api_key}"}
    gateway_headers = {"Authorization": f"Bearer {gateway_api_key}"}
    timeout = httpx.Timeout(settings.openai_read_timeout_s)

    chat_latencies: list[int] = []
    embed_latencies: list[int] = []
    gateway_latencies: list[int] = []
    chat_errors = 0
    embed_errors = 0
    gateway_errors = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        for iteration in range(1, iterations + 1):
            payload = build_chat_payload(model, iteration)
            text = embed_text_for_iteration(iteration)

            latency, status = await time_chat(client, direct_chat_url, openai_headers, payload)
            if status == 200:
                chat_latencies.append(latency)
            else:
                chat_errors += 1

            latency, status = await time_embed(client, openai_base, openai_headers, text)
            if status == 200:
                embed_latencies.append(latency)
            else:
                embed_errors += 1

            latency, status = await time_chat(client, gateway_chat_url, gateway_headers, payload)
            if status == 200:
                gateway_latencies.append(latency)
            else:
                gateway_errors += 1

    direct_chat = summarize("direct_chat", chat_latencies, chat_errors)
    direct_embed = summarize("direct_embed", embed_latencies, embed_errors)
    gateway_chat = summarize("gateway_chat", gateway_latencies, gateway_errors)

    return DecomposeReport(
        model=model,
        iterations=iterations,
        gateway_url=gateway_url,
        direct_chat=direct_chat,
        direct_embed=direct_embed,
        gateway_chat=gateway_chat,
        estimated_embed_share_ms=direct_embed.p50_ms,
        gateway_overhead_p50_ms=gateway_chat.p50_ms - direct_chat.p50_ms,
    )


def print_report(report: DecomposeReport) -> None:
    print("Decomposed latency report")
    print("Model:", report.model)
    print("Gateway URL:", report.gateway_url)
    print("Iterations:", report.iterations)
    print()
    print(f"{'Target':<16} {'p50':>8} {'p95':>8} {'errors':>8}")
    for target in (report.direct_chat, report.direct_embed, report.gateway_chat):
        print(f"{target.name:<16} {target.p50_ms:>7}ms {target.p95_ms:>7}ms {target.errors:>8}")
    print()
    print(f"Gateway overhead p50 vs direct chat: {report.gateway_overhead_p50_ms} ms")
    print(f"Direct embedding p50 (one call): {report.estimated_embed_share_ms} ms")
    print(
        "Rough embed share of overhead (if 1 embed on miss): "
        f"{round(report.estimated_embed_share_ms / report.gateway_overhead_p50_ms * 100, 1)}%"
        if report.gateway_overhead_p50_ms > 0
        else "Rough embed share: n/a"
    )


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Decompose gateway latency")
    parser.add_argument("gateway_api_key", nargs="?", default="")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--output", default="docs/benchmark_decompose.json")
    args = parser.parse_args()

    gateway_api_key = args.gateway_api_key or os.getenv("GATEWAY_TEST_API_KEY", "")
    openai_api_key = settings.openai_api_key.get_secret_value()
    if not gateway_api_key or not openai_api_key:
        print("Need gateway key and OPENAI_API_KEY in .env")
        sys.exit(1)

    report = await run_decompose(
        gateway_url=args.gateway_url,
        gateway_api_key=gateway_api_key,
        openai_api_key=openai_api_key,
        model=args.model,
        iterations=args.iterations,
    )
    print_report(report)

    if any(target.errors for target in (report.direct_chat, report.direct_embed, report.gateway_chat)):
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print()
    print("Wrote:", output_path)


if __name__ == "__main__":
    asyncio.run(main())
