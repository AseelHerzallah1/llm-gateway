# Docker — LLM Gateway

Run the gateway and PostgreSQL together with Docker Compose.

## Prerequisites

Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).  
Verify:

```powershell
docker --version
docker compose version
```

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the Python app image |
| `docker-compose.yml` | Runs `app` + `db` services together |
| `.dockerignore` | Excludes `.venv`, `.git`, `.env` from the image |

## Quick start

```powershell
cd "c:\Users\Aseel Herzallah\OneDrive\Desktop\LLM-Gateway"

# Ensure .env exists (copy from template if needed)
copy .env.example .env

# Build and start both containers
docker compose up --build

# In a second terminal — test health (host port 8001 → container port 8000)
Invoke-RestMethod -Uri "http://127.0.0.1:8001/health"
```

Expected: `status=ok`, `version=0.1.0`

## Stop

```powershell
docker compose down
```

Remove database volume too (deletes all data):

```powershell
docker compose down -v
```

## Architecture

```
Your machine
├── llm-gateway-app  (port 8001 → 8000)  →  FastAPI /health
└── llm-gateway-db   (port 5432)         →  PostgreSQL
         ↑
    app connects via hostname "db" inside Docker network
```

## Important notes

- **Host port 8001** maps to container port 8000 (avoids conflict if port 8000 is busy on your machine).
- **`DATABASE_URL` in docker-compose** overrides `.env` for the app container — hostname is `db`, not `localhost`.
- The app does **not** connect to the database yet (Phase 2.5). PostgreSQL starts and is ready; wiring comes next.
- **Do not commit `.env`** — it stays local; docker-compose reads it via `env_file`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `docker: not recognized` | Install Docker Desktop and restart terminal |
| Port 5432 in use | Stop local PostgreSQL or change the host port in `docker-compose.yml` |
| Port 8001 in use | Change `"8001:8000"` to `"8002:8000"` in `docker-compose.yml` |
| App starts before DB ready | `depends_on` + `healthcheck` on `db` service handles this |
