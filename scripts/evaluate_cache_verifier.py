"""Answer-equivalence verifier experiment for semantic cache rescue.

Two-stage decision: embedding candidate retrieval -> LLM verifier -> safe reuse or miss.
Does NOT modify production configuration.

Usage:
    python scripts/evaluate_cache_verifier.py

Outputs:
    - docs/eval/cache_verifier_responses.json (cached A-side responses, reused)
    - docs/eval/cache_verifier_experiment.json (full results)
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

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import settings
from app.embeddings.prompt import messages_to_embed_text
from app.providers.base import ChatMessage
from eval.cache_threshold_dataset import EVAL_PAIRS
from eval.pair_classification import (
    CLASS_A_LABELS,
    CLASS_B_LABELS,
    CLASS_C_LABELS,
    DIFFICULT_PAIR_LABELS,
)

CANDIDATE_THRESHOLDS: tuple[float, ...] = (0.65, 0.70, 0.75, 0.80)
VERIFIER_MODEL = "gpt-4o-mini"
GENERATION_MODEL = "gpt-4o-mini"
GENERATION_MAX_TOKENS = 150
VERIFIER_MAX_TOKENS = 120

RESPONSES_CACHE = ROOT / "docs" / "eval" / "cache_verifier_responses.json"
SIMILARITY_SOURCE = ROOT / "docs" / "eval" / "embedding_model_comparison.json"
OUTPUT_PATH = ROOT / "docs" / "eval" / "cache_verifier_experiment.json"

DIFFICULT_CASES: tuple[str, ...] = DIFFICULT_PAIR_LABELS + ("pos_inflation",)

# gpt-4o-mini list pricing (USD per 1M tokens — verify against current OpenAI pricing)
VERIFIER_INPUT_COST_PER_1M = 0.15
VERIFIER_OUTPUT_COST_PER_1M = 0.60
GENERATION_INPUT_COST_PER_1M = 0.15
GENERATION_OUTPUT_COST_PER_1M = 0.60

VERIFIER_SYSTEM = """You are a cache safety gate for an LLM API gateway.

Your task is NOT to judge whether two prompts are semantically similar or topically related.

You must decide whether an EXISTING cached response can safely be returned to a NEW request without materially violating the new request's intent, required information, scope, constraints, or format.

Rules:
- reuse=true ONLY if the cached response fully satisfies the new request with no material omission or wrong focus.
- reuse=false if the new request asks for different facts, different scope, different audience, different steps, or a different kind of answer.
- When uncertain, answer reuse=false.
- Respond with JSON only, no markdown fences."""

VERIFIER_USER_TEMPLATE = """ORIGINAL REQUEST (cached):
{request_a}

CACHED RESPONSE (produced for the original request):
{cached_response}

NEW REQUEST:
{request_b}

