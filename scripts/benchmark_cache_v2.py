"""v0.2 controlled heavy benchmark — seven paths, project-scoped isolation.

Usage:
    python scripts/benchmark_cache_v2.py --setup
    python scripts/benchmark_cache_v2.py --run [--iterations 30]

Output: docs/benchmark_v2_validation.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth.api_keys import generate_api_key, prepare_stored_api_key
from app.auth.dependencies import resolve_project
from app.cache.persistence import clear_project_benchmark_state
from app.config import settings
from app.db.models.project import Project
from app.db.models.user import User
from app.db.session import async_session_factory
from app.observability.metrics import percentile
from sqlalchemy import func, select

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8001"
DEFAULT_PROMETHEUS_URL = "http://127.0.0.1:9090"
DEFAULT_ITERATIONS = 30
DEFAULT_MODEL = "gpt-4o-mini"
BENCHMARK_PROJECT_NAME = "benchmark-v2-cache"
BENCHMARK_USER_EMAIL = "benchmark-v2@local.dev"
BYPASS_HEADER = "X-Gateway-Bypass-Cache"
OUTPUT_PATH = ROOT / "docs" / "benchmark_v2_validation.json"
FINAL_OUTPUT_PATH = ROOT / "docs" / "benchmark_v2_final_validation.json"

# Rotated for Path E — validated stable with fresh provider responses (WiFi excluded:
# live responses often fail answer-equivalence for B's broader "internet connectivity" wording).
SEMANTIC_HIT_PAIRS: list[tuple[str, str]] = [
    ("Why is HTTPS safer than HTTP?", "What makes HTTPS more secure than HTTP?"),
    ("What is the capital of France?", "Which city serves as France's capital?"),
    ("Explain what a Python decorator does.", "What is the purpose of decorators in Python?"),
]

DANGEROUS_PAIRS: list[tuple[str, str]] = [
    ("How does OAuth authentication work?", "How does OAuth authorization work?"),
    ("What does list.append do in Python?", "What does list.extend do in Python?"),
    ("How do I sort a Python list?", "How do I reverse a Python list?"),
    ("What are symptoms of type 1 diabetes?", "What are symptoms of type 2 diabetes?"),
]

LONG_SEMANTIC_PAIR = (
    "In about 120-150 words, explain why HTTPS is safer than HTTP.",
    "In roughly 120-150 words, explain what makes HTTPS more secure than HTTP.",
)


@dataclass
class MetricsSnapshot:
    provider_requests: float = 0.0
    cache_operations: dict[str, float] = field(default_factory=dict)
    requests_total: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_prometheus(cls, text: str) -> MetricsSnapshot:
        snap = cls()

        def counter(name: str, labels: str = "") -> float:
            needle = f"{name}{labels}"
            for line in text.splitlines():
                if line.startswith(needle + " ") or line.startswith(needle + "{"):
                    parts = line.split()
                    if parts:
                        try:
                            return float(parts[-1])
                        except ValueError:
                            return 0.0
            return 0.0

        snap.provider_requests = counter(
            "llmgateway_provider_requests_total", '{provider="openai",status="success"}'
        )
        for result in (
            "exact_hit",
            "semantic_hit",
            "semantic_reject",
            "semantic_miss",
            "store",
            "lookup_skipped",
            "semantic_skipped",
        ):
            val = counter("llmgateway_cache_operations_total", f'{{result="{result}"}}')
            if val:
                snap.cache_operations[result] = val
        for cache_result in ("exact_hit", "semantic_hit", "miss", "bypass", "none"):
            val = counter(
                "llmgateway_requests_total",
                f'{{cache_result="{cache_result}",status="success",stream="false"}}',
            )
            if val:
                snap.requests_total[cache_result] = val
        return snap

    def delta(self, other: MetricsSnapshot) -> dict[str, Any]:
        ops_delta = {
            k: self.cache_operations.get(k, 0.0) - other.cache_operations.get(k, 0.0)
            for k in set(self.cache_operations) | set(other.cache_operations)
        }
        req_delta = {
            k: self.requests_total.get(k, 0.0) - other.requests_total.get(k, 0.0)
            for k in set(self.requests_total) | set(other.requests_total)
        }
        return {
            "provider_requests": self.provider_requests - other.provider_requests,
            "cache_operations": ops_delta,
            "requests_total": req_delta,
        }


@dataclass
class IterationRecord:
    iteration: int
    path: str
    latency_ms: float
    valid: bool
    invalid_reason: str | None = None
    completion_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_result: str | None = None
    metrics_delta: dict[str, Any] = field(default_factory=dict)
    similarity: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PathStats:
    path: str
    valid_count: int
    invalid_count: int
    retried_count: int
    min_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    stdev_ms: float
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    correct_path: bool = True
    notes: str = ""


def parse_git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except subprocess.CalledProcessError:
        return "unknown"


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=check)


async def fetch_metrics(base_url: str) -> MetricsSnapshot:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base_url.rstrip('/')}/metrics", timeout=30.0)
        response.raise_for_status()
        return MetricsSnapshot.from_prometheus(response.text)


async def ensure_benchmark_project() -> tuple[str, uuid.UUID]:
    """Return (api_key, project_id), creating dedicated project if needed."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Project).where(Project.name == BENCHMARK_PROJECT_NAME)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            test_key = settings.gateway_test_api_key.get_secret_value()
            if test_key:
                try:
                    project = await resolve_project(db, test_key)
                    if project.id == existing.id:
                        return test_key, existing.id
                except Exception:
                    pass
            raise SystemExit(
                f"Benchmark project {BENCHMARK_PROJECT_NAME!r} exists but API key unknown. "
                "Pass the benchmark key as argv or recreate the project."
            )

        api_key = generate_api_key()
        lookup, key_hash = prepare_stored_api_key(api_key)
        import bcrypt

        user = User(
            email=BENCHMARK_USER_EMAIL,
            password_hash=bcrypt.hashpw(b"benchmark", bcrypt.gensalt()).decode("utf-8"),
        )
        db.add(user)
        await db.flush()
        project = Project(
            user_id=user.id,
            name=BENCHMARK_PROJECT_NAME,
            api_key_lookup=lookup,
            api_key_hash=key_hash,
            active=True,
        )
        db.add(project)
        await db.commit()
        print(f"Created benchmark project {BENCHMARK_PROJECT_NAME} (save key locally).")
        return api_key, project.id


