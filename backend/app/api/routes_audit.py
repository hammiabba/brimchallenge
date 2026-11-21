"""Audit log: full list, one entity's history, CSV export. Controller and auditor only; other roles see a bill's
own history inside GET /bills/{bill_id}."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.common import READ_ERRORS, Limit, Offset
from app.api.errors import not_implemented
from app.api.schemas_api import AuditEventOut, Page
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AUDIT_READERS

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEventOut], responses=READ_ERRORS)
def list_audit(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), entity_type: str | None = None,
               entity_id: str | None = None, actor: str | None = None, action: str | None = None,
               from_at: datetime | None = None, to_at: datetime | None = None,
               limit: Limit = 100, offset: Offset = 0):
    raise not_implemented("Audit list")


@router.get("/export", responses={**READ_ERRORS, 200: {"content": {"text/csv": {}}}})
def export_audit(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), entity_type: str | None = None,
                 entity_id: str | None = None, actor: str | None = None, action: str | None = None,
                 from_at: datetime | None = None, to_at: datetime | None = None):
    raise not_implemented("Audit export")


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditEventOut], responses=READ_ERRORS)
def entity_audit(entity_type: str, entity_id: str, user: CurrentUser = Depends(require_role(*AUDIT_READERS))):
    raise not_implemented("Entity audit history")
