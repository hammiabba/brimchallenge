"""Audit log reads and CSV export. The log itself is append-only (database triggers); it's written only through
the DB layer's log_event()."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.db import models
from app.services import views
from app.services.pagination import paginate

CSV_COLUMNS = ("seq", "event_id", "at", "actor_user_id", "actor_role", "on_behalf_of", "action", "entity_type",
               "entity_id", "comment", "request_id", "before", "after", "hash")
# A cell starting with one of these is run as a formula by Excel/Sheets (CSV injection), so it gets a leading quote.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _filtered(entity_type: str | None, entity_id: str | None, actor: str | None, action: str | None,
              from_at: datetime | None, to_at: datetime | None) -> Select:
    stmt = select(models.AuditEvent)
    if entity_type:
        stmt = stmt.where(models.AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(models.AuditEvent.entity_id == entity_id)
    if actor:
        stmt = stmt.where(models.AuditEvent.actor_user_id == actor)
    if action:
        stmt = stmt.where(models.AuditEvent.action == action)
    if from_at:
        stmt = stmt.where(models.AuditEvent.at >= from_at)
    if to_at:
        stmt = stmt.where(models.AuditEvent.at <= to_at)
    return stmt


def list_events(db: Session, *, limit: int, offset: int, **filters) -> s.Page[s.AuditEventOut]:
    stmt = _filtered(**filters).order_by(models.AuditEvent.seq.desc())
    rows, total = paginate(db, stmt, limit=limit, offset=offset)
    return s.Page[s.AuditEventOut](items=[views.audit_out(e) for e in rows], total=total, limit=limit, offset=offset)


def entity_events(db: Session, entity_type: str, entity_id: str) -> list[s.AuditEventOut]:
    stmt = _filtered(entity_type, entity_id, None, None, None, None).order_by(models.AuditEvent.seq)
    return [views.audit_out(e) for e in db.scalars(stmt)]


def safe_cell(value: object) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True) \
        if isinstance(value, dict | list) else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(events: Iterable[models.AuditEvent]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for e in events:
        writer.writerow([safe_cell(v) for v in (
            e.seq, e.event_id, e.at.isoformat(), e.actor_user_id, e.actor_role, e.on_behalf_of, e.action,
            e.entity_type, e.entity_id, e.comment, e.request_id, e.before_json, e.after_json, e.hash)])
    return buf.getvalue()


def export_csv(db: Session, **filters) -> str:
    return to_csv(db.scalars(_filtered(**filters).order_by(models.AuditEvent.seq)))
