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
**Commit:** _(pending push)_

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
