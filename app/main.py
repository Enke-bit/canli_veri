"""Hedef API (port 8000): MSSQL'deki verileri sunar.

Gercek veritabani okumasi yapar; sabit/demo JSON dondurmez.
Yalnizca yerel gelistirme icindir (kimlik dogrulama yok).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.config import PROJECT_ROOT, get_settings
from app.db import get_engine
from app.logging_setup import configure_logging
from app.routers import analytics, appointments, clinics, patients, sync

settings = get_settings()
logger = configure_logging("target_api", "api.log", settings.log_level)

DASHBOARD_FILE = PROJECT_ROOT / "app" / "static" / "dashboard.html"
GUIDE_FILE = PROJECT_ROOT / "app" / "static" / "kilavuz.html"
ARCHITECTURE_FILE = PROJECT_ROOT / "app" / "static" / "mimari.html"

app = FastAPI(
    title="DentSync Hedef API",
    description=(
        "MSSQL (DentSyncDemo) verilerini okuyan yerel REST API. "
        "Tarihler UTC ve ISO-8601 ('Z') formatindadir. "
        "Kimlik dogrulama yoktur; internete acik ortamda kullanmayin."
    ),
    version="1.1.0",
)

# Dashboard ayni makinedeki farkli portlardan (veya file:// ile) veri cekebilsin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(clinics.router)
app.include_router(patients.router)
app.include_router(appointments.router)
app.include_router(sync.router)
app.include_router(analytics.router)


@app.get("/health", tags=["health"], summary="API + MSSQL baglanti kontrolu")
def health() -> JSONResponse:
    info = {
        "service": "target-api",
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
    }
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            db_name = connection.execute(text("SELECT DB_NAME()")).scalar_one()
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "database": {"status": "ok", "name": db_name}, **info},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Saglik kontrolu basarisiz: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "database": {"status": "unreachable"},
                "message": "MSSQL baglantisi kurulamadi.",
                **info,
            },
        )


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    """Canli analitik paneli (tek dosya, harici CDN yok)."""
    return _static_page(DASHBOARD_FILE, "app/static/dashboard.html")


@app.get("/kilavuz", include_in_schema=False)
def guide() -> FileResponse:
    """Sifirdan calistirma kilavuzu."""
    return _static_page(GUIDE_FILE, "app/static/kilavuz.html")


@app.get("/mimari", include_in_schema=False)
def architecture() -> FileResponse:
    """Mimari ve canli veri akisi (SVG semalar)."""
    return _static_page(ARCHITECTURE_FILE, "app/static/mimari.html")


def _static_page(path: Path, relative_name: str) -> FileResponse:
    if not path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": f"Sayfa bulunamadi: {relative_name}"},
        )
    return FileResponse(path, media_type="text/html; charset=utf-8")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "name": "DentSync Hedef API",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "guide": "/kilavuz",
        "architecture": "/mimari",
        "health": "/health",
        "version": "1.2.0",
    }
