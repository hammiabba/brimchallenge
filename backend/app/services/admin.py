"""Admin reads: approval policies, users and absences. Writes arrive with log_event and the DB-backed RefData
(an edited policy must reach controls, which today read the dataset CSVs)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.db import models
from app.services import views


def policies(db: Session) -> list[models.Policy]:
    return list(db.scalars(select(models.Policy).order_by(models.Policy.rule_id)))


def users(db: Session) -> list[s.UserOut]:
    return [views.user_out(u) for u in db.scalars(select(models.User).order_by(models.User.user_id))]


def absences(db: Session) -> list[models.UserAbsence]:
    return list(db.scalars(select(models.UserAbsence).order_by(models.UserAbsence.starts_on.desc())))
