"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.routes.health import router as health_router
from app.version import __version__

app = FastAPI(
    title="LLM Gateway",
    description="Production-style LLM Gateway — streaming proxy, semantic cache, observability",
    version=__version__,
)

app.include_router(health_router)
