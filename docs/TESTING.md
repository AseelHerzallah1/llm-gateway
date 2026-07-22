# Manual Testing — LLM Gateway

Step-by-step checks for Phases 3–5: non-streaming proxy, SSE streaming, observability, auth, and error mapping.

**Local base URL:** `http://127.0.0.1:8001`  
(Port 8001 avoids conflicts with other services on 8000.)

---

## Prerequisites

| Requirement | Purpose |
|-------------|---------|
| Python 3.11+ with `.venv` | Run the app and scripts |
| Docker Desktop (running) | PostgreSQL container — start Docker before testing if you quit it |
| `.env` from `.env.example` | Database URL, OpenAI key, secrets |
| `OPENAI_API_KEY` | Real OpenAI key for live provider/chat tests |
| Gateway API key (`gw-sk-...`) | From `seed_test_project.py` — client → gateway auth |

### One-time setup

```powershell
cd "c:\Users\Aseel Herzallah\OneDrive\Desktop\LLM-Gateway"

# Virtual environment (if not created yet)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Environment file
copy .env.example .env
# Edit .env: set OPENAI_API_KEY=sk-...

# Database (Docker Desktop must be running)
docker compose up db -d
alembic upgrade head

# Seed test project (prints gw-sk-... once — save it)
python scripts/seed_test_project.py
```

Optional convenience in `.env` (gitignored):

```
GATEWAY_TEST_API_KEY=gw-sk-your-key-here
```

### Start the gateway

```powershell
.venv\Scripts\Activate.ps1
docker compose up db -d
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

If you use `--reload`, limit watch scope to avoid OneDrive loops:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --reload-dir app
```

---

## Test order (bottom-up)

Run these in order. Each layer depends on the one below.

```
Phase 3 — Non-streaming
  1. Error mapping (offline)       → no network
  2. OpenAI provider (direct)      → OpenAI only
  3. Database seed + auth          → PostgreSQL only
  4. GET /health                   → gateway up
  5. POST /v1/chat/completions     → full stack (stream=false)
  6. Error scenarios               → auth + validation

Phase 4 — Streaming
  7. OpenAI provider stream        → direct SSE from OpenAI
  8. Gateway SSE stream            → stream=true via HTTP
  9. Client disconnect cancel      → upstream cancellation
 10. Concurrent streams            → parallel stream=true requests

Phase 5 — Observability
 11. Request logging               → row in requests table after chat
 12. Cost calculation              → cost_usd > 0 on success
 13. Metrics endpoint              → p50/p95/p99 percentiles
 14. Request log API                → paginated GET /v1/requests
 15. Dashboard                     → browser page at /dashboard
```

---

## Phase 3 — Non-streaming

### 1. Error mapping (offline)

No server or API keys required.

```powershell
python scripts/test_error_mapping.py
```

**Expected:**

```
Error mapping OK
```

Verifies provider failures map to gateway status codes (504, 429, 400, 502).

---

### 2. OpenAI provider (direct, non-streaming)

Tests httpx → OpenAI without the gateway HTTP layer.

```powershell
python scripts/test_openai_provider.py
```

**Expected (example):**

```
Provider: openai
Model: gpt-4o-mini
Content: Hello!
Tokens: 12
```

**If it fails:**

| Symptom | Fix |
|---------|-----|
| `Config error` / missing key | Set `OPENAI_API_KEY` in `.env` |
| HTTP 401 from OpenAI | Invalid or expired OpenAI key |
| Timeout | Network issue or OpenAI outage |

---

### 3. Seed + API key auth

#### Seed (first time only)

```powershell
python scripts/seed_test_project.py
```

**Expected:**

```
Seeded test project successfully.
Project name: test-project
API key (save this — shown once):
gw-sk-...
```

If the user already exists, delete rows in PostgreSQL or use your saved key:

```sql
DELETE FROM projects;
DELETE FROM users;
```

Then re-run the seed script.

#### Auth lookup test

```powershell
python scripts/test_auth.py gw-sk-YOUR-KEY
```

**Expected:**

```
Auth OK
Project ID: <uuid>
Project name: test-project
Active: True
```

---

### 4. Health check

