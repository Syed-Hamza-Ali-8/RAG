"""Phase 6 added scope: `GET /chat`, the page for the person asking questions (EVAL_RESULTS.md, Phase 6 scope
added).

A static page: it holds no data and needs no token to load. In the browser it signs in through the demo
issuer, sends `{"question": ...}` to the existing `POST /v1/query`, and renders the JSON with `textContent`
only. A refusal is shown exactly as the API returns it, with no wording of its own (P4 indistinguishability
applies to the UI).
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
PAGE = "chat.html"

router = APIRouter()


@router.get("/chat", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, PAGE, {})
