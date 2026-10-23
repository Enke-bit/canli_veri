"""Dashboard icin gercek MSSQL agregasyonlari.

Butun sayilar veritabanindan hesaplanir; hicbir sabit/demo veri yoktur.
Dashboard tek istekte beslenebilsin diye ozet tek ucta toplanmistir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Appointment, Clinic, Patient, SyncLog, SyncState
from app.schemas import SyncLogOut

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

STATUSES = ("Scheduled", "Confirmed", "Completed", "Cancelled")


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _month_window(now: datetime, months: int) -> list[str]:
    """Bu ay dahil son `months` ayin anahtarlarini uretir."""
    keys: list[str] = []
    year, month = now.year, now.month
    for _ in range(months):
        keys.append(_month_key(year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(keys))


@router.get("/summary", summary="Dashboard ozeti (tum sayilar MSSQL'den)")
def analytics_summary(
    months: Annotated[int, Query(ge=1, le=24)] = 6,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    now = _utc_naive()

    # ------------------------------------------------------------- toplamlar
    active_clinics = session.execute(
        select(func.count())
        .select_from(Clinic)
        .where(Clinic.is_deleted == False)  # noqa: E712
    ).scalar_one()
    active_patients = session.execute(
        select(func.count())
        .select_from(Patient)
        .where(Patient.is_deleted == False)  # noqa: E712
    ).scalar_one()
    active_appointments = session.execute(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.is_deleted == False)  # noqa: E712
    ).scalar_one()
    deleted_appointments = session.execute(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.is_deleted == True)  # noqa: E712
    ).scalar_one()

    # ------------------------------------------------------ durum dagilimi
    status_rows = session.execute(
        select(Appointment.status, func.count())
        .where(Appointment.is_deleted == False)  # noqa: E712
        .group_by(Appointment.status)
    ).all()
    status_counts = {status: 0 for status in STATUSES}
    for status_value, count in status_rows:
        if status_value in status_counts:
            status_counts[status_value] = int(count)

    # ------------------------------------------------------ zaman cizelgesi
    today_start = now.replace(hour=0, minute=0, second=0)
    tomorrow_start = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)
    today_count = session.execute(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.is_deleted == False,  # noqa: E712
            Appointment.appointment_datetime >= today_start,
            Appointment.appointment_datetime < tomorrow_start,
        )
    ).scalar_one()
    next_7_days = session.execute(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.is_deleted == False,  # noqa: E712
            Appointment.appointment_datetime >= tomorrow_start,
            Appointment.appointment_datetime < week_end,
            Appointment.status.in_(("Scheduled", "Confirmed")),
        )
    ).scalar_one()
    past_count = session.execute(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.is_deleted == False,  # noqa: E712
            Appointment.appointment_datetime < today_start,
        )
    ).scalar_one()

    # ------------------------------------------------------ klinik hacimleri
    patient_sub = (
        select(
            Patient.external_clinic_id.label("clinic_id"),
            func.count().label("patient_count"),
        )
        .where(Patient.is_deleted == False)  # noqa: E712
        .group_by(Patient.external_clinic_id)
        .subquery()
    )
    appointment_sub = (
        select(
            Appointment.external_clinic_id.label("clinic_id"),
            func.count().label("appointment_count"),
        )
        .where(Appointment.is_deleted == False)  # noqa: E712
        .group_by(Appointment.external_clinic_id)
        .subquery()
    )
    clinic_rows = session.execute(
        select(
            Clinic.external_clinic_id,
            Clinic.name,
            func.coalesce(patient_sub.c.patient_count, 0),
            func.coalesce(appointment_sub.c.appointment_count, 0),
        )
        .outerjoin(patient_sub, patient_sub.c.clinic_id == Clinic.external_clinic_id)
        .outerjoin(
            appointment_sub,
            appointment_sub.c.clinic_id == Clinic.external_clinic_id,
        )
        .where(Clinic.is_deleted == False)  # noqa: E712
        .order_by(func.coalesce(patient_sub.c.patient_count, 0).desc(), Clinic.name)
    ).all()
    clinic_volumes = [
        {
            "clinic_id": row[0],
            "name": row[1],
            "patients": int(row[2]),
            "appointments": int(row[3]),
        }
        for row in clinic_rows
    ]

    # ------------------------------------------------- hasta kayit trendi
    month_keys = _month_window(now, months)
    first_year, first_month = (int(part) for part in month_keys[0].split("-"))
    start_date = datetime(first_year, first_month, 1)
    trend_rows = session.execute(
        select(
            func.year(Patient.created_at),
            func.month(Patient.created_at),
            func.count(),
        )
        .where(
            Patient.is_deleted == False,  # noqa: E712
            Patient.created_at >= start_date,
        )
        .group_by(func.year(Patient.created_at), func.month(Patient.created_at))
    ).all()
    trend_map = {
        _month_key(int(year), int(month)): int(count)
        for year, month, count in trend_rows
    }
    patient_registrations = [
        {"month": key, "count": trend_map.get(key, 0)} for key in month_keys
    ]

    # ------------------------------------------------------- senkronizasyon
    run_filter = (SyncLog.operation_type == "sync",)
    total_runs = session.execute(
        select(func.count()).select_from(SyncLog).where(*run_filter)
    ).scalar_one()
    success_runs = session.execute(
        select(func.count())
        .select_from(SyncLog)
        .where(*run_filter, SyncLog.status == "Success")
    ).scalar_one()
    failed_runs = session.execute(
        select(func.count())
        .select_from(SyncLog)
        .where(*run_filter, SyncLog.status == "Failed")
    ).scalar_one()
    success_rate = round((success_runs / total_runs) * 100, 1) if total_runs else None

    last_successful = session.execute(
        select(func.max(SyncState.last_successful_run_at))
    ).scalar_one_or_none()

    recent_rows = (
        session.execute(
            select(SyncLog)
            .where(*run_filter)
            .order_by(SyncLog.started_at.desc(), SyncLog.sync_log_id.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )

    lag_seconds = None
    if last_successful is not None:
        lag_seconds = max(0, int((now - last_successful).total_seconds()))

    return {
        "generated_at": _iso_z(now),
        "months": months,
        "capabilities": {
            "sync_trigger": bool(get_settings().enable_sync_trigger),
        },
        "totals": {
            "clinics": int(active_clinics),
            "patients": int(active_patients),
            "appointments": int(active_appointments),
            "deleted_appointments": int(deleted_appointments),
        },
        "appointment_status_counts": status_counts,
        "timeline": {
            "today": int(today_count),
            "next_7_days": int(next_7_days),
            "past": int(past_count),
        },
        "clinic_volumes": clinic_volumes,
        "patient_registrations": patient_registrations,
        "sync": {
            "total_runs": int(total_runs),
            "success_runs": int(success_runs),
            "failed_runs": int(failed_runs),
            "success_rate": success_rate,
            "last_successful_run_at": _iso_z(last_successful),
            "lag_seconds": lag_seconds,
            "recent_logs": [
                SyncLogOut.model_validate(row).model_dump(mode="json")
                for row in recent_rows
            ],
        },
    }