#### PowerShell

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/health"
```

#### curl

```bash
curl -s http://127.0.0.1:8001/health
```

**Expected `200 OK`:**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

No authentication required.

---

### 5. Chat completions (non-streaming, full stack)

#### Python script

```powershell
python scripts/test_chat_completions.py gw-sk-YOUR-KEY
```

Or with `GATEWAY_TEST_API_KEY` in `.env`:

```powershell
python scripts/test_chat_completions.py
```

**Expected:** `Status: 200` and a JSON body with `choices[0].message.content`.

#### PowerShell (manual)

```powershell
$headers = @{
    Authorization = "Bearer gw-sk-YOUR-KEY"
    "Content-Type" = "application/json"
}
$body = @{
    model = "gpt-4o-mini"
    messages = @(@{ role = "user"; content = "Say hello in one word." })
    stream = $false
    max_tokens = 10
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers $headers `
    -Body $body
```

#### curl

```bash
curl -s -X POST http://127.0.0.1:8001/v1/chat/completions \
  -H "Authorization: Bearer gw-sk-YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello in one word."}],
    "stream": false,
    "max_tokens": 10
  }'
```

**Success response shape (`200 OK`):**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "Hello!" },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 2,
    "total_tokens": 14
  }
}
```

---

### 6. Error scenarios (non-streaming)

All error bodies use the same shape:

```json
{
  "error": {
    "message": "...",
    "type": "...",
    "code": "..."
  }
}
```

#### Missing API key → `401`

```powershell
Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -ContentType "application/json" `
    -Body '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hi"}]}'
```

**Expected:** `401`, `"code": "invalid_api_key"`

#### Invalid API key → `401`

```powershell
$headers = @{ Authorization = "Bearer gw-sk-invalid" }
Invoke-WebRequest -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hi"}]}' `
    -SkipHttpErrorCheck
```

Check `$response.StatusCode` is `401`.

#### Invalid request body → `422`

```powershell
$headers = @{ Authorization = "Bearer gw-sk-YOUR-KEY" }
Invoke-WebRequest -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body '{"model":"gpt-4o-mini"}' `
    -SkipHttpErrorCheck
```

**Expected:** `422`, `"code": "validation_error"` (missing `messages`)

#### Bad OpenAI model → `400`

```powershell
$headers = @{ Authorization = "Bearer gw-sk-YOUR-KEY" }
Invoke-WebRequest -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body '{"model":"not-a-real-model","messages":[{"role":"user","content":"Hi"}],"stream":false}' `
    -SkipHttpErrorCheck
```

**Expected:** `400`, `"code": "invalid_request"` (OpenAI error message forwarded)

---

## Phase 4 — Streaming (SSE)

### 7. OpenAI provider stream (direct)

Tests httpx SSE → OpenAI without the gateway HTTP layer.

```powershell
python scripts/test_openai_stream.py
```

**Expected:**

- Multiple `data: {...}` lines printed as they arrive
- Final line: `data: [DONE]`
- Summary: `Events received: N` and assembled content

---

### 8. Gateway SSE stream (full stack)

Requires uvicorn running on port 8001.

#### Python script

```powershell
python scripts/test_chat_stream.py gw-sk-YOUR-KEY
```

**Expected:**

```
Status: 200
Content-Type: text/event-stream
data: {"id":"chatcmpl-...", ...}
...
data: [DONE]
Saw [DONE]: True
```

#### PowerShell (manual)

PowerShell's `Invoke-RestMethod` buffers the full response — it is **not** suitable for watching live SSE chunks. Use the Python script or curl:

```bash
curl -N -X POST http://127.0.0.1:8001/v1/chat/completions \
  -H "Authorization: Bearer gw-sk-YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Count from 1 to 5."}],
    "stream": true,
    "max_tokens": 50
  }'
```

The `-N` flag disables curl buffering so chunks appear immediately.

#### Streaming auth errors (before first byte)

If the provider rejects the request before streaming starts, the gateway returns JSON (not SSE):

```powershell
$headers = @{ Authorization = "Bearer gw-sk-YOUR-KEY" }
Invoke-WebRequest -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body '{"model":"not-a-real-model","messages":[{"role":"user","content":"Hi"}],"stream":true}' `
    -SkipHttpErrorCheck
```

**Expected:** `400` JSON with `"code": "invalid_request"`

---

### 9. Client disconnect cancellation

Simulates a client dropping the connection mid-stream. The gateway should cancel the upstream OpenAI request.

```powershell
# Terminal 1 — watch for log line:
# "Client disconnected mid-stream, cancelling upstream project_id=..."

# Terminal 2
python scripts/test_stream_cancel.py gw-sk-YOUR-KEY
```

**Expected:**

- Client prints ~5 SSE events then `Disconnecting after 5 events`
- Uvicorn logs show cancellation (not an unhandled error)
- No need to wait for `data: [DONE]` — disconnect is intentional

**Why this matters:** Without cancellation, OpenAI keeps generating tokens after the client leaves, wasting API cost and server resources.

---

### 10. Concurrent streaming requests

Verifies multiple parallel `stream=true` requests (and a few non-streaming) complete without interfering with each other.

