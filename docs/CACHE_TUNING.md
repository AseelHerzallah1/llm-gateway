# Semantic cache threshold tuning

This document records measured cosine similarities for prompt pairs and explains the default threshold (`0.92`) configured via `CACHE_SIMILARITY_THRESHOLD`.

**Embedding model:** `text-embedding-3-small` (OpenAI)

**Re-run experiments:**

```powershell
python scripts/test_cache_thresholds.py
```

---

## Measured similarities (2026-07-22)

| Pair | Prompt A (short) | Prompt B (short) | Similarity | At 0.92 |
|------|------------------|------------------|------------|---------|
| identical | capital of France? | capital of France? | **1.0000** | HIT |
| paraphrase_capital | capital of France? | capital city of France | **0.8224** | MISS |
| paraphrase_greeting | Say hello in one word | single-word greeting | **0.7230** | MISS |
| diabetes_symptoms_vs_causes | symptoms of diabetes? | causes of diabetes? | **0.5696** | MISS |
| diabetes_symptoms_vs_treatment | symptoms of diabetes? | How is diabetes treated? | **0.4928** | MISS |
| unrelated | capital of France? | bake sourdough bread? | **0.0450** | MISS |

---

## Why 0.92?

**Goal:** maximize cache hits on repeated/near-identical prompts while avoiding **false hits** — returning the wrong answer to a different question.

At **0.92**:

- **Identical prompts always hit** (similarity 1.0).
- **Same topic, different intent misses** — e.g. diabetes *symptoms* vs *causes* (0.57) stays safely below threshold.
- **Light paraphrases miss** — e.g. "capital of France" vs "capital city of France" (0.82) does not hit.

This is a **conservative, safety-first** default: low false-hit risk, but lower paraphrase hit rate.

---

## Trade-off table

| Threshold | Identical | Paraphrase (capital) | Symptoms vs causes | Risk |
|-----------|-----------|----------------------|--------------------|------|
| 0.92 (default) | HIT | MISS | MISS | Lowest false-hit risk |
| 0.85 | HIT | MISS | MISS | Still safe for diabetes pair |
| 0.80 | HIT | HIT | MISS | Paraphrases start hitting |
| 0.70 | HIT | HIT | MISS | More hits; still safe for diabetes pair |
| 0.55 | HIT | HIT | **HIT** | **Unsafe** — symptoms/causes would collide |

**Takeaway:** There is no free lunch. Lower thresholds increase hit rate but raise false-hit risk. The diabetes example (symptoms vs causes) only stays safe while threshold **> ~0.57**.

---

## Hit rate observability

Cache effectiveness is visible in production metrics:

- **`GET /v1/metrics`** → `cache_hit_rate` (from `requests.cache_hit`)
- **`GET /v1/requests?status=cache_hit`** → individual cached responses
- **`cache_entries.use_count`** → how often each stored entry was reused

After tuning threshold, compare `cache_hit_rate` and review request logs for wrong-answer reports.

---

## Recommendations

1. **Keep 0.92 for demos/interviews** — easy to explain: "only near-duplicates hit; different questions on the same topic do not."
2. **Lower to ~0.80–0.85** if paraphrase hits matter more than false-hit safety — re-run `test_cache_thresholds.py` and spot-check answers.
3. **Never go below ~0.58** with this embedding model if you must keep symptoms/causes distinct (measured gap was 0.57).
4. **Future:** pgvector index + per-project thresholds; classifier-based cache gate for high-stakes domains.

---

## Related tests

| Script | Purpose |
|--------|---------|
| `scripts/test_cache_thresholds.py` | Live similarity matrix |
| `scripts/test_cache_hit.py` | E2E identical-prompt hit |
| `scripts/test_cache_persistence.py` | DB store/hydrate/use_count |
| `scripts/test_semantic_cache.py` | Offline cosine + scoping |