Return JSON exactly:
{{"reuse": true or false, "reason": "short explanation under 30 words"}}"""


@dataclass(frozen=True)
class ThresholdMetrics:
    threshold: float
    tp: int
    fn: int
    fp: int
    tn: int
    precision: float
    recall: float
    fp_rate: float
    fn_rate: float
    accuracy: float
    class_a_candidates: int
    hard_neg_candidates: int
    unrelated_candidates: int
    verifier_calls: int
    skipped_no_candidate: int


@dataclass(frozen=True)
class VerifierResult:
    reuse: bool
    reason: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int


def _serialize_user_prompt(prompt: str) -> str:
    return messages_to_embed_text([ChatMessage(role="user", content=prompt)])


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
    if not SIMILARITY_SOURCE.exists():
        raise FileNotFoundError(
            f"Missing {SIMILARITY_SOURCE}. Run scripts/evaluate_embedding_models.py first."
        )
    payload = json.loads(SIMILARITY_SOURCE.read_text(encoding="utf-8"))
    pairs = payload["models"]["text-embedding-3-small"]["pairs"]
    return {item["label"]: float(item["similarity"]) for item in pairs}


def _parse_verifier_json(content: str) -> tuple[bool, str]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        reuse = bool(data["reuse"])
        reason = str(data.get("reason", ""))[:200]
        return reuse, reason
    except (json.JSONDecodeError, KeyError, TypeError):
        lowered = text.lower()
        if '"reuse": true' in lowered or '"reuse":true' in lowered:
            return True, text[:200]
        return False, f"unparseable verifier output: {text[:120]}"


def _metrics_at_threshold(
    rows: list[dict],
    threshold: float,
) -> ThresholdMetrics:
    tp = fn = fp = tn = 0
    class_a_candidates = hard_neg_candidates = unrelated_candidates = 0
    verifier_calls = skipped = 0

    for row in rows:
        category = row["category"]
        similarity = row["similarity"]
        candidate = similarity >= threshold
        reuse = row["verifier"]["reuse"] if candidate else False

        if category == "class_a" and candidate:
            class_a_candidates += 1
        if category == "hard_negative" and candidate:
            hard_neg_candidates += 1
        if category == "unrelated" and candidate:
            unrelated_candidates += 1
        if candidate:
            verifier_calls += 1
        else:
            skipped += 1

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

    pos_total = sum(1 for r in rows if _is_primary_positive(r["category"]))
    neg_total = sum(1 for r in rows if _is_primary_negative(r["category"]))

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fp_rate = fp / neg_total if neg_total else 0.0
    fn_rate = fn / pos_total if pos_total else 0.0
    accuracy = (tp + tn) / (pos_total + neg_total) if (pos_total + neg_total) else 0.0

    return ThresholdMetrics(
        threshold=threshold,
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        precision=precision,
        recall=recall,
        fp_rate=fp_rate,
        fn_rate=fn_rate,
        accuracy=accuracy,
        class_a_candidates=class_a_candidates,
        hard_neg_candidates=hard_neg_candidates,
        unrelated_candidates=unrelated_candidates,
        verifier_calls=verifier_calls,
        skipped_no_candidate=skipped,
    )


async def _openai_chat(
    client: httpx.AsyncClient,
    *,
    model: str,
    system: str | None,
    user: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, float, int, int]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    started = time.perf_counter()
    response = await client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    latency_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return (
        content,
        latency_ms,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
    )


async def _ensure_cached_responses(client: httpx.AsyncClient) -> dict[str, dict]:
    if RESPONSES_CACHE.exists():
        cached = json.loads(RESPONSES_CACHE.read_text(encoding="utf-8"))
        if cached.get("model") == GENERATION_MODEL and cached.get("responses"):
            print(f"Loaded {len(cached['responses'])} cached A-side responses")
            return cached

    unique_prompts = sorted({pair.prompt_a for pair in EVAL_PAIRS})
    print(f"Generating {len(unique_prompts)} A-side responses via {GENERATION_MODEL}...")

    responses: dict[str, dict] = {}
    latencies: list[float] = []

    for index, prompt in enumerate(unique_prompts, start=1):
        content, latency_ms, prompt_tokens, completion_tokens = await _openai_chat(
            client,
            model=GENERATION_MODEL,
            system=(
                "Answer the user question clearly and concisely in 2-4 sentences. "
                "Be factual and directly responsive to the exact question asked."
            ),
            user=prompt,
            max_tokens=GENERATION_MAX_TOKENS,
            temperature=0.3,
        )
        responses[prompt] = {
            "response": content.strip(),
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        latencies.append(latency_ms)
        if index % 10 == 0 or index == len(unique_prompts):
            print(f"  generated {index}/{len(unique_prompts)}...")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": GENERATION_MODEL,
        "max_tokens": GENERATION_MAX_TOKENS,
        "latency_ms": {
            "avg": statistics.mean(latencies),
            "p50": statistics.median(latencies),
        },
        "responses": responses,
    }
    RESPONSES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RESPONSES_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {RESPONSES_CACHE.relative_to(ROOT)}")
    return payload


async def _run_verifier(
    client: httpx.AsyncClient,
    *,
    request_a: str,
    request_b: str,
    cached_response: str,
) -> VerifierResult:
    user = VERIFIER_USER_TEMPLATE.format(
        request_a=request_a,
        cached_response=cached_response,
        request_b=request_b,
    )
    content, latency_ms, prompt_tokens, completion_tokens = await _openai_chat(
        client,
        model=VERIFIER_MODEL,
        system=VERIFIER_SYSTEM,
        user=user,
        max_tokens=VERIFIER_MAX_TOKENS,
        temperature=0.0,
    )
    reuse, reason = _parse_verifier_json(content)
    return VerifierResult(
        reuse=reuse,
        reason=reason,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _print_threshold_table(rows: list[ThresholdMetrics]) -> None:
    print(
        "| T | A cand | hard cand | verify | skip | TP | FN | FP | TN | Prec | Recall | FP rate |"
    )
    print(
        "|---|--------|-----------|--------|------|----|----|----|----|------|--------|---------|"
    )
    for row in rows:
        print(
            f"| {row.threshold:.2f} | {row.class_a_candidates} | {row.hard_neg_candidates} "
            f"| {row.verifier_calls} | {row.skipped_no_candidate} | {row.tp} | {row.fn} "
            f"| {row.fp} | {row.tn} | {row.precision:.3f} | {row.recall:.3f} | {row.fp_rate:.3f} |"
        )


async def main() -> None:
    print("=== Answer-equivalence verifier experiment ===")
    print(f"Verifier model: {VERIFIER_MODEL}")
    print(f"Embedding model (retrieval only): text-embedding-3-small")
    print(f"Production threshold unchanged: {settings.cache_similarity_threshold}")
    print()

    similarities = _load_similarities()
    embed_p50_ms = 214.0  # measured in embedding_model_comparison.json
    embed_avg_ms = 253.0

    api_key = settings.openai_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY required")

    client = httpx.AsyncClient(
        base_url=settings.openai_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(60.0),
    )

    try:
        response_cache = await _ensure_cached_responses(client)

        print(f"\nRunning verifier on {len(EVAL_PAIRS)} pairs...")
        experiment_rows: list[dict] = []
        verifier_latencies: list[float] = []
        verifier_prompt_tokens = 0
        verifier_completion_tokens = 0

        for index, pair in enumerate(EVAL_PAIRS, start=1):
            category = _pair_category(pair.label, pair.category)
            cached = response_cache["responses"][pair.prompt_a]
            verifier = await _run_verifier(
                client,
                request_a=pair.prompt_a,
                request_b=pair.prompt_b,
                cached_response=cached["response"],
            )
            verifier_latencies.append(verifier.latency_ms)
            verifier_prompt_tokens += verifier.prompt_tokens
            verifier_completion_tokens += verifier.completion_tokens

            row = {
                "label": pair.label,
                "category": category,
                "prompt_a": pair.prompt_a,
                "prompt_b": pair.prompt_b,
                "similarity": similarities[pair.label],
                "cached_response_preview": cached["response"][:240],
                "verifier": {
                    "reuse": verifier.reuse,
                    "reason": verifier.reason,
                    "latency_ms": verifier.latency_ms,
                    "prompt_tokens": verifier.prompt_tokens,
                    "completion_tokens": verifier.completion_tokens,
                },
            }
            experiment_rows.append(row)
            if index % 10 == 0 or index == len(EVAL_PAIRS):
                print(f"  verified {index}/{len(EVAL_PAIRS)}...")

        threshold_rows = [_metrics_at_threshold(experiment_rows, t) for t in CANDIDATE_THRESHOLDS]

        print("\n=== Candidate retrieval + verifier (Class A vs hard+unrelated) ===")
        _print_threshold_table(threshold_rows)

        # Best threshold: 0 FP, max recall
        safe_rows = [r for r in threshold_rows if r.fp == 0]
        best = max(safe_rows, key=lambda r: (r.recall, r.tp)) if safe_rows else None

        print("\n=== Best safe threshold (0 FP on hard+unrelated) ===")
        if best:
            print(
                f"threshold={best.threshold:.2f} recall={best.recall:.3f} "
                f"TP={best.tp}/14 FP={best.fp} verifier_calls={best.verifier_calls}"
            )
        else:
            print("No threshold achieved 0 false positives.")

        # Class B analysis at best threshold (or 0.75 default for reporting)
        report_threshold = best.threshold if best else 0.75
        class_b_rows = [r for r in experiment_rows if r["category"] == "class_b"]
        b_accept = b_reject = b_no_candidate = 0
        for row in class_b_rows:
            if row["similarity"] < report_threshold:
                b_no_candidate += 1
            elif row["verifier"]["reuse"]:
                b_accept += 1
            else:
                b_reject += 1

        print(f"\n=== Class B at threshold {report_threshold:.2f} (secondary) ===")
        print(f"  verifier accept (reuse=true): {b_accept}")
        print(f"  verifier reject (reuse=false): {b_reject}")
        print(f"  no candidate retrieved: {b_no_candidate}")

        class_c = next(r for r in experiment_rows if r["category"] == "class_c")
        c_candidate = class_c["similarity"] >= report_threshold
        print(
            f"\n=== Class C (pos_inflation) at {report_threshold:.2f} ==="
            f"\n  candidate={c_candidate} verifier_reuse={class_c['verifier']['reuse']}"
        )

        print("\n=== Difficult cases ===")
        print("| Pair | Class | sim | candidate@best | verifier | expected | correct |")
        print("|------|-------|-----|----------------|----------|----------|---------|")
        for label in DIFFICULT_CASES:
            row = next(r for r in experiment_rows if r["label"] == label)
            candidate = row["similarity"] >= report_threshold
            reuse = row["verifier"]["reuse"] if candidate else False
            if row["category"] == "class_a":
                expected = "reuse"
                correct = candidate and reuse
            else:
                expected = "reject"
                correct = not (candidate and reuse)
            print(
                f"| {label} | {row['category']} | {row['similarity']:.4f} | {candidate} "
                f"| {reuse} | {expected} | {correct} |"
            )
            print(f"  reason: {row['verifier']['reason']}")

        verifier_avg_ms = statistics.mean(verifier_latencies)
        verifier_p50_ms = statistics.median(verifier_latencies)
        verified_hit_ms = embed_p50_ms + verifier_p50_ms
        generation_p50_ms = response_cache["latency_ms"]["p50"]

        verifier_cost = (
            verifier_prompt_tokens / 1_000_000 * VERIFIER_INPUT_COST_PER_1M
            + verifier_completion_tokens / 1_000_000 * VERIFIER_OUTPUT_COST_PER_1M
        )
        generation_cost_per_call = (
            statistics.mean(
                [
                    r["prompt_tokens"] / 1_000_000 * GENERATION_INPUT_COST_PER_1M
                    + r["completion_tokens"] / 1_000_000 * GENERATION_OUTPUT_COST_PER_1M
                    for r in response_cache["responses"].values()
                ]
            )
        )

        print("\n=== Latency & economics (measured + reference) ===")
        print(f"  Embed p50 (reference): {embed_p50_ms:.0f} ms")
        print(f"  Verifier avg: {verifier_avg_ms:.0f} ms | p50: {verifier_p50_ms:.0f} ms")
        print(f"  Verified-hit p50 (embed + verifier): {verified_hit_ms:.0f} ms")
        print(f"  Provider generation p50 (A-side cache build): {generation_p50_ms:.0f} ms")
        print(f"  Current semantic hit p50 (benchmark): 291 ms (includes embed, no verifier)")
        print(f"  Thin proxy p50 (benchmark): 615 ms")
        print(f"  Verifier total cost this run ({len(EVAL_PAIRS)} calls): ${verifier_cost:.4f}")
        print(f"  Avg generation cost saved on hit: ~${generation_cost_per_call:.5f}")

        strategy_b_note = (
            "Strategy B (local cross-encoder/NLI) not evaluated: project has no "
            "sentence-transformers or similar dependency; adding one would materially "
            "increase Docker image size and deployment complexity for unproven benefit."
        )

        # Outcome decision
        if best and best.fp == 0 and best.recall >= 0.5 and verified_hit_ms < generation_p50_ms:
            outcome = "A"
        elif best and best.fp == 0 and best.recall >= 0.3:
            outcome = "B"
        else:
            outcome = "C" if not best or best.fp > 0 else "B"

        if best and best.fp == 0 and best.recall >= 0.5:
            if verified_hit_ms >= generation_p50_ms * 0.85:
                outcome = "B"

        print(f"\n=== Outcome: {outcome} ===")

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "methodology": {
                "retrieval_embedding_model": "text-embedding-3-small",
                "serialization": "messages_to_embed_text(user message)",
                "similarity_source": str(SIMILARITY_SOURCE.relative_to(ROOT)),
                "verifier_model": VERIFIER_MODEL,
                "generation_model": GENERATION_MODEL,
                "production_unchanged": True,
            },
            "strategy_b": strategy_b_note,
            "candidate_thresholds": [asdict(r) for r in threshold_rows],
            "best_safe_threshold": asdict(best) if best else None,
            "report_threshold": report_threshold,
            "pairs": experiment_rows,
            "class_b_summary": {
                "accept": b_accept,
                "reject": b_reject,
                "no_candidate": b_no_candidate,
            },
            "latency_ms": {
                "embed_p50_reference": embed_p50_ms,
                "verifier_avg": verifier_avg_ms,
                "verifier_p50": verifier_p50_ms,
                "verified_hit_p50": verified_hit_ms,
                "generation_p50": generation_p50_ms,
                "current_semantic_hit_p50_benchmark": 291,
                "thin_proxy_p50_benchmark": 615,
            },
            "cost_usd": {
                "verifier_total": verifier_cost,
                "avg_generation_per_call": generation_cost_per_call,
            },
            "outcome": outcome,
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")
        print("Production configuration was NOT modified.")

    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
