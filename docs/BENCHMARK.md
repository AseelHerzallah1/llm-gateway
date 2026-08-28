# Benchmark — Gateway vs Direct OpenAI

Measured proxy overhead and cache performance for non-streaming `POST /v1/chat/completions` on local dev hardware.

**Scripts:**
- `scripts/benchmark_cache_v2.py` — v0.2 seven-path cache benchmark (`--final` writes validated artifact)
- `scripts/benchmark_long_provider_baseline.py` — long-response provider baseline for Path G comparison
- `scripts/benchmark_latency.py` — direct vs gateway comparison (v0.1 era)
- `scripts/benchmark_decompose.py` — isolate embedding cost vs chat cost

**Raw output:**
- **v0.2 final validation (2026-08-27):** `docs/benchmark_v2_final_validation.json` — seven paths, 30 iterations each
- **v0.2 long provider baseline:** `docs/benchmark_v2_long_provider_validation.json`
- **v0.2 diagnostic (pre-fix):** `docs/benchmark_v2_validation.json` — engineering evidence only; do not cite as final
- **v0.1 final validation (2026-08-13):** `docs/benchmark_validation_4path.json` — four paths, 30 iterations each
- Before optimization (historical): `docs/benchmark_results_before.json`
- After optimization (historical): `docs/benchmark_results_after.json`, `docs/benchmark_results_after_fix.json`
- Decomposition (historical): `docs/benchmark_decompose.json`

---

## v0.2 final controlled validation (2026-08-27)

Seven-path clean-room run after exact-fingerprint alias fix (commit `7ada540`). **30 iterations per path.** Cache outcomes verified via Prometheus `cache_result` labels and `/v1/requests` cross-check — not inferred from latency alone.

| Path | What it measures | p50 | p95 |
|------|------------------|-----|-----|
| **A** Direct OpenAI | Client → OpenAI only | 1184 ms | 1729 ms |
| **B** Thin proxy | Gateway + `X-Gateway-Bypass-Cache: true` | 971 ms | 1714 ms |
| **C** Exact miss | L1 miss → provider (unique prompts) | 1685 ms | 2158 ms |
| **D** Exact hit | L1 fingerprint reuse | **225 ms** | 548 ms |
| **E** Verified semantic hit | L2 Class-A paraphrase pairs | 1577 ms | 2323 ms |
| **F** Semantic reject + provider | Dangerous-negative pairs | 2269 ms | 2832 ms |
| **G** Long semantic hit | L2 verified reuse, `max_tokens=180` | **1195 ms** | 1564 ms |

Artifact: `docs/benchmark_v2_final_validation.json`

### Portfolio-safe claims (v0.2)

| Claim | Value | Notes |
|-------|-------|-------|
| **L1 exact hit speedup** | **~7.5×** | p50 **225 ms** vs exact miss **1685 ms** |
| **L1 latency reduction vs miss** | **~86.6%** | (1685 − 225) / 1685 |
| **L2 long semantic saving** | **~51.2%** | p50 **1195 ms** vs long provider baseline **2450 ms** (`docs/benchmark_v2_long_provider_validation.json`) — **1255 ms** absolute |
| **L2 short semantic transparency** | p50 **1577 ms** vs bypass **971 ms** | Embed + verifier overhead can exceed generation savings on short outputs — cite honestly |
| **Safety (Path F benchmark)** | **30/30** dangerous candidates rejected | **0 unsafe semantic hits**; provider fallback after rejection — measured evaluation behavior, **not** a formal safety guarantee |

**Do not** compare L1 exact hit latency to direct OpenAI as a “cache vs provider” headline — exact hit measures deterministic reuse within the gateway, not a fair provider baseline.

**Do not** cite `docs/benchmark_v2_validation.json` (diagnostic pre-fix run) as final v0.2 numbers.

### Path definitions (v0.2)

| Path | What it measures |
|------|------------------|
| Direct OpenAI | Client → OpenAI `chat/completions` only |
| Thin proxy | Gateway with bypass header — auth + logging, no embed/cache |
| Exact miss | L1 miss on unique prompt → provider stores entry |
| Exact hit | Identical request identity repeated → L1 fingerprint hit |
| Verified semantic hit | L2 candidate @ ≥ 0.65 + verifier `true` on Class-A paraphrase |
| Semantic reject + provider | Dangerous-negative pair — verifier rejects; provider called |
| Long semantic hit | Long-form Class-A pair (`max_tokens=180`); compared to separate provider baseline script |