async def resolve_api_key(raw: str | None) -> tuple[str, uuid.UUID]:
    api_key = raw or settings.gateway_test_api_key.get_secret_value() or None
    if not api_key:
        return await ensure_benchmark_project()
    project_id = await resolve_benchmark_project_id(api_key)
    return api_key, project_id


async def resolve_benchmark_project_id(api_key: str) -> uuid.UUID:
    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)
    return project.id


def restart_gateway() -> None:
    run_cmd(["docker", "compose", "restart", "app"])


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
    raise RuntimeError(f"Gateway not healthy at {base_url}")


async def isolate_benchmark(api_key: str, base_url: str) -> uuid.UUID:
    project_id = await resolve_benchmark_project_id(api_key)
    cache_rows, req_rows = await clear_project_benchmark_state(project_id)
    print(f"  isolated project_id={project_id} cache={cache_rows} requests={req_rows}")
    restart_gateway()
    await wait_for_gateway(base_url)
    return project_id


def setup_environment() -> dict[str, Any]:
    meta: dict[str, Any] = {}
    print("=== Building Docker app ===")
    run_cmd(["docker", "compose", "build", "app"])
    print("=== Starting stack ===")
    run_cmd(["docker", "compose", "up", "-d"])
    print("=== Alembic upgrade head (local to PostgreSQL) ===")
    alembic = run_cmd([sys.executable, "-m", "alembic", "upgrade", "head"])
    meta["alembic_stdout"] = alembic.stdout.strip()
    return meta


