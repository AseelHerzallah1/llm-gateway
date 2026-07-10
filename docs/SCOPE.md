# Scope — LLM Gateway v1

## Problem statement

Applications that use large language models (LLMs) need more than a direct API call to a provider. In production, teams require:

- A single controlled entry point (auth, keys, logging)
- Streaming responses without buffering entire replies in memory
- Cost and latency visibility (percentiles, not averages)
- Optional cache hits for semantically similar prompts

This project builds a **middleware gateway** — not a chat application — that sits between client applications and LLM providers (starting with OpenAI). Clients call the gateway; the gateway proxies, measures, and optionally caches.

## Design philosophy

> **3 deeply engineered components > 11 shallow features.**

The goal is interview depth: explain streaming, cache trade-offs, and percentile metrics — not ship a bloated admin CRUD app.

## v1 in-scope

Mapped to development Phases 1–8:

| Capability | Phase | Notes |
|------------|-------|-------|
| OpenAI-compatible `POST /v1/chat/completions` | 3–4 | Non-streaming first, then real SSE streaming |
| API key authentication per project | 2–3 | Keys stored hashed in PostgreSQL |
| Single provider (OpenAI) | 3–4 | Multi-provider deferred to Phase 7 |
| Async streaming proxy with cancellation | 4 | No full-response buffering in memory |
| Request logging: latency, tokens, cost, status | 5 | Persisted to `requests` table |
| Percentile metrics (p50, p95, p99) | 5 | Per model / per project |
| Simple metrics API + minimal dashboard | 5 | One page, numbers over UI polish |
| Semantic cache (in-memory, cosine similarity) | 6 | Threshold tuning with measured hit rate |
| Basic security hardening | 8 | Key hashing audit, automated tests |
| Benchmark vs existing tool (e.g. LiteLLM) | 8 | Real numbers in docs |
| `DESIGN.md`, README, demo materials | 8 | Honest trade-offs and limitations |

### Minimal admin (in-scope, kept small)

- One simple page or endpoint to create a project and API key
- No multi-page CRUD admin

## Explicitly out-of-scope (v1)

| Item | Deferred to | Reason |
|------|-------------|--------|
| Hebrew/Arabic PII tokenization | Phase 9 (v2) | Real edge feature; core must be stable first |
| Second provider + routing + fallback | Phase 7 | Prove single-provider path before routing complexity |
| Regex prompt-injection detection | Never (v1) | Easily bypassed; real solution needs a classifier |
| LangChain in gateway core | Never (unless explicit decision) | Hides complexity; not needed for proxy/cache |
| Kubernetes / distributed deployment | Never (MVP) | Unnecessary for portfolio MVP |
| Large frontend / multi-page admin | Never (MVP) | Time sink; not the differentiator |
| FAISS / pgvector cache | Phase 6+ upgrade | In-memory first; migrate when tuning is understood |
| Per-project model allowlists / complex limits | v2+ | Simple rate limit sufficient for v1 |
| Multi-tenant billing / payments | Out of scope | Not a billing product |

## Success criteria (measurable)

### Phase 3–4 — Proxy

- [ ] Non-streaming request: client → gateway → OpenAI → client returns correct JSON
- [ ] Streaming request: tokens arrive chunk-by-chunk; gateway does not buffer full response in memory
- [ ] Client disconnect mid-stream: upstream OpenAI request is cancelled
- [ ] Provider timeout: gateway returns structured error, does not hang

### Phase 5 — Observability

- [ ] Every request logged with `latency_ms`, `input_tokens`, `output_tokens`, `cost`, `status`
- [ ] Metrics endpoint returns p50, p95, p99 (not just average)
- [ ] Dashboard displays live numbers from logged data

### Phase 6 — Semantic cache

- [ ] Similar prompts (above tuned threshold) return cached response without provider call
- [ ] Cache hit rate and cost savings logged
- [ ] Threshold documented with measured false-hit risk

### Phase 8 — Hardening

- [ ] API keys stored as hashes only (never plaintext)
- [ ] Automated tests pass for auth, proxy, and metrics
- [ ] Benchmark document with real latency overhead numbers

## Technology stack (locked)

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| HTTP client | httpx (async) |
| Concurrency | asyncio |
| Database | PostgreSQL |
| Repo | Public — [github.com/AseelHerzallah1/llm-gateway](https://github.com/AseelHerzallah1/llm-gateway) |

## Development phase map

| Phase | Deliverable |
|-------|-------------|
| 0 | GitHub repo, commit convention |
| 1 | Scope, API contract, architecture docs |
| 2 | Project skeleton, Docker, DB, minimal auth tables |
| 3 | Non-streaming proxy to one provider |
| 4 | Real streaming proxy + cancellation |
| 5 | Observability + cost tracking + dashboard |
| 6 | Semantic cache + threshold tuning |
| 7 | Second provider, routing, retries, fallback |
| 8 | Security audit, tests, benchmarks, README |
| 9 (v2) | PII protection, pgvector/FAISS |

## Commit convention

```
phase-N/task-M: short description
```

One completed task = one commit. No secrets in git.
