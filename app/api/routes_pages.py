"""HTML pages."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import Settings, get_settings
from app.languages import AUTO, LANGUAGES

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["pages"])

DEFAULT_TARGET = "en"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "languages": LANGUAGES,
            "auto_code": AUTO,
            "default_source": AUTO,
            "default_target": DEFAULT_TARGET,
            "max_chars": settings.max_chars,
        },
    )