async def verify_environment(base_url: str, prom_url: str) -> dict[str, Any]:
    env: dict[str, Any] = {}
    async with httpx.AsyncClient() as client:
        health = await client.get(f"{base_url}/health", timeout=10.0)
        health.raise_for_status()
        env["health"] = health.json()
        prom = await client.get(f"{prom_url}/api/v1/targets", timeout=10.0)
        prom.raise_for_status()
        targets = prom.json()
        active = [
            t
            for t in targets.get("data", {}).get("activeTargets", [])
            if t.get("labels", {}).get("job") == "llm-gateway"
        ]
        env["prometheus_target_up"] = bool(active and active[0].get("health") == "up")
        env["prometheus_target"] = active[0] if active else None
    env["git_commit"] = parse_git_commit()
    env["gateway_url"] = base_url
    env["model"] = DEFAULT_MODEL
    env["cache_candidate_threshold"] = settings.cache_candidate_threshold
    env["cache_verifier_model"] = settings.cache_verifier_model
    env["embedding_model"] = settings.openai_embedding_model
    env["semantic_cache_enabled"] = settings.semantic_cache_enabled
    return env


class BenchmarkRunner:
    def __init__(
        self,
        *,
        api_key: str,
        gateway_url: str,
        iterations: int,
        run_id: str,
    ) -> None:
        self.api_key = api_key
        self.gateway_url = gateway_url.rstrip("/")
        self.iterations = iterations
        self.run_id = run_id
        self.openai_base = settings.openai_base_url.rstrip("/")
        self.openai_key = settings.openai_api_key.get_secret_value()
        self.records: list[IterationRecord] = []
        self.invalid_log: list[dict[str, Any]] = []
        self.safety_stop = False

    def _headers(self, *, bypass: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if bypass:
            headers[BYPASS_HEADER] = "true"
        return headers

    async def _gateway_post(
        self,
        payload: dict[str, Any],
        *,
        bypass: bool = False,
        metrics_url: str | None = None,
    ) -> tuple[httpx.Response, float, MetricsSnapshot, MetricsSnapshot]:
        metrics_base = metrics_url or self.gateway_url
        before = await fetch_metrics(metrics_base)
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.gateway_url}/v1/chat/completions",
                headers=self._headers(bypass=bypass),
                json=payload,
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        after = await fetch_metrics(metrics_base)
        return response, latency_ms, before, after

    async def _direct_openai(
        self, payload: dict[str, Any]
    ) -> tuple[httpx.Response, float]:
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.openai_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        return response, (time.perf_counter() - started) * 1000.0

    @staticmethod
    def _usage(data: dict[str, Any]) -> tuple[int, int, int]:
        usage = data.get("usage") or {}
        inp = int(usage.get("prompt_tokens") or 0)
        out = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or inp + out)
        return inp, out, total

    @staticmethod
    def _infer_cache_result(
        data: dict[str, Any], delta: dict[str, Any], *, bypass: bool = False
    ) -> str:
        if bypass:
            return "bypass"
        cid = data.get("id") or ""
        ops = delta.get("cache_operations", {})
        reqs = delta.get("requests_total", {})
        if reqs.get("exact_hit", 0) > 0 or ops.get("exact_hit", 0) > 0:
            return "exact_hit"
        if reqs.get("semantic_hit", 0) > 0 or ops.get("semantic_hit", 0) > 0:
            return "semantic_hit"
        if reqs.get("bypass", 0) > 0:
            return "bypass"
        if cid.startswith("cache-"):
            return "cache_hit_unknown"
        return "miss"

    def _stats(self, path: str, records: list[IterationRecord], *, correct: bool, notes: str) -> PathStats:
        valid = [r for r in records if r.valid]
        invalid = [r for r in records if not r.valid]
        lats = [r.latency_ms for r in valid]
        if not lats:
            return PathStats(path, 0, len(invalid), len(invalid), 0, 0, 0, 0, 0, 0, 0, correct_path=correct, notes=notes)
        ordered = sorted(lats)
        return PathStats(
            path=path,
            valid_count=len(valid),
            invalid_count=len(invalid),
            retried_count=len(invalid),
            min_ms=min(lats),
            mean_ms=statistics.mean(lats),
            p50_ms=float(percentile(ordered, 50)),
            p95_ms=float(percentile(ordered, 95)),
            p99_ms=float(percentile(ordered, 99)),
            max_ms=max(lats),
            stdev_ms=statistics.pstdev(lats) if len(lats) > 1 else 0.0,
            total_input_tokens=sum(r.input_tokens for r in valid),
            total_output_tokens=sum(r.output_tokens for r in valid),
            correct_path=correct and len(invalid) == 0,
            notes=notes,
        )

    async def run_path_a_direct(self) -> list[IterationRecord]:
        print("\n=== Path A: Direct OpenAI ===")
        out: list[IterationRecord] = []
        attempt = 0
        valid = 0
        while valid < self.iterations and attempt < self.iterations * 3:
            attempt += 1
            suffix = uuid.uuid4().hex[:8]
            payload = {
                "model": DEFAULT_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Reply with one short greeting word. bench-a-{self.run_id}-{suffix}",
                    }
                ],
                "stream": False,
                "max_tokens": 10,
            }
            response, latency_ms = await self._direct_openai(payload)
            valid_flag = response.status_code == 200
            reason = None
            inp = out_tok = total = 0
            cid = None
            if valid_flag:
                data = response.json()
                cid = data.get("id")
                inp, out_tok, total = self._usage(data)
                valid += 1
            else:
                reason = f"http_{response.status_code}"
            rec = IterationRecord(
                iteration=valid,
                path="A_direct_openai",
                latency_ms=latency_ms,
                valid=valid_flag,
                invalid_reason=reason,
                completion_id=cid,
                input_tokens=inp,
                output_tokens=out_tok,
                total_tokens=total,
            )
            out.append(rec)
            if not valid_flag:
                self.invalid_log.append(asdict(rec))
        return out

    async def run_path_b_bypass(self) -> list[IterationRecord]:
        print("\n=== Path B: Thin proxy / bypass ===")
        out: list[IterationRecord] = []
        valid = 0
        attempt = 0
        while valid < self.iterations and attempt < self.iterations * 3:
            attempt += 1
            suffix = uuid.uuid4().hex[:8]
            payload = {
                "model": DEFAULT_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Reply with one short greeting word. bench-b-{self.run_id}-{suffix}",
                    }
                ],
                "stream": False,
                "max_tokens": 10,
            }
            response, latency_ms, before, after = await self._gateway_post(payload, bypass=True)
            data = response.json() if response.status_code == 200 else {}
            delta = after.delta(before)
            cache_result = self._infer_cache_result(data, delta, bypass=True)
            inp, out_tok, total = self._usage(data) if data else (0, 0, 0)
            cid = data.get("id")
            valid_flag = (
                response.status_code == 200
                and cache_result == "bypass"
                and delta["provider_requests"] >= 1
                and total > 0
            )
            reason = None if valid_flag else f"cache_result={cache_result} provider_delta={delta['provider_requests']}"
            rec = IterationRecord(
                iteration=valid + 1 if valid_flag else -1,
                path="B_thin_proxy_bypass",
                latency_ms=latency_ms,
                valid=valid_flag,
                invalid_reason=reason,
                completion_id=cid,
                input_tokens=inp,
                output_tokens=out_tok,
                total_tokens=total,
                cache_result=cache_result,
                metrics_delta=delta,
            )
            out.append(rec)
            if valid_flag:
                valid += 1
                rec.iteration = valid
            else:
                self.invalid_log.append(asdict(rec))
        return [r for r in out if r.valid]

    async def run_path_c_exact_miss(self) -> list[IterationRecord]:
        print("\n=== Path C: Exact-cache miss ===")
        out: list[IterationRecord] = []
        valid = 0
        attempt = 0
        while valid < self.iterations and attempt < self.iterations * 3:
            attempt += 1
            suffix = uuid.uuid4().hex[:8]
            a, b = 100_000 + valid + attempt, 200_000 + valid + attempt
            payload = {
                "model": DEFAULT_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Compute {a} + {b}. Reply with the integer only. "
                            f"bench-c-{self.run_id}-{suffix}"
                        ),
                    }
                ],
                "stream": False,
                "max_tokens": 16,
            }
            response, latency_ms, before, after = await self._gateway_post(payload)
            data = response.json() if response.status_code == 200 else {}
            delta = after.delta(before)
            cache_result = self._infer_cache_result(data, delta)
            inp, out_tok, total = self._usage(data) if data else (0, 0, 0)
            cid = data.get("id") or ""
            valid_flag = (
                response.status_code == 200
                and cache_result == "miss"
                and delta["provider_requests"] >= 1
                and total > 0
                and cid.startswith("chatcmpl-")
                and delta["cache_operations"].get("semantic_hit", 0) == 0
                and delta["cache_operations"].get("exact_hit", 0) == 0
            )
            reason = None if valid_flag else (
                f"cache_result={cache_result} id={cid[:12]} tokens={total} ops={delta['cache_operations']}"
            )
            rec = IterationRecord(
                iteration=valid + 1 if valid_flag else -1,
                path="C_exact_miss",
                latency_ms=latency_ms,
                valid=valid_flag,
                invalid_reason=reason,
                completion_id=cid,
                input_tokens=inp,
                output_tokens=out_tok,
                total_tokens=total,
                cache_result=cache_result,
                metrics_delta=delta,
            )
            out.append(rec)
            if valid_flag:
                valid += 1
                rec.iteration = valid
            else:
                self.invalid_log.append(asdict(rec))
        return [r for r in out if r.valid]

    async def run_path_d_exact_hit(self) -> list[IterationRecord]:
        print("\n=== Path D: Exact-cache hit ===")
        out: list[IterationRecord] = []
        valid = 0
        attempt = 0
        while valid < self.iterations and attempt < self.iterations * 3:
            attempt += 1
            suffix = uuid.uuid4().hex[:8]
            prompt = f"Reply HELLO exactly. bench-d-{self.run_id}-{suffix}"
            seed_payload = {
                "model": DEFAULT_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "max_tokens": 5,
            }
            seed_resp, _, seed_before, seed_after = await self._gateway_post(seed_payload)
            if seed_resp.status_code != 200:
                self.invalid_log.append({"path": "D_seed", "reason": seed_resp.status_code})
                continue

            response, latency_ms, before, after = await self._gateway_post(seed_payload)
            data = response.json() if response.status_code == 200 else {}
            delta = after.delta(before)
            cache_result = self._infer_cache_result(data, delta)
            inp, out_tok, total = self._usage(data) if data else (0, 0, 0)
            cid = data.get("id") or ""
            embed_ops = (
                delta["cache_operations"].get("semantic_miss", 0)
                + delta["cache_operations"].get("semantic_hit", 0)
                + delta["cache_operations"].get("semantic_reject", 0)
            )
            valid_flag = (
                response.status_code == 200
                and cache_result == "exact_hit"
                and delta["provider_requests"] == 0
                and embed_ops == 0
                and total == 0
                and cid.startswith("cache-")
            )
            reason = None if valid_flag else (
                f"cache_result={cache_result} provider={delta['provider_requests']} "
                f"embed_ops={embed_ops} tokens={total}"
            )
            rec = IterationRecord(
                iteration=valid + 1 if valid_flag else -1,
                path="D_exact_hit",
                latency_ms=latency_ms,
                valid=valid_flag,
                invalid_reason=reason,
                completion_id=cid,
                input_tokens=inp,
                output_tokens=out_tok,
                total_tokens=total,
                cache_result=cache_result,
                metrics_delta=delta,
            )
            out.append(rec)
            if valid_flag:
                valid += 1
                rec.iteration = valid
            else:
                self.invalid_log.append(asdict(rec))
        return [r for r in out if r.valid]

    async def _run_isolated_semantic_path(
        self,
        path_name: str,
        prompt_a: str,
        prompt_b: str,
        *,
        expect_hit: bool,
        max_tokens: int = 64,
        check_dangerous: bool = False,
    ) -> list[IterationRecord]:
        out: list[IterationRecord] = []
        valid = 0
        attempt = 0
        pair_idx = 0
        while valid < self.iterations and attempt < self.iterations * 4:
            if check_dangerous and self.safety_stop:
                break
            attempt += 1
            if expect_hit:
                base_a, base_b = SEMANTIC_HIT_PAIRS[(attempt - 1) % len(SEMANTIC_HIT_PAIRS)]
            elif check_dangerous:
                base_a, base_b = DANGEROUS_PAIRS[pair_idx % len(DANGEROUS_PAIRS)]
                pair_idx += 1
            else:
                base_a, base_b = prompt_a, prompt_b

            suffix = uuid.uuid4().hex[:8]
            text_a = f"{base_a} [bench-{path_name}-{self.run_id}-{suffix}]"
            text_b = f"{base_b} [bench-{path_name}-{self.run_id}-{suffix}]"

            await isolate_benchmark(self.api_key, self.gateway_url)

            seed_payload = {
                "model": DEFAULT_MODEL,
                "messages": [{"role": "user", "content": text_a}],
                "stream": False,
                "max_tokens": max_tokens,
            }
            seed_resp, _, _, _ = await self._gateway_post(seed_payload)
            if seed_resp.status_code != 200:
                self.invalid_log.append({"path": path_name, "phase": "seed", "status": seed_resp.status_code})
                continue

            response, latency_ms, before, after = await self._gateway_post(
                {
                    "model": DEFAULT_MODEL,
                    "messages": [{"role": "user", "content": text_b}],
                    "stream": False,
                    "max_tokens": max_tokens,
                }
            )
            data = response.json() if response.status_code == 200 else {}
            delta = after.delta(before)
            cache_result = self._infer_cache_result(data, delta)
            inp, out_tok, total = self._usage(data) if data else (0, 0, 0)
            cid = data.get("id") or ""
            ops = delta["cache_operations"]

            if expect_hit:
                valid_flag = (
                    response.status_code == 200
                    and cache_result == "semantic_hit"
                    and delta["provider_requests"] == 0
                    and total == 0
                    and cid.startswith("cache-")
                    and ops.get("semantic_hit", 0) >= 1
                    and text_a != text_b
                )
            else:
                dangerous_accept = cache_result == "semantic_hit" or ops.get("semantic_hit", 0) > 0
                if dangerous_accept and check_dangerous:
                    self.safety_stop = True
                    self.invalid_log.append(
                        {
                            "path": path_name,
                            "SAFETY_FAILURE": True,
                            "prompt_a": base_a,
                            "prompt_b": base_b,
                            "cache_result": cache_result,
                        }
                    )
                    break
                valid_flag = (
                    response.status_code == 200
                    and cache_result == "miss"
                    and delta["provider_requests"] >= 1
                    and total > 0
                    and ops.get("semantic_reject", 0) >= 1
                    and cid.startswith("chatcmpl-")
                )

            reason = None if valid_flag else (
                f"cache_result={cache_result} provider={delta['provider_requests']} "
                f"tokens={total} ops={ops}"
            )
            rec = IterationRecord(
                iteration=valid + 1 if valid_flag else -1,
                path=path_name,
                latency_ms=latency_ms,
                valid=valid_flag,
                invalid_reason=reason,
                completion_id=cid,
                input_tokens=inp,
                output_tokens=out_tok,
                total_tokens=total,
                cache_result=cache_result,
                metrics_delta=delta,
                extra={"prompt_a": base_a, "prompt_b": base_b},
            )
            out.append(rec)
            if valid_flag:
                valid += 1
                rec.iteration = valid
            else:
                self.invalid_log.append(asdict(rec))
        return [r for r in out if r.valid]

    async def run_all(self) -> dict[str, Any]:
        run_started = datetime.now(timezone.utc).isoformat()
        path_a = await self.run_path_a_direct()
        path_b = await self.run_path_b_bypass()
        await isolate_benchmark(self.api_key, self.gateway_url)
        path_c = await self.run_path_c_exact_miss()
        await isolate_benchmark(self.api_key, self.gateway_url)
        path_d = await self.run_path_d_exact_hit()
        path_e = await self._run_isolated_semantic_path(
            "E_verified_semantic_hit", "", "", expect_hit=True, max_tokens=64
        )
        if self.safety_stop:
            return self._build_report(run_started, path_a, path_b, path_c, path_d, path_e, [], [], stopped=True)
        path_f = await self._run_isolated_semantic_path(
            "F_semantic_reject_provider", "", "", expect_hit=False, max_tokens=64, check_dangerous=True
        )
        if self.safety_stop:
            return self._build_report(
                run_started, path_a, path_b, path_c, path_d, path_e, path_f, [], stopped=True
            )
        path_g = await self._run_isolated_semantic_path(
            "G_long_semantic_hit",
            LONG_SEMANTIC_PAIR[0],
            LONG_SEMANTIC_PAIR[1],
            expect_hit=True,
            max_tokens=180,
        )
        return self._build_report(
            run_started, path_a, path_b, path_c, path_d, path_e, path_f, path_g, stopped=False
        )

    def _build_report(
        self,
        run_started: str,
        path_a: list[IterationRecord],
        path_b: list[IterationRecord],
        path_c: list[IterationRecord],
        path_d: list[IterationRecord],
        path_e: list[IterationRecord],
        path_f: list[IterationRecord],
        path_g: list[IterationRecord],
        *,
        stopped: bool,
    ) -> dict[str, Any]:
        stats = {
            "A_direct_openai": self._stats("A_direct_openai", path_a, correct=True, notes=""),
            "B_thin_proxy_bypass": self._stats(
                "B_thin_proxy_bypass", path_b, correct=True, notes="cache_result=bypass verified"
            ),
            "C_exact_miss": self._stats("C_exact_miss", path_c, correct=True, notes="provider miss only"),
            "D_exact_hit": self._stats(
                "D_exact_hit", path_d, correct=True, notes="0 provider/embed/verifier on measured hit"
            ),
            "E_verified_semantic_hit": self._stats(
                "E_verified_semantic_hit", path_e, correct=not stopped, notes="Class-A paraphrase pairs"
            ),
            "F_semantic_reject_provider": self._stats(
                "F_semantic_reject_provider",
                path_f,
                correct=not stopped and not self.safety_stop,
                notes="dangerous-negative pairs; semantic_reject + provider",
            ),
            "G_long_semantic_hit": self._stats(
                "G_long_semantic_hit", path_g, correct=not stopped, notes="max_tokens=180 semantic hit; word-count HTTPS pair"
            ),
        }
        thin_p50 = stats["B_thin_proxy_bypass"].p50_ms
        direct_p50 = stats["A_direct_openai"].p50_ms
        exact_hit_p50 = stats["D_exact_hit"].p50_ms
        exact_miss_p50 = stats["C_exact_miss"].p50_ms
        sem_hit_p50 = stats["E_verified_semantic_hit"].p50_ms
        sem_reject_p50 = stats["F_semantic_reject_provider"].p50_ms
        long_sem_p50 = stats["G_long_semantic_hit"].p50_ms

        comparative = {
            "thin_proxy_overhead_p50_ms": thin_p50 - direct_p50,
            "thin_proxy_overhead_p50_pct": (
                ((thin_p50 - direct_p50) / direct_p50 * 100.0) if direct_p50 else None
            ),
            "exact_hit_speedup_vs_thin_proxy_p50_ms": thin_p50 - exact_hit_p50,
            "exact_hit_speedup_vs_exact_miss_p50_ms": exact_miss_p50 - exact_hit_p50,
            "semantic_hit_p50_ms": sem_hit_p50,
            "research_verified_hit_p50_reference_ms": 743,
            "semantic_hit_vs_thin_proxy_p50_ms": thin_p50 - sem_hit_p50,
            "semantic_hit_vs_exact_miss_p50_ms": exact_miss_p50 - sem_hit_p50,
            "long_semantic_hit_p50_ms": long_sem_p50,
            "long_semantic_vs_thin_proxy_saved_ms": thin_p50 - long_sem_p50,
            "semantic_reject_penalty_vs_bypass_p50_ms": sem_reject_p50 - thin_p50,
        }

        return {
            "timestamp": run_started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": parse_git_commit(),
            "branch": "feat/v0.2-observability-release",
            "version": "0.2.0",
            "methodology": "v0.2 seven-path controlled benchmark with per-iteration isolation for semantic paths",
            "safety_stop": self.safety_stop or stopped,
            "iterations_target": self.iterations,
            "run_id": self.run_id,
            "path_statistics": {k: asdict(v) for k, v in stats.items()},
            "comparative_metrics": comparative,
            "raw_iterations": {
                "A": [asdict(r) for r in path_a],
                "B": [asdict(r) for r in path_b],
                "C": [asdict(r) for r in path_c],
                "D": [asdict(r) for r in path_d],
                "E": [asdict(r) for r in path_e],
                "F": [asdict(r) for r in path_f],
                "G": [asdict(r) for r in path_g],
            },
            "invalid_iterations": self.invalid_log,
            "limitations": [
                "Client-side latency includes network variance",
                "Semantic paths restart gateway per iteration for isolation",
                "Prometheus counters are process-lifetime; deltas used per request",
            ],
        }


