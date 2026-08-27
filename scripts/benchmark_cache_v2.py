"""v0.2 four-path cache benchmark with project-scoped isolation.

Usage (prepare only — does not run timed iterations unless --run is passed):
    python scripts/benchmark_cache_v2.py --prepare-only
    python scripts/benchmark_cache_v2.py gw-sk-benchmark-key --iterations 30 --run

Isolation (every prepare / run):
    1. Resolve dedicated benchmark project_id from the benchmark API key.
    2. DELETE cache_entries + requests rows for that project_id only.
    3. Restart the gateway process so in-memory exact index + semantic entries
       re-hydrate from PostgreSQL (benchmark project starts empty; other projects
       are untouched in PostgreSQL and reload into memory on startup).

This prevents cross-session cache pollution on the shared dev/test project key.

Paths measured when --run is set (30 iterations default):
    1. direct_openai
    2. gateway_thin_proxy (X-Gateway-Bypass-Cache)
    3. gateway_exact_miss (unique prompt A, then unique prompt B — always miss)
    4. gateway_exact_hit (repeat identical prompt — L1 exact_hit)
    5. gateway_semantic_miss (paraphrase pair where verifier must reject or no candidate)
    6. gateway_semantic_hit (Class-A paraphrase pair — verified semantic_hit)

Output: docs/benchmark_v2_validation.json (only written with --run).

Requires:
    - Gateway at http://127.0.0.1:8001 (Docker or uvicorn)
    - OPENAI_API_KEY in .env
    - Benchmark API key (pass as argv or BENCHMARK_API_KEY in .env)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth.dependencies import resolve_project
from app.cache.persistence import clear_project_benchmark_state
from app.config import settings
from app.db.session import async_session_factory
from app.observability.metrics import percentile

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8001"
DEFAULT_ITERATIONS = 30
DEFAULT_MODEL = "gpt-4o-mini"
BENCHMARK_PROJECT_NAME = "benchmark-v2-cache"
BYPASS_HEADER = "X-Gateway-Bypass-Cache"


@dataclass(frozen=True)
class PathSummary:
    name: str
    samples: int
    p50_ms: int
    p95_ms: int
    p99_ms: int
    errors: int
    verified_hits: int = 0
    verified_misses: int = 0


async def resolve_benchmark_project_id(api_key: str) -> uuid.UUID:
    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
    return project.id


async def isolate_benchmark_project(project_id: uuid.UUID) -> tuple[int, int]:
    """Clear PostgreSQL cache + request logs for the benchmark project only."""
    return await clear_project_benchmark_state(project_id)


def restart_gateway_process() -> None:
    """Re-hydrate in-memory cache from PostgreSQL after benchmark project rows are cleared."""
    compose_file = ROOT / "docker-compose.yml"
    if compose_file.exists():
        subprocess.run(
            ["docker", "compose", "restart", "app"],
            cwd=ROOT,
            check=True,
        )
        return
    print(
        "docker-compose.yml not found — restart uvicorn manually so hydrate_gateway_cache "
        "reloads without stale in-memory rows for the benchmark project."
    )


async def wait_for_gateway(base_url: str, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"{base_url.rstrip('/')}/health", timeout=5.0)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2.0)
    raise SystemExit(f"Gateway not healthy at {base_url} after {timeout_s:.0f}s")


async def prepare_isolated_benchmark(api_key: str, base_url: str) -> uuid.UUID:
    project_id = await resolve_benchmark_project_id(api_key)
    cache_rows, request_rows = await isolate_benchmark_project(project_id)
    print(
        f"Isolated benchmark project_id={project_id} "
        f"(deleted cache_rows={cache_rows}, request_rows={request_rows})"
    )
    restart_gateway_process()
    await wait_for_gateway(base_url)
    print("Gateway restarted and healthy — in-memory cache re-hydrated from PostgreSQL.")
    return project_id


def summarize(name: str, latencies: list[int], *, hits: int = 0, misses: int = 0) -> PathSummary:
    if not latencies:
        return PathSummary(name, 0, 0, 0, 0, 0, hits, misses)
    ordered = sorted(latencies)
    return PathSummary(
        name=name,
        samples=len(ordered),
        p50_ms=percentile(ordered, 50),
        p95_ms=percentile(ordered, 95),
        p99_ms=percentile(ordered, 99),
        errors=0,
        verified_hits=hits,
        verified_misses=misses,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="v0.2 cache benchmark with project isolation")
    parser.add_argument("api_key", nargs="?", help="Dedicated benchmark gateway API key")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--prepare-only", action="store_true", help="Isolate and exit")
    parser.add_argument("--run", action="store_true", help="Run timed benchmark paths")
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs" / "benchmark_v2_validation.json"),
        help="JSON output path (only with --run)",
    )
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key:
        secret = settings.gateway_test_api_key.get_secret_value()
        api_key = secret or None
    if not api_key:
        raise SystemExit("Pass benchmark API key or set GATEWAY_TEST_API_KEY (prefer dedicated key).")

    project_id = await prepare_isolated_benchmark(api_key, args.gateway_url)
    print(f"Benchmark project ready: {project_id}")

    if args.prepare_only and not args.run:
        print("Prepare-only complete. Re-run with --run when ready to measure.")
        return

    if not args.run:
        print("No --run flag — isolation complete. Pass --run to execute timed paths.")
        return

    raise SystemExit(
        "Timed v0.2 path execution is not implemented in this checkpoint. "
        "Use --prepare-only before the heavy run; implement iteration loops next."
    )


if __name__ == "__main__":
    asyncio.run(main())
