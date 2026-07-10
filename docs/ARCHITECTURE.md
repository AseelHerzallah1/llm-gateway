# Architecture — LLM Gateway v1

## System context

```mermaid
flowchart LR
    Client[ClientApp] --> Gateway[LLMGateway]
    Gateway --> DB[(PostgreSQL)]
    Gateway --> OpenAI[OpenAIAPI]
    Admin[AdminUser] --> Gateway
```

The gateway is the only component clients talk to. It owns auth, logging, caching, and proxy logic. PostgreSQL stores projects, request logs, and cache entries. OpenAI is the sole LLM provider in v1.

---

## Request flow — non-streaming (Phase 3)

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway
    participant DB as PostgreSQL
    participant O as OpenAI

    C->>G: POST /v1/chat/completions
    G->>G: Validate API key
    G->>DB: Lookup project by key hash
    DB-->>G: Project record
    G->>O: POST /v1/chat/completions
    O-->>G: Full JSON response
    G->>DB: Log request metrics
    G-->>C: OpenAI-shaped response
```

---

## Request flow — streaming (Phase 4)

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway
    participant O as OpenAI

    C->>G: POST /v1/chat/completions stream=true
    G->>G: Validate API key
    G->>O: POST stream=true
    loop Each token chunk
        O-->>G: SSE chunk
        G-->>C: Forward SSE chunk immediately
    end
    Note over C,G: If client disconnects, G cancels upstream
    G->>G: Log metrics after stream ends
```

**Key constraint:** Gateway forwards chunks as they arrive. It does **not** accumulate the full response in memory before sending.

---

## Request flow — with semantic cache (Phase 6)

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway
    participant Cache as SemanticCache
    participant E as EmbeddingsAPI
    participant O as OpenAI

    C->>G: POST /v1/chat/completions
    G->>G: Validate API key
    G->>E: Compute prompt embedding
    G->>Cache: Find nearest neighbor
    alt Similarity above threshold
        Cache-->>G: Cached response
        G-->>C: Cached response
        Note over G: cache_hit=true, no provider call
    else Cache miss
        G->>O: Forward to provider
        O-->>G: Response
        G->>Cache: Store embedding + response
        G-->>C: Response
    end
```

---

## Component map (by phase)

| Component | Directory (planned) | Phase |
|-----------|---------------------|-------|
| FastAPI app | `app/main.py` | 2 |
| Config | `app/config.py` | 2 |
| Database | `app/db/` | 2 |
| Auth middleware | `app/auth/` | 3 |
| Provider interface | `app/providers/base.py` | 3 |
| OpenAI provider | `app/providers/openai.py` | 3–4 |
| Chat route | `app/routes/chat.py` | 3–4 |
| Observability | `app/observability/` | 5 |
| Metrics route | `app/routes/metrics.py` | 5 |
| Semantic cache | `app/cache/` | 6 |
| Embeddings | `app/embeddings/` | 6 |

---

## Database tables (v1)

```mermaid
erDiagram
    users ||--o{ projects : owns
    projects ||--o{ requests : generates
    projects ||--o{ cache_entries : has

    users {
        uuid id PK
        string email
        string password_hash
        timestamp created_at
    }

    projects {
        uuid id PK
        uuid user_id FK
        string name
        string api_key_hash
        boolean active
        timestamp created_at
    }

    requests {
        uuid id PK
        uuid project_id FK
        timestamp created_at
        string status
        string model
        int latency_ms
        int input_tokens
        int output_tokens
        float cost_usd
        boolean cache_hit
        string error_reason
    }

    cache_entries {
        uuid id PK
        uuid project_id FK
        vector embedding
        text cached_response
        string model
        int use_count
        timestamp last_used_at
    }
```

`cache_entries` added in Phase 6. `users` and `projects` in Phase 2. `requests` in Phase 5.

---

## Key design decisions

| Decision | Choice | Trade-off |
|----------|--------|-----------|
| OpenAI-compatible API | Yes | Easy client adoption; locked to their schema |
| Non-streaming before streaming | Yes | Slower progress, but isolates proxy bugs |
| Observability before cache | Yes | Can measure cache impact when it ships |
| In-memory cache first | Yes | Simple; lost on restart — acceptable for v1 |
| Single provider v1 | Yes | Less routing complexity; prove proxy first |
| Percentiles over averages | Yes | Harder to compute; much more meaningful |

---

## What is intentionally not in v1 architecture

- Load balancer / multiple gateway instances
- Redis or message queue
- Kubernetes
- LangChain orchestration layer
- PII detection pipeline (Phase 9)
