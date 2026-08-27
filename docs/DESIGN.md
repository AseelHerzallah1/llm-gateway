# Design Decisions — LLM Gateway v1

This document explains **why** the gateway is built the way it is — for design reviews and technical walkthroughs. Diagrams live in [`ARCHITECTURE.md`](ARCHITECTURE.md); API contracts in [`API.md`](API.md).

---

## 1. What we optimized for

| Priority | Rationale |
|----------|-----------|
| **Depth over feature count** | Three strong pillars (streaming, cache, observability) beat eleven shallow admin screens |
| **OpenAI compatibility** | Clients change only `base_url` + `api_key` — no SDK fork |
| **Evidence-based trade-offs** | Thresholds, benchmarks, and security choices are measured or audited, not assumed |
| **Incremental phases** | Each phase ships, tests, and commits before the next layer of complexity |

---

## 2. Stack choices

| Choice | Why | Trade-off |
|--------|-----|-----------|
| **Python 3.11 + FastAPI** | Async-first HTTP, Pydantic validation, fast to iterate | GIL limits CPU-bound work; fine for I/O-bound proxy |
| **httpx (async)** | Same API for direct calls and streaming SSE | Another dependency vs raw aiohttp |
| **PostgreSQL** | Durable request logs, cache entries, bcrypt auth | Ops overhead vs SQLite for a demo |
| **SQLAlchemy async + asyncpg** | Typed models, migrations via Alembic | More boilerplate than raw SQL |
| **In-memory semantic cache + PG persistence** | Fast lookup at runtime; survives restarts | Not shared across gateway replicas without redesign |

**Not chosen (v1):** LangChain in the core (hides control flow), Kubernetes (single-node MVP scope), pgvector/FAISS (add when in-memory tuning is understood — see [`CACHE_TUNING.md`](CACHE_TUNING.md)).

---

## 3. Streaming proxy

### Decision: forward SSE chunks immediately

The gateway **does not** buffer the full provider response before returning to the client. Chunks pass through as they arrive from httpx's `aiter_lines()`.

**Why:** Time-to-first-token is the user-visible metric for chat UX. Buffering would add latency and memory proportional to response length.

### Decision: cancel upstream on client disconnect

`_sse_event_generator()` polls `request.is_disconnected()`. On drop, it breaks the forward loop and `await stream_iter.aclose()` in `finally`.

**Why:** Without cancellation, the provider keeps generating tokens after the client leaves — wasted cost and server resources.

**Trade-off:** Mid-stream provider errors are logged after the stream ends; we do not retry mid-stream (only on stream **open** / first chunk — see retries below).

### Decision: parse usage from SSE for logging

Token counts are extracted from the final usage chunk via `parse_sse_usage()` so request logs stay accurate without re-tokenizing.

---

## 4. Gateway cache (v0.2 — L1 exact + L2 verified semantic)

### Decision: two-layer cache instead of cosine-only reuse (v0.2)

**v0.1** used cosine similarity ≥ **0.92** as the production reuse gate. **v0.2** requires **L1 exact_hit** (SHA-256 fingerprint) or **L2 semantic_hit** (candidate @ **0.65** + gpt-4o-mini verifier returning literal `true`).

Research commit `5d5935c` validated this design. Historical cosine measurements remain in `docs/eval/` — they informed the redesign but are not current production behavior.

### Decision: skip embed when no semantic entries exist

`has_semantic_entries(project_id, model)` false → no embedding on L2 lookup path.

### Decision: reuse lookup embedding on store

On miss, the embedding computed during lookup is passed to `store_non_streaming_completion()` instead of embedding twice.

**Why:** Duplicate embed on miss was ~520 ms of the ~744 ms gateway overhead before optimization.

### Decision: register L1 fingerprint alias after verified L2 hit

When the verifier accepts a semantic candidate, the gateway upserts the **current request fingerprint** into the L1 exact index (`_register_exact_fingerprint_alias` in `chat_integration.py`). Identical repeats thereafter become **exact_hit** without embed or verifier cost.

**Why:** Benchmark Path D showed that semantic-only reuse without alias registration prevented identical repeats from hitting L1. Alias registration makes the two-layer design compositional — L2 for paraphrase, L1 for exact identity.

### Decision: cache only on non-streaming path

Streaming requests always hit the provider. Streaming + cache would require buffering or complex partial-cache semantics — out of scope for v1.

### Decision: PostgreSQL persistence + in-memory index

Entries persist to `cache_entries` (fingerprint, request_messages, use counters); gateway hydrates into `GatewayCache` at startup.

---

## 5. Observability

### Decision: persist every request to PostgreSQL

Each chat call logs `latency_ms`, tokens, `cost_usd`, `status`, `cache_hit`, and optional `error_reason`.

**Why:** Percentiles and cost attribution require raw samples — not just in-memory counters.

### Decision: percentiles (p50 / p95 / p99), not averages

`/v1/metrics` aggregates logged latencies with a percentile helper.

**Why:** Averages hide tail latency. One slow provider call does not dominate the story if p95 is healthy — and vice versa.

### Decision: async request logging (`REQUEST_LOG_ASYNC=true`)

Non-streaming success path schedules `persist_request_log` via FastAPI `BackgroundTasks` by default.

**Why:** Synchronous DB writes added measurable latency on the critical path (benchmark Phase 8.3b).

**Trade-off:** Log row may appear slightly after the HTTP response; acceptable for analytics, not for synchronous audit gates.

### Decision: minimal dashboard

Single HTML page at `/dashboard` reads `/v1/metrics` and `/v1/requests` with the user's API key in `sessionStorage`.

**Why:** Demonstrates end-to-end observability without building a React admin product.

