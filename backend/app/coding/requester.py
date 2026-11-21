"""
The requester's side of coding: who may be a requester, and the department their lines default to.

Owner: Person A. Called from app/services/bills.update_header (see docs/ISSUES_FOR_DB.md).
- requester_problem(db, user_id): a clerk can't make a terminated user (U015) the requester of a bill;
  history already has bills of theirs that need a new owner, so we don't add more.
- recode_for_requester(db, bill, changes): when the requester changes, each line still on our suggestion
  gets its department from the new requester (or back to the suggestion when the requester is cleared).
  Lines a clerk already accepted or overrode are left alone.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models

# Users in these states can't be made a requester (on_leave is fine: they still own their spend).
BLOCKED_STATUSES = ("terminated", "inactive")
_REQUESTER_SUFFIX = re.compile(r"; department \S+ from requester \S+(?: \(replaces \S+\))?$")


def requester_problem(db: Session, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(models.User, user_id)
    if user is None:
        return f"{user_id} doesn't exist."
    if user.status in BLOCKED_STATUSES:
        since = f" since {user.status_since}" if user.status_since else ""
        return f"{user_id} ({user.full_name}) is {user.status}{since} and can't be a requester."
    return None


def recode_for_requester(db: Session, bill: models.Bill, changes: dict) -> None:
    if "requester_user_id" not in changes:
        return
    requester = changes["requester_user_id"]
    dept = db.get(models.User, requester).department_id if requester else None
    original = {ln.get("line_no"): (ln.get("coding") or {}) for ln in (bill.draft_json or {}).get("lines", [])}
    lines = db.scalars(select(models.BillLine).where(models.BillLine.bill_id == bill.bill_id,
                                                    models.BillLine.coding_status == "suggested"))
    for line in lines:
        first = original.get(line.line_no, {})
        base_dept = first.get("department_id") or line.suggested_department_id
        base_reason = _REQUESTER_SUFFIX.sub("", first.get("reason") or line.suggestion_reason or "")
        if dept and dept != base_dept:
            line.suggested_department_id = dept
            line.suggestion_reason = (f"{base_reason}; department {dept} from requester {requester} "
                                      f"(replaces {base_dept})")
        else:
            line.suggested_department_id, line.suggestion_reason = base_dept, base_reason
