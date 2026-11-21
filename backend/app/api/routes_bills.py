"""Bills: list, detail, edits, flags, submit, approve/reject, step assignment, void, and the approval queue.

Routes check the role (require_role) and delegate everything else to app/services, which applies object scope
(404 outside it), state transitions, controls permissions and the audit event.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS, WRITE_ERRORS, Limit, Offset
from app.api.errors import not_implemented
from app.api.schemas_api import (
    AssignIn,
    BillDetail,
    BillHeaderPatch,
    BillStatus,
    BillSummary,
    DecisionIn,
    FlagResolveIn,
    LineCodingPatch,
    Page,
    RejectIn,
    RowVersionIn,
    VoidIn,
)
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import ALL_ROLES, AP_CLERK, CONTROLLER_ADMIN, FINANCE_MANAGER, SIGNERS
from app.db.database import get_session
from app.services import approvals, bills, views

router = APIRouter(tags=["bills"])


@router.get("/bills", response_model=Page[BillSummary], responses=READ_ERRORS)
def list_bills(user: CurrentUser = Depends(require_role(*ALL_ROLES)),
               status: Annotated[list[BillStatus] | None, Query()] = None,
               vendor_id: str | None = None, department_id: str | None = None,
               q: Annotated[str | None, Query(max_length=100)] = None,
               limit: Limit = 50, offset: Offset = 0, db: Session = Depends(get_session)):
    return bills.list_bills(db, user, status=status, vendor_id=vendor_id, department_id=department_id, q=q,
                            limit=limit, offset=offset)


@router.get("/bills/{bill_id}", response_model=BillDetail, responses=READ_ERRORS)
def get_bill(bill_id: str, user: CurrentUser = Depends(require_role(*ALL_ROLES)),
             db: Session = Depends(get_session)):
    return bills.bill_detail(db, user, bill_id)


@router.patch("/bills/{bill_id}", response_model=BillDetail, responses=WRITE_ERRORS)
def update_bill_header(bill_id: str, body: BillHeaderPatch, user: CurrentUser = Depends(require_role(AP_CLERK))):
    raise not_implemented("Bill header edit")


@router.patch("/bills/{bill_id}/lines/{line_no}", response_model=BillDetail, responses=WRITE_ERRORS)
def code_line(bill_id: str, line_no: int, body: LineCodingPatch,
              user: CurrentUser = Depends(require_role(AP_CLERK))):
    raise not_implemented("Line coding")


@router.post("/bills/{bill_id}/flags/{flag_id}/resolve", response_model=BillDetail, responses=WRITE_ERRORS)
def resolve_flag(bill_id: str, flag_id: int, body: FlagResolveIn,
                 user: CurrentUser = Depends(require_role(AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN))):
    raise not_implemented("Flag resolution")


@router.post("/bills/{bill_id}/submit", response_model=BillDetail, responses=WRITE_ERRORS)
def submit_bill(bill_id: str, body: RowVersionIn, user: CurrentUser = Depends(require_role(AP_CLERK))):
    raise not_implemented("Submit for approval")


@router.post("/bills/{bill_id}/approve", response_model=BillDetail, responses=WRITE_ERRORS)
def approve_bill(bill_id: str, body: DecisionIn, user: CurrentUser = Depends(require_role(*SIGNERS))):
    raise not_implemented("Approve")


@router.post("/bills/{bill_id}/reject", response_model=BillDetail, responses=WRITE_ERRORS)
def reject_bill(bill_id: str, body: RejectIn, user: CurrentUser = Depends(require_role(*SIGNERS))):
    raise not_implemented("Reject")


@router.post("/bills/{bill_id}/route/{step_no}/assign", response_model=BillDetail, responses=WRITE_ERRORS)
def assign_step(bill_id: str, step_no: int, body: AssignIn,
                user: CurrentUser = Depends(require_role(FINANCE_MANAGER, CONTROLLER_ADMIN))):
    raise not_implemented("Approver assignment")


@router.post("/bills/{bill_id}/void", response_model=BillDetail, responses=WRITE_ERRORS)
def void_bill(bill_id: str, body: VoidIn, user: CurrentUser = Depends(require_role(AP_CLERK, CONTROLLER_ADMIN))):
    raise not_implemented("Void")


@router.get("/approvals/queue", response_model=list[BillSummary], responses=READ_ERRORS)
def approval_queue(user: CurrentUser = Depends(require_role(*SIGNERS)), db: Session = Depends(get_session)):
    return views.bill_summaries(db, approvals.queue(db, user))
