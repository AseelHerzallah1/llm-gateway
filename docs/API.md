# API Contract — LLM Gateway v1

OpenAI-compatible subset. Clients that already use the OpenAI SDK should work by changing only the `base_url` and `api_key`.

**Base URL (local dev):** `http://localhost:8000`

---

## Endpoints overview

| Method | Path | Phase | Description |
|--------|------|-------|-------------|
| `GET` | `/health` | 2 | Liveness check — returns gateway status |
| `POST` | `/v1/chat/completions` | 3–4 | Proxy chat completion to provider (non-streaming → streaming) |
| `GET` | `/v1/metrics` | 5 | Aggregated metrics: latency percentiles, cost, cache hit rate |
| `GET` | `/v1/requests` | 5 | Filterable request log (paginated) |
| `POST` | `/admin/projects` | 2–3 | Create project + API key (minimal admin) |

### Not in v1

| Method | Path | Reason |
|--------|------|--------|
| `POST` | `/v1/embeddings` | Out of scope for v1 API surface (embeddings used internally for cache in Phase 6) |
| `GET` | `/v1/models` | Deferred — v1 uses a configured default model |
| Multi-provider routing headers | — | Phase 7 |

---

## `GET /health`

**Phase:** 2  
**Auth:** None

### Response `200 OK`

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

Used by Docker health checks and deployment verification.

---

## `POST /v1/chat/completions`

**Phase:** 3 (non-streaming) → 4 (streaming)  
**Auth:** Required — see [Authentication](#authentication)  
**Content-Type:** `application/json`

Primary proxy endpoint. Forwards compatible fields to OpenAI; returns OpenAI-shaped responses.

### Request body (v1 supported fields)

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    { "role": "user", "content": "Hello" }
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1024
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `model` | string | yes | Must be an allowed model for the project |
| `messages` | array | yes | OpenAI chat message format |
| `stream` | boolean | no | Default `false`. Phase 4 enables `true` (SSE) |
| `temperature` | number | no | Passed through to provider |
| `max_tokens` | integer | no | Passed through to provider |

### Response `200 OK` (non-streaming, Phase 3)

OpenAI-compatible `chat.completion` object — gateway adds no extra fields in the response body (metrics logged server-side in Phase 5).

### Response `200 OK` (streaming, Phase 4)

`Content-Type: text/event-stream`

Server-Sent Events (SSE) — each event is a `data: {...}` line matching OpenAI streaming format, terminated by `data: [DONE]`.

### Error responses

| Status | When |
|--------|------|
| `401` | Missing or invalid API key |
| `429` | Rate limit exceeded |
| `502` | Provider error or timeout |
| `504` | Gateway timeout waiting for provider |

---

## `GET /v1/metrics`

**Phase:** 5  
**Auth:** Required

### Query parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `project_id` | uuid | — | Filter to one project |
| `model` | string | — | Filter to one model |
| `since` | ISO 8601 | 24h ago | Start of time window |

### Response `200 OK`

```json
{
  "window": { "since": "2026-07-09T00:00:00Z", "until": "2026-07-10T00:00:00Z" },
  "total_requests": 142,
  "success_rate": 0.98,
  "cache_hit_rate": 0.12,
  "latency_ms": { "p50": 320, "p95": 890, "p99": 1420 },
  "tokens": { "input": 45000, "output": 12000 },
  "cost_usd": 0.84
}
```

---

## `GET /v1/requests`

**Phase:** 5  
**Auth:** Required

### Query parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | — | `success`, `error`, `cache_hit` |
| `model` | string | — | Filter by model |
| `limit` | integer | 50 | Max 200 |
| `offset` | integer | 0 | Pagination offset |

### Response `200 OK`

```json
{
  "total": 142,
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-07-10T12:00:00Z",
      "model": "gpt-4o-mini",
      "status": "success",
      "latency_ms": 340,
      "input_tokens": 120,
      "output_tokens": 45,
      "cost_usd": 0.002,
      "cache_hit": false
    }
  ]
}
```

---

## `POST /admin/projects`

**Phase:** 2–3  
**Auth:** Admin credentials (simple — single admin user in v1)

### Request body

```json
{
  "name": "my-app"
}
```

### Response `201 Created`

```json
{
  "project_id": "uuid",
  "name": "my-app",
  "api_key": "gw-sk-xxxxxxxx"
}
```

> **Important:** `api_key` is shown **once** at creation. Only the hash is stored.

---

## Versioning

- All proxy endpoints live under `/v1/`
- Breaking changes require `/v2/` — v1 contract frozen once Phase 3 ships

## Compatibility goal

A client using the OpenAI Python SDK should work with:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="gw-sk-xxxxxxxx",
)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}],
)
```

This is the bar for Phase 3 completion.

---

## Request / response schemas (Phase 1 — Task 1.3)

### `ChatCompletionRequest`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["model", "messages"],
  "properties": {
    "model": { "type": "string", "minLength": 1 },
    "messages": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["role", "content"],
        "properties": {
          "role": { "type": "string", "enum": ["system", "user", "assistant"] },
          "content": { "type": "string" }
        }
      }
    },
    "stream": { "type": "boolean", "default": false },
    "temperature": { "type": "number", "minimum": 0, "maximum": 2 },
    "max_tokens": { "type": "integer", "minimum": 1 }
  }
}
```

