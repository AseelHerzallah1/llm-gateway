# Benchmark — Gateway vs Direct OpenAI

Measured proxy overhead for non-streaming `POST /v1/chat/completions` on local dev hardware.

**Scripts:**
- `scripts/benchmark_latency.py` — direct vs gateway comparison
- `scripts/benchmark_decompose.py` — isolate embedding cost vs chat cost

**Raw output:**
- Before optimization: `docs/benchmark_results_before.json`
- After optimization: re-run → `docs/benchmark_results_after.json`
- Decomposition: `docs/benchmark_decompose.json`

---

## Question

How much latency does the gateway add compared to calling OpenAI directly — and **where** does that time go?

A benchmark that only shows “gateway is slower” is not enough. We decomposed the path, fixed the worst miss-path waste, and re-measure.

---

## Setup

| Item | Value |
|------|-------|
| Model | `gpt-4o-mini` |
| Gateway | `http://127.0.0.1:8001` (local uvicorn) |
| Direct baseline | `https://api.openai.com/v1/chat/completions` |
| Iterations | 5 timed requests (+ warmup for latency script) |
| Prompt | Unique per iteration (avoids semantic cache hits) |
| `max_tokens` | 10 |

---

## Phase 1 — Before optimization (2026-07-22)

| Target | p50 | p95 |
|--------|-----|-----|
| Direct OpenAI | 791 ms | 1000 ms |
| LLM Gateway | 1535 ms | 2248 ms |
| **Overhead** | **+744 ms** | **+1248 ms** |

### Root cause (decomposition)

We added `scripts/benchmark_decompose.py` to time three paths separately:

| Path | What it measures |
|------|------------------|
| `direct_chat` | OpenAI chat completion only |
| `direct_embed` | OpenAI `/embeddings` only (same text shape as cache lookup) |
| `gateway_chat` | Full gateway proxy |

**Decompose sample (2026-07-23):**

| Target | p50 |
|--------|-----|
| direct_chat | 938 ms |
| direct_embed | **260 ms** |
| gateway_chat | _(re-run with valid gateway key)_ |

**Findings from code + decompose:**

1. **Duplicate embedding on cache miss** — lookup embedded the prompt, then store embedded again after the provider returned (~2× embed cost).
2. **Lookup embedded even when unnecessary** — no fast path when no cache entries exist for project/model.
3. **Request logging blocked the response** — `persist_request_log()` ran synchronously before returning JSON.

Embedding alone is ~260 ms p50. Two embed calls ≈ **520 ms** of the ~744 ms overhead — the dominant waste.

---

## Phase 2 — Optimizations applied (2026-07-23)

| Change | File | Effect |
|--------|------|--------|
| Skip lookup when no cache entries | `app/cache/memory.py`, `chat_integration.py` | No embed call when cache cannot hit |
| Reuse lookup embedding on store | `chat_integration.py`, `chat.py` | One embed per miss instead of two |
| Async request logging | `app/routes/chat.py`, `REQUEST_LOG_ASYNC` | DB write off critical path |
| `SEMANTIC_CACHE_ENABLED` config | `app/config.py` | Optional thin-proxy mode |

**Expected improvement on cache-miss path:** ~250–350 ms p50 overhead reduction (one fewer embed + async log).

---

## Phase 3 — Re-measure (you run this)

```powershell
# 1. Restart gateway after pulling changes
uvicorn app.main:app --host 127.0.0.1 --port 8001

# 2. Set a valid gateway key in .env
# GATEWAY_TEST_API_KEY=gw-sk-...   (from seed_test_project.py)

# 3. Decompose
python scripts/benchmark_decompose.py --iterations 10

# 4. Before/after comparison
python scripts/benchmark_latency.py --iterations 10 --output docs/benchmark_results_after.json
```

Compare `benchmark_results_before.json` vs `benchmark_results_after.json`.

---

## Config knobs

| Env var / header | Default | Purpose |
|------------------|---------|---------|
| `SEMANTIC_CACHE_ENABLED` | `true` | Set `false` to measure thin-proxy latency (no embed on miss) |
| `REQUEST_LOG_ASYNC` | `true` | Set `false` to restore synchronous DB logging |
| `X-Gateway-Bypass-Cache: true` | off | Benchmark script sends this — skips embed lookup/store for that request |

### Two valid overhead measurements

| Mode | Typical p50 overhead | When to cite |
|------|----------------------|--------------|
| **Thin proxy** (bypass header or cache disabled) | ~+88 ms | Minimum auth + logging cost |
| **Cache-on miss** (semantic cache enabled, warm DB) | ~+460–620 ms | Realistic miss path including one embed |

Do not compare these as “before/after optimizations” — they measure different code paths. See `docs/benchmark_results_after_fix.json` vs `docs/benchmark_results_after.json`.

---

## Honest limitations

| Limitation | Impact |
|------------|--------|
| Small sample sizes | Use 20+ iterations for stable p95 |
| Hydrated cache at startup | After first request, `has_entries` is true — benchmark still does 1 embed on miss, not 0 |
| Non-streaming only | Streaming profile differs |
| Client-side timing | Includes network variance |

---

## Summary

Gateway overhead was decomposed (not just “gateway is slower”): duplicate embedding on cache miss was the dominant waste (~520 ms of ~744 ms before optimization). Fixes — reuse lookup embedding, skip lookup when cache empty, async logging — are documented with before/after JSON in this folder. Cite **+88 ms p50** only for thin-proxy / bypass mode (`benchmark_results_after_fix.json`); cache-on miss overhead is higher (~+460–620 ms).
