# Architecture — LLM Gateway

## System context

```mermaid
flowchart LR
    Client[ClientApp] --> Gateway[LLMGateway]
    Gateway --> DB[(PostgreSQL)]
    Gateway --> Router[ProviderRouter]
    Router --> OpenAI[OpenAI]
    Router --> Groq[Groq]
    Router --> Anthropic[Anthropic]
```

The gateway is the only component clients talk to. It owns auth, optional PII redaction, **L1 exact + L2 verified semantic cache**, observability, and provider routing. PostgreSQL stores projects, request logs, and cache entries. The **provider router** selects OpenAI, Groq, or Anthropic by model name, with retries and cross-provider fallback.

---

## Request flow — non-streaming (v0.2 cache + optional PII)

```mermaid
flowchart TD
    Client[Client] --> Auth[Auth / request processing]
    Auth --> PII[PII handling optional]
    PII --> L1[L1 Exact Cache SHA-256 fingerprint]
    L1 -->|exact_hit| Return1[Return cached response]
    L1 -->|miss| Gates[L2 Semantic Gates]
    Gates -->|PII / multi-turn / time-sensitive / bypass| Provider[Provider LLM]
    Gates -->|allowed| Embed[Embedding candidate retrieval ≥ 0.65]
    Embed --> Verifier[Answer-Equivalence Verifier gpt-4o-mini]
    Verifier -->|true| Return2[semantic_hit]
    Verifier -->|false / failure| Provider
    Provider --> Persist[PostgreSQL persistence + in-memory index]
    Persist --> Obs[Prometheus / request logs]
    Return1 --> Obs
    Return2 --> Obs
```

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway
    participant PII as PII module
    participant L1 as L1 Exact index
    participant E as Embeddings API
    participant L2 as L2 semantic scan
    participant V as Verifier gpt-4o-mini
    participant R as Provider router
    participant P as LLM provider
    participant DB as PostgreSQL

    C->>G: POST /v1/chat/completions
    G->>G: Validate API key
    opt PII_REDACTION_ENABLED
        G->>PII: Redact prompt (non-stream only)
        PII-->>G: Redacted messages + token map
    end
    G->>L1: lookup_exact(fingerprint)
    alt exact_hit
        L1-->>G: Cached response
        G-->>C: Response (0 embed, 0 verifier, 0 provider)
    else L1 miss
        opt L2 gates pass
            G->>E: Embed prompt
            G->>L2: Best candidate if cosine ≥ 0.65
            G->>V: should_reuse(A, cached_response, B)
            alt verifier true
                V-->>G: semantic_hit
                G->>L1: Register requesting fingerprint alias
                G-->>C: Cached response
            else reject / miss / failure
                G->>R: Route by model + retry/fallback
                R->>P: Forward prompt
                P-->>G: Response
                G->>DB: Upsert cache entry (fingerprint + embedding)
                G-->>C: Response
            end
        end
    end
    G->>DB: Log request metrics
```

**Streaming:** Same auth and routing, but **no PII redaction** and **no cache** on the hot path — SSE chunks forward immediately; upstream cancels on client disconnect.

**L2 terminology:** Cosine **0.65** is a **retrieval** threshold only — not a safety threshold. Similarity selects candidates; the answer-equivalence verifier alone authorizes reuse.

---

## Request flow — streaming

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway
    participant R as Provider router
    participant P as LLM provider

    C->>G: POST stream=true
    G->>G: Validate API key
    G->>R: Route + retry on stream open
    R->>P: POST stream=true
    loop Each chunk
        P-->>G: SSE chunk
        G-->>C: Forward immediately
    end
    Note over C,G: Client disconnect cancels upstream
    G->>G: Log metrics after stream ends
```

---

## Component map

| Component | Directory | Role |
|-----------|-----------|------|
| FastAPI app | `app/main.py` | App factory, lifespan, cache hydration |
| Config | `app/config.py` | Env-driven settings (providers, cache, PII) |
| Database | `app/db/` | SQLAlchemy models + async sessions |
| Auth | `app/auth/` | bcrypt API keys, lookup prefix |
| PII redaction | `app/security/pii.py` | Regex detect/redact; optional detokenize |
| Chat route | `app/routes/chat.py` | JSON + SSE completions |
| Semantic cache | `app/cache/` | L1 exact index + L2 verified semantic + PostgreSQL persistence |
| Cache verifier | `app/cache/verifier.py` | gpt-4o-mini answer-equivalence gate |
| Embeddings | `app/embeddings/` | OpenAI embeddings for cache |
| Provider interface | `app/providers/base.py` | Shared `LLMProvider` contract |
| OpenAI / Groq / Anthropic | `app/providers/*.py` | Provider adapters |
| Router + retry + fallback | `app/providers/router.py`, `retry.py`, `fallback.py` | Model routing, resilience |
| Observability | `app/observability/` | Request logs, percentiles, cost |
| Metrics / dashboard | `app/routes/metrics.py`, `app/static/dashboard.html` | `/v1/metrics`, minimal UI |

---

## Database tables

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
        string fingerprint
        jsonb request_messages
        vector embedding
        text cached_response
        string model
        int use_count
        int exact_use_count
        int semantic_use_count
        timestamp last_used_at
    }
```

`requests` stores **metadata only** — not prompt or response bodies. When PII redaction is enabled on non-streaming requests, embeddings are built from **redacted** prompt text.

---

## Key design decisions

| Decision | Choice | Trade-off |
|----------|--------|-----------|
| OpenAI-compatible API | Yes | Easy client adoption; locked to their schema |
| Multi-provider router | OpenAI + Groq + Anthropic | More moving parts; better availability story |
| Retries + cross-provider fallback | Yes | Model id may change on fallback |
| Non-streaming before streaming | Yes | Isolates proxy bugs incrementally |
| Observability before cache | Yes | Measure cache impact when it ships |
| In-memory L1 exact index + PG persistence | Yes | O(1) exact hits; linear L2 scan in v0.2 |
| Optional PII redaction (Phase 9) | Regex, non-streaming | Not DLP/NER; streaming bypasses redaction |
| Percentiles over averages | Yes | More meaningful tail latency |

---

## What is intentionally not in architecture (yet)

- Load balancer / multiple gateway replicas with shared cache index
- Redis or message queue
- Kubernetes deployment manifests
- LangChain orchestration in the core
- NER/ML-based PII or prompt-injection classifiers
- pgvector / FAISS (in-memory cache first — see [`CACHE_TUNING.md`](CACHE_TUNING.md))
