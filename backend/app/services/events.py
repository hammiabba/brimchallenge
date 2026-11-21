"""The API's single path into the audit log. Every write service calls `record` exactly once, inside its write
transaction, before the route commits; the event and the change land together or not at all.

It fills in what the API knows and the DB helper doesn't: the actor and role from the session, and the request id
from the middleware, so every event of one HTTP request can be correlated.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api.middleware import get_request_id
from app.db.audit import AuditRecord, log_event


def record(db: Session, *, actor_user_id: str, actor_role: str, action: str, entity_type: str, entity_id: str,
           before: dict[str, Any] | None = None, after: dict[str, Any] | None = None, comment: str | None = None,
           on_behalf_of: str | None = None) -> AuditRecord:
    return log_event(db, actor_user_id=actor_user_id, actor_role=actor_role, action=action, entity_type=entity_type,
                     entity_id=entity_id, before=before, after=after, comment=comment, on_behalf_of=on_behalf_of,
                     request_id=get_request_id())
