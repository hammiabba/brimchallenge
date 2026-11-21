"""Offset pagination with a total count. Fine at this data size; at 100x the list endpoints would move to keyset
(cursor) pagination on (received_date, bill_id) so deep pages don't scan."""
from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


def paginate(db: Session, stmt: Select, *, limit: int, offset: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    return rows, total
