"""Sentetik kaynak API (port 8001).

Gercek bir dis sistem gibi davranir; veriyi data/synthetic_source.json
dosyasinda tutar. Bu API'ye yapilan degisiklikler senkronizasyon
tarafindan 'kaynaktaki degisiklik' olarak algilanir.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app.source_schemas import (
    SourceAppointmentPage,
    SourceAppointmentPatch,
    SourceAppointmentStatus,
    SourceClinicPage,
    SourcePatientPage,
)
from mock_source import storage
from mock_source.storage import SourceDataError
from app.config import get_settings

app = FastAPI(
    title="DentSync Mock Kaynak API",
    description=(
        "Tamamen sentetik klinik/randevu verisi sunan sahte kaynak sistem. "
        "Tarihler UTC ve ISO-8601 ('Z') formatindadir."
    ),
    version="1.1.0",
)

# Dashboard tarayicidan bu API'ye istek atabilsin (yerel gelistirme).
_source_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_source_settings.cors_origins),
    allow_origin_regex=_source_settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

AppointmentStatus = SourceAppointmentStatus


class SourceAppointmentCreate(BaseModel):
    external_appointment_id: str | None = Field(default=None, max_length=50)
    external_patient_id: str = Field(..., min_length=1, max_length=50)
    external_clinic_id: str = Field(..., min_length=1, max_length=50)
    appointment_datetime: datetime
    end_datetime: datetime
    procedure_type: str = Field(..., min_length=1, max_length=100)
    status: AppointmentStatus = "Scheduled"

    @model_validator(mode="after")
    def validate_times(self) -> "SourceAppointmentCreate":
        if self.end_datetime <= self.appointment_datetime:
            raise ValueError("end_datetime, appointment_datetime'ten sonra olmalidir.")
        return self


@app.exception_handler(SourceDataError)
async def source_data_error_handler(_: Request, exc: SourceDataError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    return _parse_dt(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_incoming(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _clinic_to_api(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_clinic_id": record["ExternalClinicId"],
        "name": record["Name"],
        "created_at": _iso_z(record["CreatedAt"]),
        "updated_at": _iso_z(record["UpdatedAt"]),
        "is_deleted": bool(record.get("IsDeleted", False)),
    }


def _patient_to_api(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_patient_id": record["ExternalPatientId"],
        "external_clinic_id": record["ExternalClinicId"],
        "first_name": record["FirstName"],
        "last_name": record["LastName"],
        "email": record.get("Email"),
        "phone": record.get("Phone"),
        "created_at": _iso_z(record["CreatedAt"]),
        "updated_at": _iso_z(record["UpdatedAt"]),
        "is_deleted": bool(record.get("IsDeleted", False)),
    }


def _appointment_to_api(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_appointment_id": record["ExternalAppointmentId"],
        "external_patient_id": record["ExternalPatientId"],
        "external_clinic_id": record["ExternalClinicId"],
        "appointment_datetime": _iso_z(record["AppointmentDateTime"]),
        "end_datetime": _iso_z(record["EndDateTime"]),
        "procedure_type": record["ProcedureType"],
        "status": record["Status"],
        "created_at": _iso_z(record["CreatedAt"]),
        "updated_at": _iso_z(record["UpdatedAt"]),
        "is_deleted": bool(record.get("IsDeleted", False)),
    }


def _paginate(
    records: list[dict[str, Any]],
    limit: int,
    offset: int,
    updated_since: datetime | None,
    include_deleted: bool,
    id_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filtered = records
    if not include_deleted:
        filtered = [r for r in filtered if not r.get("IsDeleted", False)]
    if updated_since is not None:
        since = _parse_dt(updated_since)
        filtered = [r for r in filtered if _parse_dt(r["UpdatedAt"]) >= since]
    # Deterministik ve kararli siralama: (UpdatedAt, dis kimlik)
    ordered = sorted(filtered, key=lambda r: (_parse_dt(r["UpdatedAt"]), str(r[id_key])))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    pagination = {
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": next_offset is not None,
        "next_offset": next_offset,
    }
    return page, pagination


@app.get("/health", summary="Kaynak API ve veri dosyasi durumu")
def health() -> dict[str, Any]:
    try:
        data = storage.load_data(required=True)
    except SourceDataError as exc:
        return {
            "status": "degraded",
            "service": "mock-source-api",
            "source_data_loaded": False,
            "message": str(exc),
        }
    return {
        "status": "ok",
        "service": "mock-source-api",
        "source_data_loaded": True,
        "source_data_file": str(storage.data_path()),
        "counts": {
            "clinics": len(data["clinics"]),
            "patients": len(data["patients"]),
            "appointments": len(data["appointments"]),
        },
    }


@app.get("/source/stats", summary="Kaynak veri ozeti")
def source_stats() -> dict[str, Any]:
    data = storage.load_data(required=True)
    now = datetime.now(timezone.utc)
    active_appointments = [a for a in data["appointments"] if not a.get("IsDeleted", False)]
    status_counts: dict[str, int] = {}
    for appointment in active_appointments:
        status_value = appointment["Status"]
        status_counts[status_value] = status_counts.get(status_value, 0) + 1
    upcoming = [
        a
        for a in active_appointments
        if _parse_dt(a["AppointmentDateTime"]) >= now
        and a["Status"] in {"Scheduled", "Confirmed"}
    ]
    return {
        "clinics": len(data["clinics"]),
        "patients": len(data["patients"]),
        "appointments": len(data["appointments"]),
        "active": {
            "clinics": sum(1 for c in data["clinics"] if not c.get("IsDeleted", False)),
            "patients": sum(1 for p in data["patients"] if not p.get("IsDeleted", False)),
            "appointments": len(active_appointments),
        },
        "appointment_status_counts": status_counts,
        "upcoming_appointments": len(upcoming),
        "generated_at": data.get("meta", {}).get("generated_at"),
        "now": _iso_z(now),
    }


@app.get("/source/clinics", response_model=SourceClinicPage, summary="Klinik listesi")
def list_clinics(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    updated_since: datetime | None = None,
    include_deleted: bool = True,
) -> dict[str, Any]:
    data = storage.load_data(required=True)
    page, pagination = _paginate(
        data["clinics"], limit, offset, updated_since, include_deleted, "ExternalClinicId"
    )
    return {"data": [_clinic_to_api(r) for r in page], "pagination": pagination}


@app.get("/source/patients", response_model=SourcePatientPage, summary="Hasta listesi")
def list_patients(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    updated_since: datetime | None = None,
    include_deleted: bool = True,
    clinic_id: str | None = None,
) -> dict[str, Any]:
    data = storage.load_data(required=True)
    records = data["patients"]
    if clinic_id:
        records = [r for r in records if r["ExternalClinicId"] == clinic_id]
    page, pagination = _paginate(
        records, limit, offset, updated_since, include_deleted, "ExternalPatientId"
    )
    return {"data": [_patient_to_api(r) for r in page], "pagination": pagination}


@app.get(
    "/source/appointments",
    response_model=SourceAppointmentPage,
    summary="Randevu listesi",
)
def list_appointments(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    updated_since: datetime | None = None,
    include_deleted: bool = True,
    clinic_id: str | None = None,
    patient_id: str | None = None,
) -> dict[str, Any]:
    data = storage.load_data(required=True)
    records = data["appointments"]
    if clinic_id:
        records = [r for r in records if r["ExternalClinicId"] == clinic_id]
    if patient_id:
        records = [r for r in records if r["ExternalPatientId"] == patient_id]
    page, pagination = _paginate(
        records,
        limit,
        offset,
        updated_since,
        include_deleted,
        "ExternalAppointmentId",
    )
    return {"data": [_appointment_to_api(r) for r in page], "pagination": pagination}


@app.post(
    "/source/appointments",
    response_model=SourceAppointmentPage,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni randevu (sentetik)",
)
def create_appointment(payload: SourceAppointmentCreate) -> dict[str, Any]:
    with storage.transaction() as data:
        patient = next(
            (p for p in data["patients"] if p["ExternalPatientId"] == payload.external_patient_id),
            None,
        )
        clinic = next(
            (c for c in data["clinics"] if c["ExternalClinicId"] == payload.external_clinic_id),
            None,
        )
        if patient is None:
            raise HTTPException(status_code=404, detail="Hasta bulunamadi.")
        if clinic is None:
            raise HTTPException(status_code=404, detail="Klinik bulunamadi.")
        if patient.get("IsDeleted") or clinic.get("IsDeleted"):
            raise HTTPException(
                status_code=409, detail="Silinmis hasta veya klinige randevu eklenemez."
            )
        if patient["ExternalClinicId"] != clinic["ExternalClinicId"]:
            raise HTTPException(
                status_code=422,
                detail="Hasta ile randevu klinigi ayni olmalidir.",
            )

        external_id = payload.external_appointment_id or (
            "APT-LOCAL-" + uuid.uuid4().hex[:12]
        )
        if any(a["ExternalAppointmentId"] == external_id for a in data["appointments"]):
            raise HTTPException(status_code=409, detail="Randevu kimligi zaten kullanimda.")

        now = storage.utc_now_iso()
        record = {
            "ExternalAppointmentId": external_id,
            "ExternalPatientId": payload.external_patient_id,
            "ExternalClinicId": payload.external_clinic_id,
            "AppointmentDateTime": _normalize_incoming(payload.appointment_datetime),
            "EndDateTime": _normalize_incoming(payload.end_datetime),
            "ProcedureType": payload.procedure_type,
            "Status": payload.status,
            "CreatedAt": now,
            "UpdatedAt": now,
            "IsDeleted": False,
        }
        data["appointments"].append(record)
        created = _appointment_to_api(record)

    return {
        "data": [created],
        "pagination": {
            "limit": 1,
            "offset": 0,
            "total": 1,
            "has_more": False,
            "next_offset": None,
        },
    }


@app.patch(
    "/source/appointments/{external_id}",
    response_model=SourceAppointmentPage,
    summary="Randevu guncelle",
)
def update_appointment(external_id: str, payload: SourceAppointmentPatch) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Guncellenecek alan belirtilmedi.")

    with storage.transaction() as data:
        record = next(
            (a for a in data["appointments"] if a["ExternalAppointmentId"] == external_id),
            None,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Randevu bulunamadi.")
        if record.get("IsDeleted"):
            raise HTTPException(status_code=409, detail="Silinmis randevu guncellenemez.")

        start = _parse_dt(changes.get("appointment_datetime", record["AppointmentDateTime"]))
        end = _parse_dt(changes.get("end_datetime", record["EndDateTime"]))
        if end <= start:
            raise HTTPException(
                status_code=422,
                detail="end_datetime, appointment_datetime'ten sonra olmalidir.",
            )

        if "appointment_datetime" in changes:
            record["AppointmentDateTime"] = _normalize_incoming(changes["appointment_datetime"])
        if "end_datetime" in changes:
            record["EndDateTime"] = _normalize_incoming(changes["end_datetime"])
        if "procedure_type" in changes:
            record["ProcedureType"] = changes["procedure_type"]
        if "status" in changes:
            record["Status"] = changes["status"]
        record["UpdatedAt"] = storage.utc_now_iso()
        updated = _appointment_to_api(record)

    return {
        "data": [updated],
        "pagination": {
            "limit": 1,
            "offset": 0,
            "total": 1,
            "has_more": False,
            "next_offset": None,
        },
    }


@app.post(
    "/source/appointments/{external_id}/cancel",
    response_model=SourceAppointmentPage,
    summary="Randevuyu iptal et",
)
def cancel_appointment(external_id: str) -> dict[str, Any]:
    with storage.transaction() as data:
        record = next(
            (a for a in data["appointments"] if a["ExternalAppointmentId"] == external_id),
            None,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Randevu bulunamadi.")
        if record.get("IsDeleted"):
            raise HTTPException(status_code=409, detail="Silinmis randevu iptal edilemez.")
        if record["Status"] != "Cancelled":
            record["Status"] = "Cancelled"
            record["UpdatedAt"] = storage.utc_now_iso()
        cancelled = _appointment_to_api(record)

    return {
        "data": [cancelled],
        "pagination": {
            "limit": 1,
            "offset": 0,
            "total": 1,
            "has_more": False,
            "next_offset": None,
        },
    }


@app.delete(
    "/source/appointments/{external_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Randevuyu yumusak sil (IsDeleted=true)",
)
def delete_appointment(external_id: str):
    with storage.transaction() as data:
        record = next(
            (a for a in data["appointments"] if a["ExternalAppointmentId"] == external_id),
            None,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Randevu bulunamadi.")
        if not record.get("IsDeleted"):
            record["IsDeleted"] = True
            if record["Status"] != "Cancelled":
                record["Status"] = "Cancelled"
            record["UpdatedAt"] = storage.utc_now_iso()


@app.get("/source/appointments/{external_id}", summary="Tek randevu")
def get_appointment(external_id: str) -> dict[str, Any]:
    data = storage.load_data(required=True)
    record = next(
        (a for a in data["appointments"] if a["ExternalAppointmentId"] == external_id), None
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Randevu bulunamadi.")
    return {"data": _appointment_to_api(record)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mock_source.main:app", host="127.0.0.1", port=8001, reload=False)
