"""
What a clerk sees for one inbox email: its triage, the suggested next step and the bills it produced.

Used by GET /intake/emails/{email_id} (api/routes_intake.py) and, for the suggested action only, by the
GET /intake/emails list (app/services/intake.py, one call per email), so the list and the email page suggest the
same next step.
Input: the stored Email row (and its intake items). Output: SuggestedAction / EmailDetail. Reads only.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_api import UtcDateTime
from app.db import models
from app.intake.actions import SuggestedAction, suggest_action
from app.reference.csv_repository import default_repository
from app.reference.repository import ReferenceRepository
from app.shared.schemas import EmailClass, EmailTriage


class EmailItem(BaseModel):
    """One file from the email, as intake handled it."""
    item_id: int
    file_name: str
    file_hash: str | None
    status: Literal["ok", "llm_skipped", "failed", "queued", "processing"]  # db.models.INTAKE_STATUSES
    error: str | None
    warnings: list[str]
    bill_id: str | None


class EmailDetail(BaseModel):
    email_id: str
    from_name: str | None
    from_address: str
    to_address: str | None
    subject: str
    received_at: UtcDateTime      # sent as ISO 8601 UTC with Z, like GET /intake/emails
    body: str
    attachments: list[str]
    email_class: str | None          # None until the inbox job has triaged it
    triage_reason: str | None
    triaged_at: UtcDateTime | None
    suggested_action: SuggestedAction | None
    bill_ids: list[str]
    items: list[EmailItem]


def _as_dict(e: models.Email) -> dict:
    return {"email_id": e.email_id, "from_name": e.from_name, "from_address": e.from_address,
            "to_address": e.to_address, "subject": e.subject, "body": e.body,
            "received_at": e.received_at.isoformat(), "attachments": list(e.attachments or [])}


def action_for(e: models.Email, repo: ReferenceRepository | None = None) -> SuggestedAction | None:
    """The suggested next step for a triaged email; None before triage."""
    if not e.email_class:
        return None
    triage = EmailTriage(email_id=e.email_id, email_class=EmailClass(e.email_class),
                         attachments_to_process=list(e.attachments or []), reason=e.triage_reason or "")
    return suggest_action(_as_dict(e), triage, repo or default_repository())


def email_detail(db: Session, email_id: str, repo: ReferenceRepository | None = None) -> EmailDetail | None:
    e = db.get(models.Email, email_id)
    if e is None:
        return None
    items = list(db.scalars(select(models.IntakeItem).where(models.IntakeItem.email_id == email_id)
                            .order_by(models.IntakeItem.item_id)))
    return EmailDetail(
        **_as_dict(e) | {"received_at": e.received_at}, email_class=e.email_class, triage_reason=e.triage_reason,
        triaged_at=e.triaged_at, suggested_action=action_for(e, repo),
        bill_ids=list(dict.fromkeys(i.bill_id for i in items if i.bill_id)),
        items=[EmailItem(item_id=i.item_id, file_name=i.file_name, file_hash=i.file_hash, status=i.status,
                         error=i.error, warnings=list(i.warnings or []), bill_id=i.bill_id) for i in items])
