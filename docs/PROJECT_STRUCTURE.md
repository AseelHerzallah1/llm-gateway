# Project structure

```
llm-gateway/
├── app/                    # Application source code
│   ├── auth/               # API key + admin auth
│   ├── cache/              # L1 exact + L2 verified semantic cache (v0.2)
│   │   ├── fingerprint.py  # Versioned SHA-256 request identity
│   │   ├── semantic_gates.py
│   │   ├── verifier.py     # gpt-4o-mini answer-equivalence gate
│   │   ├── memory.py       # GatewayCache (exact index + semantic scan)
│   │   └── chat_integration.py
│   ├── db/                 # Database session + models
│   ├── embeddings/         # Prompt embeddings
│   ├── observability/      # Metrics, logging, Prometheus
│   ├── providers/          # OpenAI, Groq, Anthropic adapters
│   ├── routes/             # HTTP endpoints (chat, metrics, prometheus, dashboard)
│   └── security/           # PII redaction
├── deploy/                 # Prometheus + Grafana provisioning (v0.2)
│   ├── prometheus/
│   └── grafana/dashboards/
├── docs/                   # Design documents + benchmark artifacts
├── migrations/             # Alembic migrations
├── scripts/                # Demo, benchmarks, E2E helpers
│   ├── benchmark_cache_v2.py           # v0.2 seven-path benchmark
│   ├── benchmark_long_provider_baseline.py
│   ├── demo_grafana_workload.py        # Grafana visualization workload
│   ├── targeted_cache_validation.py    # Pre-benchmark smoke paths
│   └── demo.py                         # Quick live demo
├── tests/                  # unit + integration (pytest -m db)
├── .env.example            # Environment variable template
├── docker-compose.yml      # db + app + prometheus + grafana
├── pyproject.toml
└── requirements.txt
```

Each package grew incrementally across phases — see [`DESIGN.md`](DESIGN.md) for the phase timeline.

## Install and run (Phase 2.2+)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Copy env template and edit values (Phase 2.3+)
copy .env.example .env        # Windows — do NOT commit .env

# Start the server (use --reload-dir app to avoid .venv reload loops)
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8001

# Verify health check
Invoke-RestMethod -Uri "http://127.0.0.1:8001/health"
```

Expected response:

```json
{"status":"ok","version":"0.1.0"}
```

On startup you should also see a log line like:

```
INFO: Starting LLM Gateway (env=development, host=0.0.0.0, port=8000)
```

> **Note:** `APP_PORT` in `.env` is loaded into settings. The uvicorn `--port` flag still controls the actual listen port for now.

## Database migrations (Phase 2.6+)

```powershell
docker compose up db -d
alembic upgrade head
alembic current
```

See [`migrations/README.md`](../migrations/README.md) for details.
