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
from app.cache.factory import create_gateway_cache
from app.cache.persistence import hydrate_gateway_cache
from app.cache.verifier import AnswerEquivalenceVerifier, create_verifier_client
from app.embeddings.openai import create_openai_embedding_provider
from app.providers.router import create_provider_router
from app.routes.chat import router as chat_router
from app.routes.dashboard import router as dashboard_router
from app.routes.health import router as health_router
from app.routes.prometheus import router as prometheus_router
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

    app.state.provider_router = create_provider_router()
    logger.info(
        "Provider router initialized: %s",
        ", ".join(app.state.provider_router.provider_names),
    )

    app.state.semantic_cache = create_gateway_cache()
    loaded = await hydrate_gateway_cache(app.state.semantic_cache)
    logger.info(
        "Gateway cache initialized (candidate_threshold=%.2f, entries=%d)",
        app.state.semantic_cache.candidate_threshold,
        loaded,
    )

    app.state.embedding_provider = create_openai_embedding_provider()
    logger.info("Embedding provider initialized: %s", app.state.embedding_provider.name)

    verifier_client = create_verifier_client()
    app.state.cache_verifier = AnswerEquivalenceVerifier(
        verifier_client,
        settings.cache_verifier_model,
    )
    app.state.cache_verifier_client = verifier_client
    logger.info("Cache verifier initialized: %s", settings.cache_verifier_model)

    yield

    await app.state.cache_verifier_client.aclose()
    await app.state.embedding_provider.aclose()
    await app.state.provider_router.aclose()
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
app.include_router(prometheus_router)
app.include_router(dashboard_router)
app.include_router(chat_router)
app.include_router(metrics_router)
app.include_router(requests_router)
