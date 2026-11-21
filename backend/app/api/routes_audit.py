"""Audit log: full list, one entity's history, CSV export. Controller and auditor only; other roles see a bill's
own history inside GET /bills/{bill_id}."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS, Limit, Offset
from app.api.schemas_api import AuditEventOut, Page
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AUDIT_READERS
from app.db.database import get_session
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEventOut], responses=READ_ERRORS)
def list_audit(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), entity_type: str | None = None,
               entity_id: str | None = None, actor: str | None = None, action: str | None = None,
               from_at: datetime | None = None, to_at: datetime | None = None,
               limit: Limit = 100, offset: Offset = 0, db: Session = Depends(get_session)):
    return audit.list_events(db, limit=limit, offset=offset, entity_type=entity_type, entity_id=entity_id,
                             actor=actor, action=action, from_at=from_at, to_at=to_at)


@router.get("/export", responses={**READ_ERRORS, 200: {"content": {"text/csv": {}}}})
def export_audit(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), entity_type: str | None = None,
                 entity_id: str | None = None, actor: str | None = None, action: str | None = None,
                 from_at: datetime | None = None, to_at: datetime | None = None,
                 db: Session = Depends(get_session)) -> Response:
    body = audit.export_csv(db, entity_type=entity_type, entity_id=entity_id, actor=actor, action=action,
                            from_at=from_at, to_at=to_at)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditEventOut], responses=READ_ERRORS)
def entity_audit(entity_type: str, entity_id: str, user: CurrentUser = Depends(require_role(*AUDIT_READERS)),
                 db: Session = Depends(get_session)):
    return audit.entity_events(db, entity_type, entity_id)