---

## 6. Multi-provider routing and resilience

### Decision: route by model name prefix

| Prefix | Provider |
|--------|----------|
| `gpt-*`, `o1*`, `o3*`, `o4*` | OpenAI |
| `llama-*`, `mixtral-*`, `gemma-*`, `qwen-*` | Groq |
| `claude-*` | Anthropic (when key configured) |

**Why:** Matches how clients already specify models; no separate routing header.

**Trade-off:** Model naming collisions across providers must be avoided via prefix rules.

### Decision: retry transient errors only

Retry on 429, 5xx, and timeouts — never on 4xx client errors. Exponential backoff: `backoff_s * 2^attempt`.

**Why:** Retrying bad requests wastes quota and delays inevitable failure.

### Decision: fallback after primary exhausts retries

Groq failure → OpenAI with `PROVIDER_FALLBACK_OPENAI_MODEL`; OpenAI failure → Groq with `PROVIDER_FALLBACK_GROQ_MODEL`.

**Why:** Availability over strict model fidelity — a degraded answer beats a 502 for many apps.

**Trade-off:** Response model may differ from the client's request; logged model reflects what actually served.

### Decision: shared provider interface

All backends implement `LLMProvider` (`complete`, `stream`, `aclose`). Groq reuses the OpenAI httpx client with a different base URL.

**Why:** Chat route stays one code path; new providers are adapters, not route forks.

---

## 7. Security

### Decision: bcrypt + lookup prefix for API keys

See [`SECURITY.md`](SECURITY.md). SHA-256 was fast to crack offline if the DB leaked; bcrypt slows offline attacks while a 12-char lookup prefix keeps auth indexed.

**Trade-off:** Re-seed required after migration; legacy SHA-256 rows supported until then.

### Decision: keys shown once at creation

Only the hash and lookup prefix are stored — same pattern as Stripe/GitHub personal access tokens.

---

## 8. Performance (honest numbers)

| Metric | Before opt | After opt | Notes |
|--------|------------|-----------|-------|
| Gateway overhead p50 | +744 ms | ~+620 ms | Non-stream, cache miss, local dev |
| Single embed p50 | ~260 ms | ~265 ms | Dominates miss path |
| Root cause | 2× embed + sync log | 1× embed + async log | See [`BENCHMARK.md`](BENCHMARK.md) |

**What we did not claim:** Sub-50 ms proxy overhead while semantic cache is enabled on miss path — embedding dominates.

**Knobs:** `SEMANTIC_CACHE_ENABLED=false` for thin-proxy measurement; `REQUEST_LOG_ASYNC=false` to debug logging ordering.

---

## 9. Testing strategy

Three layers, each with a purpose:

| Layer | Location | Purpose |
|-------|----------|---------|
| **Unit** | `tests/unit/` | Pure logic: similarity, retries, routing, cost, percentiles |
| **Mocked integration** | `tests/integration/` (no `@pytest.mark.db`) | HTTP routes with mocked providers — CI without Postgres/OpenAI |
| **DB integration** | `@pytest.mark.db` | Real bcrypt auth, PostgreSQL logs, cache persistence |
| **Manual scripts** | `scripts/test_*.py` | Live OpenAI/Groq, SSE cancel, benchmarks, demo |

### Heavier DB tests (Phase 8.2b–8.2e)

| Task | File | What it proves |
|------|------|----------------|
| 8.2b | `test_auth_db.py`, `test_request_log_db.py`, `test_chat_db.py` | Auth + logging end-to-end |
| 8.2c | `test_provider_resilience_db.py` | Real retry/fallback through chat route |
| 8.2d | `test_streaming_db.py` | SSE success, disconnect, **20/40** parallel streams, mixed batch |
| 8.2e | `test_cache_db.py` | Hit/miss, threshold miss, empty-cache embed skip |

Stub providers in `tests/fakes/` keep CI deterministic; OpenAI is never called in pytest DB tests.

Run: `pytest`, `pytest -m db`, or `python scripts/demo.py` for a live walkthrough.

---

## 10. Known limitations (v1)

| Limitation | Mitigation / v2 direction |
|------------|---------------------------|
| In-memory cache not shared across replicas | pgvector + shared index, or sticky sessions |
| Semantic cache on non-stream only | Stream cache needs design (partial response matching) |
| PII redaction limited to supported patterns | Regex email/phone + opt-in card/IBAN; non-streaming only; not DLP — see [`PII.md`](PII.md) |
| Benchmark sample size | Run 20+ iterations for stable p95 |
| Anthropic routed but optional | Enable when `ANTHROPIC_API_KEY` set |
| Groq/OpenAI fallback changes model id | Document in client integration guides |

---

## 11. File map (decision → code)

| Concern | Primary files |
|---------|----------------|
| Chat route | `app/routes/chat.py` |
| Streaming + cancel | `app/routes/chat.py` → `_sse_event_generator` |
| Cache integration | `app/cache/chat_integration.py`, `app/cache/memory.py` |
| Providers | `app/providers/openai.py`, `groq.py`, `anthropic.py` |
| Retry / fallback | `app/providers/retry.py`, `fallback.py`, `router.py` |
| Auth | `app/auth/api_keys.py`, `dependencies.py` |
| Metrics | `app/routes/metrics.py`, `app/observability/` |
| Config | `app/config.py` |

---

## Summary

The gateway focuses on three systems problems — **streaming without buffering**, **semantic cache with measured false-hit trade-offs**, and **percentile observability** — with optional **pattern-based PII redaction** on non-streaming requests. Major choices are documented with benchmarks, a security audit, and tests from mocked unit tests through PostgreSQL integration (including parallel streaming).
