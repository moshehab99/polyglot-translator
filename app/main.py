"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_translate import router as api_router
from app.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Polyglot – Smart Language Translator", version="0.1.0")
    app.include_router(api_router)
    return app


app = create_app()
