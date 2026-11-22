"""
Idempotent intake: the same file (same sha256) received twice is linked to the bill it already made.

Called once from app/services/intake.store_outcome, before a new bill is stored, so a repeated file never makes
a second bill.
This is not duplicate detection: a vendor re-sending the *same PDF* is a transport repeat, so we
point at the existing bill instead of creating a second one. A *different* file for the same
invoice (rescanned, re-exported, renumbered) is still a new bill, and controls' DUPLICATE_* flags
catch it.

A voided bill doesn't count: if a clerk voided the first bill (e.g. it was read wrong), sending
the file again makes a fresh one.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.audit import SYSTEM_ACTOR
from app.extraction.pipeline import ExtractionOutcome
from app.services.events import record

ALREADY_RECEIVED = "already_received"


def existing_bill_for_file(db: Session, file_hash: str | None) -> models.Bill | None:
    """The earliest live bill created from exactly this file, if any."""
    if not file_hash:
        return None
    return db.scalars(select(models.Bill)
                      .where(models.Bill.file_hash == file_hash, models.Bill.status != "void")
                      .order_by(models.Bill.created_at, models.Bill.bill_id)).first()


def link_to_existing_bill(db: Session, item: models.IntakeItem, outcome: ExtractionOutcome,
                          started_by: str) -> str | None:
    """If this file already made a bill, link the intake item to it, note why, record the event and return
    the bill id. Returns None (and changes nothing) when the file is new or extraction produced no draft."""
    if outcome.draft is None or (bill := existing_bill_for_file(db, outcome.file_hash)) is None:
        return None
    item.bill_id = bill.bill_id
    item.warnings = [*item.warnings, f"{ALREADY_RECEIVED}: this exact file was already received as bill "
                                     f"{bill.bill_id} (status {bill.status}); no new bill was created"]
    record(db, actor_user_id=SYSTEM_ACTOR, actor_role=SYSTEM_ACTOR, action="intake.already_received",
           entity_type="intake_item", entity_id=str(item.item_id),
           after={"bill_id": bill.bill_id, "file_name": item.file_name, "file_hash": outcome.file_hash,
                  "started_by": started_by})
    return bill.bill_id
