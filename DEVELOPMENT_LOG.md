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
**Commit:** _(pending push)_

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
