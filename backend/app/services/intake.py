"""Intake reads: the caller's own submissions and the intake item list. Writes (submissions, inbox jobs) arrive
with the DB helper that turns a DraftBill into a bill."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.auth.deps import CurrentUser
from app.db import models
from app.services.pagination import paginate


def my_submissions(db: Session, user: CurrentUser) -> list[models.IntakeItem]:
    return list(db.scalars(select(models.IntakeItem).where(models.IntakeItem.created_by == user.user_id)
                           .order_by(models.IntakeItem.created_at.desc())))


def list_items(db: Session, *, status: str | None, email_id: str | None, limit: int,
               offset: int) -> s.Page[s.IntakeItemOut]:
    stmt = select(models.IntakeItem)
    if status:
        stmt = stmt.where(models.IntakeItem.status == status)
    if email_id:
        stmt = stmt.where(models.IntakeItem.email_id == email_id)
    rows, total = paginate(db, stmt.order_by(models.IntakeItem.item_id.desc()), limit=limit, offset=offset)
    return s.Page[s.IntakeItemOut](items=[s.IntakeItemOut.model_validate(r) for r in rows], total=total,
                                   limit=limit, offset=offset)
