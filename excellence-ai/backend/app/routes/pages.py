"""
pages.py — HTML page routes for login and the main app.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.routes.auth import get_current_user

router = APIRouter(tags=["pages"])

_templates_path = Path(__file__).parent.parent.parent.parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(_templates_path))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/app")
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/app", response_class=HTMLResponse)
async def app_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    name = user.get("email", "User").split("@")[0].replace(".", " ").title()
    initials = "".join(p[0].upper() for p in name.split()[:2]) or "PK"
    return templates.TemplateResponse(
        "app.html",
        {"request": request, "user": user, "name": name, "initials": initials},
    )
