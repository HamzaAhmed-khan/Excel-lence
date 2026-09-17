"""
auth.py — Mock authentication. Any email + password ≥ 4 chars succeeds.
Session stored in an HTTP-only signed cookie using itsdangerous.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from app.config import settings
from app.models import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE_NAME = "el_session"
_SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _signer() -> TimestampSigner:
    return TimestampSigner(settings.app_secret_key)


def _make_session_token(email: str) -> str:
    payload = json.dumps({"email": email, "ts": datetime.utcnow().isoformat()})
    return _signer().sign(payload).decode()


def _verify_session(token: str) -> dict | None:
    try:
        raw = _signer().unsign(token, max_age=_SESSION_MAX_AGE)
        return json.loads(raw)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    return _verify_session(token)


def require_auth(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    # Mock auth — anything goes as long as validation passes
    token = _make_session_token(body.email)

    # Derive display name from email
    name_part = body.email.split("@")[0].replace(".", " ").replace("_", " ").title()

    resp = JSONResponse(
        content={
            "ok": True,
            "user": {"email": body.email, "name": name_part},
            "redirect": "/app",
        }
    )
    resp.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        secure=False,  # set True behind HTTPS proxy in production
    )
    return resp


@router.post("/logout")
async def logout(response: Response):
    resp = JSONResponse(content={"ok": True, "redirect": "/login"})
    resp.delete_cookie(_COOKIE_NAME)
    return resp


@router.get("/me")
async def me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
