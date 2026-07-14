# Manual Testing — Phase 3 (Non-Streaming Proxy)

Step-by-step checks for the non-streaming gateway: health, auth, provider, chat completions, and error mapping.

**Local base URL:** `http://127.0.0.1:8001`  
(Port 8001 avoids conflicts with other services on 8000.)

---

## Prerequisites

| Requirement | Purpose |
|-------------|---------|
| Python 3.11+ with `.venv` | Run the app and scripts |
| Docker Desktop | PostgreSQL container |
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

# Database
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
1. Error mapping (offline)     → no network
2. OpenAI provider (direct)    → OpenAI only
3. Database seed + auth        → PostgreSQL only
4. GET /health                 → gateway up
5. POST /v1/chat/completions → full stack
6. Error scenarios             → auth + validation + stream rejection
```

---

## 1. Error mapping (offline)

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

## 2. OpenAI provider (direct)

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

## 3. Seed + API key auth

### Seed (first time only)

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

### Auth lookup test

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

## 4. Health check

### PowerShell

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/health"
```

### curl

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

## 5. Chat completions (full stack)

### Python script

```powershell
python scripts/test_chat_completions.py gw-sk-YOUR-KEY
```

Or with `GATEWAY_TEST_API_KEY` in `.env`:

```powershell
python scripts/test_chat_completions.py
```

**Expected:** `Status: 200` and a JSON body with `choices[0].message.content`.

### PowerShell (manual)

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

### curl

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

### Alternative auth header

The gateway also accepts `X-API-Key`:

```powershell
Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers @{ "X-API-Key" = "gw-sk-YOUR-KEY"; "Content-Type" = "application/json" } `
    -Body '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hi"}],"stream":false}'
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

## 6. Error scenarios

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

### Missing API key → `401`

```powershell
Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -ContentType "application/json" `
    -Body '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hi"}]}'
```

**Expected:** `401`, `"code": "invalid_api_key"`

### Invalid API key → `401`

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

### Streaming not supported → `400`

```powershell
$headers = @{ Authorization = "Bearer gw-sk-YOUR-KEY" }
Invoke-WebRequest -Method Post `
    -Uri "http://127.0.0.1:8001/v1/chat/completions" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hi"}],"stream":true}' `
    -SkipHttpErrorCheck
```

**Expected:** `400`, `"code": "streaming_not_supported"`

### Invalid request body → `422`

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

### Bad OpenAI model (via gateway) → `400`

Use a valid gateway key but an invalid model name:

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

## Phase 3 checklist

| # | Test | Command / action | Pass criteria |
|---|------|------------------|---------------|
| 1 | Error mapping | `python scripts/test_error_mapping.py` | Prints `Error mapping OK` |
| 2 | OpenAI provider | `python scripts/test_openai_provider.py` | Content + token count printed |
| 3 | Seed project | `python scripts/seed_test_project.py` | `gw-sk-...` key printed |
| 4 | Auth lookup | `python scripts/test_auth.py <key>` | `Auth OK` |
| 5 | Health | `GET /health` | `status: ok` |
| 6 | Chat (script) | `python scripts/test_chat_completions.py <key>` | HTTP 200 |
| 7 | No auth | POST without header | HTTP 401 |
| 8 | Stream rejected | POST with `"stream": true` | HTTP 400 |
| 9 | Bad body | POST without `messages` | HTTP 422 |

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|--------------|-----|
| `Connection refused` on 8001 | uvicorn not running | Start uvicorn (see above) |
| `ModuleNotFoundError: app` | Wrong directory or venv | Activate `.venv`, run from project root |
| Database connection error | PostgreSQL not up | `docker compose up db -d` |
| `relation "projects" does not exist` | Migrations not applied | `alembic upgrade head` |
| Auth OK in script but 401 on HTTP | Wrong key in header | Re-copy key from seed output |
| 502 `provider_error` | Bad `OPENAI_API_KEY` in `.env` | Fix server-side OpenAI key |
| uvicorn reload loop | OneDrive syncing `.venv` | Drop `--reload` or use `--reload-dir app` |
| Docker app image pull fails | Network/CDN issue | Run DB in Docker, app locally (this guide) |

---

## Script reference

| Script | Network | Keys needed |
|--------|---------|-------------|
| `scripts/test_error_mapping.py` | None | None |
| `scripts/test_openai_provider.py` | OpenAI | `OPENAI_API_KEY` |
| `scripts/seed_test_project.py` | PostgreSQL | `DATABASE_URL` |
| `scripts/test_auth.py` | PostgreSQL | Gateway key (argument) |
| `scripts/test_chat_completions.py` | Gateway + OpenAI | Gateway key + running uvicorn |

---

## What's next (Phase 4+)

- **Phase 4:** Streaming (`stream: true`, SSE) — new tests will be added here
- **Phase 5:** Metrics and request logging endpoints
- **Phase 6:** Semantic cache behavior tests
