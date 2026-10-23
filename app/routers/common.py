"""Router ortak yardimcilari."""
from __future__ import annotations

from app.schemas import Pagination


def pagination(limit: int, offset: int, total: int) -> Pagination:
    next_offset = offset + limit if offset + limit < total else None
    return Pagination(
        limit=limit,
        offset=offset,
        total=total,
        has_more=next_offset is not None,
        next_offset=next_offset,
    )
