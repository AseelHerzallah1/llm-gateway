"""Empirical semantic-cache threshold evaluation using real OpenAI embeddings.

Usage:
    python scripts/evaluate_cache_threshold.py

Requires OPENAI_API_KEY in .env. Does NOT change production configuration.

Outputs:
    - Console report (table, distributions, borderline mistakes)
    - docs/eval/cache_threshold_evaluation.json (new artifact; does not overwrite benchmarks)
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.cache.similarity import cosine_similarity
from app.config import settings
from app.embeddings.openai import create_openai_embedding_provider
from eval.cache_threshold_dataset import BORDERLINE_THRESHOLDS, EVAL_PAIRS, THRESHOLDS


@dataclass(frozen=True)
class ScoredPair:
    label: str
    category: str
    prompt_a: str
    prompt_b: str
    similarity: float
    should_hit: bool


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


def _metrics(scored: list[ScoredPair], threshold: float) -> ThresholdMetrics:
    tp = fn = fp = tn = 0
    for pair in scored:
        predicted_hit = pair.similarity >= threshold
        if pair.should_hit and predicted_hit:
            tp += 1
        elif pair.should_hit and not predicted_hit:
            fn += 1
        elif not pair.should_hit and predicted_hit:
            fp += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0
    fn_rate = fn / (fn + tp) if (fn + tp) else 0.0
    accuracy = (tp + tn) / len(scored) if scored else 0.0

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


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "max": 0.0}
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def _mistakes(scored: list[ScoredPair], threshold: float, *, false_positive: bool) -> list[ScoredPair]:
    out: list[ScoredPair] = []
    for pair in scored:
        predicted_hit = pair.similarity >= threshold
        if false_positive and not pair.should_hit and predicted_hit:
            out.append(pair)
        if not false_positive and pair.should_hit and not predicted_hit:
            out.append(pair)
    return sorted(out, key=lambda p: p.similarity, reverse=false_positive)


def _print_table(rows: list[ThresholdMetrics]) -> None:
    header = (
        "| Threshold | TP | FN | FP | TN | Precision | Recall | FP Rate | FN Rate | Accuracy |"
    )
    sep = "|-----------|----|----|----|----|-----------|--------|---------|---------|----------|"
    print(header)
    print(sep)
    for row in rows:
        print(
            f"| {row.threshold:.2f} "
            f"| {row.tp} | {row.fn} | {row.fp} | {row.tn} "
            f"| {row.precision:.3f} | {row.recall:.3f} "
            f"| {row.fp_rate:.3f} | {row.fn_rate:.3f} | {row.accuracy:.3f} |"
        )


async def main() -> None:
    provider = create_openai_embedding_provider()
    unique_prompts = sorted({pair.prompt_a for pair in EVAL_PAIRS} | {pair.prompt_b for pair in EVAL_PAIRS})
    vectors: dict[str, list[float]] = {}

    print(f"Embedding model: {settings.openai_embedding_model}")
    print(f"Production threshold (unchanged): {settings.cache_similarity_threshold}")
    print(f"Unique prompts: {len(unique_prompts)} | Evaluation pairs: {len(EVAL_PAIRS)}")
    print()

    try:
        for index, prompt in enumerate(unique_prompts, start=1):
            vectors[prompt] = await provider.embed(prompt)
            if index % 20 == 0 or index == len(unique_prompts):
                print(f"  embedded {index}/{len(unique_prompts)} prompts...")
    finally:
        await provider.aclose()

    scored: list[ScoredPair] = []
    for pair in EVAL_PAIRS:
        similarity = cosine_similarity(vectors[pair.prompt_a], vectors[pair.prompt_b])
        scored.append(
            ScoredPair(
                label=pair.label,
                category=pair.category,
                prompt_a=pair.prompt_a,
                prompt_b=pair.prompt_b,
                similarity=similarity,
                should_hit=pair.category == "positive",
            )
        )

    positive_sims = [p.similarity for p in scored if p.category == "positive"]
    hard_neg_sims = [p.similarity for p in scored if p.category == "hard_negative"]
    unrelated_sims = [p.similarity for p in scored if p.category == "unrelated"]
    negative_sims = hard_neg_sims + unrelated_sims

    pos_dist = _distribution(positive_sims)
    hard_dist = _distribution(hard_neg_sims)
    neg_dist = _distribution(negative_sims)

    print("\n=== Similarity distribution summary ===")
    print(
        f"Positive pairs (n={len(positive_sims)}): "
        f"min={pos_dist['min']:.4f} median={pos_dist['median']:.4f} max={pos_dist['max']:.4f}"
    )
    print(
        f"Hard-negative pairs (n={len(hard_neg_sims)}): "
        f"min={hard_dist['min']:.4f} median={hard_dist['median']:.4f} max={hard_dist['max']:.4f}"
    )
    print(
        f"All negatives (hard+unrelated, n={len(negative_sims)}): "
        f"min={neg_dist['min']:.4f} median={neg_dist['median']:.4f} max={neg_dist['max']:.4f}"
    )

    overlap = pos_dist["min"] <= neg_dist["max"]
    gap_low = pos_dist["min"] - neg_dist["max"]
    print(
        f"\nOverlap between positive min and negative max: "
        f"{'YES - no clean global separation' if overlap else 'NO - gap exists'}"
    )
    if overlap:
        print(
            f"  positive min ({pos_dist['min']:.4f}) <= negative max ({neg_dist['max']:.4f}); "
            f"overlap span ~ {neg_dist['max'] - pos_dist['min']:.4f}"
        )
    else:
        print(f"  separation gap (positive min - negative max) ~ {gap_low:.4f}")

    threshold_rows = [_metrics(scored, threshold) for threshold in THRESHOLDS]
    print("\n=== Threshold comparison ===")
    _print_table(threshold_rows)

    print("\n=== Borderline false positives (hardest negatives that would HIT) ===")
    for threshold in BORDERLINE_THRESHOLDS:
        fps = _mistakes(scored, threshold, false_positive=True)
        print(f"\nThreshold {threshold:.2f}: {len(fps)} false positive(s)")
        for pair in fps[:8]:
            print(f"  [{pair.similarity:.4f}] {pair.label}")
            print(f"    A: {pair.prompt_a}")
            print(f"    B: {pair.prompt_b}")

    print("\n=== Borderline false negatives (paraphrases that would MISS) ===")
    for threshold in BORDERLINE_THRESHOLDS:
        fns = _mistakes(scored, threshold, false_positive=False)
        print(f"\nThreshold {threshold:.2f}: {len(fns)} false negative(s)")
        for pair in fns[:8]:
            print(f"  [{pair.similarity:.4f}] {pair.label}")
            print(f"    A: {pair.prompt_a}")
            print(f"    B: {pair.prompt_b}")

    # Recommendation logic
    print("\n=== Recommendation (configuration NOT changed) ===")
    current = next(row for row in threshold_rows if row.threshold == 0.92)
    best_balanced = None
    for row in threshold_rows:
        if row.fp == 0 and row.recall >= 0.5:
            best_balanced = row
    if best_balanced is None:
        for row in threshold_rows:
            if row.fp <= 1 and (best_balanced is None or row.recall > best_balanced.recall):
                best_balanced = row

    print(
        f"At production default 0.92: precision={current.precision:.3f}, "
        f"recall={current.recall:.3f}, FP={current.fp}, FN={current.fn}"
    )
    if best_balanced:
        print(
            f"Best trade-off candidate in sweep: {best_balanced.threshold:.2f} "
            f"(precision={best_balanced.precision:.3f}, recall={best_balanced.recall:.3f}, "
            f"FP={best_balanced.fp}, FN={best_balanced.fn})"
        )

    output_dir = ROOT / "docs" / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cache_threshold_evaluation.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": settings.openai_embedding_model,
        "production_threshold_unchanged": settings.cache_similarity_threshold,
        "pair_counts": {
            "positive": len(positive_sims),
            "hard_negative": len(hard_neg_sims),
            "unrelated": len(unrelated_sims),
            "total": len(scored),
        },
        "distributions": {
            "positive": pos_dist,
            "hard_negative": hard_dist,
            "all_negative": neg_dist,
            "overlap_positive_min_with_negative_max": overlap,
        },
        "pairs": [asdict(p) for p in scored],
        "threshold_metrics": [asdict(row) for row in threshold_rows],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
