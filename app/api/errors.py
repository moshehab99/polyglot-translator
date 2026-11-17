"""Exception handlers implementing the error policy.

Clients only ever see ``{"detail": "<safe message>"}``. Provider details, upstream
status codes, model names and keys are logged server-side and never returned.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.logging import get_logger
from app.providers.base import (
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderError,
    ProviderRateLimitError,
)
from app.services.translation_service import TranslationValidationError

logger = get_logger("api")

RATE_LIMIT_MESSAGE = "Too many requests, please try again shortly."
UNAVAILABLE_MESSAGE = "Translation service is temporarily unavailable. Please try again later."
BAD_OUTPUT_MESSAGE = "The translation could not be produced. Please try again."
UNEXPECTED_MESSAGE = "Unexpected server error."


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def _validation_error(_: Request, exc: TranslationValidationError) -> JSONResponse:
    return _error(422, str(exc))


async def _request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Collapse pydantic's error list into one readable sentence.
    parts = []
    for err in exc.errors():
        location = ".".join(str(loc) for loc in err.get("loc", ()) if loc != "body")
        message = err.get("msg", "invalid value")
        parts.append(f"{location}: {message}" if location else message)
    return _error(422, "Invalid request. " + "; ".join(parts))


async def _provider_error(_: Request, exc: ProviderError) -> JSONResponse:
    if isinstance(exc, ProviderRateLimitError):
        logger.warning("Provider %s rate limited: %s", exc.provider, exc.detail)
        return _error(429, RATE_LIMIT_MESSAGE)
    if isinstance(exc, ProviderAuthError):
        logger.error(
            "Provider %s rejected the server API key. Check your .env. Upstream: %s",
            exc.provider,
            exc.detail,
        )
        return _error(503, UNAVAILABLE_MESSAGE)
    if isinstance(exc, ProviderBadOutputError):
        logger.error("Provider %s returned unusable output: %s", exc.provider, exc.detail)
        return _error(502, BAD_OUTPUT_MESSAGE)
    logger.error("Provider %s unavailable: %s", exc.provider, exc.detail)
    return _error(503, UNAVAILABLE_MESSAGE)


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error while serving request", exc_info=exc)
    return _error(500, UNEXPECTED_MESSAGE)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TranslationValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _request_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(ProviderError, _provider_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unexpected_error)
