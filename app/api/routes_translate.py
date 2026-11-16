"""JSON API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Settings, get_settings
from app.api.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    # Deliberately exposes only the provider name: no model, no key.
    return HealthResponse(status="ok", provider=settings.provider)
