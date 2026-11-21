"""
Intake: employee/clerk submissions and the AP inbox run, persisted as real bills.

Both are slow (an LLM call per file), so the HTTP request only records what was asked and returns 202; the work
runs as a background task with its own sessions, and the client polls (GET /submissions, GET /intake/inbox/jobs/{id}).

The intake lane's functions do the reading: classify() triages an email, extract_outcome() turns a file into a
DraftBill. This module stores the results:
- the triage on the email row, and one intake_items row per file (including failures, so AP can see them);
- each DraftBill as a bill in needs_review (app.db.bills.create_bill_from_draft), then a controls run on it with
  the rest of the batch, so duplicates and splits within one inbox run are caught.

No database lock is held while a file is being read: extraction happens between write transactions.
Background events are written by the "system" actor, with the user who started the work in the payload.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError
from app.auth.deps import CurrentUser
from app.auth.roles import EMPLOYEE
from app.config import get_settings
from app.controls.incoming import with_department
from app.db import models
from app.db.audit import SYSTEM_ACTOR, AuditAction
from app.db.bills import create_bill_from_draft
from app.db.database import as_write_engine
from app.db.types import to_utc, utcnow
from app.extraction.pipeline import ExtractionOutcome, extract_outcome
from app.intake.classifier import classify
from app.intake.received import link_to_existing_bill
from app.intake.upload import ALLOWED_EXTS
from app.services import controls_runner
from app.services.events import record
from app.services.pagination import paginate
from app.shared.schemas import DraftBill

# ---------------------------------------------------------------- reads


def my_submissions(db: Session, user: CurrentUser) -> list[models.IntakeItem]:
    return list(db.scalars(select(models.IntakeItem).where(models.IntakeItem.created_by == user.user_id,
                                                           models.IntakeItem.email_id.is_(None))
                           .order_by(models.IntakeItem.created_at.desc(), models.IntakeItem.item_id.desc())))


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


def list_emails(db: Session, *, email_class: str | None, triaged: bool | None, limit: int,
                offset: int) -> s.Page[s.EmailOut]:
    stmt = select(models.Email)
    if email_class:
        stmt = stmt.where(models.Email.email_class == email_class)
    if triaged is not None:
        stmt = stmt.where(models.Email.email_class.isnot(None) if triaged else models.Email.email_class.is_(None))
    rows, total = paginate(db, stmt.order_by(models.Email.received_at.desc(), models.Email.email_id), limit=limit,
                           offset=offset)
    items: dict[str, list[models.IntakeItem]] = {}
    if rows:
        ids = [e.email_id for e in rows]
        for item in db.scalars(select(models.IntakeItem).where(models.IntakeItem.email_id.in_(ids))
                               .order_by(models.IntakeItem.item_id)):
            items.setdefault(item.email_id, []).append(item)
    out = [s.EmailOut(email_id=e.email_id, from_name=e.from_name, from_address=e.from_address, subject=e.subject,
                      received_at=e.received_at, attachments=list(e.attachments or []), email_class=e.email_class,
                      triage_reason=e.triage_reason, triaged_at=e.triaged_at,
                      items=[s.IntakeItemOut.model_validate(i) for i in items.get(e.email_id, [])]) for e in rows]
    return s.Page[s.EmailOut](items=out, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------- shared storage step


@dataclass
class Overrides:
    """Bill fields set from who submitted, not from the document (an employee's own department and name)."""

    requester_user_id: str | None = None
    department_id: str | None = None


@dataclass
class Extracted:
    item_id: int
    outcome: ExtractionOutcome
    email_id: str | None = None
    overrides: Overrides = field(default_factory=Overrides)


def _write_session(bind: Engine) -> Session:
    return Session(as_write_engine(bind), expire_on_commit=False)


def store_outcome(bind: Engine, job: Extracted, *, started_by: str, batch: list[DraftBill]) -> str | None:
    """One write transaction per file: update the intake item and, if a DraftBill came out, create the bill, fill in
    who it's for, run controls with the batch, and record one event. Returns the new bill id.

    Department, when the document gives none: the submitter's own (employees), else the department the line coding
    suggestions put the most money on (controls.incoming.with_department), so routing has a manager to send the
    bill to. draft_json keeps the document exactly as read; the source is recorded in the event and shown on the
    bill as department_source ("coding" = suggested, not yet confirmed by a person)."""
    with _write_session(bind) as db:
        item = db.get(models.IntakeItem, job.item_id)
        out = job.outcome
        item.status, item.file_hash = out.status, out.file_hash or None
        item.error, item.warnings = out.error, list(out.warnings)
        bill_id = link_to_existing_bill(db, item, out, started_by)
        if out.draft is not None and bill_id is None:
            received = item.created_at.date()
            created = create_bill_from_draft(db, out.draft, created_by=started_by, received_date=received,
                                             source_email_id=job.email_id)
            bill_id = item.bill_id = created.bill_id
            item.warnings = [*item.warnings, *created.warnings]
            bill = db.get(models.Bill, bill_id)
            if job.overrides.requester_user_id:
                bill.requester_user_id = job.overrides.requester_user_id
            source = "invoice" if bill.department_id else None
            if job.overrides.department_id:
                bill.department_id, source = job.overrides.department_id, "submitter"
            elif bill.department_id is None:
                suggested, how = with_department(out.draft)
                if how == "coding" and db.get(models.Department, suggested.department_id) is not None:
                    bill.department_id, source = suggested.department_id, "coding"
                    item.warnings = [*item.warnings, f"department {suggested.department_id} suggested from coding"]
            others = [d for d in batch if d is not out.draft]
            controls_runner.rerun(db, bill_id, batch=others)
            record(db, actor_user_id=SYSTEM_ACTOR, actor_role=SYSTEM_ACTOR, action=AuditAction.BILL_CREATED,
                   entity_type="bill", entity_id=bill_id,
                   after={"intake_item_id": item.item_id, "file_name": item.file_name, "email_id": job.email_id,
                          "started_by": started_by, "status": "needs_review", "department_id": bill.department_id,
                          "department_source": source, "warnings": item.warnings})
        elif bill_id is None:
            record(db, actor_user_id=SYSTEM_ACTOR, actor_role=SYSTEM_ACTOR, action="intake.item_failed",
                   entity_type="intake_item", entity_id=str(item.item_id),
                   after={"status": out.status, "error": out.error, "file_name": item.file_name,
                          "started_by": started_by})
        db.commit()
        return bill_id


# ---------------------------------------------------------------- submissions


def _check_file(filename: str) -> None:
    if Path(filename).suffix.lower() not in ALLOWED_EXTS:
        raise ApiError(415, "intake.unsupported_file", f"Allowed file types: {', '.join(sorted(ALLOWED_EXTS))}.")


def queue_submission(db: Session, user: CurrentUser, filename: str, department_id: str | None) -> tuple[int, Overrides]:
    """Record the submission (status queued) in the request's write transaction. Employees submit for their own
    department only, and become the bill's requester."""
    _check_file(filename)
    if user.role == EMPLOYEE:
        if department_id not in (None, user.department_id):
            raise ApiError(403, "intake.other_department", "You can only submit invoices for your own department.")
        overrides = Overrides(requester_user_id=user.user_id, department_id=user.department_id)
    else:
        if department_id is not None and db.get(models.Department, department_id) is None:
            raise ApiError(422, "intake.unknown_department", f"Department {department_id} doesn't exist.")
        overrides = Overrides(department_id=department_id)
    item = models.IntakeItem(email_id=None, file_name=Path(filename).name, file_hash=None, status="queued", error=None,
                             warnings=[], created_at=utcnow(), created_by=user.user_id)
    db.add(item)
    db.flush()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.INTAKE_ITEM_CREATED,
           entity_type="intake_item", entity_id=str(item.item_id),
           after={"file_name": item.file_name, "department_id": overrides.department_id})
    return item.item_id, overrides


