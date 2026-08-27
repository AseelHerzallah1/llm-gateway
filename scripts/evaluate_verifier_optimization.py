"""Verifier latency optimization experiment.

Compares verifier model / prompt / input variants against the baseline experiment.
Does NOT modify production configuration.

Usage:
    python scripts/evaluate_verifier_optimization.py

Outputs:
    - docs/eval/verifier_optimization_experiment.json
"""

from __future__ import annotations

import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import settings
from eval.cache_threshold_dataset import EVAL_PAIRS
from eval.pair_classification import CLASS_A_LABELS, CLASS_B_LABELS, CLASS_C_LABELS

CANDIDATE_THRESHOLD = 0.65
EMBED_P50_MS = 214.0  # reference from embedding_model_comparison.json

RESPONSES_CACHE = ROOT / "docs" / "eval" / "cache_verifier_responses.json"
SIMILARITY_SOURCE = ROOT / "docs" / "eval" / "embedding_model_comparison.json"
BASELINE_SOURCE = ROOT / "docs" / "eval" / "cache_verifier_experiment.json"
OUTPUT_PATH = ROOT / "docs" / "eval" / "verifier_optimization_experiment.json"

LATENCY_BENCHMARK_LABELS: tuple[str, ...] = (
    "pos_https_security",
    "pos_france_capital",
    "neg_oauth_auth_vs_authz",
    "neg_list_append_vs_extend",
    "neg_type1_vs_type2_diabetes",
    "pos_wifi",
    "pos_inflation",
    "neg_sort_vs_reverse_list",
)
LATENCY_REPEATS = 4

CRITICAL_LABELS: tuple[str, ...] = (
    "neg_oauth_auth_vs_authz",
    "neg_list_append_vs_extend",
    "neg_sort_vs_reverse_list",
    "neg_type1_vs_type2_diabetes",
    "pos_https_security",
    "pos_france_capital",
    "pos_python_decorators",
    "pos_wifi",
    "pos_inflation",
)

PromptVariant = Literal["A", "B", "C"]
InputStrategy = Literal[1, 2]
ProviderName = Literal["openai", "groq"]

# Candidate models to probe (fast / low-cost only)
CANDIDATE_MODELS: tuple[tuple[ProviderName, str], ...] = (
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4.1-nano"),
    ("openai", "gpt-4.1-mini"),
    ("groq", "llama-3.1-8b-instant"),
    ("groq", "llama-3.3-70b-versatile"),
    ("groq", "gemma2-9b-it"),
)

# Approximate USD per 1M tokens (verify against current pricing)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "gemma2-9b-it": (0.20, 0.20),
}

SYSTEM_STRICT = (
    "You are a cache safety gate. Decide whether an EXISTING cached LLM response can "
    "safely be returned to a NEW request without materially violating the new request's "
    "intent, required information, scope, constraints, or format. "
    "This is NOT a semantic similarity task."
)

SYSTEM_MINIMAL = (
    "Return true ONLY if the exact cached response can safely satisfy the new request "
    "without missing requested information, changing intent, violating constraints, "
    "or answering a different question. Otherwise return false."
)


@dataclass(frozen=True)
class VerifierConfig:
    provider: ProviderName
    model: str
    variant: PromptVariant
    input_strategy: InputStrategy
    config_id: str

    @property
    def max_tokens(self) -> int:
        if self.variant == "B":
            return 4
        if self.variant == "C":
            return 8
        return 80


@dataclass
class VerifierCallResult:
    reuse: bool
    raw: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None


@dataclass
class ConfigEvaluation:
    config: VerifierConfig
    available: bool
    disqualified: bool
    disqualify_reason: str | None
    tp: int
    fn: int
    fp: int
    tn: int
    precision: float
    recall: float
    fp_rate: float
    class_a_recall: float
    latency_avg_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    avg_prompt_tokens: float
    avg_completion_tokens: float
    cost_per_call_usd: float
    verified_hit_p50_ms: float
    pair_decisions: list[dict[str, Any]]
    critical_decisions: dict[str, dict[str, Any]]
    latency_samples: list[float]


