"""Kaynak API'den gelen cevaplarin dogrulanmasi icin semalar."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import UtcDateTime

SourceAppointmentStatus = Literal["Scheduled", "Confirmed", "Completed", "Cancelled"]


class SourceClinic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_clinic_id: str
    name: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    is_deleted: bool = False


class SourcePatient(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_patient_id: str
    external_clinic_id: str
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    is_deleted: bool = False


class SourceAppointment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_appointment_id: str
    external_patient_id: str
    external_clinic_id: str
    appointment_datetime: UtcDateTime
    end_datetime: UtcDateTime
    procedure_type: str
    status: SourceAppointmentStatus
    created_at: UtcDateTime
    updated_at: UtcDateTime
    is_deleted: bool = False


class SourcePagination(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool
    next_offset: int | None = None


class SourceClinicPage(BaseModel):
    data: list[SourceClinic]
    pagination: SourcePagination


class SourcePatientPage(BaseModel):
    data: list[SourcePatient]
    pagination: SourcePagination


class SourceAppointmentPage(BaseModel):
    data: list[SourceAppointment]
    pagination: SourcePagination


class SourceAppointmentPatch(BaseModel):
    appointment_datetime: datetime | None = None
    end_datetime: datetime | None = None
    procedure_type: str | None = Field(default=None, min_length=1, max_length=100)
    status: SourceAppointmentStatus | None = None
