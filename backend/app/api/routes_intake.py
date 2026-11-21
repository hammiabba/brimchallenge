"""
Intake reads owned by Person A: one inbox email in full, and the original file behind a bill.

Owner: Person A. Thin wrappers around app/intake/review.py and app/intake/files.py. The inbox list
(GET /intake/emails), submissions and the inbox job are the API lane's (routes_intake_jobs.py).

Roles: the back office that reads intake (ap_clerk, finance_manager, controller_admin, auditor), the same as
GET /intake/emails and /intake/items. Employees and approvers are refused (403); an unknown id is 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS
from app.api.errors import not_found
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import BACK_OFFICE_READ
from app.db.database import get_session
from app.intake import files
from app.intake.review import EmailDetail, email_detail

router = APIRouter(prefix="/intake", tags=["intake"])


@router.get("/emails/{email_id}", response_model=EmailDetail, responses=READ_ERRORS)
def get_email(email_id: str, user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)),
              db: Session = Depends(get_session)) -> EmailDetail:
    """One inbox email: body, triage (class, reason), the suggested next step (with a ready reply or the payment
    answer where useful), and the intake items and bills made from it."""
    detail = email_detail(db, email_id)
    if detail is None:
        raise not_found("email", email_id)
    return detail


@router.get("/files/{file_hash}", responses={**READ_ERRORS, 200: {"content": {"application/pdf": {},
                                                                           "image/png": {}, "image/jpeg": {}}}})
def get_file(file_hash: str, user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)),
             db: Session = Depends(get_session)) -> Response:
    """The original invoice file (PDF or image), by the sha256 shown on the bill and the intake item."""
    found = files.load(db, file_hash)
    if found is None:
        raise not_found("file", file_hash)
    data, ctype, name = found
    inline = ctype != "application/octet-stream"
    safe = "".join(c for c in name if c.isalnum() or c in " ._-") or "file"
    return Response(data, media_type=ctype, headers={
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{safe}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})
