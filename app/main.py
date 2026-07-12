"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.session import close_db, verify_db_connection
from app.errors import GatewayHTTPException, gateway_exception_handler
from app.routes.health import router as health_router
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

    yield

    await close_db()
    logger.info("Shutting down LLM Gateway")


app = FastAPI(
    title="LLM Gateway",
    description="Production-style LLM Gateway — streaming proxy, semantic cache, observability",
    version=__version__,
    lifespan=lifespan,
)

app.add_exception_handler(GatewayHTTPException, gateway_exception_handler)

app.include_router(health_router)