### `ChatCompletionResponse` (non-streaming)

```json
{
  "type": "object",
  "required": ["id", "object", "created", "model", "choices"],
  "properties": {
    "id": { "type": "string" },
    "object": { "type": "string", "const": "chat.completion" },
    "created": { "type": "integer" },
    "model": { "type": "string" },
    "choices": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "index": { "type": "integer" },
          "message": {
            "type": "object",
            "properties": {
              "role": { "type": "string" },
              "content": { "type": "string" }
            }
          },
          "finish_reason": { "type": "string" }
        }
      }
    },
    "usage": {
      "type": "object",
      "properties": {
        "prompt_tokens": { "type": "integer" },
        "completion_tokens": { "type": "integer" },
        "total_tokens": { "type": "integer" }
      }
    }
  }
}
```

### `StreamChunk` (streaming, one SSE event)

```json
{
  "type": "object",
  "properties": {
    "id": { "type": "string" },
    "object": { "type": "string", "const": "chat.completion.chunk" },
    "created": { "type": "integer" },
    "model": { "type": "string" },
    "choices": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "index": { "type": "integer" },
          "delta": {
            "type": "object",
            "properties": {
              "role": { "type": "string" },
              "content": { "type": "string" }
            }
          },
          "finish_reason": { "type": "string", "nullable": true }
        }
      }
    }
  }
}
```

### `ErrorResponse` (all endpoints)

```json
{
  "type": "object",
  "required": ["error"],
  "properties": {
    "error": {
      "type": "object",
      "required": ["message", "type", "code"],
      "properties": {
        "message": { "type": "string" },
        "type": { "type": "string" },
        "code": { "type": "string" }
      }
    }
  }
}
```

---

## Authentication (Phase 1 — Task 1.4)

### Client → Gateway (project API key)

All `/v1/*` endpoints require authentication.

**Header (preferred — OpenAI SDK compatible):**

```
Authorization: Bearer gw-sk-<project-key>
```

**Alternative header:**

```
X-API-Key: gw-sk-<project-key>
```

### Validation flow

1. Extract key from `Authorization` or `X-API-Key`
2. Lookup project candidates by `api_key_lookup` prefix (first 12 chars of secret segment)
3. Verify with **bcrypt** against `projects.api_key_hash`
4. Legacy rows without `api_key_lookup` fall back to SHA-256 equality match
5. Reject if: missing, malformed, not found, or project inactive

See `docs/SECURITY.md` for the Phase 8 audit and migration notes.

### Admin → Gateway (project creation)

`POST /admin/projects` uses separate admin credentials:

```
Authorization: Bearer <admin-session-token>
```

v1: single admin user in `users` table. Session token issued via simple login endpoint (Phase 2).

### Error codes

| HTTP | `error.code` | When |
|------|--------------|------|
| `401` | `invalid_api_key` | Key missing, wrong format, or not found |
| `401` | `inactive_project` | Project exists but is disabled |
| `403` | `forbidden` | Valid key but insufficient permissions |
| `429` | `rate_limit_exceeded` | Project exceeded request limit |

### Example error body

```json
{
  "error": {
    "message": "Invalid API key provided.",
    "type": "authentication_error",
    "code": "invalid_api_key"
  }
}
```

### Security rules

- API keys shown **once** at project creation; only bcrypt/argon2 hash stored
- Keys never logged in plaintext
- Admin passwords stored hashed (bcrypt/argon2) — never plaintext

