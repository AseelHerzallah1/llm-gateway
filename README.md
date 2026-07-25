# LLM Gateway

A production-style **LLM Gateway** — middleware between your applications and LLM providers (OpenAI, Groq, Anthropic). Clients use an OpenAI-compatible API; the gateway handles auth, streaming, semantic caching, retries, fallback, and observability.

Built as a portfolio project with phased commits, automated tests, and documented trade-offs.

---

## Features

| Capability | Details |
|------------|---------|
| **OpenAI-compatible API** | `POST /v1/chat/completions` — change `base_url` + `api_key` only |
| **Streaming proxy** | SSE forwarded chunk-by-chunk; upstream cancelled on client disconnect |
| **Semantic cache** | Embedding similarity (cosine ≥ 0.92); persisted to PostgreSQL |
| **Multi-provider routing** | GPT → OpenAI, Llama/Mixtral → Groq, Claude → Anthropic |
| **Retries + fallback** | Transient 429/5xx/timeout retry; optional cross-provider fallback |
| **Observability** | Request logs, p50/p95/p99 latency, cost, cache hit rate, dashboard |
| **Security** | bcrypt API key storage with indexed lookup prefix |

---

## Stack

Python 3.11 · FastAPI · httpx · asyncio · PostgreSQL · SQLAlchemy async · Alembic · pytest

---

## Quick start

```powershell
git clone https://github.com/AseelHerzallah1/llm-gateway.git
cd llm-gateway

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ".[dev]"

copy .env.example .env
# Edit .env: OPENAI_API_KEY, DATABASE_URL

docker compose up db -d
alembic upgrade head
python scripts/seed_test_project.py   # save the gw-sk-... key

uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### Run the demo

```powershell
# Add to .env: GATEWAY_TEST_API_KEY=gw-sk-...
python scripts/demo.py
```

Walks through health → chat → stream → cache hit → metrics. See [`docs/TESTING.md`](docs/TESTING.md) for the full manual test matrix.

### Run tests

```powershell
pytest                  # 62 tests (mocked + unit)
pytest -m db -v         # 17 PostgreSQL integration tests
```

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`docs/DESIGN.md`](docs/DESIGN.md) | **Why** — decisions, trade-offs, limitations |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Diagrams and component map |
| [`docs/API.md`](docs/API.md) | Endpoints, schemas, error codes |
| [`docs/SCOPE.md`](docs/SCOPE.md) | v1 in/out of scope |
| [`docs/TESTING.md`](docs/TESTING.md) | Manual + automated test guide |
| [`docs/BENCHMARK.md`](docs/BENCHMARK.md) | Gateway vs direct OpenAI latency |
| [`docs/CACHE_TUNING.md`](docs/CACHE_TUNING.md) | Similarity threshold measurements |
| [`docs/SECURITY.md`](docs/SECURITY.md) | API key hashing audit |
| [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) | Phase-by-phase build log for interviews |

---

## Project structure

```
app/
  auth/           API key generation, bcrypt verify
  cache/          Semantic cache + PostgreSQL persistence
  db/             SQLAlchemy models, session
  embeddings/     OpenAI embedding provider
  observability/  Request logs, cost, percentiles, SSE usage
  providers/      OpenAI, Groq, Anthropic + router, retry, fallback
  routes/         chat, health, metrics, requests, dashboard
tests/
  unit/           Pure logic tests
  integration/    HTTP + DB integration (pytest -m db)
  fakes/          Stub providers for resilience/stream/cache tests
scripts/          Manual E2E scripts + demo.py
docs/             Design, API, benchmarks
```

---

## Local URLs

| URL | Description |
|-----|-------------|
| `http://127.0.0.1:8001/health` | Liveness |
| `http://127.0.0.1:8001/v1/chat/completions` | Chat proxy |
| `http://127.0.0.1:8001/v1/metrics` | Latency percentiles + cost |
| `http://127.0.0.1:8001/dashboard` | Minimal metrics UI |
