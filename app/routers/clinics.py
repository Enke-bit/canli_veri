"""Klinik uclari (MSSQL'den okur)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Clinic
from app.routers.common import pagination
from app.schemas import ClinicOut, Page

router = APIRouter(prefix="/api/v1/clinics", tags=["clinics"])


@router.get("", response_model=Page[ClinicOut], summary="Klinikleri listele")
def list_clinics(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_deleted: bool = False,
    session: Session = Depends(get_db),
) -> Page[ClinicOut]:
    filters = []
    if not include_deleted:
        filters.append(Clinic.is_deleted == False)  # noqa: E712

    total = session.execute(
        select(func.count()).select_from(Clinic).where(*filters)
    ).scalar_one()
    rows = (
        session.execute(
            select(Clinic)
            .where(*filters)
            .order_by(Clinic.external_clinic_id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return Page[ClinicOut](
        data=[ClinicOut.model_validate(row) for row in rows],
        pagination=pagination(limit, offset, total),
    )
