# llm-gateway

A production-style **LLM Gateway** — a middleware layer between applications and large language model providers.

## Status

**In active development.** Built phase by phase with incremental commits.

## Planned capabilities (v1)

- OpenAI-compatible API (`POST /v1/chat/completions`)
- Async streaming proxy with cancellation handling
- Semantic cache (embedding-based)
- Observability with percentile latency (p50 / p95 / p99) and cost tracking

## Stack

- Python · FastAPI · httpx · asyncio
- PostgreSQL

## Documentation

Design and API docs live in [`docs/`](docs/). Docker setup: [`docs/DOCKER.md`](docs/DOCKER.md).
