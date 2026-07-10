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

## Install (after Phase 2.2)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env        # then fill in real values
```
