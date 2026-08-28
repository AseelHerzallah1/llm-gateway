"""Evaluate hardened verifier prompt vs baseline on fixed + live-generated responses.

Usage:
    python scripts/evaluate_verifier_hardening.py

Outputs:
    docs/eval/verifier_hardening_experiment.json
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.cache.verifier import parse_verifier_output
from app.config import settings
from app.embeddings.prompt import messages_to_embed_text
from app.providers.base import ChatMessage
from eval.cache_threshold_dataset import EVAL_PAIRS
from eval.pair_classification import CLASS_A_LABELS, CLASS_B_LABELS, CLASS_C_LABELS

CANDIDATE_THRESHOLD = 0.65
VERIFIER_MODEL = "gpt-4o-mini"
GENERATION_MODEL = "gpt-4o-mini"
GENERATION_MAX_TOKENS = 200
VERIFIER_MAX_TOKENS = 4
LIVE_RESPONSES_PER_PAIR = 3
EMBED_P50_MS = 214.0

RESPONSES_CACHE = ROOT / "docs" / "eval" / "cache_verifier_responses.json"
SIMILARITY_SOURCE = ROOT / "docs" / "eval" / "embedding_model_comparison.json"
OUTPUT_PATH = ROOT / "docs" / "eval" / "verifier_hardening_experiment.json"

OLD_SYSTEM_PROMPT = (
    "Return true ONLY if the exact cached response can safely satisfy the new request "
    "without missing requested information, changing intent, violating constraints, "
    "or answering a different question. Otherwise return false."
)

HARDENED_SYSTEM_PROMPT = (
    "You are the cache reuse safety gate for an LLM API gateway. "
    "This is NOT a semantic similarity or topical overlap task.\n\n"
    "Return true ONLY when ALL are true:\n"
    "1. Request A and Request B share the same PRIMARY user intent and underlying task.\n"
    "2. Any differences are wording, phrasing, or harmless specificity only.\n"
    "3. The cached response directly answers Request B as written, without repurposing "
    "incidental content.\n"
    "4. Request B does not shift to a neighboring concept, operation, subtype, comparison, "
    "direction, or requested task.\n\n"
    "Return false when A and B differ in PRIMARY INTENT — even if the cached response "
    "incidentally mentions information relevant to B. Incidental coverage is NOT sufficient.\n\n"
    "Examples that MUST be false (different primary intent, not paraphrases):\n"
    "- authentication vs authorization\n"
    "- append vs extend (Python lists)\n"
    "- sort vs reverse (Python lists)\n"
    "- Type 1 vs Type 2 diabetes\n\n"
    "When uncertain, return false."
)

USER_TEMPLATE = """ORIGINAL REQUEST (cached):
{request_a}

CACHED RESPONSE (produced for the original request):
{cached_response}

NEW REQUEST:
{request_b}

