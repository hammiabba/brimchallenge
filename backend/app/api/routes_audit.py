"""Audit log: full list, one entity's history, CSV export. Controller and auditor only; other roles see a bill's
own history inside GET /bills/{bill_id}. Pagination is keyset (after_seq), so pages never skip or repeat events
while new ones are written."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS
from app.api.schemas_api import AuditEventOut, AuditPage
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AUDIT_READERS
from app.db.database import get_session, get_write_session
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditPage, responses=READ_ERRORS)
def list_audit(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), entity_type: str | None = None,
               entity_id: str | None = None, actor: str | None = None, action: str | None = None,
               since: datetime | None = None, until: datetime | None = None,
               after_seq: Annotated[int | None, Query(ge=0)] = None,
               limit: Annotated[int, Query(ge=1, le=500)] = 100, db: Session = Depends(get_session)):
    return audit.list_page(db, after_seq=after_seq, limit=limit, entity_type=entity_type, entity_id=entity_id,
                           actor=actor, action=action, since=since, until=until)


@router.get("/export", responses={**READ_ERRORS, 200: {"content": {"text/csv": {}}}})
def export_audit(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), entity_type: str | None = None,
                 entity_id: str | None = None, actor: str | None = None, action: str | None = None,
                 since: datetime | None = None, until: datetime | None = None,
                 db: Session = Depends(get_write_session)) -> StreamingResponse:
    filters = {"entity_type": entity_type, "entity_id": entity_id, "actor_user_id": actor, "action": action,
               "since": since, "until": until}
    audit.record_export(db, user, filters)
    db.commit()
    return StreamingResponse(audit.stream_csv(db.get_bind(), filters), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditEventOut], responses=READ_ERRORS)
def entity_audit(entity_type: str, entity_id: str, user: CurrentUser = Depends(require_role(*AUDIT_READERS)),
                 db: Session = Depends(get_session)):
    return audit.entity_history(db, entity_type, entity_id)
