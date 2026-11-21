"""Employee/clerk submissions, the background inbox run and intake items.

The inbox run makes LLM calls per file, so it runs as a background job: POST returns 202 with a job id at once and
the client polls GET /intake/inbox/jobs/{job_id}.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS, WRITE_ERRORS, Limit, Offset
from app.api.schemas_api import IntakeItemOut, JobOut, Page
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AP_CLERK, BACK_OFFICE_READ, EMPLOYEE
from app.db import models
from app.db.database import get_session, get_write_session
from app.services import intake, jobs

router = APIRouter(tags=["intake"])


@router.post("/submissions", response_model=IntakeItemOut, status_code=202, responses=WRITE_ERRORS)
def submit_file(background: BackgroundTasks, file: UploadFile = File(...), department_id: str | None = Form(None),
                user: CurrentUser = Depends(require_role(EMPLOYEE, AP_CLERK)),
                db: Session = Depends(get_write_session)):
    """Upload one invoice (PDF or image). Returns 202 with the queued item; poll GET /submissions for the result."""
    filename = file.filename or "upload"
    item_id, overrides = intake.queue_submission(db, user, filename, department_id)
    data = file.file.read()
    out = IntakeItemOut.model_validate(db.get(models.IntakeItem, item_id))
    bind = db.get_bind()
    db.commit()
    # Release the write session now: the background task opens its own write transactions, and SQLite has one
    # writer at a time, so nothing on this session may start a new transaction after the commit.
    db.close()
    background.add_task(intake.process_submission, bind, item_id, data, filename, user.user_id, overrides)
    return out


@router.get("/submissions", response_model=list[IntakeItemOut], responses=READ_ERRORS)
def my_submissions(user: CurrentUser = Depends(require_role(EMPLOYEE, AP_CLERK)),
                   db: Session = Depends(get_session)):
    return intake.my_submissions(db, user)


@router.post("/intake/inbox/jobs", response_model=JobOut, status_code=202, responses=WRITE_ERRORS)
def start_inbox_job(background: BackgroundTasks, user: CurrentUser = Depends(require_role(AP_CLERK)),
                    db: Session = Depends(get_write_session)):
    """Start processing the AP inbox in the background. Returns 202 at once; poll the job for progress."""
    job = jobs.start(db, user)
    out = jobs.snapshot(job)
    bind = db.get_bind()
    db.commit()
    db.close()  # see submit_file: the background run needs the write lock
    background.add_task(jobs.run, bind, job.job_id)
    return out


@router.get("/intake/inbox/jobs/{job_id}", response_model=JobOut, responses=READ_ERRORS)
def inbox_job_status(job_id: str, user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)),
                     db: Session = Depends(get_session)):
    return jobs.status(db, job_id)


@router.get("/intake/items", response_model=Page[IntakeItemOut], responses=READ_ERRORS)
def intake_items(user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)), status: str | None = None,
                 email_id: str | None = None, limit: Limit = 50, offset: Offset = 0,
                 db: Session = Depends(get_session)):
    return intake.list_items(db, status=status, email_id=email_id, limit=limit, offset=offset)
