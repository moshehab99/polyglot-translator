"""JSON API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Settings, get_settings, get_translation_service
from app.api.schemas import (
    ArabicScriptRequest,
    ArabicScriptResponse,
    ErrorResponse,
    HealthResponse,
    TranslateRequest,
    TranslateResponse,
)
from app.languages import get_language
from app.services.translation_service import TranslationService

router = APIRouter(prefix="/api", tags=["api"])

_ERROR_RESPONSES = {
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    # Deliberately exposes only the provider name: no model, no key.
    return HealthResponse(status="ok", provider=settings.provider)


@router.post("/translate", response_model=TranslateResponse, responses=_ERROR_RESPONSES)
async def translate(
    body: TranslateRequest,
    service: Annotated[TranslationService, Depends(get_translation_service)],
) -> TranslateResponse:
    result = await service.translate(body.text, body.source, body.target)
    target = get_language(body.target)
    return TranslateResponse(
        translation=result.translation,
        detected_source=result.detected_source.code,  # type: ignore[arg-type]
        source_rtl=result.detected_source.rtl,
        target_rtl=target.rtl,
    )


@router.post("/arabic-script", response_model=ArabicScriptResponse, responses=_ERROR_RESPONSES)
async def arabic_script(
    body: ArabicScriptRequest,
    service: Annotated[TranslationService, Depends(get_translation_service)],
) -> ArabicScriptResponse:
    """Write Franco-Arabic in Arabic script; other words, digits and emoji stay as written."""
    return ArabicScriptResponse(result=await service.to_arabic_script(body.text))
