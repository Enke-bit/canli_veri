"""Senkronizasyon durumu ve gecmisi uclari."""
from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, get_engine
from app.models import SyncLog, SyncState
from app.routers.common import pagination
from app.schemas import (
    Page,
    SyncLogOut,
    SyncStateOut,
    SyncStatusOut,
)
from app.sync_engine import ENTITY_ORDER, SyncEngine

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])

# Dashboard'dan ayni anda iki senkronizasyon baslatilmasini engeller.
_run_lock = threading.Lock()


@router.get("/status", response_model=SyncStatusOut, summary="Son senkronizasyon durumu")
def sync_status(session: Session = Depends(get_db)) -> SyncStatusOut:
    states = (
        session.execute(select(SyncState).order_by(SyncState.entity_type))
        .scalars()
        .all()
    )
    latest_rows = (
        session.execute(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(50))
        .scalars()
        .all()
    )
    latest_by_entity: dict[str, SyncLog] = {}
    for row in latest_rows:
        latest_by_entity.setdefault(row.entity_type, row)

    last_success = session.execute(
        select(func.max(SyncState.last_successful_run_at))
    ).scalar_one_or_none()

    return SyncStatusOut(
        states=[SyncStateOut.model_validate(row) for row in states],
        latest_logs=[
            SyncLogOut.model_validate(row) for row in latest_by_entity.values()
        ],
        last_successful_run_at=last_success,
    )


@router.post("/run", summary="Senkronizasyonu simdi calistir (dashboard)")
def trigger_sync(
    entities: Annotated[str, Query(description="clinics,patients,appointments")] = "clinics,patients,appointments",
    force_full: bool = False,
) -> dict:
    """Kaynak API -> MSSQL senkronizasyonunu hemen calistirir.

    Varsayilan olarak KAPALIDIR; .env icinde ENABLE_SYNC_TRIGGER=true gerekir.
    Ayni anda ikinci bir calisma 409 dondurur.
    """
    settings = get_settings()
    if not settings.enable_sync_trigger:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=(
                "Dashboard'dan senkronizasyon kapali. .env dosyasinda "
                "ENABLE_SYNC_TRIGGER=true yapip hedef API'yi yeniden baslatin."
            ),
        )

    selected = [part.strip().lower() for part in entities.split(",") if part.strip()]
    unknown = [item for item in selected if item not in ENTITY_ORDER]
    if unknown or not selected:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Gecersiz tur: {', '.join(unknown) or '(bos)'}. "
                f"Gecerli: {', '.join(ENTITY_ORDER)}"
            ),
        )
    ordered = [entity for entity in ENTITY_ORDER if entity in selected]

    if not _run_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Baska bir senkronizasyon calisiyor. Bitmesini bekleyin.",
        )
    try:
        engine = get_engine()
        sync = SyncEngine(settings, engine)
        try:
            result = sync.run(entities=ordered, force_full=force_full)
        finally:
            sync.close()
    finally:
        _run_lock.release()

    return {
        "job_id": result.job_id,
        "success": result.success,
        "error": result.error,
        "skipped_entities": result.skipped_entities,
        "entities": [stats.as_dict() for stats in result.entities],
    }


@router.get("/logs", response_model=Page[SyncLogOut], summary="Senkronizasyon gecmisi")
def sync_logs(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    entity_type: str | None = None,
    log_status: Annotated[str | None, Query(alias="status")] = None,
    session: Session = Depends(get_db),
) -> Page[SyncLogOut]:
    filters = []
    if entity_type:
        filters.append(SyncLog.entity_type == entity_type)
    if log_status:
        filters.append(SyncLog.status == log_status)

    total = session.execute(
        select(func.count()).select_from(SyncLog).where(*filters)
    ).scalar_one()
    rows = (
        session.execute(
            select(SyncLog)
            .where(*filters)
            .order_by(SyncLog.started_at.desc(), SyncLog.sync_log_id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return Page[SyncLogOut](
        data=[SyncLogOut.model_validate(row) for row in rows],
        pagination=pagination(limit, offset, total),
    )
