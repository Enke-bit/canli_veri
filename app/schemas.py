"""Hedef API'nin istek/cevap semalari.

Tum tarihler UTC olarak ve sonda 'Z' ile dondurulur. Veritabaninda
naive UTC saklanir; disariya cevirirken UTC oldugu acikca belirtilir.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

AppointmentStatus = Literal["Scheduled", "Confirmed", "Completed", "Cancelled"]


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime, PlainSerializer(_iso_utc, return_type=str, when_used="json")
]


class ClinicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_clinic_id: str
    name: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    is_deleted: bool


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_patient_id: str
    external_clinic_id: str
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    is_deleted: bool


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_appointment_id: str
    external_patient_id: str
    external_clinic_id: str
    appointment_datetime: UtcDateTime
    end_datetime: UtcDateTime
    procedure_type: str
    status: AppointmentStatus
    created_at: UtcDateTime
    updated_at: UtcDateTime
    is_deleted: bool


class Pagination(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool
    next_offset: int | None


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    data: list[T]
    pagination: Pagination


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus = Field(
        ..., description="Scheduled, Confirmed, Completed veya Cancelled"
    )


class SyncStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_type: str
    last_synced_at: UtcDateTime | None
    last_successful_run_at: UtcDateTime | None


class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sync_log_id: int
    job_id: str
    entity_type: str
    operation_type: str
    started_at: UtcDateTime
    finished_at: UtcDateTime | None
    status: Literal["Running", "Success", "Failed", "Skipped"]
    records_read: int
    records_inserted: int
    records_updated: int
    records_deleted_marked: int
    error_count: int
    error_summary: str | None


class SyncStatusOut(BaseModel):
    states: list[SyncStateOut]
    latest_logs: list[SyncLogOut]
    last_successful_run_at: UtcDateTime | None