def _pair_category(label: str, dataset_category: str) -> str:
    if label in CLASS_A_LABELS:
        return "class_a"
    if label in CLASS_B_LABELS:
        return "class_b"
    if label in CLASS_C_LABELS:
        return "class_c"
    if dataset_category == "hard_negative":
        return "hard_negative"
    return "unrelated"


def _is_primary_positive(category: str) -> bool:
    return category == "class_a"


def _is_primary_negative(category: str) -> bool:
    return category in ("hard_negative", "unrelated")


def _load_similarities() -> dict[str, float]:
    payload = json.loads(SIMILARITY_SOURCE.read_text(encoding="utf-8"))
    pairs = payload["models"]["text-embedding-3-small"]["pairs"]
    return {item["label"]: float(item["similarity"]) for item in pairs}


def _load_responses() -> dict[str, dict]:
    payload = json.loads(RESPONSES_CACHE.read_text(encoding="utf-8"))
    return payload["responses"]


def _build_user_prompt(
    *,
    variant: PromptVariant,
    input_strategy: InputStrategy,
    request_a: str,
    request_b: str,
    cached_response: str,
) -> str:
    if input_strategy == 1:
        body = (
            f"ORIGINAL REQUEST (cached):\n{request_a}\n\n"
            f"CACHED RESPONSE:\n{cached_response}\n\n"
            f"NEW REQUEST:\n{request_b}\n"
        )
    else:
        body = f"CACHED RESPONSE:\n{cached_response}\n\nNEW REQUEST:\n{request_b}\n"

    if variant == "A":
        return body + '\nReturn JSON only: {"reuse": true or false, "reason": "under 30 words"}'
    if variant == "B":
        return body + "\nAnswer with exactly one word: true or false"
    return body + '\nReturn JSON only: {"reuse": true} or {"reuse": false}'


def _parse_output(variant: PromptVariant, content: str) -> tuple[bool, str]:
    text = content.strip()
    if variant == "B":
        lowered = re.sub(r"[^a-z]", "", text.lower())
        if lowered == "true":
            return True, text
        if lowered == "false":
            return False, text
        if "true" in lowered and "false" not in lowered:
            return True, text
        return False, text

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        return bool(data["reuse"]), text
    except (json.JSONDecodeError, KeyError, TypeError):
        lowered = text.lower()
        if '"reuse": true' in lowered or '"reuse":true' in lowered:
            return True, text
        return False, text


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _cost_per_call(model: str, prompt_tokens: float, completion_tokens: float) -> float:
    pricing = MODEL_PRICING.get(model, (0.15, 0.60))
    return (
        prompt_tokens / 1_000_000 * pricing[0]
        + completion_tokens / 1_000_000 * pricing[1]
    )


async def _probe_models(client: httpx.AsyncClient) -> list[tuple[ProviderName, str]]:
    available: list[tuple[ProviderName, str]] = []
    probe_user = _build_user_prompt(
        variant="B",
        input_strategy=1,
        request_a="What is 2+2?",
        request_b="What is two plus two?",
        cached_response="2+2 equals 4.",
    )
    for provider, model in CANDIDATE_MODELS:
        try:
            await _call_verifier(
                client,
                provider=provider,
                model=model,
                variant="B",
                input_strategy=1,
                user_prompt=probe_user,
                max_tokens=4,
            )
            available.append((provider, model))
            print(f"  available: {provider}/{model}")
        except Exception as exc:
            print(f"  unavailable: {provider}/{model} ({exc})")
    return available