```powershell
python scripts/test_concurrent_streams.py gw-sk-YOUR-KEY

# Optional: custom concurrency (default 5)
python scripts/test_concurrent_streams.py gw-sk-YOUR-KEY 8
```

**Expected:**

```
Streaming:     5/5 succeeded
Non-streaming: 3/3 succeeded
Concurrent streams OK
```

**If it fails:**

| Symptom | Likely cause |
|---------|--------------|
| Connection refused | uvicorn not running |
| Some streams FAIL with 401 | Invalid gateway key |
| Timeouts under load | OpenAI rate limits or slow network — retry with lower concurrency |
| Stream hangs | Check `OPENAI_STREAM_IDLE_TIMEOUT_S` in `.env` (default 30s) |

---

### 11. Provider timeout handling

Offline test — no gateway or OpenAI key required.

```powershell
python scripts/test_provider_timeouts.py
```

**Expected:**

```
Provider timeout handling OK
```

Verifies connect timeout to unreachable host and idle timeout → `504 gateway_timeout` mapping.

---

## Phase 5 — Observability

Run after Phase 4. Requires migration `0002` (`requests` table) and at least one successful chat completion logged.

### 11. SSE usage parser (offline)

```powershell
python scripts/test_sse_usage.py
```

**Expected:** `SSE usage parsing OK`

### 12. Request logging (E2E)

Send a non-streaming chat completion, then confirm a row was written:

```powershell
python scripts/test_request_logging.py gw-sk-your-key
```

**Expected:** `Request logging OK` with `Cost USD` > 0.

### 13. Cost calculation (offline)

```powershell
python scripts/test_cost.py
```

**Expected:** `Cost estimation OK`

### 14. Percentile helper (offline)

```powershell
python scripts/test_percentiles.py
```

**Expected:** `Percentile helper OK`

### 15. Metrics endpoint

```powershell
python scripts/test_metrics.py gw-sk-your-key
```

**Expected:** JSON with `latency_ms.p50`, `p95`, `p99`, token totals, and `cost_usd`.

Optional manual check:

```powershell
curl -H "Authorization: Bearer gw-sk-your-key" http://127.0.0.1:8001/v1/metrics
```

### 16. Request log listing

```powershell
python scripts/test_requests.py gw-sk-your-key
```

**Expected:** `Requests endpoint OK` with `total` ≥ 1 and expected item fields.

### 17. Dashboard page

```powershell
python scripts/test_dashboard.py
```

**Expected:** `Dashboard page OK`

Manual UI check (good for screenshots):

1. Open `http://127.0.0.1:8001/dashboard`
2. Paste your `gw-sk-...` key
3. Click **Refresh**
4. Confirm metrics cards and recent-requests table populate

The API key stays in browser `sessionStorage` only — it is not sent to any route except `/v1/metrics` and `/v1/requests`.

---

## Checklists

### Phase 3

| # | Test | Command / action | Pass criteria |
|---|------|------------------|---------------|
| 1 | Error mapping | `python scripts/test_error_mapping.py` | Prints `Error mapping OK` |
| 2 | OpenAI provider | `python scripts/test_openai_provider.py` | Content + token count printed |
| 3 | Seed project | `python scripts/seed_test_project.py` | `gw-sk-...` key printed |
| 4 | Auth lookup | `python scripts/test_auth.py <key>` | `Auth OK` |
| 5 | Health | `GET /health` | `status: ok` |
| 6 | Chat (script) | `python scripts/test_chat_completions.py <key>` | HTTP 200 |
| 7 | No auth | POST without header | HTTP 401 |
| 8 | Bad body | POST without `messages` | HTTP 422 |

### Phase 4

| # | Test | Command / action | Pass criteria |
|---|------|------------------|---------------|
| 1 | Provider stream | `python scripts/test_openai_stream.py` | SSE chunks + `[DONE]` |
| 2 | Gateway stream | `python scripts/test_chat_stream.py <key>` | HTTP 200, `text/event-stream`, `[DONE]` |
| 3 | Stream auth error | POST stream + invalid model | HTTP 400 JSON (before SSE) |
| 4 | Disconnect cancel | `python scripts/test_stream_cancel.py <key>` | Client drops; server logs cancellation |
| 5 | Concurrent streams | `python scripts/test_concurrent_streams.py <key>` | All N streams + non-stream requests succeed |
| 6 | Provider timeouts | `python scripts/test_provider_timeouts.py` | Prints `Provider timeout handling OK` |

### Phase 5

