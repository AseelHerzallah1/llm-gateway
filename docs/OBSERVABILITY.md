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

## CI and release

- **CI** (`.github/workflows/ci.yml`): runs on PRs and pushes to `main` — migrations, full pytest suite, `docker compose config`.
- **Release** (`.github/workflows/release.yml`): triggered by manual tags `v*.*.*` — tests, Docker build, push to GHCR (`ghcr.io/aseelherzallah1/llm-gateway:<version>` and `:latest`), GitHub Release with auto-generated notes.
