"""Hasta uclari (MSSQL'den okur)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Patient
from app.routers.common import pagination
from app.schemas import Page, PatientOut

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


@router.get("", response_model=Page[PatientOut], summary="Hastalari listele")
def list_patients(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    clinic_id: str | None = None,
    include_deleted: bool = False,
    session: Session = Depends(get_db),
) -> Page[PatientOut]:
    filters = []
    if not include_deleted:
        filters.append(Patient.is_deleted == False)  # noqa: E712
    if clinic_id:
        filters.append(Patient.external_clinic_id == clinic_id)

    total = session.execute(
        select(func.count()).select_from(Patient).where(*filters)
    ).scalar_one()
    rows = (
        session.execute(
            select(Patient)
            .where(*filters)
            .order_by(Patient.external_patient_id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return Page[PatientOut](
        data=[PatientOut.model_validate(row) for row in rows],
        pagination=pagination(limit, offset, total),
    )