---

## v0.1 final controlled validation (2026-08-13)

Clean-room run after resetting PostgreSQL cache/request logs and restarting uvicorn (empty in-memory semantic cache). **30 iterations per path.** Cache miss/hit status verified through `/v1/requests` — not inferred from latency or request order. Cache-miss prompts used semantically distinct math questions to avoid false semantic hits.

| Path | p50 | p95 | p99 |
|------|-----|-----|-----|
| **Direct OpenAI** | 574 ms | 960 ms | 2354 ms |
| **Gateway thin proxy** (cache bypass header) | 615 ms | 2071 ms | 6025 ms |
| **Semantic cache miss** | 908 ms | 2554 ms | 3291 ms |
| **Semantic cache hit** | 291 ms | 357 ms | 365 ms |

### Portfolio-safe claims

| Claim | Value | Notes |
|-------|-------|-------|
| Thin-proxy p50 overhead | **~+41 ms** | vs direct OpenAI (bypass header) |
| Semantic cache hit p50 | **~291 ms** | embed lookup + gateway; **no chat-provider call** |
| Semantic cache hit p99 | **~365 ms** | stable tail because provider is skipped |

**Do not** present thin-proxy p95/p99 differences as steady gateway overhead — provider and network variance dominates tail latency on direct, thin-proxy, and cache-miss paths.

### Path definitions

| Path | What it measures |
|------|------------------|
| Direct OpenAI | Client → OpenAI `chat/completions` only |
| Thin proxy | Gateway with `X-Gateway-Bypass-Cache: true` — auth + async logging, no embed/cache |
| Cache miss | Semantic cache enabled; unique prompts; one embed + provider call |
| Cache hit | Identical prompt repeated; embed lookup + cached response only |

Direct embedding (auxiliary, same run): p50 **219 ms**, p95 240 ms, p99 267 ms.

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

## Phase 1 — Before optimization (2026-07-22) *(historical)*

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

## Phase 2 — Optimizations applied (2026-07-23) *(historical)*

| Change | File | Effect |
|--------|------|--------|
| Skip lookup when no cache entries | `app/cache/memory.py`, `chat_integration.py` | No embed call when cache cannot hit |
| Reuse lookup embedding on store | `chat_integration.py`, `chat.py` | One embed per miss instead of two |
| Async request logging | `app/routes/chat.py`, `REQUEST_LOG_ASYNC` | DB write off critical path |
| `SEMANTIC_CACHE_ENABLED` config | `app/config.py` | Optional thin-proxy mode |

**Expected improvement on cache-miss path:** ~250–350 ms p50 overhead reduction (one fewer embed + async log).

---

## Phase 3 — Re-measure *(historical — superseded by final validation above)*

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

### Two valid overhead measurements *(updated with final validation)*

| Mode | p50 overhead / latency | When to cite |
|------|-------------------------|--------------|
| **Thin proxy** (bypass header or cache disabled) | **~+41 ms** vs direct | Minimum auth + logging cost |
| **Cache-on miss** (semantic cache enabled) | **~+334 ms** vs direct (908 vs 574 ms p50) | Realistic miss path including one embed |
| **Cache hit** | **~291 ms p50** total | No provider call; cite p99 ~365 ms for stable tail |

Historical mid-optimization samples (`benchmark_results_after_fix.json`, `benchmark_results_after.json`) showed ~+88 ms and ~+620 ms thin-proxy/miss overhead on earlier runs with smaller samples — see files for the optimization timeline.

Do not compare historical and final numbers as “before/after optimizations” without noting different sample sizes and run conditions.

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

Gateway overhead was decomposed (not just “gateway is slower”): duplicate embedding on cache miss was the dominant waste (~520 ms of ~744 ms before optimization). Fixes — reuse lookup embedding, skip lookup when cache empty, async logging — are documented with historical before/after JSON in this folder.

**Final validated numbers (2026-08-13):** cite **~+41 ms p50** thin-proxy overhead, **~291 ms p50** semantic cache hit, and **~365 ms p99** cache-hit tail from `docs/benchmark_validation_4path.json`. Provider/network variance affects p95/p99 on direct, thin-proxy, and cache-miss paths.