def process_submission(bind: Engine, item_id: int, data: bytes, filename: str, started_by: str,
                       overrides: Overrides, extractor: Callable[..., ExtractionOutcome] | None = None) -> None:
    """Background task: read the file, then store the result."""
    _set_status(bind, [item_id], "processing")
    try:
        outcome = (extractor or extract_outcome)(data, Path(filename).name)
    except Exception as exc:  # a bad file must never leave the item stuck in processing
        outcome = ExtractionOutcome(Path(filename).name, "", "failed", error=f"{type(exc).__name__}: {exc}")
    batch = [outcome.draft] if outcome.draft else []
    store_outcome(bind, Extracted(item_id, outcome, overrides=overrides), started_by=started_by, batch=batch)


def _set_status(bind: Engine, item_ids: list[int], status: str) -> None:
    """Progress marker only (queued -> processing), not a business change, so it isn't audited."""
    with _write_session(bind) as db:
        for item_id in item_ids:
            db.get(models.IntakeItem, item_id).status = status
        db.commit()


# ---------------------------------------------------------------- inbox run


def untriaged_emails(db: Session) -> list[models.Email]:
    """Emails not triaged yet. A second run picks up only new mail, so it never creates the same bills twice."""
    return list(db.scalars(select(models.Email).where(models.Email.email_class.is_(None))
                           .order_by(models.Email.received_at, models.Email.email_id)))


def _email_dict(e: models.Email) -> dict:
    return {"email_id": e.email_id, "from_name": e.from_name, "from_address": e.from_address,
            "to_address": e.to_address, "subject": e.subject, "received_at": e.received_at.isoformat(),
            "body": e.body, "attachments": list(e.attachments or [])}


def triage_email(bind: Engine, email: dict, started_by: str,
                 classifier: Callable[[dict], object] | None = None) -> list[tuple[int, str]]:
    """Classify one email and store the triage plus a queued intake item per attachment to process (a missing
    attachment is stored as a failed item). Returns [(item_id, file_name)] for the files to extract."""
    triage = (classifier or classify)(email)
    folder = get_settings().dataset_dir / "incoming_invoices"
    with _write_session(bind) as db:
        row = db.get(models.Email, email["email_id"])
        row.email_class, row.triage_reason, row.triaged_at = triage.email_class.value, triage.reason, utcnow()
        queued: list[tuple[int, str]] = []
        for name in triage.attachments_to_process:
            present = (folder / name).is_file()
            item = models.IntakeItem(email_id=row.email_id, file_name=name, file_hash=None,
                                     status="queued" if present else "failed",
                                     error=None if present else "attachment not found", warnings=[],
                                     created_at=to_utc(utcnow()), created_by=started_by)
            db.add(item)
            db.flush()
            if present:
                queued.append((item.item_id, name))
        record(db, actor_user_id=SYSTEM_ACTOR, actor_role=SYSTEM_ACTOR, action=AuditAction.INTAKE_ITEM_CREATED,
               entity_type="email", entity_id=row.email_id,
               after={"email_class": row.email_class, "reason": triage.reason, "files": [n for _, n in queued],
                      "started_by": started_by})
        db.commit()
    return queued
