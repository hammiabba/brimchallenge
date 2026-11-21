"""Audit log reads and the CSV export, on top of the DB layer's app.db.audit (list_events, iter_events_csv,
chain_head). Authorization is the route's job; nothing here checks roles.

An export is itself audited (audit.exported) with the chain head at export time: the newest (seq, hash). Keeping
that pair outside the database lets anyone prove later that no events were removed from the end of the log, which
verify_chain alone can't detect.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.auth.deps import CurrentUser
from app.db import audit as audit_db
from app.services.events import record


def to_out(r: audit_db.AuditRecord) -> s.AuditEventOut:
    return s.AuditEventOut(seq=r.seq, event_id=r.event_id, at=r.at, actor_user_id=r.actor_user_id,
                           actor_role=r.actor_role, on_behalf_of=r.on_behalf_of, action=r.action,
                           entity_type=r.entity_type, entity_id=r.entity_id, before=r.before, after=r.after,
                           comment=r.comment, request_id=r.request_id)


def list_page(db: Session, *, after_seq: int | None, limit: int, entity_type: str | None, entity_id: str | None,
              actor: str | None, action: str | None, since: datetime | None, until: datetime | None) -> s.AuditPage:
    rows = audit_db.list_events(db, entity_type=entity_type, entity_id=entity_id, actor_user_id=actor, action=action,
                                since=since, until=until, after_seq=after_seq, limit=limit)
    items = [to_out(r) for r in rows]
    return s.AuditPage(items=items, next_after_seq=items[-1].seq if len(items) == limit else None)


def entity_history(db: Session, entity_type: str, entity_id: str) -> list[s.AuditEventOut]:
    """Every event about one entity, oldest first (pages through the keyset API until done)."""
    out: list[s.AuditEventOut] = []
    after = None
    while True:
        rows = audit_db.list_events(db, entity_type=entity_type, entity_id=entity_id, after_seq=after,
                                    limit=audit_db.MAX_PAGE)
        out.extend(to_out(r) for r in rows)
        if len(rows) < audit_db.MAX_PAGE:
            return out
        after = rows[-1].seq


def record_export(db: Session, user: CurrentUser, filters: dict) -> None:
    """Log the export with the chain head, in the caller's write transaction (the caller commits)."""
    head = audit_db.chain_head(db)
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=audit_db.AuditAction.AUDIT_EXPORTED,
           entity_type="audit_log", entity_id="export",
           after={"filters": {k: v for k, v in filters.items() if v is not None},
                  "chain_head": {"seq": head[0], "hash": head[1]} if head else None})


def stream_csv(bind: Engine, filters: dict) -> Iterator[str]:
    """CSV records for a streaming response. Opens its own read session, which stays open while the response is
    being sent and closes when the stream ends."""
    with Session(bind) as session:
        yield from audit_db.iter_events_csv(session, **filters)
