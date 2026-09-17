"""
main.py — FastAPI application entrypoint for ExcelLence AI.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import HealthResponse
from app.routes import auth, chat, extract, filewatcher, pages, workbooks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("excellence-ai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    logger.info(f"Storage: workbooks={settings.workbook_dir}, uploads={settings.upload_dir}")

    if not settings.groq_configured:
        logger.warning(
            "GROQ_API_KEY is not set. AI features unavailable. "
            "Add it to .env — get a free key at https://console.groq.com/keys"
        )
    else:
        logger.info("Groq API key configured")

    logger.info(f"ExcelLence AI ready at http://{settings.host}:{settings.port}")
    yield


app = FastAPI(
    title="ExcelLence AI",
    description="AI-powered Excel workbench",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# ── CORS (localhost only) ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ──────────────────────────────────────────────────────────────
_static_path = Path(__file__).parent.parent / "frontend" / "static"
app.mount("/static", StaticFiles(directory=str(_static_path)), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(workbooks.router)
app.include_router(chat.router)
app.include_router(extract.router)
app.include_router(filewatcher.router)


@app.get("/")
async def root(request: Request):
    from app.routes.auth import get_current_user
    if get_current_user(request):
        return RedirectResponse("/app")
    return RedirectResponse("/login")


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        groq_configured=settings.groq_configured,
        storage_writable=settings.storage_writable,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "code": "INTERNAL_ERROR"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
