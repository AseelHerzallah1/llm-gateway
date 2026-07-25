# Development Log — LLM Gateway

A running record of completed tasks, decisions, tests, problems, and lessons learned.
Review this before meetings.

---

## Project metadata

| Field | Value |
|-------|-------|
| Repository | https://github.com/AseelHerzallah1/llm-gateway |
| Stack | Python · FastAPI · httpx · asyncio · PostgreSQL |
| Started | 2026-07-10 |
| Development model | One task → one commit → push |

---

## Phase 0 — GitHub repo init

### Task 0.1 — Initialize repository scaffold

**Date:** 2026-07-10  
**Commit:** `b28f655` — `phase-0/task-0.1: initialize repository scaffold`

**What we built:**
- `.gitignore` (Python, `.env`, venv, IDE files)
- Minimal `README.md`
- `docs/` directory placeholder

**Decisions:**
- Public repo for portfolio visibility
- Repo name: `llm-gateway`
- Commit convention: `phase-N/task-M: description`
- README kept minimal until Phase 8

**Tests:** `git status` clean; `git log -1` shows single author `AseelHerzallah1`

**Problems:**
- Cursor auto-added `Co-authored-by: Cursor <cursoragent@cursor.com>` to first commit
- Fixed by amending commit message and force-pushing
- Added local `prepare-commit-msg` hook + `.cursor/rules/no-cursor-attribution.mdc`
- User disabled Commit Attribution in Cursor Settings

**Lessons:**
- Always verify `git show -s --format=%B HEAD` after agent-created commits
- `.git/hooks/` is local only — not pushed to GitHub

---

## Phase 1 — Scope and API contract

### Task 1.1 — Define v1 scope and boundaries

**Date:** 2026-07-10  
**Commit:** `1c9240e` — `phase-1/task-1.1: define v1 scope and boundaries`

**What we built:**
- `docs/SCOPE.md` — problem statement, v1 in/out-of-scope, success criteria, phase map

**Decisions:**
- Strict 9-phase order; no skipping ahead
- Semantic cache in Phase 6 (after observability in Phase 5)
- PII tokenization deferred to Phase 9 (v2)
- LangChain excluded from core unless explicitly decided later
- Explanations to developer in English; brief Arabic summaries per phase only

**Tests:** Documentation only — no runtime tests