async def cross_check(api_key: str, gateway_url: str) -> dict[str, Any]:
    metrics = await fetch_metrics(gateway_url)
    async with httpx.AsyncClient() as client:
        reqs = await client.get(
            f"{gateway_url}/v1/requests",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 200},
            timeout=30.0,
        )
        reqs.raise_for_status()
        req_data = reqs.json()
    project_id = await resolve_benchmark_project_id(api_key)
    async with async_session_factory() as db:
        from app.db.models.cache_entry import CacheEntryRecord
        from app.db.models.request import RequestLog

        cache_count = await db.scalar(
            select(func.count())
            .select_from(CacheEntryRecord)
            .where(CacheEntryRecord.project_id == project_id)
        )
        req_count = await db.scalar(
            select(func.count()).select_from(RequestLog).where(RequestLog.project_id == project_id)
        )
        cache_hits = await db.scalar(
            select(func.count())
            .select_from(RequestLog)
            .where(RequestLog.project_id == project_id, RequestLog.cache_hit.is_(True))
        )

    return {
        "prometheus_cache_operations": metrics.cache_operations,
        "prometheus_requests_by_cache_result": metrics.requests_total,
        "prometheus_provider_requests_openai_success": metrics.provider_requests,
        "postgres_benchmark_project": {
            "project_id": str(project_id),
            "cache_entries": cache_count,
            "request_logs": req_count,
            "cache_hit_rows": cache_hits,
        },
        "requests_api_sample_total": req_data.get("total"),
        "note": (
            "Request logs expose cache_hit bool only; Prometheus cache_result label is authoritative "
            "for exact_hit/semantic_hit/bypass/miss. cache_operations counters include semantic_reject "
            "and store at operation granularity."
        ),
    }


