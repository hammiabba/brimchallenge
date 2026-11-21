"""
The background inbox run and its in-process status registry.

POST /intake/inbox/jobs records the start (audited) and returns 202 with a job id; the run happens in a background
task and the client polls GET /intake/inbox/jobs/{job_id}. One run at a time.

Phases of a run:
1. for each untriaged email: classify, store the triage and a queued intake item per file (one transaction each);
   then read each file (no lock held while the LLM works);
2. store every result: create the bill and run controls with the whole batch, so duplicates and splits inside the
   run are caught (one transaction per file);
3. record the finish.

Trade-off: job status lives in process memory, so a restart forgets running jobs (the intake items, bills and audit
events are all in the database and survive). At scale this becomes a jobs table and a worker queue.
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError, not_found
from app.auth.deps import CurrentUser
from app.config import get_settings
from app.db import models
from app.db.audit import SYSTEM_ACTOR, AuditAction
from app.db.types import utcnow
from app.extraction.pipeline import ExtractionOutcome, extract_outcome
from app.intake.classifier import classify
from app.services import intake
from app.services.events import record


@dataclass
class Job:
    job_id: str
    started_by: str
    started_at: datetime
    status: str = "queued"
    finished_at: datetime | None = None
    total_emails: int = 0
    processed_emails: int = 0
    item_ids: list[int] = field(default_factory=list)
    error: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _running() -> Job | None:
    return next((j for j in _jobs.values() if j.status in ("queued", "running")), None)


def start(db: Session, user: CurrentUser) -> Job:
    """Register a run and audit its start, in the request's write transaction (the route commits)."""
    with _lock:
        busy = _running()
        if busy is not None:
            raise ApiError(409, "intake.job_running", f"Inbox run {busy.job_id} is still going.",
                           {"job_id": busy.job_id})
        job = Job(job_id=uuid.uuid4().hex[:12], started_by=user.user_id, started_at=utcnow())
        job.total_emails = len(intake.untriaged_emails(db))
        _jobs[job.job_id] = job
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.INTAKE_RUN_STARTED,
           entity_type="intake_run", entity_id=job.job_id, after={"emails": job.total_emails})
    return job


def run(bind: Engine, job_id: str, *, classifier: Callable[[dict], object] | None = None,
        extractor: Callable[..., ExtractionOutcome] | None = None) -> None:
    # Looked up at call time (not as default arguments), so tests can swap in a fake reader.
    classifier, extractor = classifier or classify, extractor or extract_outcome
    job = _jobs[job_id]
    job.status = "running"
    try:
        with Session(bind) as db:
            emails = [intake._email_dict(e) for e in intake.untriaged_emails(db)]
        job.total_emails = len(emails)
        extracted: list[intake.Extracted] = []
        folder = get_settings().dataset_dir / "incoming_invoices"
        for email in emails:
            queued = intake.triage_email(bind, email, job.started_by, classifier)
            job.item_ids.extend(item_id for item_id, _ in queued)
            intake._set_status(bind, [i for i, _ in queued], "processing")
            for item_id, name in queued:
                try:
                    outcome = extractor((folder / name).read_bytes(), name, email_id=email["email_id"],
                                        sender=email.get("from_address"))
                except Exception as exc:  # one bad file must not stop the run
                    outcome = ExtractionOutcome(name, "", "failed", error=f"{type(exc).__name__}: {exc}")
                extracted.append(intake.Extracted(item_id, outcome, email_id=email["email_id"]))
            job.processed_emails += 1
        batch = [e.outcome.draft for e in extracted if e.outcome.draft is not None]
        for e in extracted:
            intake.store_outcome(bind, e, started_by=job.started_by, batch=batch)
        job.status = "done"
    except Exception as exc:
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = utcnow()
        _record_finish(bind, job)


def _record_finish(bind: Engine, job: Job) -> None:
    with intake._write_session(bind) as db:
        record(db, actor_user_id=SYSTEM_ACTOR, actor_role=SYSTEM_ACTOR, action=AuditAction.INTAKE_RUN_FINISHED,
               entity_type="intake_run", entity_id=job.job_id,
               after={"status": job.status, "emails": job.processed_emails, "files": len(job.item_ids),
                      "error": job.error, "started_by": job.started_by})
        db.commit()


def snapshot(job: Job, items: list[models.IntakeItem] | None = None) -> s.JobOut:
    return s.JobOut(job_id=job.job_id, status=job.status, started_by=job.started_by, started_at=job.started_at,
                    finished_at=job.finished_at, total_emails=job.total_emails,
                    processed_emails=job.processed_emails,
                    items=[s.IntakeItemOut.model_validate(i) for i in items or []], error=job.error)


def status(db: Session, job_id: str) -> s.JobOut:
    job = _jobs.get(job_id)
    if job is None:
        raise not_found("job", job_id)
    items = list(db.scalars(select(models.IntakeItem).where(models.IntakeItem.item_id.in_(job.item_ids))
                            .order_by(models.IntakeItem.item_id))) if job.item_ids else []
    return snapshot(job, items)


def reset_for_tests() -> None:
    with _lock:
        _jobs.clear()