Answer with exactly one word: true or false"""

LIVE_POSITIVE_LABELS = (
    "pos_https_security",
    "pos_france_capital",
    "pos_python_decorators",
    "pos_wifi",
)
LIVE_NEGATIVE_LABELS = (
    "neg_oauth_auth_vs_authz",
    "neg_list_append_vs_extend",
    "neg_sort_vs_reverse_list",
    "neg_type1_vs_type2_diabetes",
)
CRITICAL_LABELS = LIVE_POSITIVE_LABELS + LIVE_NEGATIVE_LABELS


@dataclass
class VerifierCall:
    reuse: bool | None
    raw: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int


def _serialize(prompt: str) -> str:
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


def _load_similarities() -> dict[str, float]:
    payload = json.loads(SIMILARITY_SOURCE.read_text(encoding="utf-8"))
    pairs = payload["models"]["text-embedding-3-small"]["pairs"]
    return {item["label"]: float(item["similarity"]) for item in pairs}


def _load_responses() -> dict[str, dict]:
    return json.loads(RESPONSES_CACHE.read_text(encoding="utf-8"))["responses"]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def _call_verifier(
    client: httpx.AsyncClient,
    *,
    system_prompt: str,
    request_a: str,
    request_b: str,
    cached_response: str,
) -> VerifierCall:
    user_prompt = USER_TEMPLATE.format(
        request_a=_serialize(request_a),
        cached_response=cached_response,
        request_b=_serialize(request_b),
    )
    started = time.perf_counter()
    response = await client.post(
        "/chat/completions",
        json={
            "model": VERIFIER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": VERIFIER_MAX_TOKENS,
        },
    )
    response.raise_for_status()
    latency_ms = (time.perf_counter() - started) * 1000
    data = response.json()
    raw = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return VerifierCall(
        reuse=parse_verifier_output(raw),
        raw=raw.strip(),
        latency_ms=latency_ms,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )


async def _generate_response(client: httpx.AsyncClient, prompt: str, *, seed: int) -> str:
    response = await client.post(
        "/chat/completions",
        json={
            "model": GENERATION_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3 + seed * 0.1,
            "max_tokens": GENERATION_MAX_TOKENS,
        },
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _evaluate_fixed_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    class_a = [r for r in rows if r["category"] == "class_a" and r["candidate"]]
    hard = [r for r in rows if r["category"] == "hard_negative" and r["candidate"]]
    unrelated = [r for r in rows if r["category"] == "unrelated" and r["candidate"]]
    class_b = [r for r in rows if r["category"] == "class_b" and r["candidate"]]

    tp = sum(1 for r in class_a if r["reuse"] is True)
    fn = sum(1 for r in class_a if r["reuse"] is not True)
    fp = sum(
        1
        for r in hard + unrelated
        if r["reuse"] is True
    )
    tn = sum(
        1
        for r in hard + unrelated
        if r["reuse"] is not True
    )
    neg_total = len(hard) + len(unrelated)
    pos_total = len(class_a)

    critical = {
        label: next((r for r in rows if r["label"] == label), None)
        for label in (
            "neg_oauth_auth_vs_authz",
            "neg_list_append_vs_extend",
            "neg_sort_vs_reverse_list",
            "neg_type1_vs_type2_diabetes",
        )
    }

    latencies = [r["latency_ms"] for r in rows if r.get("candidate") and r.get("latency_ms")]

    return {
        "class_a_recall": tp / pos_total if pos_total else 0.0,
        "class_a_tp": tp,
        "class_a_fn": fn,
        "class_a_total_candidates": pos_total,
        "hard_fp": sum(1 for r in hard if r["reuse"] is True),
        "unrelated_fp": sum(1 for r in unrelated if r["reuse"] is True),
        "total_fp": fp,
        "precision": tp / (tp + fp) if (tp + fp) else 0.0,
        "class_b_accept": sum(1 for r in class_b if r["reuse"] is True),
        "class_b_reject": sum(1 for r in class_b if r["reuse"] is not True),
        "class_b_total_candidates": len(class_b),
        "critical_decisions": {
            label: {
                "reuse": row["reuse"] if row else None,
                "raw": row["raw"] if row else None,
                "similarity": row["similarity"] if row else None,
            }
            for label, row in critical.items()
        },
        "verifier_p50_ms": statistics.median(latencies) if latencies else 0.0,
        "verifier_p95_ms": _percentile(latencies, 0.95),
        "verified_hit_p50_ms": EMBED_P50_MS + (statistics.median(latencies) if latencies else 0.0),
    }


async def _run_fixed_eval(
    client: httpx.AsyncClient,
    *,
    system_prompt: str,
    prompt_name: str,
) -> dict[str, Any]:
    similarities = _load_similarities()
    responses = _load_responses()
    rows: list[dict[str, Any]] = []

    for pair in EVAL_PAIRS:
        category = _pair_category(pair.label, pair.category)
        similarity = similarities[pair.label]
        candidate = similarity >= CANDIDATE_THRESHOLD
        cached = responses[pair.prompt_a]["response"]
        if not candidate:
            rows.append(
                {
                    "label": pair.label,
                    "category": category,
                    "similarity": similarity,
                    "candidate": False,
                    "reuse": None,
                    "raw": "",
                    "latency_ms": 0.0,
                }
            )
            continue

        result = await _call_verifier(
            client,
            system_prompt=system_prompt,
            request_a=pair.prompt_a,
            request_b=pair.prompt_b,
            cached_response=cached,
        )
        rows.append(
            {
                "label": pair.label,
                "category": category,
                "similarity": similarity,
                "candidate": True,
                "reuse": result.reuse,
                "raw": result.raw,
                "latency_ms": result.latency_ms,
            }
        )
        await asyncio.sleep(0.05)

    metrics = _evaluate_fixed_rows(rows)
    return {"prompt_name": prompt_name, "rows": rows, "metrics": metrics}


async def _run_live_response_eval(
    client: httpx.AsyncClient,
    *,
    system_prompt: str,
) -> dict[str, Any]:
    labels = LIVE_POSITIVE_LABELS + LIVE_NEGATIVE_LABELS
    pair_map = {p.label: p for p in EVAL_PAIRS}
    results: list[dict[str, Any]] = []

    for label in labels:
        pair = pair_map[label]
        expected = label.startswith("pos_")
        for seed in range(LIVE_RESPONSES_PER_PAIR):
            cached_response = await _generate_response(client, pair.prompt_a, seed=seed)
            verifier = await _call_verifier(
                client,
                system_prompt=system_prompt,
                request_a=pair.prompt_a,
                request_b=pair.prompt_b,
                cached_response=cached_response,
            )
            passed = verifier.reuse is expected if expected else verifier.reuse is False
            results.append(
                {
                    "label": label,
                    "seed": seed,
                    "expected_reuse": expected,
                    "reuse": verifier.reuse,
                    "raw": verifier.raw,
                    "passed": passed,
                    "response_preview": cached_response[:200],
                }
            )
            await asyncio.sleep(0.05)

    positives = [r for r in results if r["expected_reuse"]]
    negatives = [r for r in results if not r["expected_reuse"]]
    return {
        "results": results,
        "positive_pass_rate": sum(1 for r in positives if r["passed"]) / len(positives),
        "negative_pass_rate": sum(1 for r in negatives if r["passed"]) / len(negatives),
        "negative_failures": [r for r in negatives if not r["passed"]],
        "positive_failures": [r for r in positives if not r["passed"]],
    }


async def main() -> None:
    api_key = settings.openai_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY required")

    client = httpx.AsyncClient(
        base_url=settings.openai_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(90.0),
    )

    try:
        print("=== Fixed-response evaluation (baseline prompt) ===")
        old_fixed = await _run_fixed_eval(client, system_prompt=OLD_SYSTEM_PROMPT, prompt_name="old")
        print(json.dumps(old_fixed["metrics"], indent=2))

        print("\n=== Fixed-response evaluation (hardened prompt) ===")
        hardened_fixed = await _run_fixed_eval(
            client, system_prompt=HARDENED_SYSTEM_PROMPT, prompt_name="hardened"
        )
        print(json.dumps(hardened_fixed["metrics"], indent=2))

        print("\n=== Live-response robustness (hardened prompt) ===")
        live = await _run_live_response_eval(client, system_prompt=HARDENED_SYSTEM_PROMPT)
        print(f"positive pass rate: {live['positive_pass_rate']:.2%}")
        print(f"negative pass rate: {live['negative_pass_rate']:.2%}")
        if live["negative_failures"]:
            print("NEGATIVE FAILURES:")
            for item in live["negative_failures"]:
                print(f"  {item['label']} seed={item['seed']} reuse={item['reuse']} raw={item['raw']!r}")

        hardened = hardened_fixed["metrics"]
        accept_hardened = (
            hardened["total_fp"] == 0
            and live["negative_pass_rate"] == 1.0
            and hardened["class_a_recall"] >= 13 / 14
        )

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_threshold": CANDIDATE_THRESHOLD,
            "verifier_model": VERIFIER_MODEL,
            "old_system_prompt": OLD_SYSTEM_PROMPT,
            "hardened_system_prompt": HARDENED_SYSTEM_PROMPT,
            "old_fixed": old_fixed,
            "hardened_fixed": hardened_fixed,
            "live_response_robustness": live,
            "recommendation": "adopt_hardened_prompt" if accept_hardened else "do_not_adopt",
        }
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {OUTPUT_PATH}")
        print(f"Recommendation: {payload['recommendation']}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
