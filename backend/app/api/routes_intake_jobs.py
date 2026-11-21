"""Employee/clerk submissions, the background inbox run and intake items.

The inbox run makes LLM calls per file, so it runs as a background job: POST returns 202 with a job id at once and
the client polls GET /intake/inbox/jobs/{job_id}.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.common import READ_ERRORS, WRITE_ERRORS, Limit, Offset
from app.api.errors import not_implemented
from app.api.schemas_api import IntakeItemOut, JobOut, Page
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AP_CLERK, BACK_OFFICE_READ, EMPLOYEE

router = APIRouter(tags=["intake"])


@router.post("/submissions", response_model=IntakeItemOut, status_code=202, responses=WRITE_ERRORS)
def submit_file(file: UploadFile = File(...), department_id: str | None = Form(None),
                user: CurrentUser = Depends(require_role(EMPLOYEE, AP_CLERK))):
    raise not_implemented("Submission")


@router.get("/submissions", response_model=list[IntakeItemOut], responses=READ_ERRORS)
def my_submissions(user: CurrentUser = Depends(require_role(EMPLOYEE, AP_CLERK))):
    raise not_implemented("My submissions")


@router.post("/intake/inbox/jobs", response_model=JobOut, status_code=202, responses=WRITE_ERRORS)
def start_inbox_job(user: CurrentUser = Depends(require_role(AP_CLERK))):
    raise not_implemented("Inbox job")


@router.get("/intake/inbox/jobs/{job_id}", response_model=JobOut, responses=READ_ERRORS)
def inbox_job_status(job_id: str, user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ))):
    raise not_implemented("Inbox job status")


@router.get("/intake/items", response_model=Page[IntakeItemOut], responses=READ_ERRORS)
def intake_items(user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)), status: str | None = None,
                 email_id: str | None = None, limit: Limit = 50, offset: Offset = 0):
    raise not_implemented("Intake items")
