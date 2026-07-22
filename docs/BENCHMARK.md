# Benchmark — Gateway vs Direct OpenAI

Measured proxy overhead for non-streaming `POST /v1/chat/completions` on local dev hardware.

**Run date:** 2026-07-22  
**Script:** `scripts/benchmark_latency.py`  
**Raw output:** `docs/benchmark_results.json`

---

## Question

How much latency does the gateway add compared to calling OpenAI directly?

This matters for portfolio interviews: a proxy must justify its cost (auth, logging, cache, routing) with measurable overhead — not hand-waving.

---

## Setup

| Item | Value |
|------|-------|
| Model | `gpt-4o-mini` |
| Gateway | `http://127.0.0.1:8001` (local uvicorn) |
| Direct baseline | `https://api.openai.com/v1/chat/completions` |
| Iterations | 5 timed requests (+ 1 warmup each side) |
| Prompt | Unique per iteration (avoids semantic cache hits) |
| `max_tokens` | 10 |
| Network | Home broadband, Windows 11 |

**Why not LiteLLM?** LiteLLM is another proxy layer with a different feature set (routing, caching, callbacks). For v1 we benchmark against **direct OpenAI** — the fairest baseline for “what does *my* gateway add?” LiteLLM comparison is optional future work.

---

## Methodology

1. **Warmup** — one request to each target (excluded from stats)
2. **Measure client-side total latency** — time from HTTP POST start to full JSON response
3. **Same payload shape** — OpenAI-compatible chat completion body on both paths
4. **Unique prompt suffix** — prevents semantic cache from making gateway look artificially fast
5. **Report p50 / p95 / p99** — using the same percentile helper as `/v1/metrics`

**What is included in gateway latency:**
- API key auth (PostgreSQL lookup + bcrypt verify)
- Semantic cache path (OpenAI embedding call + in-memory cosine search) — **even on cache miss**
- Provider proxy to OpenAI
- Request logging to PostgreSQL

**What is excluded:**
- Streaming (separate benchmark recommended for v2)
- Cache hits (would show gateway faster — measured separately in Phase 6)

---

## Results (2026-07-22)

| Target | p50 | p95 | p99 | Errors |
|--------|-----|-----|-----|--------|
| Direct OpenAI | 791 ms | 1000 ms | 1012 ms | 0 |
| LLM Gateway | 1535 ms | 2248 ms | 2348 ms | 0 |

| Overhead metric | Value |
|-----------------|-------|
| **p50 delta** | **+744 ms** |
| **p95 delta** | **+1248 ms** |
| p50 % vs direct | +94% |

### How to read this

- **Absolute milliseconds matter more than percentage.** OpenAI itself takes ~800 ms for this tiny completion; the gateway adds ~744 ms on top.
- The largest gateway-only cost is likely the **embedding call for semantic cache lookup** on every non-streaming request (cache miss path). That is an intentional trade-off: pay embedding latency on misses to skip provider calls on hits.
- Auth + DB logging add smaller but non-zero overhead.
- p95 gap is wider because gateway does more work (embed + auth + log) and variance stacks with provider variance.

---

## Reproduce

```powershell
# Terminal 1 — gateway + PostgreSQL running
uvicorn app.main:app --host 127.0.0.1 --port 8001

# Terminal 2
python scripts/benchmark_latency.py gw-sk-your-key --iterations 10
```

Output is printed to the console and saved to `docs/benchmark_results.json`.

---

## Honest limitations

| Limitation | Impact |
|------------|--------|
| Small sample (5 runs) | Good for dev sanity check; use 20+ for production decisions |
| Single machine / network | Numbers vary by region and ISP |
| Non-streaming only | Streaming overhead profile differs (SSE passthrough is lighter) |
| Cache always consulted | Overhead includes embedding; a `CACHE_ENABLED=false` mode would measure “thin proxy” latency |
| No LiteLLM baseline | Different product; direct OpenAI is the cleaner comparison |

---

## Future optimizations (not implemented)

- Skip embedding when cache is disabled or project opts out
- Fire-and-forget request logging (don’t block response on DB commit)
- Connection pooling warm-up at startup
- Separate benchmark doc for streaming first-token latency

---

## Meeting-ready summary

> I benchmarked non-streaming chat latency against direct OpenAI on the same model and prompt. The gateway adds about **744 ms p50 overhead**, mostly from semantic cache embedding + auth/logging — acceptable for a feature-rich proxy, and cache hits would invert that trade-off on repeated similar prompts.
