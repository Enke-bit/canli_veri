"""Randevu uclari (MSSQL'den okur/yazar)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Appointment, SyncLog
from app.routers.common import pagination
from app.schemas import (
    AppointmentOut,
    AppointmentStatus,
    AppointmentStatusUpdate,
    Page,
)

router = APIRouter(prefix="/api/v1/appointments", tags=["appointments"])


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _parse_filter(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=Page[AppointmentOut], summary="Randevulari listele")
def list_appointments(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    appointment_status: Annotated[
        AppointmentStatus | None, Query(alias="status")
    ] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    clinic_id: str | None = None,
    patient_id: str | None = None,
    include_deleted: bool = False,
    session: Session = Depends(get_db),
) -> Page[AppointmentOut]:
    filters = []
    if not include_deleted:
        filters.append(Appointment.is_deleted == False)  # noqa: E712
    if appointment_status:
        filters.append(Appointment.status == appointment_status)
    start = _parse_filter(date_from)
    end = _parse_filter(date_to)
    if start is not None:
        filters.append(Appointment.appointment_datetime >= start)
    if end is not None:
        filters.append(Appointment.appointment_datetime <= end)
    if clinic_id:
        filters.append(Appointment.external_clinic_id == clinic_id)
    if patient_id:
        filters.append(Appointment.external_patient_id == patient_id)

    total = session.execute(
        select(func.count()).select_from(Appointment).where(*filters)
    ).scalar_one()
    rows = (
        session.execute(
            select(Appointment)
            .where(*filters)
            .order_by(
                Appointment.appointment_datetime.desc(),
                Appointment.external_appointment_id,
            )
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return Page[AppointmentOut](
        data=[AppointmentOut.model_validate(row) for row in rows],
        pagination=pagination(limit, offset, total),
    )


@router.get(
    "/{external_id}", response_model=AppointmentOut, summary="Tek randevu (dis kimlik)"
)
def get_appointment(
    external_id: str, session: Session = Depends(get_db)
) -> AppointmentOut:
    row = session.execute(
        select(Appointment).where(
            Appointment.external_appointment_id == external_id
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Randevu bulunamadi: {external_id}",
        )
    return AppointmentOut.model_validate(row)


@router.patch(
    "/{external_id}/status",
    response_model=AppointmentOut,
    summary="Randevu durumunu guncelle",
)
def update_appointment_status(
    external_id: str,
    payload: AppointmentStatusUpdate,
    session: Session = Depends(get_db),
) -> AppointmentOut:
    row = session.execute(
        select(Appointment).where(
            Appointment.external_appointment_id == external_id
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Randevu bulunamadi: {external_id}",
        )
    if row.is_deleted:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Silinmis randevunun durumu degistirilemez.",
        )
    if row.status == payload.status:
        return AppointmentOut.model_validate(row)

    previous = row.status
    now = _utc_naive()
    row.status = payload.status
    row.updated_at = now
    row.synced_at = now
    session.add(
        SyncLog(
            job_id=str(uuid.uuid4()),
            entity_type="appointments",
            operation_type="api_status_update",
            started_at=now,
            finished_at=now,
            status="Success",
            records_read=1,
            records_updated=1,
            error_summary=(
                f"{external_id}: {previous} -> {payload.status} (hedef API uzerinden). "
                "Not: kaynak sistem tekrar gonderirse kaynak degeri kazanir."
            )[:2000],
        )
    )
    session.commit()
    session.refresh(row)
    return AppointmentOut.model_validate(row)