**Alternatives considered:**
- Observability before cache vs cache before observability → chose observability first (user's required order) so we can measure cache impact when it lands in Phase 6

**Meeting-ready summary:**
> Before writing code, I defined strict v1 scope for an LLM gateway focused on three deep pillars: streaming proxy, semantic cache, and percentile observability. I explicitly cut PII handling, multi-provider routing, LangChain, and regex security to later phases so engineering depth stays on systems problems, not admin CRUD.

---

### Task 1.2–1.4 — API contract, schemas, and auth

**Date:** 2026-07-10  
**Commit:** `f5a538d` — `phase-1/task-1.2-1.4: document API endpoints schemas and auth`

**Decisions:**
- OpenAI-compatible `/v1/chat/completions` as primary proxy endpoint
- Auth via `Authorization: Bearer gw-sk-...` (OpenAI SDK compatible)
- API keys shown once at creation; only hash stored
- Metrics and request log endpoints scoped to Phase 5

**Tests:** Documentation only

**Meeting-ready summary:**
> I defined an OpenAI-compatible API contract so existing SDK clients only need to change base_url and api_key. Auth uses Bearer tokens, errors follow a consistent schema, and streaming uses SSE matching OpenAI's format.

---

### Task 1.5 — Architecture and data flow

**Date:** 2026-07-10  
**Commit:** `32b5b0a` — `phase-1/task-1.5: add architecture and data flow diagrams`

**What we built:**
- `docs/ARCHITECTURE.md` — system context, sequence diagrams, component map, ER diagram

**Decisions:**
- Document non-streaming, streaming, and cache flows as separate diagrams
- Component directories planned upfront for consistent Phase 2+ structure

**Tests:** Documentation only

**Meeting-ready summary:**
> I documented three request flows — non-streaming proxy, streaming with cancellation, and semantic cache lookup — so each phase has a clear target architecture before implementation starts.

---

## Phase 1 complete

All documentation tasks finished. Next: **Phase 2, Task 2.1** — project skeleton.

---

## Phase 2 — Basic project structure

### Task 2.1 — Project skeleton and dependencies

**Date:** 2026-07-10  
**Commit:** `4b26b76` — `phase-2/task-2.1: add project skeleton and dependencies`

**What we built:**
- `pyproject.toml` — project metadata, dependencies, tool config
- `requirements.txt` — pip-installable dependency list
- `.env.example` — environment variable template
- `app/` package tree (empty `__init__.py` files per planned module)
- `tests/`, `migrations/` placeholders
- `docs/PROJECT_STRUCTURE.md` — folder layout reference

**Decisions:**
- `pyproject.toml` as source of truth; `requirements.txt` for simple `pip install`
- Dependencies listed upfront (FastAPI, httpx, SQLAlchemy, asyncpg, Alembic, bcrypt) — installed in Task 2.2+
- No `app/main.py` yet — that's Task 2.2
- Python >= 3.11 required (async typing improvements)

**Tests:**
- `tomllib.load(pyproject.toml)` — valid TOML
- `pip install -r requirements.txt --dry-run` — resolves without error

**Alternatives considered:**
- Poetry vs plain pip → chose pip + pyproject.toml for fewer abstractions to explain in interviews
- Single `requirements-dev.txt` → used `[project.optional-dependencies]` in pyproject.toml instead

**Meeting-ready summary:**
> I set up the Python project skeleton with a modular package layout matching the architecture doc — separate packages for auth, providers, routes, observability, and cache. Dependencies are declared but no application code runs yet; that starts with the FastAPI entrypoint in the next task.

---

### Task 2.2 — FastAPI entrypoint and health check

**Date:** 2026-07-10  
**Commit:** `504e9cf` — `phase-2/task-2.2: add FastAPI entrypoint and health check`

**What we built:**
- `app/main.py` — FastAPI application entrypoint
- `app/routes/health.py` — `GET /health` endpoint
- `app/version.py` — single version constant (`0.1.0`)

**Decisions:**
- Health route in `app/routes/health.py`, not inline in `main.py` — keeps entrypoint thin; pattern for future routes
- Pydantic `HealthResponse` model — response shape validated and documented automatically
- `async def` on health handler — consistent with future async proxy handlers (even though this handler does no I/O)
- No config loading yet — hardcoded version; `app/config.py` comes in Task 2.3

**Tests:**
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
# → {"status":"ok","version":"0.1.0"}
```

**Alternatives considered:**
- Health in `main.py` directly → rejected; modular routes scale better
- Sync `def` vs `async def` → chose async for consistency across the app

**Meeting-ready summary:**
> I added a FastAPI entrypoint with a /health liveness endpoint returning status and version. The route lives in its own module following the architecture plan. I verified it with uvicorn and a live HTTP request.

---

### Task 2.3 — Config loading from environment

**Date:** 2026-07-11  
**Commit:** _(pending push)_

**What we built:**
- `app/config.py` — `Settings` class using `pydantic-settings`, loads from `.env`
- Updated `app/main.py` — startup log reads from `settings`

**Decisions:**
- `SecretStr` for `openai_api_key` and `secret_key` — prevents accidental logging of secrets
- `@lru_cache` on `get_settings()` — settings loaded once per process, not on every import call
- `lifespan` hook in FastAPI — logs config at startup without changing `/health` response
- `.env` copied locally from `.env.example`; never committed (in `.gitignore`)

**Tests:**
```bash
python -c "from app.config import settings; print(settings.app_env)"
# → development

uvicorn app.main:app --host 127.0.0.1 --port 8001
# → INFO: Starting LLM Gateway (env=development, host=0.0.0.0, port=8000)
```

**Meeting-ready summary:**
> I centralized configuration in a Pydantic Settings class that reads from environment variables and a .env file. Secrets use SecretStr, settings are cached per process, and startup logs confirm which environment loaded — without hardcoding values in code.

---

### Task 2.4 — Docker Compose (app + PostgreSQL)

**Date:** 2026-07-11  
**Commit:** _(pending push)_

**What we built:**
- `Dockerfile` — Python 3.11 image, installs deps, runs uvicorn
- `docker-compose.yml` — `app` + `db` (PostgreSQL 16) services
- `.dockerignore` — keeps image small (no `.venv`, `.env`, docs)
- `docs/DOCKER.md` — setup and troubleshooting guide

**Decisions:**
- PostgreSQL hostname `db` inside Docker network; `localhost` only when running uvicorn on host
- Host port `8001:8000` — avoids conflict with user's busy port 8000
- `depends_on` + `healthcheck` on `db` — app waits until PostgreSQL is ready
- `postgres_data` named volume — database survives `docker compose down`
- App does not connect to DB yet — that's Task 2.5

**Tests:**
- Docker not installed on dev machine during implementation — files validated manually
- User test: `docker compose up --build` then `Invoke-RestMethod http://127.0.0.1:8001/health`

**Meeting-ready summary:**
> I containerized the gateway with Docker Compose — one service for FastAPI, one for PostgreSQL. The app container overrides DATABASE_URL to use the Docker network hostname. A healthcheck ensures Postgres is ready before the app starts. The app doesn't use the DB yet; this task only establishes the runtime environment.

---

### Task 2.5 — Database connection setup

**Date:** 2026-07-11  
**Commit:** _(pending push)_

**What we built:**
- `app/db/base.py` — SQLAlchemy `Base` for future ORM models
- `app/db/session.py` — async engine, session factory, `get_db` dependency, `verify_db_connection()`
- Updated `app/main.py` — verifies DB on startup, disposes pool on shutdown

**Decisions:**
- **asyncpg** driver via `postgresql+asyncpg://` URL — matches FastAPI async style
- `verify_db_connection()` runs `SELECT 1` at startup — fail fast if Postgres is down
- `get_db()` dependency ready for routes in Phase 3+ (not wired to any endpoint yet)
- `echo=True` SQL logging only in `development` environment
- Local setup: uvicorn on host + Postgres in Docker (`localhost:5432`)

**Tests:**
```bash
python -c "import asyncio; from app.db.session import verify_db_connection; asyncio.run(verify_db_connection())"
# → DB connection OK

# Restart uvicorn — server log should show:
# INFO: Database connection verified
```

**Meeting-ready summary:**
> I set up async SQLAlchemy with asyncpg. On startup the gateway runs SELECT 1 to verify PostgreSQL is reachable before accepting requests. Sessions are provided via a get_db dependency for future routes. The connection pool is disposed cleanly on shutdown.

---

### Task 2.6 — Initial migrations (users + projects)

**Date:** 2026-07-11  
**Commit:** _(pending push)_

**What we built:**
- `app/db/models/user.py` — User ORM model
- `app/db/models/project.py` — Project ORM model (FK to users)
- `alembic.ini` + `migrations/env.py` — async Alembic setup
- `migrations/versions/0001_create_users_and_projects.py` — first migration

**Decisions:**
- UUID primary keys — standard for distributed APIs
- `password_hash` / `api_key_hash` columns — never store plaintext (hashing in Phase 3)
- Alembic async `env.py` — matches asyncpg engine from Task 2.5
- Only `users` + `projects` now — `requests` (Phase 5), `cache_entries` (Phase 6) later

**Tests:**
```bash
alembic upgrade head   # → Running upgrade -> 0001
alembic current        # → 0001 (head)
docker exec llm-gateway-db psql -U gateway -d llm_gateway -c "\dt"
# → users, projects, alembic_version
```

**Meeting-ready summary:**
> I added SQLAlchemy ORM models for users and projects, and an Alembic migration that creates both tables with UUID keys and foreign key relationships. Migrations run asynchronously against the same PostgreSQL database, and I verified the tables exist after upgrade.

---

## Phase 2 complete

Next: **Phase 3, Task 3.1** — provider interface (abstract base for OpenAI).

---

## Phase 3 — One provider, non-streaming proxy

### Task 3.1 — Provider interface

**Date:** 2026-07-12  
**Commit:** _(pending push)_

**What we built:**
- `app/providers/base.py` — `LLMProvider` ABC, `ChatMessage`, `CompletionRequest`, `CompletionResponse`

**Decisions:**
- Python `abc.ABC` + `@abstractmethod` — standard interface pattern
- `dataclass(frozen=True)` for DTOs — immutable, simple to explain
- `complete()` only (non-streaming) — streaming added as separate method in Phase 4
- Normalized `CompletionResponse` — gateway uses same shape regardless of provider

**Tests:** ABC cannot be instantiated; incomplete subclass raises TypeError

**API keys:** Not needed until Task 3.2 (OpenAI HTTP calls)

**Meeting-ready summary:**
> I defined an abstract LLMProvider interface with complete() for non-streaming requests. Request and response types are normalized dataclasses so routes never depend on a specific vendor SDK.

---

### Task 3.2 — OpenAI provider (non-streaming)

**Date:** 2026-07-12  
**Commit:** _(pending push)_

**What we built:**
- `app/providers/openai.py` — `OpenAIProvider` using httpx async client
- `create_openai_provider()` — builds provider from settings
- `scripts/test_openai_provider.py` — manual live test script

**Decisions:**
- **httpx** async client — no OpenAI SDK (fewer dependencies, full control)
- `stream: False` hardcoded in payload — streaming is Phase 4
- Maps OpenAI JSON → normalized `CompletionResponse`
- `OpenAIProviderError` wraps HTTP failures — full gateway error mapping in Task 3.5
- `aclose()` for clean client shutdown

**Tests:**
- `OpenAIProvider` implements `LLMProvider` — verified
- Live API test requires `OPENAI_API_KEY` in `.env` — not set on dev machine during commit

**User action needed:**
Add real key to `.env`:
```
OPENAI_API_KEY=sk-...
```
Then run: `python scripts/test_openai_provider.py`

**Meeting-ready summary:**
> I implemented OpenAIProvider using httpx to call /v1/chat/completions with stream=false. The provider implements our abstract interface and normalizes the response. I deliberately avoided the OpenAI SDK so the HTTP layer is visible and testable.

---

### Task 3.3 — API key auth middleware

**Date:** 2026-07-12  
**Commit:** _(pending push)_

**What we built:**
- `app/auth/api_keys.py` — generate/hash/validate key format
- `app/auth/dependencies.py` — `get_current_project` FastAPI dependency
- `app/errors.py` — structured `GatewayHTTPException` + handler
- `scripts/seed_test_project.py` — creates test user + project
- `scripts/test_auth.py` — manual auth test

**Decisions:**
- SHA-256 hash for API key lookup (per docs/API.md validation flow)
- Accept `Authorization: Bearer` or `X-API-Key` header
- bcrypt for admin **passwords** only (users table); API keys use SHA-256
- `get_current_project` ready to inject into routes in Task 3.4

**Tests:**
- `seed_test_project.py` — inserts test user + project
- `test_auth.py` with invalid key — rejected (exit 1)

**User action:** Save API key printed by seed script; test with:
`python scripts/test_auth.py <your-key>`

**Meeting-ready summary:**
> I built API key auth as a FastAPI dependency. Keys are extracted from Bearer or X-API-Key headers, hashed with SHA-256, and looked up in the projects table. Invalid or inactive projects return structured 401 errors matching our API contract.

---

### Task 3.4 — POST /v1/chat/completions (non-streaming)

**Date:** 2026-07-14  
**Commit:** _(pending push)_

**What we built:**
- `app/schemas/chat.py` — OpenAI-compatible request/response models
- `app/routes/chat.py` — proxied chat completion endpoint
- Updated `app/main.py` — LLM provider in app lifespan, chat router registered
- `scripts/test_chat_completions.py` — manual HTTP test

**Decisions:**
- Auth via `get_current_project` dependency — route only runs for valid keys
- Provider stored on `app.state` — one httpx client for app lifetime
- `stream: true` rejected with 400 until Phase 4
- Provider errors mapped to 502 (full error taxonomy in Task 3.5)
- Response shape matches OpenAI `chat.completion` object

**Tests:**
- POST without API key → 401 `invalid_api_key` (verified)
- Full success test requires running uvicorn + gateway key + OpenAI key

**User test:**
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001
python scripts/test_chat_completions.py gw-sk-your-key
```

**Meeting-ready summary:**
> I wired the first real gateway endpoint: authenticated clients POST to /v1/chat/completions, the gateway validates their project API key, forwards to OpenAI via our provider interface, and returns an OpenAI-shaped JSON response.

---

### Task 3.5 — Provider error mapping

**Date:** 2026-07-14  
**Commit:** `2755c12`

**What we built:**
- `app/providers/exceptions.py` — `OpenAIProviderError` with `status_code` and `is_timeout`
- Expanded `app/errors.py` — `map_openai_provider_error()`, rate limit / timeout helpers, validation handler
- Updated `app/providers/openai.py` — parse OpenAI error JSON, distinguish timeout vs HTTP vs connection errors
- Updated `app/routes/chat.py` — uses centralized mapper instead of generic 502
- Updated `app/main.py` — `RequestValidationError` → structured 422 response
- `scripts/test_error_mapping.py` — offline mapping assertions

**Error mapping:**

| Upstream situation | Gateway status | Code |
|--------------------|----------------|------|
| httpx timeout | 504 | `gateway_timeout` |
| OpenAI 429 | 429 | `rate_limit_exceeded` |
| OpenAI 400 | 400 | `invalid_request` |
| OpenAI 401/403 (server key) | 502 | `provider_error` (message sanitized) |
| OpenAI 5xx | 502 | `provider_error` |
| Connection errors | 502 | `provider_error` |
| Invalid JSON body | 422 | `validation_error` |

**Tests:**
- `python scripts/test_error_mapping.py` → Error mapping OK

**Meeting-ready summary:**
> I centralized provider failure handling: OpenAI timeouts become 504, rate limits become 429, client mistakes from OpenAI become 400, and server-side misconfiguration never leaks upstream auth details. FastAPI validation errors also return our consistent error JSON shape.

---

### Task 3.6 — Manual testing documentation

**Date:** 2026-07-14  
**Commit:** _(pending push)_

**What we built:**
- `docs/TESTING.md` — Phase 3 manual test guide with PowerShell, curl, and script commands
- Checklist covering health, auth, provider, chat completions, and error scenarios
- Troubleshooting table for common local dev issues (port 8001, OneDrive reload, Docker DB-only)

**Tests:** Documentation only — no code changes

**Meeting-ready summary:**
> I documented the full Phase 3 test flow: bottom-up from offline error mapping through direct OpenAI calls to authenticated chat completions, with copy-paste PowerShell/curl examples and a pass/fail checklist.

---

## Phase 4 — Real streaming proxy

### Task 4.1 — Provider streaming interface + OpenAI SSE

**Date:** 2026-07-15  
**Commit:** `1bf98a1`

**What we built:**
- `app/providers/base.py` — `stream()` abstract method on `LLMProvider`
- `app/providers/openai.py` — httpx streaming via `client.stream()`, forwards SSE lines chunk-by-chunk
- `_build_payload()` shared helper for streaming and non-streaming requests
- `scripts/test_openai_stream.py` — live provider streaming test

**Decisions:**
- **Transparent SSE passthrough** — gateway re-emits OpenAI `data: ...` lines without re-serializing JSON
- **No full-response buffering** — `async for line in response.aiter_lines()` yields immediately
- HTTP errors before stream starts mapped via existing `OpenAIProviderError` (route wiring in Task 4.2)
- Same httpx client and timeout settings as non-streaming

**Tests:**
- `python scripts/test_openai_stream.py` → SSE chunks + `data: [DONE]` (verified live)

**Meeting-ready summary:**
> I added streaming to the provider layer: OpenAIProvider opens an httpx stream, reads SSE lines as they arrive, and yields them without buffering the full response. This is the foundation for the gateway's real-time token proxy in the next task.

---

### Task 4.2 — SSE streaming endpoint

**Date:** 2026-07-15  
**Commit:** `cb7ba78`

**What we built:**
- Updated `app/routes/chat.py` — `stream: true` returns `StreamingResponse` (`text/event-stream`)
- Prefetch first SSE chunk before starting response so provider HTTP errors map to JSON (502/504/429/400)
- SSE headers: `Cache-Control`, `Connection`, `X-Accel-Buffering`
- `scripts/test_chat_stream.py` — manual HTTP streaming test

**Decisions:**
- `response_model=None` on route — FastAPI cannot union JSON and SSE response types
- Removed `streaming_not_supported` rejection — streaming enabled for Phase 4
- Mid-stream provider failures log and terminate SSE (HTTP status already committed as 200)

**Tests:**
- `POST /v1/chat/completions` with `stream: true` without auth → 401 (verified)
- Full E2E: `python scripts/test_chat_stream.py gw-sk-...` with uvicorn running

**Meeting-ready summary:**
> I wired the chat endpoint for real SSE streaming: authenticated clients set stream=true and receive OpenAI-compatible event-stream chunks forwarded chunk-by-chunk. Provider errors before the first byte still return structured JSON errors.

---

### Task 4.3 — Client disconnect cancellation

**Date:** 2026-07-15  
**Commit:** `d3f1534`

**What we built:**
- `_sse_event_generator()` in `app/routes/chat.py` — polls `request.is_disconnected()`, closes provider stream in `finally`
- Updated `app/providers/openai.py` — treat `httpx.StreamClosed` as clean shutdown when upstream is cancelled
- `scripts/test_stream_cancel.py` — reads a few SSE events then closes connection early

**Decisions:**
- **`await stream_iter.aclose()`** in `finally` — closes async generator, exits httpx `stream()` context, cancels upstream HTTP
- Check disconnect **before each yield** — stop forwarding and break loop
- Handle **`asyncio.CancelledError`** — ASGI server may cancel the stream task on client drop

**Tests:**
- `python scripts/test_stream_cancel.py gw-sk-...` — client drops after 5 events; check uvicorn logs for cancellation message

**Meeting-ready summary:**
> When a client disconnects mid-stream, the gateway stops forwarding SSE chunks and closes the provider async generator, which tears down the httpx upstream connection instead of letting OpenAI keep generating tokens nobody reads.

---

### Task 4.4 — Streaming testing documentation

**Date:** 2026-07-15  
**Commit:** `bf84654`

**Note:** This was committed under task 4.4 before aligning with the original 6-task Phase 4 plan. The original plan's 4.4 (concurrent verification) is the next entry below.

**What we built:**
- Expanded `docs/TESTING.md` — Phase 4 sections for provider stream, gateway SSE, disconnect cancellation
- Updated Phase 3 checklist (removed obsolete `streaming_not_supported` test)
- Added Phase 4 checklist, script reference, and troubleshooting (Docker quit, port conflicts, curl `-N`)

**Tests:** Documentation only — no code changes

**Meeting-ready summary:**
> Phase 4 streaming flows are documented: how to test direct provider streaming, gateway SSE with stream=true, and client disconnect cancellation, with copy-paste commands and pass/fail checklists.

---

### Task 4.4 — Concurrent request handling verification (original plan)

**Date:** 2026-07-15  
**Commit:** `890936d`

**What we built:**
- `scripts/test_concurrent_streams.py` — fires N parallel streaming requests + 3 non-streaming via `asyncio.gather`
- Updated `docs/TESTING.md` — section 10 and Phase 4 checklist item for concurrency

**Decisions:**
- Default concurrency **5** — enough to stress async handling without hammering OpenAI rate limits
- Single shared `httpx.AsyncClient` with raised connection limits — mirrors real multi-client usage
- Mixed stream + non-stream in one run — verifies both code paths work under parallel load

**Tests:**
- `python scripts/test_concurrent_streams.py gw-sk-...` → all streams reach `[DONE]`, non-stream return 200

**Meeting-ready summary:**
> I added a concurrency verification script that runs multiple parallel SSE streams through the gateway plus non-streaming requests, confirming the async proxy handles overlapping requests without cross-talk or dropped streams.

**Remaining (original plan):** Task 4.6 — timeouts and provider hang handling.

---

### Task 4.6 — Timeouts and provider hang handling (original plan)

**Date:** 2026-07-15  
**Commit:** _(pending push)_

**What we built:**
- Configurable timeouts in `app/config.py` — connect, read, stream idle, write, pool
- `app/providers/openai.py` — granular `httpx.Timeout`, `_iter_sse_events()` with `asyncio.wait_for` idle detection
- `.env.example` — timeout settings documented
- `scripts/test_provider_timeouts.py` — offline 504 mapping + connect timeout to unreachable host

**Decisions:**
- **Stream idle timeout (default 30s)** — if OpenAI sends no SSE chunk for 30s, treat as hang → `504 gateway_timeout`
- **Separate read timeout (60s)** for non-streaming full responses
- **Configurable via `.env`** — tunable per environment without code changes
- Mid-stream timeout ends SSE gracefully (HTTP 200 already sent); pre-stream timeout returns JSON 504

**Tests:**
- `python scripts/test_provider_timeouts.py` → Provider timeout handling OK

**Meeting-ready summary:**
> I added explicit timeout layers: connect/read/write limits on httpx, plus a stream idle watchdog that detects when OpenAI stops sending chunks. Hung or slow streams surface as gateway 504 errors instead of tying up connections forever.

**Phase 4 complete (original plan).** Next: Phase 5 — observability.

---

## Phase 5 — Observability and cost tracking

### Task 5.1 — `requests` table migration + ORM model

**Date:** 2026-07-15  
**Commit:** `8710090`

**What we built:**
- `migrations/versions/0002_create_requests_table.py` — `requests` table per architecture spec
- `app/db/models/request.py` — `RequestLog` ORM model
- Updated `app/db/models/project.py` — `requests` relationship
- Updated `app/db/models/__init__.py` — export `RequestLog` for Alembic discovery

**Schema (`requests`):**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `project_id` | UUID FK | Indexed — filter metrics per project |
| `created_at` | timestamptz | Indexed — time-window queries |
| `status` | string | `success`, `error`, `cache_hit` |
| `model` | string | e.g. `gpt-4o-mini` |
| `latency_ms` | int | End-to-end gateway latency |
| `input_tokens` / `output_tokens` | int | From provider usage |
| `cost_usd` | float | Computed in Task 5.2+ |
| `cache_hit` | bool | Phase 6 sets true on cache hits |
| `error_reason` | string nullable | Short error code/message |

**Tests:**
- `alembic upgrade head` → migration 0002 applies cleanly

**Meeting-ready summary:**
> I added the requests table — the foundation for observability. Every chat completion will log latency, tokens, cost, and status here so we can compute p50/p95/p99 percentiles instead of meaningless averages.

---

### Task 5.2 — Wire request logging into chat completions

**Date:** 2026-07-15  
**Commit:** `430e091`

**What we built:**
- `app/observability/request_log.py` — `persist_request_log()` writes to `requests` table
- `app/observability/sse_usage.py` — parse token usage from streaming SSE chunks
- Updated `app/routes/chat.py` — log success/error for non-streaming and streaming paths
- Updated `app/providers/openai.py` — `stream_options.include_usage` for streaming token counts
- `scripts/test_request_logging.py` — E2E check after chat completion
- `scripts/test_sse_usage.py` — offline usage parser test

**Decisions:**
- **Own DB session per log** — safe for streaming (runs after response body finishes)
- **Latency** measured wall-clock from route entry to log write
- **cost_usd = 0** for now — cost calculation in Task 5.3
- Stream outcomes: `success` ([DONE]), `error` (provider fail, disconnect, incomplete)

**Tests:**
- `python scripts/test_sse_usage.py` → SSE usage parsing OK
- `python scripts/test_request_logging.py gw-sk-...` → row in `requests` table

**Meeting-ready summary:**
> Every chat completion now writes a row to the requests table with latency, tokens, and status. Streaming requests include usage via OpenAI's stream_options, and errors are logged before we return structured error responses to the client.

---

### Task 5.3 — Cost calculation

**Date:** 2026-07-22  
**Commit:** `d221dfe`
- Updated `persist_request_log()` — auto-computes cost when tokens are present
- `scripts/test_cost.py` — offline pricing tests
- Updated `scripts/test_request_logging.py` — asserts `cost_usd > 0` on success

**Decisions:**
- **Prefix matching** on model name — `gpt-4o-mini-2024-07-18` maps to `gpt-4o-mini` rates
- **Rates in code** for v1 — simple and interview-friendly; env/config later if needed
- **Errors with 0 tokens** → cost 0; successful requests with tokens always get a cost
- **8 decimal places** — enough precision for micro-cent token costs

**Pricing (gpt-4o-mini):** $0.15 / 1M input, $0.60 / 1M output tokens

**Tests:**
- `python scripts/test_cost.py` → Cost estimation OK
- `python scripts/test_request_logging.py gw-sk-...` → Cost USD > 0

**Meeting-ready summary:**
> I added per-model cost estimation from token counts using published OpenAI rates. Every successful logged request now stores cost_usd, which feeds into the metrics API we'll build next.

---

### Task 5.4 — Metrics endpoint

**Date:** 2026-07-22  
**Commit:** `e41d1df`

**What we built:**
- `app/observability/metrics.py` — `compute_metrics()` and pure-Python percentile helper
- `app/schemas/metrics.py` — response models for `/v1/metrics`
- `app/routes/metrics.py` — `GET /v1/metrics` with auth and optional filters
- Registered metrics router in `app/main.py`
- `scripts/test_percentiles.py` — offline percentile tests
- `scripts/test_metrics.py` — E2E metrics fetch

**Decisions:**
- **Percentiles, not averages** — p50/p95/p99 from sorted `latency_ms` values in the window
- **Project scoping** — metrics always limited to the authenticated project; cross-project `project_id` returns 403
- **Default window** — last 24 hours (`since` query param overrides start)
- **cache_hit_rate** — computed now; stays 0 until Phase 6 semantic cache

**Tests:**
- `python scripts/test_percentiles.py` → Percentile helper OK
- `python scripts/test_metrics.py gw-sk-...` → JSON with latency percentiles

**Meeting-ready summary:**
> I exposed GET /v1/metrics so clients can see p50/p95/p99 latency, success rate, token totals, and cost for their project over a time window — the observability read path on top of the request logs we already persist.

---

### Task 5.5 — Request log listing

**Date:** 2026-07-22  
**Commit:** `25e722e`

**What we built:**
- `app/observability/request_list.py` — paginated query with status/model filters
- `app/schemas/requests.py` — response models for `/v1/requests`
- `app/routes/requests.py` — `GET /v1/requests` with auth
- Registered requests router in `app/main.py`
- `scripts/test_requests.py` — E2E list + filter validation

**Decisions:**
- **Newest first** — ordered by `created_at DESC`
- **Project scoping** — only the authenticated project's rows
- **Status filter** — `success`, `error`, or `cache_hit` (cache rows, not a status value)
- **Pagination** — default limit 50, max 200, offset from 0

**Tests:**
- `python scripts/test_requests.py gw-sk-...` → paginated JSON with expected fields

**Meeting-ready summary:**
> I added GET /v1/requests so clients can browse individual request logs with pagination and filters — the drill-down companion to the aggregated metrics endpoint.

---

### Task 5.6 — Minimal dashboard + testing docs

**Date:** 2026-07-22  
**Commit:** `1a2f48b`

**What we built:**
- `app/static/dashboard.html` — single-page metrics + recent requests UI
- `app/routes/dashboard.py` — `GET /dashboard` (no server-side auth; browser calls APIs with user key)
- `scripts/test_dashboard.py` — verifies HTML page is served
- Updated `docs/TESTING.md` — Phase 5 test order, checklist, script reference

**Decisions:**
- **Numbers over UI polish** — cards for p50/p95/p99, success rate, cost; table for recent requests
- **API key in browser only** — stored in `sessionStorage`; dashboard route does not accept keys server-side
- **Same data as APIs** — fetches `/v1/metrics` and `/v1/requests?limit=20` client-side

**Tests:**
- `python scripts/test_dashboard.py` → Dashboard page OK
- Manual: open `http://127.0.0.1:8001/dashboard`, paste key, Refresh

**Meeting-ready summary:**
> I shipped a one-page observability dashboard that reads live metrics and request logs through the same authenticated APIs — good for demos and screenshots without building a full frontend.

---

## Phase 6 — Semantic cache

### Task 6.1 — OpenAI embedding provider

**Date:** 2026-07-22  
**Commit:** `866716c`

**What we built:**
- `app/embeddings/base.py` — `EmbeddingProvider` interface
- `app/embeddings/openai.py` — OpenAI `/v1/embeddings` client
- `app/embeddings/prompt.py` — canonical message text for embedding
- `scripts/test_embed_prompt.py` — offline serialization test
- `scripts/test_embeddings.py` — live embedding dimension check
- Config: `OPENAI_EMBEDDING_MODEL` (default `text-embedding-3-small`)

**Decisions:**
- **Same httpx pattern** as chat provider — separate client, shared API key
- **Full message list embedded** — system + user + assistant roles in stable `role: content` format
- **Not wired into chat yet** — cache lookup lands in Task 6.2–6.3

**Tests:**
- `python scripts/test_embed_prompt.py` → Prompt serialization OK
- `python scripts/test_embeddings.py` → Embeddings OK (requires OpenAI key)

**Meeting-ready summary:**
> I added an embedding client that turns chat messages into vectors via OpenAI's embeddings API — the first building block for semantic cache lookup by cosine similarity.

---

### Task 6.2 — In-memory semantic cache

**Date:** 2026-07-22  
**Commit:** `b7903eb`

**What we built:**
- `app/cache/similarity.py` — pure-Python cosine similarity
- `app/cache/types.py` — `CacheEntry` and `CacheLookupResult`
- `app/cache/memory.py` — `InMemorySemanticCache` lookup/store
- `app/cache/factory.py` — builds cache from `CACHE_SIMILARITY_THRESHOLD`
- Initialized `app.state.semantic_cache` in `app/main.py` lifespan
- `scripts/test_cache_similarity.py` — offline similarity tests
- `scripts/test_semantic_cache.py` — offline hit/miss/scoping tests

**Decisions:**
- **In-memory only** — entries lost on restart; pgvector deferred per SCOPE
- **Scoped by project + model** — no cross-tenant or cross-model hits
- **Best match above threshold** — linear scan over entries (fine for v1 portfolio scale)
- **Not wired into chat yet** — lookup on completions lands in Task 6.3

**Tests:**
- `python scripts/test_cache_similarity.py` → Cosine similarity OK
- `python scripts/test_semantic_cache.py` → Semantic cache OK

**Meeting-ready summary:**
> I built an in-memory semantic cache that finds the nearest stored embedding by cosine similarity, scoped per project and model — ready to plug into the chat route so similar prompts skip the provider call.

---

### Task 6.3 — Wire cache into non-streaming chat

**Date:** 2026-07-22  
**Commit:** `42305d0`

**What we built:**
- `app/cache/chat_integration.py` — cache lookup/store helpers for chat route
- Updated `app/routes/chat.py` — non-streaming path checks cache before provider
- Updated `app/main.py` — `app.state.embedding_provider` in lifespan
- `scripts/test_cache_hit.py` — E2E similar-prompt cache hit test

**Decisions:**
- **Non-streaming only** — streaming still always calls provider (Phase 6 scope)
- **Graceful degradation** — embedding/cache errors log a warning and fall through to OpenAI
- **Cache hit logging** — `cache_hit=true`, zero tokens/cost (no provider call)
- **Cached response id** — `cache-{uuid}` so clients can distinguish from live completions
- **Cache key uses request model** — `body.model` for store/lookup (not OpenAI's dated model suffix)

**Tests:**
- `python scripts/test_cache_hit.py gw-sk-...` → Cache hit OK

**Meeting-ready summary:**
> Non-streaming chat now embeds the prompt, checks the semantic cache, and returns the stored answer on a similarity hit — skipping OpenAI entirely while logging cache_hit for metrics.

> **Plan note:** This commit maps to **plan task 6.4** (cache lookup before provider). Plan **6.3** (DB persistence) followed in the next commit.

---

### Task 6.3 — `cache_entries` table + persistence

**Date:** 2026-07-22  
**Commit:** `7a11255`

**What we built:**
- Migration `0003_create_cache_entries_table.py` — `cache_entries` with JSONB embeddings
- `app/db/models/cache_entry.py` — ORM model with `use_count`, `last_used_at`
- `app/cache/persistence.py` — persist, hydrate on startup, increment use_count on hit
- Updated chat store/hit path to write/read PostgreSQL
- `scripts/test_cache_persistence.py` — store, hydrate, use_count test

**Decisions:**
- **JSONB embeddings** — no pgvector yet; linear scan matches in-memory v1 approach
- **Hydrate on startup** — reload all rows into process memory for fast lookup
- **use_count** — incremented on cache hit for reuse analytics

**Tests:**
- `alembic upgrade head` → migration 0003 applies
- `python scripts/test_cache_persistence.py` → Cache persistence OK

**Meeting-ready summary:**
> Cache entries now survive process restarts — embeddings and responses persist in PostgreSQL, hydrate into memory at startup, and track reuse via use_count.

---

### Task 6.5 — Threshold tuning + hit rate documentation

**Date:** 2026-07-22  
**Commit:** `df1a5e5`

**What we built:**
- `app/cache/threshold_pairs.py` — prompt pairs for experiments (incl. diabetes symptoms vs causes)
- `scripts/test_cache_thresholds.py` — live similarity measurements at 0.92
- `docs/CACHE_TUNING.md` — measured similarities, trade-offs, recommendations

**Decisions:**
- **Keep 0.92 default** — identical prompts hit; same-topic-different-intent pairs miss (diabetes 0.57)
- **Paraphrases miss at 0.92** — capital-of-France paraphrase measured 0.82; documented as trade-off
- **Hit rate via existing metrics** — `cache_hit_rate` on `/v1/metrics`, no new endpoint

**Measured (text-embedding-3-small):**
- symptoms vs causes: **0.5696** → MISS at 0.92 ✓
- paraphrase capital: **0.8224** → MISS at 0.92

**Tests:**
- `python scripts/test_cache_thresholds.py` → Threshold tuning OK

**Meeting-ready summary:**
> I measured real embedding similarities for hit/miss pairs and documented why 0.92 avoids false hits like symptoms vs causes, at the cost of missing light paraphrases.

---

## Phase 7 — Second provider, routing, retries, fallback

### Task 7.1 — Anthropic provider

**Date:** 2026-07-22  
**Commit:** `8ecb6c6`

**What we built:**
- `app/providers/anthropic.py` — Messages API client (non-streaming + streaming)
- `AnthropicProviderError` in `app/providers/exceptions.py`
- Anthropic settings in `app/config.py` and `.env.example`
- `scripts/test_anthropic_provider.py` — direct completion test
- `scripts/test_anthropic_stream.py` — OpenAI-compatible SSE translation test

**Decisions:**
- **OpenAI-compatible SSE output** — Anthropic events translated to `chat.completion.chunk` for gateway reuse
- **System prompt split** — `system` role extracted to Anthropic `system` field
- **Not routed yet** — chat still uses OpenAI only until Task 7.2

**Tests:**
- `python scripts/test_anthropic_provider.py` → content + tokens (requires `ANTHROPIC_API_KEY`)
- `python scripts/test_anthropic_stream.py` → stream chunks + `[DONE]`

**Meeting-ready summary:**
> I added Anthropic as a second LLM backend behind the same provider interface — including streaming translated to OpenAI-style SSE so the gateway route can stay unchanged when routing lands next.

---

### Task 7.2 — Provider routing (OpenAI + Groq)

**Date:** 2026-07-22  
**Commit:** `6c6d1b5`

**What we built:**
- `app/providers/router.py` — model prefix routing to providers
- `app/providers/groq.py` — Groq via OpenAI-compatible client (`provider_name=groq`)
- Updated `app/routes/chat.py` — uses `provider_router.get_provider(model)`
- Updated `app/main.py` — initializes router with configured providers
- Groq settings in `app/config.py` and `.env.example`
- `scripts/test_provider_routing.py` — offline routing rules
- `scripts/test_groq_routing.py` — E2E Groq via gateway

**Routing rules:**
- `gpt-*`, `o1*`, `o3*`, `o4*` → OpenAI
- `llama-*`, `mixtral-*`, `gemma-*`, `qwen-*` → Groq
- `claude-*` → Anthropic (when `ANTHROPIC_API_KEY` configured)

**Decisions:**
- **Groq reuses OpenAIProvider** — same `/v1/chat/completions` shape, different base URL
- **Optional providers** — only registered when API key is present in env
- **Anthropic deferred** — code ready; Groq used for live second-provider testing

**Tests:**
- `python scripts/test_provider_routing.py` → Provider routing rules OK
- `python scripts/test_groq_routing.py gw-sk-...` → after `GROQ_API_KEY` saved in `.env`

**Meeting-ready summary:**
> The gateway now routes by model name — GPT models hit OpenAI, Llama/Mixtral hit Groq — through one OpenAI-compatible chat endpoint, with providers registered only when keys are configured.

---

### Task 7.3 — Provider retries

**Date:** 2026-07-22  
**Commit:** `50509d8`

**What we built:**
- `app/providers/retry.py` — `complete_with_retry()` and `stream_with_retry()`
- Updated `app/routes/chat.py` — retries before returning errors to clients
- Config: `PROVIDER_MAX_RETRIES` (default 2), `PROVIDER_RETRY_BACKOFF_S` (default 0.5)
- `scripts/test_provider_retries.py` — offline retry policy tests

**Decisions:**
- **Retry only transient errors** — 429, 5xx, timeouts; never 4xx client errors
- **Exponential backoff** — 0.5s, 1.0s, 2.0s between attempts
- **Stream retries** — only on opening the stream / first chunk (not mid-stream)
- **Works for OpenAI + Groq** — shared `OpenAIProviderError` path; Anthropic ready too

**Tests:**
- `python scripts/test_provider_retries.py` → Provider retry policy OK

**Meeting-ready summary:**
> Transient provider failures now retry with exponential backoff before the gateway returns an error — covering rate limits, upstream 5xx, and timeouts for both streaming and non-streaming requests.

---

### Task 7.4 — Provider fallback

**Date:** 2026-07-22  
**Commit:** `0219209`

**What we built:**
- `app/providers/fallback.py` — `complete_with_fallback()` and `stream_with_fallback()`
- `ProviderRouter.get_fallback_target()` — maps primary provider → secondary provider + fallback model
- Updated `app/routes/chat.py` — uses fallback wrappers instead of retry-only
- Config: `PROVIDER_FALLBACK_ENABLED`, `PROVIDER_FALLBACK_OPENAI_MODEL`, `PROVIDER_FALLBACK_GROQ_MODEL`
- `scripts/test_provider_fallback.py` — offline fallback test with failing primary + success fallback

**Fallback rules (when enabled and secondary provider configured):**
- Groq primary fails → OpenAI with `PROVIDER_FALLBACK_OPENAI_MODEL` (default `gpt-4o-mini`)
- OpenAI primary fails → Groq with `PROVIDER_FALLBACK_GROQ_MODEL` (default `llama-3.3-70b-versatile`)
- Anthropic primary fails → OpenAI with `PROVIDER_FALLBACK_OPENAI_MODEL`

**Decisions:**
- **Fallback after retries** — primary must exhaust retry policy before fallback runs
- **Model swap on fallback** — request is retried with the configured fallback model, not the client's original model id
- **Same retry policy on fallback** — secondary provider also gets retries
- **Logging** — warning log when fallback triggers; request log stores the fallback model/tokens

**Tests:**
- `python scripts/test_provider_fallback.py` → Provider fallback OK

**Meeting-ready summary:**
> If the primary provider still fails after retries, the gateway automatically tries a configured fallback provider and model — so a Groq outage can transparently degrade to OpenAI instead of failing the client request.

---

## Phase 8 — Security, testing, benchmarks, hardening

### Task 8.1 — API key hashing audit

**Date:** 2026-07-22  
**Commit:** `df3b4c1`

**What we built:**
- Upgraded API key storage from SHA-256 to **bcrypt** (12 rounds)
- Added `api_key_lookup` column + migration `0004` for indexed auth lookup
- `verify_api_key()` supports bcrypt and legacy SHA-256 during migration
- `docs/SECURITY.md` — audit findings and migration steps
- `scripts/test_api_key_hashing.py` — offline hash/verify tests

**Decisions:**
- **bcrypt + lookup prefix** — indexed lookup without scanning all projects; slow hashes if DB leaks
- **Legacy SHA-256 fallback** — existing dev keys keep working until re-seed
- **Re-seed for new format** — `python scripts/seed_test_project.py` after migration

**Tests:**
- `python scripts/test_api_key_hashing.py` → API key hashing OK
- `alembic upgrade head` then re-seed for bcrypt keys in DB

**Meeting-ready summary:**
> I audited API key storage and upgraded from fast SHA-256 digests to bcrypt with a lookup prefix — so a database leak doesn't enable high-speed offline cracking, while auth stays indexed and fast at request time.

---

### Task 8.2 — Automated tests

**Date:** 2026-07-22  
**Commit:** `72cd5e5`

**What we built:**
- `tests/unit/` — auth, routing, retries, fallback, percentiles, cost, cache similarity, error mapping
- `tests/integration/` — health, chat proxy, metrics route (mocked startup — no live DB required)
- `tests/conftest.py` — shared fixtures with mocked `app.state` and auth override
- Pytest markers: `unit`, `integration`
- `pyproject.toml` — pytest config already present; markers added

**Decisions:**
- **Scripts stay** — manual E2E scripts in `scripts/` remain for live API/DB checks
- **Integration tests mock startup** — set `app.state` directly; no PostgreSQL or OpenAI needed for CI
- **41 tests** — covers SCOPE success criteria for auth, proxy, and metrics at unit/integration level

**Tests:**
- `pip install -e ".[dev]"` then `pytest`
- `pytest -m unit` — logic only
- `pytest -m integration` — HTTP layer

**Meeting-ready summary:**
> I added a pytest suite with unit tests for core logic and integration tests for the HTTP routes — all runnable offline with mocked providers and auth, so regressions are caught before manual E2E scripts.

---

### Task 8.3 — Latency benchmark

**Date:** 2026-07-22  
**Commit:** `e0f1035`

**What we built:**
- `scripts/benchmark_latency.py` — compares direct OpenAI vs gateway client-side latency
- `docs/BENCHMARK.md` — methodology, honest limitations, measured results
- `docs/benchmark_results.json` — raw output from local 5-iteration run

**Measured results (gpt-4o-mini, non-streaming, cache miss path):**
- Direct OpenAI p50: **791 ms**
- Gateway p50: **1535 ms**
- Gateway overhead p50: **+744 ms**

**Decisions:**
- **Direct OpenAI baseline** — cleaner than LiteLLM for “what does my proxy add?”
- **Unique prompts per iteration** — avoids semantic cache skewing latency down
- **Report absolute ms + percent** — percent is misleading when provider dominates total time

**Tests:**
- `python scripts/benchmark_latency.py gw-sk-... --iterations 5`

**Meeting-ready summary:**
> I measured real proxy overhead: about 744 ms p50 on non-streaming chat, mainly from embedding-for-cache lookup plus auth/logging — with documented methodology so the numbers are reproducible and honest about trade-offs.

---

### Task 8.3b — Benchmark investigation + miss-path optimization

**Date:** 2026-07-23  
**Commit:** `f23492b`

**Problem:** Initial benchmark showed +744 ms p50 overhead — too high to hand-wave in interviews.

**Investigation:**
- Added `scripts/benchmark_decompose.py` — isolates direct chat vs direct embed vs gateway
- Decompose showed **~260 ms p50 per embedding call**; old miss path did **two embeds**

**Fixes:**
- Skip cache lookup embed when no entries for project/model (`has_entries`)
- Reuse lookup embedding on cache store (one embed per miss, not two)
- Async request logging via `BackgroundTasks` (`REQUEST_LOG_ASYNC=true`)
- `SEMANTIC_CACHE_ENABLED` config for thin-proxy mode

**Tests:**
- `pytest` — 43 passed
- Re-run `benchmark_latency.py` with valid `GATEWAY_TEST_API_KEY` for after numbers

**Meeting-ready summary:**
> I treated bad benchmark numbers as a debugging task: decomposed latency, found duplicate embedding as the main cost, fixed the miss path, and documented before/after methodology instead of moving on with a checklist tick.

---

### Task 8.2b — Heavier DB integration tests

**Date:** 2026-07-25  
**Commit:** `a635855`

**What we built:**
- `tests/integration/conftest.py` — isolated DB fixtures (`db_project`, `db_client`)
- `tests/integration/test_auth_db.py` — real bcrypt auth + inactive project
- `tests/integration/test_request_log_db.py` — `persist_request_log` writes rows
- `tests/integration/test_chat_db.py` — chat with real auth/logging, mocked provider only
- `@pytest.mark.db` — run with `pytest -m db` (skips when PostgreSQL unavailable)
- Engine pool reset between integration tests (Windows asyncpg stability)

**Tests:**
- `pytest -m db` → 7 passed (with PostgreSQL)
- `pytest` → 50 passed total

**Later sub-tasks (8.2c–8.2e):** retry/fallback E2E, streaming at 20/40 concurrency, semantic cache hit/miss — see below and [`docs/DESIGN.md`](docs/DESIGN.md) §9.

**Meeting-ready summary:**
> Lightweight tests mocked the DB; heavier tests spin up real project rows, exercise bcrypt auth and request logging end-to-end, and verify provider failures land in PostgreSQL — with OpenAI still mocked so CI stays deterministic.

---

### Task 8.2c — Provider retry/fallback E2E (real DB)

**Date:** 2026-07-25  
**Commit:** `98b2b58`

**What we built:**
- `tests/fakes/providers.py` — flaky, always-fail, success providers + minimal test routers
- `tests/integration/test_provider_resilience_db.py` — chat route exercises real `complete_with_fallback` (not mocked)
- Retry test: primary fails twice with 503, succeeds on third attempt; success row logged
- Fallback test: Groq primary exhausted → OpenAI fallback model in response + DB
- Failure test: both primary and fallback exhausted → HTTP 502 + error row logged

**Tests:**
- `pytest -m db` → 10 passed (with PostgreSQL)
- `pytest` → 53 passed total

**Meeting-ready summary:**
> Unit tests proved retry/fallback logic in isolation; these integration tests wire stub providers into the real chat route with bcrypt auth and PostgreSQL logging, so we know the full request path behaves correctly when upstream is flaky or a secondary provider takes over.

---

### Task 8.2d — Streaming disconnect and concurrency E2E (real DB)

**Date:** 2026-07-25  
**Commits:** `88d0e88` (initial), expanded in `1442fb5`

**What we built:**
- `StreamingProvider` / `SlowStreamProvider` fakes in `tests/fakes/providers.py`
- `tests/integration/test_streaming_db.py`:
  - Full SSE stream completes → success row with parsed token usage
  - Simulated client disconnect mid-stream → `client_disconnected` error row + upstream closed
  - **20 and 40 parallel streams** (parametrized) — all must see `[DONE]` + success rows
  - **Mixed batch:** 20 concurrent streams + 3 concurrent non-streaming requests (mirrors `scripts/test_concurrent_streams.py`)
- `tests/integration/conftest.py` — teardown deletes `cache_entries` (needed for mixed non-stream requests)

**Tests (after expansion):**
- Streaming file alone: 5 passed
- Full `pytest -m db`: 17 passed (with PostgreSQL)
- Full `pytest`: 62 passed total

**Meeting-ready summary:**
> Streaming is harder to test than JSON because the client can drop mid-flight. These tests exercise the real SSE generator, verify upstream cancellation, and stress **40 parallel streams** in-process with stub providers — proving concurrent requests do not corrupt auth, logging, or stream state.

---

### Task 8.2e — Semantic cache hit/miss E2E (real DB)

**Date:** 2026-07-25  
**Commit:** `1442fb5`

**What we built:**
- `tests/fakes/embeddings.py` — deterministic vectors by prompt keyword (no OpenAI)
- `db_cache_client` fixture — real `InMemorySemanticCache` + PostgreSQL persistence
- `tests/integration/test_cache_db.py`:
  - Miss → provider called, cache row persisted, `cache_hit=false`
  - Hit → provider skipped, cached content returned, `use_count` incremented
  - Below-threshold similarity → miss even when cache has entries
  - Empty cache → skip embed on lookup (only embed once on store)

**Tests:**
- `pytest -m db` → 17 passed (with PostgreSQL)
- `pytest` → 62 passed total

**Meeting-ready summary:**
> Cache logic had unit tests on cosine similarity and memory store; these integration tests run the full chat route with real cache persistence and request logging, proving hits skip the provider and misses store embeddings without duplicate lookup work on an empty cache.

---

### Task 8.4 — Design document (`docs/DESIGN.md`)

**Date:** 2026-07-25  
**Commit:** `dbeaaca`
  - Stack choices and rejected alternatives
  - Streaming, cache, observability, multi-provider resilience, security
  - Benchmark numbers and honest limitations
  - Testing pyramid + table of all 8.2b–8.2e DB integration tests

**Meeting-ready summary:**
> ARCHITECTURE.md shows what connects to what; DESIGN.md explains every major trade-off — duplicate embed overhead, 0.92 threshold false-hit risk, async logging, fallback model swap — so I can defend decisions in a systems interview, not just demo endpoints.

---

### Task 8.5 — README and demo script

**Date:** 2026-07-25  
**Commit:** `dbeaaca`

**What we built:**
- Rewrote root `README.md` — features, quick start, doc index, test commands, local URLs
- `scripts/demo.py` — single walkthrough: health → chat → stream → cache hit → metrics → dashboard link

**Tests:**
- `python scripts/demo.py gw-sk-...` — requires live uvicorn + OpenAI key

**Meeting-ready summary:**
> The README is the front door for recruiters; the demo script is a five-step live narrative that hits every pillar in under a minute — proxy, streaming, semantic cache, and percentile metrics.

---

## Phase 8 complete

All Phase 8 tasks (8.1–8.5) delivered. Next phase per scope: **Phase 9 — PII protection (v2)**.

---
