# Observability

LLM Gateway exposes **two complementary observability layers**. They serve different audiences and storage models; neither replaces the other.

## Application metrics (`GET /v1/metrics`)

PostgreSQL-backed, **project-scoped** observability for product and debugging use:

- Per-project latency percentiles (p50 / p95 / p99)
- Token usage and estimated cost aggregates
- Requires gateway API key authentication (same as chat)

Also available: `GET /v1/requests` (paginated request log) and `/dashboard` (minimal HTML UI).

**Authoritative for:** request history, project-level cost reporting, audit trails.

## Prometheus metrics (`GET /metrics`)

Process-level **operational telemetry** for monitoring stacks (Prometheus + Grafana):

- Request rates, success/error ratios, latency histograms
- Semantic cache activity (hit / miss / store / lookup skipped)
- Provider attempts (including retries), fallbacks, tokens, estimated cost counter

**Properties:**

- Unauthenticated — intended for **internal** scrape networks only
- Low-cardinality labels only (`status`, `stream`, `cache_result`, `provider`, etc.)
- No model names, project IDs, API keys, prompts, or PII in labels
- `llmgateway_estimated_cost_usd_total` is an operational counter; **PostgreSQL remains authoritative** for historical cost

Disable with `PROMETHEUS_ENABLED=false` (the endpoint returns 404).

## Local monitoring stack

Full stack (PostgreSQL + gateway + Prometheus + Grafana):

```powershell
docker compose up
```

Minimal development (database + app only):

```powershell
docker compose up db app
```

| Service    | URL                         | Notes                                      |
|------------|-----------------------------|--------------------------------------------|
| Gateway    | http://localhost:8001       | Chat, `/v1/metrics`, `/metrics`            |
| Prometheus | http://localhost:9090       | Scrapes `app:8000/metrics` every 15s       |
| Grafana    | http://localhost:3000       | Provisioned datasource + **LLM Gateway Overview** dashboard |

Grafana defaults to `admin` / `admin` for local development. Override via `.env`:

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=your-local-password
```

Do not expose Grafana, Prometheus, or `/metrics` to the public internet without authentication and network controls.

## Grafana dashboard — LLM Gateway Overview

Provisioned from `deploy/grafana/dashboards/llm-gateway.json` when running `docker compose up`.

| Panel | What it shows |
|-------|----------------|
| **Total Requests** | Non-streaming request count |
| **Cache Hit Rate** | `(exact_hit + semantic_hit) / (exact_hit + semantic_hit + miss)` — bypass excluded |
| **Exact Hits (L1)** | L1 fingerprint hits |
| **Semantic Hits (L2)** | Verified semantic reuse count |
| **Provider Calls** | Upstream LLM attempts |
| **Errors** | Request/provider errors |
| **Requests by Result** | Time series: `exact_hit`, `semantic_hit`, `miss`, `bypass` |
| **Cache Operations** | `exact_hit`, `semantic_hit`, `semantic_reject`, `semantic_miss`, `store`, etc. |
| **Semantic Rejects** | Verifier rejected candidates (before provider fallback) |
| **Latency** | Request duration histogram percentiles |
| **Tokens / estimated cost** | Operational token and cost counters |

### Demo visualization workload (not a performance benchmark)

Script: `scripts/demo_grafana_workload.py` → `docs/demo_grafana_workload.json`

Final screenshot run (2026-08-27):

| Metric | Count |
|--------|-------|
| Total requests | 53 |
| Exact hits (L1) | 26 |
| Semantic hits (L2) | 3 |
| Semantic rejects | 4 |
| Misses | 19 |
| Bypass | 5 |
| Provider calls | 24 |
| Errors | 0 |
| Cache hit rate | 60.4% |

The **3 semantic hits** populate L2 panels for dashboard visualization only — not a latency or throughput benchmark. After an L2 semantic hit, the new request fingerprint may be registered for L1, so later identical requests in the same workload often become **exact hits** (explains high L1 count relative to L2).

Reproduce locally:

```powershell
docker compose up -d
python scripts/demo_grafana_workload.py
# Open http://localhost:3000/d/llm-gateway-overview/llm-gateway-overview
```

## CI and release

- **CI** (`.github/workflows/ci.yml`): runs on PRs and pushes to `main` — migrations, full pytest suite, `docker compose config`.
- **Release** (`.github/workflows/release.yml`): triggered by manual tags `v*.*.*` — tests, Docker build, push to GHCR (`ghcr.io/aseelherzallah1/llm-gateway:<version>` and `:latest`), GitHub Release with auto-generated notes.
