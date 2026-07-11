# Project structure

```
llm-gateway/
├── app/                    # Application source code
│   ├── auth/               # API key + admin auth (Phase 3)
│   ├── cache/              # Semantic cache (Phase 6)
│   ├── db/                 # Database session + models (Phase 2.5)
│   ├── embeddings/         # Prompt embeddings (Phase 6)
│   ├── observability/      # Metrics + logging (Phase 5)
│   ├── providers/          # OpenAI adapter (Phase 3)
│   └── routes/             # HTTP endpoints (Phase 2.2)
├── docs/                   # Design documents
├── migrations/             # Alembic migrations (Phase 2.6)
├── tests/                  # Automated tests (Phase 8)
├── .env.example            # Environment variable template
├── pyproject.toml          # Project metadata + dependencies
└── requirements.txt        # Pip-installable dependency list
```

Each package is created empty in Phase 2.1. Code is added in later phases — one layer at a time.

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