async def _call_verifier(
    client: httpx.AsyncClient,
    *,
    provider: ProviderName,
    model: str,
    variant: PromptVariant,
    input_strategy: InputStrategy,
    user_prompt: str,
    max_tokens: int,
) -> VerifierCallResult:
    system = SYSTEM_STRICT if variant == "A" else SYSTEM_MINIMAL
    started = time.perf_counter()

    if provider == "openai":
        base_url = settings.openai_base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
        )
    else:
        base_url = settings.groq_base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
        )

    latency_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    reuse, raw = _parse_output(variant, content)
    return VerifierCallResult(
        reuse=reuse,
        raw=raw,
        latency_ms=latency_ms,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


def _configs_to_run(available: list[tuple[ProviderName, str]]) -> list[VerifierConfig]:
    configs: list[VerifierConfig] = []
    for provider, model in available:
        variants: list[tuple[PromptVariant, InputStrategy]] = []
        if model == "gpt-4o-mini":
            variants = [("B", 1), ("C", 1), ("B", 2), ("C", 2)]
        else:
            variants = [("B", 1), ("C", 1), ("B", 2)]
        for variant, input_strategy in variants:
            configs.append(
                VerifierConfig(
                    provider=provider,
                    model=model,
                    variant=variant,
                    input_strategy=input_strategy,
                    config_id=f"{provider}:{model}:v{variant}:in{input_strategy}",
                )
            )
    return configs


def _evaluate_metrics(pair_rows: list[dict[str, Any]]) -> tuple[int, int, int, int, float, float, float, float]:
    tp = fn = fp = tn = 0
    for row in pair_rows:
        category = row["category"]
        candidate = row["candidate"]
        reuse = row["reuse"] if candidate else False
        if _is_primary_positive(category):
            if candidate and reuse:
                tp += 1
            else:
                fn += 1
        elif _is_primary_negative(category):
            if candidate and reuse:
                fp += 1
            else:
                tn += 1
    pos_total = sum(1 for r in pair_rows if _is_primary_positive(r["category"]))
    neg_total = sum(1 for r in pair_rows if _is_primary_negative(r["category"]))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fp_rate = fp / neg_total if neg_total else 0.0
    class_a_recall = recall
    return tp, fn, fp, tn, precision, recall, fp_rate, class_a_recall


def _load_baseline_evaluation(similarities: dict[str, float], responses: dict[str, dict]) -> ConfigEvaluation:
    baseline = json.loads(BASELINE_SOURCE.read_text(encoding="utf-8"))
    pair_rows: list[dict[str, Any]] = []
    for pair in baseline["pairs"]:
        category = pair["category"]
        candidate = pair["similarity"] >= CANDIDATE_THRESHOLD
        reuse = pair["verifier"]["reuse"] if candidate else False
        pair_rows.append(
            {
                "label": pair["label"],
                "category": category,
                "similarity": pair["similarity"],
                "candidate": candidate,
                "reuse": reuse,
                "raw": pair["verifier"]["reason"],
                "latency_ms": pair["verifier"]["latency_ms"],
                "prompt_tokens": pair["verifier"]["prompt_tokens"],
                "completion_tokens": pair["verifier"]["completion_tokens"],
            }
        )

    tp, fn, fp, tn, precision, recall, fp_rate, class_a_recall = _evaluate_metrics(pair_rows)
    latencies = [r["latency_ms"] for r in pair_rows if r["candidate"]]
    prompt_tokens = [r["prompt_tokens"] for r in pair_rows if r["candidate"]]
    completion_tokens = [r["completion_tokens"] for r in pair_rows if r["candidate"]]

    critical = {
        label: next(r for r in pair_rows if r["label"] == label)
        for label in CRITICAL_LABELS
    }

    return ConfigEvaluation(
        config=VerifierConfig("openai", "gpt-4o-mini", "A", 1, "baseline:gpt-4o-mini:vA:in1"),
        available=True,
        disqualified=fp > 0 or any(
            critical[l]["candidate"] and critical[l]["reuse"]
            for l in ("neg_oauth_auth_vs_authz", "neg_list_append_vs_extend",
                      "neg_sort_vs_reverse_list", "neg_type1_vs_type2_diabetes")
            if l in critical
        ),
        disqualify_reason=None if fp == 0 else "baseline has FP",
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        precision=precision,
        recall=recall,
        fp_rate=fp_rate,
        class_a_recall=class_a_recall,
        latency_avg_ms=statistics.mean(latencies),
        latency_p50_ms=statistics.median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        avg_prompt_tokens=statistics.mean(prompt_tokens),
        avg_completion_tokens=statistics.mean(completion_tokens),
        cost_per_call_usd=_cost_per_call(
            "gpt-4o-mini",
            statistics.mean(prompt_tokens),
            statistics.mean(completion_tokens),
        ),
        verified_hit_p50_ms=EMBED_P50_MS + statistics.median(latencies),
        pair_decisions=pair_rows,
        critical_decisions=critical,
        latency_samples=latencies,
    )


async def _evaluate_config(
    client: httpx.AsyncClient,
    config: VerifierConfig,
    similarities: dict[str, float],
    responses: dict[str, dict],
) -> ConfigEvaluation:
    pair_rows: list[dict[str, Any]] = []
    latency_samples: list[float] = []

    for pair in EVAL_PAIRS:
        category = _pair_category(pair.label, pair.category)
        similarity = similarities[pair.label]
        candidate = similarity >= CANDIDATE_THRESHOLD
        cached = responses[pair.prompt_a]["response"]

        if not candidate:
            pair_rows.append(
                {
                    "label": pair.label,
                    "category": category,
                    "similarity": similarity,
                    "candidate": False,
                    "reuse": False,
                    "raw": "",
                    "latency_ms": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                }
            )
            continue

        user_prompt = _build_user_prompt(
            variant=config.variant,
            input_strategy=config.input_strategy,
            request_a=pair.prompt_a,
            request_b=pair.prompt_b,
            cached_response=cached,
        )
        try:
            result = await _call_verifier(
                client,
                provider=config.provider,
                model=config.model,
                variant=config.variant,
                input_strategy=config.input_strategy,
                user_prompt=user_prompt,
                max_tokens=config.max_tokens,
            )
        except Exception as exc:
            result = VerifierCallResult(
                reuse=False,
                raw="",
                latency_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                error=str(exc),
            )

        pair_rows.append(
            {
                "label": pair.label,
                "category": category,
                "similarity": similarity,
                "candidate": True,
                "reuse": result.reuse,
                "raw": result.raw,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "error": result.error,
            }
        )
        if result.latency_ms:
            latency_samples.append(result.latency_ms)

    # Repeated latency benchmark on subset
    bench_latencies: list[float] = []
    for label in LATENCY_BENCHMARK_LABELS:
        pair = next(p for p in EVAL_PAIRS if p.label == label)
        cached = responses[pair.prompt_a]["response"]
        user_prompt = _build_user_prompt(
            variant=config.variant,
            input_strategy=config.input_strategy,
            request_a=pair.prompt_a,
            request_b=pair.prompt_b,
            cached_response=cached,
        )
        for _ in range(LATENCY_REPEATS):
            try:
                result = await _call_verifier(
                    client,
                    provider=config.provider,
                    model=config.model,
                    variant=config.variant,
                    input_strategy=config.input_strategy,
                    user_prompt=user_prompt,
                    max_tokens=config.max_tokens,
                )
                bench_latencies.append(result.latency_ms)
            except Exception:
                pass
            await asyncio.sleep(0.05)

    report_latencies = bench_latencies if bench_latencies else latency_samples

    tp, fn, fp, tn, precision, recall, fp_rate, class_a_recall = _evaluate_metrics(pair_rows)
    critical = {label: next(r for r in pair_rows if r["label"] == label) for label in CRITICAL_LABELS}

    must_reject = (
        "neg_oauth_auth_vs_authz",
        "neg_list_append_vs_extend",
        "neg_sort_vs_reverse_list",
        "neg_type1_vs_type2_diabetes",
    )
    disqualified = fp > 0 or any(
        critical[l]["candidate"] and critical[l]["reuse"] for l in must_reject if l in critical
    )
    reason = None
    if fp > 0:
        fps = [r["label"] for r in pair_rows if _is_primary_negative(r["category"]) and r["candidate"] and r["reuse"]]
        reason = f"FP on {fps}"
    elif disqualified:
        bad = [l for l in must_reject if critical.get(l, {}).get("candidate") and critical[l].get("reuse")]
        reason = f"unsafe accept on {bad}"

    prompt_tokens = [r["prompt_tokens"] for r in pair_rows if r["candidate"] and r["prompt_tokens"]]
    completion_tokens = [r["completion_tokens"] for r in pair_rows if r["candidate"] and r["completion_tokens"]]

    return ConfigEvaluation(
        config=config,
        available=True,
        disqualified=disqualified,
        disqualify_reason=reason,
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        precision=precision,
        recall=recall,
        fp_rate=fp_rate,
        class_a_recall=class_a_recall,
        latency_avg_ms=statistics.mean(report_latencies) if report_latencies else 0.0,
        latency_p50_ms=statistics.median(report_latencies) if report_latencies else 0.0,
        latency_p95_ms=_percentile(report_latencies, 0.95) if report_latencies else 0.0,
        avg_prompt_tokens=statistics.mean(prompt_tokens) if prompt_tokens else 0.0,
        avg_completion_tokens=statistics.mean(completion_tokens) if completion_tokens else 0.0,
        cost_per_call_usd=_cost_per_call(
            config.model,
            statistics.mean(prompt_tokens) if prompt_tokens else 0.0,
            statistics.mean(completion_tokens) if completion_tokens else 0.0,
        ),
        verified_hit_p50_ms=EMBED_P50_MS + (statistics.median(report_latencies) if report_latencies else 0.0),
        pair_decisions=pair_rows,
        critical_decisions=critical,
        latency_samples=report_latencies,
    )


def _summary_row(ev: ConfigEvaluation) -> dict[str, Any]:
    return {
        "config_id": ev.config.config_id,
        "provider": ev.config.provider,
        "model": ev.config.model,
        "variant": ev.config.variant,
        "input_strategy": ev.config.input_strategy,
        "disqualified": ev.disqualified,
        "tp": ev.tp,
        "fn": ev.fn,
        "fp": ev.fp,
        "tn": ev.tn,
        "precision": ev.precision,
        "recall": ev.recall,
        "class_a_recall": ev.class_a_recall,
        "fp_rate": ev.fp_rate,
        "latency_avg_ms": ev.latency_avg_ms,
        "latency_p50_ms": ev.latency_p50_ms,
        "latency_p95_ms": ev.latency_p95_ms,
        "avg_prompt_tokens": ev.avg_prompt_tokens,
        "avg_completion_tokens": ev.avg_completion_tokens,
        "cost_per_call_usd": ev.cost_per_call_usd,
        "verified_hit_p50_ms": ev.verified_hit_p50_ms,
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(
        "| config | safe | recall | FP | p50 ms | p95 ms | tok out | $/call | hit p50 |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        safe = "no" if row["disqualified"] else "yes"
        print(
            f"| {row['config_id']} | {safe} | {row['class_a_recall']:.3f} | {row['fp']} "
            f"| {row['latency_p50_ms']:.0f} | {row['latency_p95_ms']:.0f} "
            f"| {row['avg_completion_tokens']:.1f} | {row['cost_per_call_usd']:.5f} "
            f"| {row['verified_hit_p50_ms']:.0f} |"
        )


async def main() -> None:
    print("=== Verifier latency optimization experiment ===")
    print(f"Candidate threshold: {CANDIDATE_THRESHOLD}")
    print(f"Baseline preserved at: {BASELINE_SOURCE.relative_to(ROOT)}")
    print()

    if not settings.openai_api_key.get_secret_value():
        raise SystemExit("OPENAI_API_KEY required")

    similarities = _load_similarities()
    responses = _load_responses()

    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    try:
        print("Probing available verifier models...")
        available = await _probe_models(client)
        print()

        baseline = _load_baseline_evaluation(similarities, responses)
        print(
            f"Loaded baseline: recall={baseline.class_a_recall:.3f} "
            f"FP={baseline.fp} p50={baseline.latency_p50_ms:.0f}ms"
        )

        evaluations: list[ConfigEvaluation] = [baseline]
        for config in _configs_to_run(available):
            if config.config_id == baseline.config.config_id:
                continue
            print(f"Evaluating {config.config_id}...")
            evaluations.append(await _evaluate_config(client, config, similarities, responses))

        summary_rows = [_summary_row(ev) for ev in evaluations]
        safe_rows = [r for r in summary_rows if not r["disqualified"]]

        print("\n=== All configurations ===")
        _print_table(summary_rows)

        best_quality = max(safe_rows, key=lambda r: (r["class_a_recall"], -r["fn"])) if safe_rows else None
        fastest_safe = min(safe_rows, key=lambda r: r["latency_p50_ms"]) if safe_rows else None

        def score(row: dict[str, Any]) -> float:
            # Balance recall and latency; penalize FN heavily
            return row["class_a_recall"] * 100 - row["latency_p50_ms"] / 20 - row["fp"] * 50

        best_overall = max(safe_rows, key=score) if safe_rows else None

        print("\n=== Rankings (safe only) ===")
        if best_quality:
            print(f"Best quality: {best_quality['config_id']} recall={best_quality['class_a_recall']:.3f}")
        if fastest_safe:
            print(f"Fastest safe: {fastest_safe['config_id']} p50={fastest_safe['latency_p50_ms']:.0f}ms")
        if best_overall:
            print(f"Best overall: {best_overall['config_id']}")

        # Inflation response-level analysis
        inflation_cached = responses["What is inflation in economics?"]["response"]
        print("\n=== Inflation Class-C response-level note ===")
        print(f"Cached response for A: {inflation_cached[:300]}...")
        print(
            "Prompt B asks to define inflation AND explain how it affects prices. "
            "Cached response defines inflation and mentions rising prices/purchasing power "
            "but does not explicitly explain consumer price impact in depth."
        )

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "methodology": {
                "candidate_threshold": CANDIDATE_THRESHOLD,
                "embedding_model": "text-embedding-3-small",
                "baseline_source": str(BASELINE_SOURCE.relative_to(ROOT)),
                "responses_source": str(RESPONSES_CACHE.relative_to(ROOT)),
                "latency_repeats_per_benchmark_pair": LATENCY_REPEATS,
                "latency_benchmark_pairs": list(LATENCY_BENCHMARK_LABELS),
                "production_unchanged": True,
            },
            "available_models": [{"provider": p, "model": m} for p, m in available],
            "baseline_reference": {
                "verifier_p50_ms": 942,
                "verified_hit_p50_ms": 1156,
                "class_a_recall": 0.929,
                "fp_hard_unrelated": 0,
            },
            "historical_latency_reference": {
                "current_cosine_only_hit_p50_ms": 291,
                "thin_proxy_p50_ms": 615,
                "short_cache_miss_p50_ms": 908,
                "longer_generation_p50_ms": 1511,
                "note": "Historical benchmark numbers — not remeasured in this run",
            },
            "optional_pregates": {
                "unrelated_never_retrieved_at_065": True,
                "different_model_must_not_reuse": "design rule — not implemented",
                "multi_turn_disallow_semantic": "design rule — dataset is single-turn",
                "time_sensitive_keywords": "future optional gate — not implemented in experiment",
            },
            "local_verifier_feasibility": {
                "implemented": False,
                "reason": (
                    "No sentence-transformers/cross-encoder in project. Typical cross-encoder "
                    "models (e.g. ms-marco-MiniLM, 80-130MB) measure passage relevance, not "
                    "'can cached answer satisfy new question'. Would add Docker weight and "
                    "still miss response-aware equivalence without cached response text in "
                    "standard NLI pairs. Recommend separate experiment if pursued."
                ),
                "estimated_cpu_latency_ms": "20-80ms per pair for MiniLM-L6 cross-encoder on CPU",
                "docker_impact": "moderate (+100-400MB depending on torch install)",
            },
            "configurations": summary_rows,
            "disqualified": [
                {
                    "config_id": r["config_id"],
                    "reason": next(
                        e.disqualify_reason for e in evaluations if e.config.config_id == r["config_id"]
                    ),
                }
                for r in summary_rows
                if r["disqualified"]
            ],
            "rankings": {
                "best_quality": best_quality,
                "fastest_safe": fastest_safe,
                "best_overall": best_overall,
            },
            "inflation_analysis": {
                "prompt_a": "What is inflation in economics?",
                "prompt_b": "Define inflation and how it affects prices.",
                "cached_response": inflation_cached,
                "prompt_level_label": "class_c — should not reuse",
                "response_level_note": (
                    "Cached response mentions rising prices and decreased purchasing power; "
                    "verifier may reasonably judge partial satisfaction. Label ambiguity noted."
                ),
            },
            "detailed_evaluations": [
                {
                    "summary": _summary_row(ev),
                    "critical_decisions": ev.critical_decisions,
                    "class_b_summary": {
                        "accept": sum(
                            1
                            for r in ev.pair_decisions
                            if r["category"] == "class_b" and r["candidate"] and r["reuse"]
                        ),
                        "reject": sum(
                            1
                            for r in ev.pair_decisions
                            if r["category"] == "class_b" and r["candidate"] and not r["reuse"]
                        ),
                    },
                }
                for ev in evaluations
            ],
        }

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {OUTPUT_PATH.relative_to(ROOT)}")
        print("Production configuration was NOT modified.")

    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
