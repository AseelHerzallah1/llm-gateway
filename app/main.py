"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.db.session import close_db, verify_db_connection
from app.errors import (
    GatewayHTTPException,
    gateway_exception_handler,
    validation_exception_handler,
)
from app.providers.openai import create_openai_provider
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router
from app.routes.metrics import router as metrics_router
from app.routes.requests import router as requests_router
from app.version import __version__

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run once at startup and shutdown."""
    logger.info(
        "Starting LLM Gateway (env=%s, host=%s, port=%s)",
        settings.app_env,
        settings.app_host,
        settings.app_port,
    )

    await verify_db_connection()
    logger.info("Database connection verified")

    app.state.llm_provider = create_openai_provider()
    logger.info("LLM provider initialized: %s", app.state.llm_provider.name)

    yield

    await app.state.llm_provider.aclose()
    await close_db()
    logger.info("Shutting down LLM Gateway")


app = FastAPI(
    title="LLM Gateway",
    description="Production-style LLM Gateway — streaming proxy, semantic cache, observability",
    version=__version__,
    lifespan=lifespan,
)

app.add_exception_handler(GatewayHTTPException, gateway_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(metrics_router)
app.include_router(requests_router)
