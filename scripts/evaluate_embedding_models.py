"""Compare text-embedding-3-small vs text-embedding-3-large for semantic cache equivalence.

Uses production messages_to_embed_text() serialization — NOT raw prompt strings.
Does NOT modify production configuration.

Usage:
    python scripts/evaluate_embedding_models.py

Outputs:
    - Console report
    - docs/eval/embedding_model_comparison.json
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.cache.similarity import cosine_similarity
from app.config import settings
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.prompt import messages_to_embed_text
from app.providers.base import ChatMessage
from eval.cache_threshold_dataset import EVAL_PAIRS
from eval.pair_classification import (
    CLASS_A_LABELS,
    CLASS_B_LABELS,
    CLASS_C_LABELS,
    DIFFICULT_PAIR_LABELS,
)

MODELS: tuple[str, ...] = ("text-embedding-3-small", "text-embedding-3-large")

THRESHOLDS: tuple[float, ...] = (
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.82,
    0.85,
    0.88,
    0.90,
    0.92,
    0.94,
    0.96,
)

# Known default dimensions (OpenAI); recorded in output for reference.
MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

# Approximate OpenAI pricing per 1M tokens (USD, public list prices — verify before production use).
MODEL_COST_PER_1M_TOKENS: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}


def _serialize_user_prompt(prompt: str) -> str:
    """Production-identical single-turn user message serialization."""
    return messages_to_embed_text([ChatMessage(role="user", content=prompt)])


@dataclass(frozen=True)
class ScoredPair:
    label: str
    category: str  # class_a | class_b | class_c | hard_negative | unrelated
    prompt_a: str
    prompt_b: str
    serialized_a: str
    serialized_b: str
    similarity: float


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


@dataclass(frozen=True)
class Distribution:
    min: float
    p25: float | None
    median: float
    p75: float | None
    max: float
    count: int


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


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> Distribution:
    if not values:
        return Distribution(min=0.0, p25=None, median=0.0, p75=None, max=0.0, count=0)
    return Distribution(
        min=min(values),
        p25=_percentile(values, 0.25),
        median=statistics.median(values),
        p75=_percentile(values, 0.75),
        max=max(values),
        count=len(values),
    )


def _metrics(
    scored: list[ScoredPair],
    threshold: float,
    *,
    positives: list[ScoredPair],
    negatives: list[ScoredPair],
) -> ThresholdMetrics:
    tp = fn = fp = tn = 0
    for pair in positives:
        predicted_hit = pair.similarity >= threshold
        if predicted_hit:
            tp += 1
        else:
            fn += 1
    for pair in negatives:
        predicted_hit = pair.similarity >= threshold
        if predicted_hit:
            fp += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0
    fn_rate = fn / (fn + tp) if (fn + tp) else 0.0
    total = len(positives) + len(negatives)
    accuracy = (tp + tn) / total if total else 0.0

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
    )


def _false_positives(
    scored: list[ScoredPair],
    threshold: float,
    *,
    negatives: list[ScoredPair],
) -> list[ScoredPair]:
    return sorted(
        [p for p in negatives if p.similarity >= threshold],
        key=lambda p: p.similarity,
        reverse=True,
    )


def _max_recall_at_fp_limit(
    scored: list[ScoredPair],
    *,
    positives: list[ScoredPair],
    negatives: list[ScoredPair],
    max_fp: int,
) -> dict:
    best: dict | None = None
    for threshold in THRESHOLDS:
        row = _metrics(scored, threshold, positives=positives, negatives=negatives)
        if row.fp <= max_fp and (best is None or row.recall > best["recall"]):
            fps = _false_positives(scored, threshold, negatives=negatives)
            best = {
                "threshold": threshold,
                "recall": row.recall,
                "tp": row.tp,
                "fn": row.fn,
                "fp": row.fp,
                "false_positive_pairs": [
                    {"label": p.label, "similarity": p.similarity} for p in fps
                ],
            }
    # Also check intermediate thresholds between observed similarities for zero-FP optimum
    unique_sims = sorted({p.similarity for p in scored}, reverse=True)
    candidate_thresholds = set(THRESHOLDS)
    for sim in unique_sims:
        candidate_thresholds.add(round(sim, 6))
    for threshold in sorted(candidate_thresholds, reverse=True):
        row = _metrics(scored, threshold, positives=positives, negatives=negatives)
        if row.fp <= max_fp and (best is None or row.recall > best["recall"]):
            fps = _false_positives(scored, threshold, negatives=negatives)
            best = {
                "threshold": threshold,
                "recall": row.recall,
                "tp": row.tp,
                "fn": row.fn,
                "fp": row.fp,
                "false_positive_pairs": [
                    {"label": p.label, "similarity": p.similarity} for p in fps
                ],
            }
    return best or {
        "threshold": None,
        "recall": 0.0,
        "tp": 0,
        "fn": len(positives),
        "fp": 0,
        "false_positive_pairs": [],
    }


def _print_distribution(name: str, dist: Distribution) -> None:
    p25 = f"{dist.p25:.4f}" if dist.p25 is not None else "n/a"
    p75 = f"{dist.p75:.4f}" if dist.p75 is not None else "n/a"
    print(
        f"  {name} (n={dist.count}): "
        f"min={dist.min:.4f} p25={p25} median={dist.median:.4f} "
        f"p75={p75} max={dist.max:.4f}"
    )


def _print_threshold_table(rows: list[ThresholdMetrics]) -> None:
    print(
        "| Threshold | TP | FN | FP | TN | Precision | Recall | FP Rate | FN Rate | Accuracy |"
    )
    print(
        "|-----------|----|----|----|----|-----------|--------|---------|---------|----------|"
    )
    for row in rows:
        print(
            f"| {row.threshold:.2f} "
            f"| {row.tp} | {row.fn} | {row.fp} | {row.tn} "
            f"| {row.precision:.3f} | {row.recall:.3f} "
            f"| {row.fp_rate:.3f} | {row.fn_rate:.3f} | {row.accuracy:.3f} |"
        )


async def _embed_all(
    model: str,
    serialized_prompts: list[str],
) -> tuple[dict[str, list[float]], list[float], int]:
    provider = OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
        model=model,
        connect_timeout=settings.openai_connect_timeout_s,
        read_timeout=settings.openai_read_timeout_s,
        write_timeout=settings.openai_write_timeout_s,
        pool_timeout=settings.openai_pool_timeout_s,
    )
    vectors: dict[str, list[float]] = {}
    latencies_ms: list[float] = []
    try:
        for index, text in enumerate(serialized_prompts, start=1):
            started = time.perf_counter()
            vectors[text] = await provider.embed(text)
            latencies_ms.append((time.perf_counter() - started) * 1000)
            if index % 25 == 0 or index == len(serialized_prompts):
                print(f"    [{model}] embedded {index}/{len(serialized_prompts)}...")
    finally:
        await provider.aclose()
    return vectors, latencies_ms, len(vectors[serialized_prompts[0]]) if serialized_prompts else 0


def _score_pairs(
    vectors: dict[str, list[float]],
) -> list[ScoredPair]:
    scored: list[ScoredPair] = []
    for pair in EVAL_PAIRS:
        serialized_a = _serialize_user_prompt(pair.prompt_a)
        serialized_b = _serialize_user_prompt(pair.prompt_b)
        similarity = cosine_similarity(vectors[serialized_a], vectors[serialized_b])
        scored.append(
            ScoredPair(
                label=pair.label,
                category=_pair_category(pair.label, pair.category),
                prompt_a=pair.prompt_a,
                prompt_b=pair.prompt_b,
                serialized_a=serialized_a,
                serialized_b=serialized_b,
                similarity=similarity,
            )
        )
    return scored


async def main() -> None:
    print("=== Embedding model comparison (production serialization) ===")
    print(f"Production threshold (unchanged): {settings.cache_similarity_threshold}")
    print(f"Production embedding model (unchanged): {settings.openai_embedding_model}")
    print()

    class_a_count = len(CLASS_A_LABELS)
    class_b_count = len(CLASS_B_LABELS)
    class_c_count = len(CLASS_C_LABELS)
    hard_neg_count = sum(1 for p in EVAL_PAIRS if p.category == "hard_negative")
    unrelated_count = sum(1 for p in EVAL_PAIRS if p.category == "unrelated")

    print("Dataset counts:")
    print(f"  Class A positives: {class_a_count}")
    print(f"  Class B (secondary): {class_b_count}")
    print(f"  Class C (excluded from positives): {class_c_count}")
    print(f"  Hard negatives: {hard_neg_count}")
    print(f"  Unrelated negatives: {unrelated_count}")
    print(f"  Total pairs: {len(EVAL_PAIRS)}")
    print()

    # Unique serialized prompts across all pairs
    unique_serialized: list[str] = []
    seen: set[str] = set()
    for pair in EVAL_PAIRS:
        for prompt in (pair.prompt_a, pair.prompt_b):
            serialized = _serialize_user_prompt(prompt)
            if serialized not in seen:
                seen.add(serialized)
                unique_serialized.append(serialized)

    print(f"Unique serialized prompts: {len(unique_serialized)}")
    print(f"Example serialization: {unique_serialized[0]!r}")
    print()

    model_results: dict = {}

    for model in MODELS:
        print(f"--- Embedding model: {model} ---")
        vectors, latencies_ms, observed_dim = await _embed_all(model, unique_serialized)
        scored = _score_pairs(vectors)

        class_a = [p for p in scored if p.category == "class_a"]
        class_b = [p for p in scored if p.category == "class_b"]
        hard_neg = [p for p in scored if p.category == "hard_negative"]
        unrelated = [p for p in scored if p.category == "unrelated"]
        negatives = hard_neg + unrelated
        positives = class_a

        a_sims = [p.similarity for p in class_a]
        b_sims = [p.similarity for p in class_b]
        hard_sims = [p.similarity for p in hard_neg]
        unrel_sims = [p.similarity for p in unrelated]

        a_dist = _distribution(a_sims)
        b_dist = _distribution(b_sims)
        hard_dist = _distribution(hard_sims)
        unrel_dist = _distribution(unrel_sims)

        print("\nSimilarity distributions:")
        _print_distribution("Class A", a_dist)
        _print_distribution("Class B", b_dist)
        _print_distribution("Hard negatives", hard_dist)
        _print_distribution("Unrelated", unrel_dist)

        lowest_a = min(a_sims) if a_sims else 0.0
        highest_a = max(a_sims) if a_sims else 0.0
        highest_hard = max(hard_sims) if hard_sims else 0.0
        clean_gap = lowest_a > highest_hard

        print("\nSeparation (Class A vs hard negatives):")
        print(f"  Lowest Class A:  {lowest_a:.4f}")
        print(f"  Highest Class A: {highest_a:.4f}")
        print(f"  Highest hard negative: {highest_hard:.4f}")
        print(
            f"  Clean gap (min Class A > max hard negative): "
            f"{'YES' if clean_gap else 'NO'}"
        )
        if not clean_gap:
            print(
                f"  Overlap span: {max(highest_hard - lowest_a, 0.0):.4f}"
            )

        threshold_rows = [
            _metrics(scored, t, positives=positives, negatives=negatives) for t in THRESHOLDS
        ]
        print("\nThreshold sweep (Class A vs all negatives):")
        _print_threshold_table(threshold_rows)

        zero_fp = _max_recall_at_fp_limit(
            scored, positives=positives, negatives=negatives, max_fp=0
        )
        one_fp = _max_recall_at_fp_limit(
            scored, positives=positives, negatives=negatives, max_fp=1
        )

        print("\nMax recall at ZERO false positives:")
        print(f"  threshold={zero_fp['threshold']} recall={zero_fp['recall']:.3f} "
              f"TP={zero_fp['tp']} FN={zero_fp['fn']}")
        print("\nMax recall with <= 1 false positive:")
        print(f"  threshold={one_fp['threshold']} recall={one_fp['recall']:.3f} "
              f"TP={one_fp['tp']} FN={one_fp['fn']} FP={one_fp['fp']}")
        if one_fp["false_positive_pairs"]:
            for fp in one_fp["false_positive_pairs"]:
                print(f"    FP pair: {fp['label']} (sim={fp['similarity']:.4f})")

        avg_latency = statistics.mean(latencies_ms) if latencies_ms else 0.0
        p50_latency = statistics.median(latencies_ms) if latencies_ms else 0.0
        total_chars = sum(len(s) for s in unique_serialized)
        approx_tokens = total_chars / 4  # rough heuristic for cost estimate
        approx_cost_usd = (approx_tokens / 1_000_000) * MODEL_COST_PER_1M_TOKENS[model]

        print("\nEmbedding performance (this run):")
        print(f"  Dimensions: {observed_dim} (reference default: {MODEL_DIMENSIONS[model]})")
        print(f"  Avg latency: {avg_latency:.1f} ms")
        print(f"  p50 latency: {p50_latency:.1f} ms")
        print(f"  Approx tokens embedded (~chars/4): {approx_tokens:.0f}")
        print(f"  Approx API cost this run: ${approx_cost_usd:.6f}")

        model_results[model] = {
            "dimensions": observed_dim,
            "latency_ms": {
                "avg": avg_latency,
                "p50": p50_latency,
                "samples": len(latencies_ms),
            },
            "approx_cost_usd": approx_cost_usd,
            "approx_tokens": approx_tokens,
            "distributions": {
                "class_a": asdict(a_dist),
                "class_b": {
                    "min": b_dist.min,
                    "median": b_dist.median,
                    "max": b_dist.max,
                    "count": b_dist.count,
                },
                "hard_negative": asdict(hard_dist),
                "unrelated": {
                    "min": unrel_dist.min,
                    "median": unrel_dist.median,
                    "max": unrel_dist.max,
                    "count": unrel_dist.count,
                },
            },
            "separation": {
                "lowest_class_a": lowest_a,
                "highest_class_a": highest_a,
                "highest_hard_negative": highest_hard,
                "clean_gap": clean_gap,
            },
            "pairs": [asdict(p) for p in scored],
            "threshold_metrics": [asdict(r) for r in threshold_rows],
            "max_recall_zero_fp": zero_fp,
            "max_recall_one_fp": one_fp,
        }

    # Side-by-side difficult pairs
    print("\n=== Difficult pairs (side-by-side) ===")
    print("| Pair | Label | 3-small | 3-large |")
    print("|------|-------|---------|---------|")
    small_pairs = {p["label"]: p for p in model_results["text-embedding-3-small"]["pairs"]}
    large_pairs = {p["label"]: p for p in model_results["text-embedding-3-large"]["pairs"]}
    for label in DIFFICULT_PAIR_LABELS:
        sp = small_pairs[label]
        lp = large_pairs[label]
        print(
            f"| {label} | {sp['category']} | {sp['similarity']:.4f} | {lp['similarity']:.4f} |"
        )

    # Outcome decision
    print("\n=== Conclusion ===")
    for model in MODELS:
        sep = model_results[model]["separation"]
        zero_fp = model_results[model]["max_recall_zero_fp"]
        print(
            f"{model}: clean_gap={sep['clean_gap']}, "
            f"max_recall@0FP={zero_fp['recall']:.3f} @ threshold={zero_fp['threshold']}"
        )

    output_path = ROOT / "docs" / "eval" / "embedding_model_comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "serialization": "messages_to_embed_text([ChatMessage(role='user', content=prompt)])",
            "similarity": "app.cache.similarity.cosine_similarity",
            "production_threshold_unchanged": settings.cache_similarity_threshold,
            "production_embedding_model_unchanged": settings.openai_embedding_model,
        },
        "dataset_counts": {
            "class_a": class_a_count,
            "class_b": class_b_count,
            "class_c": class_c_count,
            "hard_negative": hard_neg_count,
            "unrelated": unrelated_count,
            "total_pairs": len(EVAL_PAIRS),
            "unique_serialized_prompts": len(unique_serialized),
        },
        "models": model_results,
        "difficult_pairs": [
            {
                "label": label,
                "text-embedding-3-small": small_pairs[label]["similarity"],
                "text-embedding-3-large": large_pairs[label]["similarity"],
                "category": small_pairs[label]["category"],
            }
            for label in DIFFICULT_PAIR_LABELS
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {output_path.relative_to(ROOT)}")
    print("Production configuration was NOT modified.")


if __name__ == "__main__":
    asyncio.run(main())