async def main_async(args: argparse.Namespace) -> None:
    env_meta: dict[str, Any] = {}
    if args.setup or args.run:
        env_meta = setup_environment()
        await wait_for_gateway(args.gateway_url)
    env = await verify_environment(args.gateway_url, args.prometheus_url)
    env.update(env_meta)

    api_key, project_id = await resolve_api_key(args.api_key)
    print(f"Benchmark project_id={project_id}")

    if args.setup and not args.run:
        await isolate_benchmark(api_key, args.gateway_url)
        print("Setup complete.")
        return

    if not args.run:
        parser = argparse.ArgumentParser()
        parser.error("Pass --setup and/or --run")

    await isolate_benchmark(api_key, args.gateway_url)
    run_id = uuid.uuid4().hex[:10]
    runner = BenchmarkRunner(
        api_key=api_key,
        gateway_url=args.gateway_url,
        iterations=args.iterations,
        run_id=run_id,
    )
    report = await runner.run_all()
    report["environment"] = env
    report["benchmark_project_id"] = str(project_id)
    report["cross_check"] = await cross_check(api_key, args.gateway_url)

    out_path = FINAL_OUTPUT_PATH if args.final else OUTPUT_PATH
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    if report.get("safety_stop"):
        raise SystemExit("SAFETY STOP: dangerous semantic false accept detected")


def main() -> None:
    parser = argparse.ArgumentParser(description="v0.2 controlled heavy benchmark")
    parser.add_argument("api_key", nargs="?", help="Dedicated benchmark API key")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--setup", action="store_true", help="Build/restart stack + migrate")
    parser.add_argument("--run", action="store_true", help="Execute benchmark paths")
    parser.add_argument(
        "--final",
        action="store_true",
        help="Write docs/benchmark_v2_final_validation.json (preserves first diagnostic artifact)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
