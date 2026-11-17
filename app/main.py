"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes_translate import router as api_router
from app.config import Settings, get_settings
from app.logging import configure_logging, get_logger
from app.providers.factory import build_provider

logger = get_logger("main")


def resolve_settings(app: FastAPI) -> Settings:
    """Load settings honouring ``app.dependency_overrides`` so tests can inject them."""
    dependency = app.dependency_overrides.get(get_settings, get_settings)
    return dependency()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast: a missing/blank API key aborts startup instead of surfacing as a 500.
    try:
        settings = resolve_settings(app)
    except Exception:
        logger.error("Invalid configuration; refusing to start. Check your .env file.")
        raise
    app.state.settings = settings
    app.state.provider = build_provider(settings)
    logger.info("Polyglot started with provider=%s", settings.provider)
    yield


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Polyglot – Smart Language Translator", version="0.1.0", lifespan=lifespan
    )
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