| # | Test | Command / action | Pass criteria |
|---|------|------------------|---------------|
| 1 | SSE usage parser | `python scripts/test_sse_usage.py` | `SSE usage parsing OK` |
| 2 | Cost calculation | `python scripts/test_cost.py` | `Cost estimation OK` |
| 3 | Percentiles | `python scripts/test_percentiles.py` | `Percentile helper OK` |
| 4 | Request logging | `python scripts/test_request_logging.py <key>` | Row logged, `cost_usd > 0` |
| 5 | Metrics API | `python scripts/test_metrics.py <key>` | Latency percentiles returned |
| 6 | Requests API | `python scripts/test_requests.py <key>` | Paginated list with fields |
| 7 | Dashboard | `python scripts/test_dashboard.py` then open `/dashboard` | Page loads; Refresh shows data |

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|--------------|-----|
| `Connection refused` on 8001 | uvicorn not running | Start uvicorn (see above) |
| Port 8001 already in use | Old uvicorn still running | Stop the other process or use another port |
| Database connection error | Docker not running or DB stopped | Start Docker Desktop, then `docker compose up db -d` |
| `ModuleNotFoundError: app` | Wrong directory or venv | Activate `.venv`, run from project root |
| `relation "projects" does not exist` | Migrations not applied | `alembic upgrade head` |
| Auth OK in script but 401 on HTTP | Wrong key in header | Re-copy key from seed output |
| 502 `provider_error` | Bad `OPENAI_API_KEY` in `.env` | Fix server-side OpenAI key |
| 404 on `/v1/metrics` or `/v1/requests` | Old uvicorn without new routes | Restart uvicorn after pulling code |
| 404 on `/dashboard` | Same as above | Restart uvicorn |
| Docker app image pull fails | Network/CDN issue | Run DB in Docker, app locally (this guide) |
| Stream hangs with no output | Client buffering | Use `curl -N` or the Python stream scripts |

---

## Script reference

| Script | Network | Keys needed |
|--------|---------|-------------|
| `scripts/test_error_mapping.py` | None | None |
| `scripts/test_openai_provider.py` | OpenAI | `OPENAI_API_KEY` |
| `scripts/test_openai_stream.py` | OpenAI | `OPENAI_API_KEY` |
| `scripts/seed_test_project.py` | PostgreSQL | `DATABASE_URL` |
| `scripts/test_auth.py` | PostgreSQL | Gateway key (argument) |
| `scripts/test_chat_completions.py` | Gateway + OpenAI | Gateway key + running uvicorn |
| `scripts/test_chat_stream.py` | Gateway + OpenAI | Gateway key + running uvicorn |
| `scripts/test_stream_cancel.py` | Gateway + OpenAI | Gateway key + running uvicorn |
| `scripts/test_concurrent_streams.py` | Gateway + OpenAI | Gateway key + running uvicorn |
| `scripts/test_provider_timeouts.py` | None (offline) | None |
| `scripts/test_sse_usage.py` | None (offline) | None |
| `scripts/test_cost.py` | None (offline) | None |
| `scripts/test_percentiles.py` | None (offline) | None |
| `scripts/test_request_logging.py` | Gateway + OpenAI + PostgreSQL | Gateway key + running uvicorn |
| `scripts/test_metrics.py` | Gateway + PostgreSQL | Gateway key + running uvicorn |
| `scripts/test_requests.py` | Gateway + PostgreSQL | Gateway key + running uvicorn |
| `scripts/test_dashboard.py` | Gateway | Running uvicorn |
| `scripts/test_cache_similarity.py` | None (offline) | None |
| `scripts/test_semantic_cache.py` | None (offline) | None |
| `scripts/test_embeddings.py` | OpenAI | `OPENAI_API_KEY` |
| `scripts/test_cache_persistence.py` | PostgreSQL | Migration 0003 |
| `scripts/test_cache_hit.py` | Gateway + OpenAI | Gateway key + running uvicorn |
| `scripts/test_cache_thresholds.py` | OpenAI | `OPENAI_API_KEY` |

---

## Phase 6 — Semantic cache

### 18. Cache similarity (offline)

```powershell
python scripts/test_cache_similarity.py
python scripts/test_semantic_cache.py
```

### 19. Embeddings (live)

```powershell
python scripts/test_embeddings.py
```

### 20. Cache persistence

```powershell
alembic upgrade head
python scripts/test_cache_persistence.py
```

### 21. Cache hit (E2E)

```powershell
python scripts/test_cache_hit.py gw-sk-your-key
```

### 22. Threshold tuning

```powershell
python scripts/test_cache_thresholds.py
```

See `docs/CACHE_TUNING.md` for measured similarities and threshold trade-offs.

---

## What's next (Phase 7+)
