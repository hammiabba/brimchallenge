"""Approvals: the current step of a bill, the signed-in user's queue, and approve / reject / assign.

The current step is derived here from the stored route and decisions. The DB layer is adding next_pending_step and
is_approval_complete; these functions switch to them when they land.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError, not_found
from app.auth.deps import CurrentUser
from app.controls.approvals import STEP_ROLES, can_approve
from app.db import models
from app.db.audit import AuditAction
from app.db.bills import latest_controls_run, load_draft_bill, route_for_bill
from app.db.types import utcnow
from app.services import controls_runner
from app.services.events import record
from app.services.guards import check_row_version, invalid_state, next_id
from app.services.scope import get_bill_for


def latest_run(db: Session, bill_id: str) -> models.ControlsRun | None:
    return db.scalars(select(models.ControlsRun).where(models.ControlsRun.bill_id == bill_id)
                      .order_by(models.ControlsRun.version.desc()).limit(1)).first()


def route_steps(db: Session, run_id: int) -> list[models.ApprovalRouteStep]:
    return list(db.scalars(select(models.ApprovalRouteStep).where(models.ApprovalRouteStep.run_id == run_id)
                           .order_by(models.ApprovalRouteStep.step_no)))


def run_decisions(db: Session, run_id: int) -> dict[int, models.ApprovalDecision]:
    """Latest decision per step of a run."""
    rows = db.scalars(select(models.ApprovalDecision).where(models.ApprovalDecision.run_id == run_id)
                      .order_by(models.ApprovalDecision.acted_at))
    return {d.step_no: d for d in rows}


def current_step(db: Session, bill_id: str) -> models.ApprovalRouteStep | None:
    """The lowest step of the latest controls run that has no approval yet, or None if fully approved/unrouted."""
    run = latest_run(db, bill_id)
    if run is None:
        return None
    decided = run_decisions(db, run.run_id)
    for step in route_steps(db, run.run_id):
        d = decided.get(step.step_no)
        if d is None or d.decision != "approved":
            return step
    return None


def queue(db: Session, user: CurrentUser) -> list[models.Bill]:
    """Pending bills whose current step is assigned to `user` (the delegate is already the assignee, P08)."""
    candidate_ids = db.scalars(
        select(models.ApprovalRouteStep.bill_id)
        .join(models.Bill, models.Bill.bill_id == models.ApprovalRouteStep.bill_id)
        .where(models.Bill.status == "pending_approval", models.ApprovalRouteStep.user_id == user.user_id)
        .group_by(models.ApprovalRouteStep.bill_id)
    ).all()
    mine = []
    for bill_id in candidate_ids:
        step = current_step(db, bill_id)
        if step is not None and step.user_id == user.user_id:
            mine.append(bill_id)
    if not mine:
        return []
    return list(db.scalars(select(models.Bill).where(models.Bill.bill_id.in_(mine))
                           .order_by(func.coalesce(models.Bill.due_date, models.Bill.invoice_date))))


# ---------------------------------------------------------------- writes

def _next_decision_id(db: Session) -> str:
    return next_id(db, models.ApprovalDecision.decision_id, "AP-A-", 5)


def decision_check(db: Session, user: CurrentUser, bill: models.Bill):
    """Everything that decides whether `user` may approve or reject `bill` right now, without writing anything.
    Raises ApiError with the reason; returns (step_row, step, route). Used by the write and by allowed_actions.

    The permission itself is controls.can_approve (P07 self-approval, assignee, step role, the final signer's limit,
    P08 delegation), fed only from stored data: the stored route, the bill rebuilt from the database and RefData
    from the database."""
    if bill.status != "pending_approval":
        raise invalid_state("bill", bill.status, "pending_approval")
    step_row = current_step(db, bill.bill_id)
    if step_row is None:
        raise ApiError(409, "bill.no_pending_step", "This bill has no approval step waiting.")
    route = route_for_bill(db, bill.bill_id)
    step = next((st for st in route if st.step_no == step_row.step_no), None)
    if step is None:
        raise ApiError(409, "bill.route_mismatch", "The stored route doesn't match its steps. Re-run controls.")
    if step_row.user_id and step.user_id != step_row.user_id:
        step = step.model_copy(update={"user_id": step_row.user_id})  # a manually assigned approver
    already_signed = db.scalar(select(func.count()).select_from(models.ApprovalDecision).where(
        models.ApprovalDecision.bill_id == bill.bill_id, models.ApprovalDecision.decision == "approved",
        models.ApprovalDecision.actor_user_id == user.user_id, models.ApprovalDecision.run_id == step_row.run_id))
    if already_signed:
        raise ApiError(403, "approval.already_signed", "You already approved an earlier step of this bill.")
    stored = latest_controls_run(db, bill.bill_id)
    ref = controls_runner.refdata_for(db, bill.bill_id)
    permission = can_approve(user.user_id, step, load_draft_bill(db, bill.bill_id), ref, route=route,
                             amount_cad=controls_runner.routed_amount(stored))
    if not permission.allowed:
        raise ApiError(403, "approval.not_allowed", permission.reason)
    return step_row, step, route


def _decide(db: Session, user: CurrentUser, bill_id: str, row_version: int, decision: str,
            comment: str | None) -> tuple[models.Bill, models.ApprovalRouteStep, bool]:
    bill = get_bill_for(db, user, bill_id)
    check_row_version(bill.row_version, row_version, "bill")
    step_row, step, route = decision_check(db, user, bill)
    db.add(models.ApprovalDecision(
        decision_id=_next_decision_id(db), bill_id=bill_id, step_no=step.step_no, run_id=step_row.run_id,
        actor_user_id=user.user_id, actor_role=user.role, step_role=step.role, on_behalf_of=step.delegated_from,
        decision=decision, comment=comment, acted_at=utcnow(), origin="app"))
    last = step.step_no == max(st.step_no for st in route)
    return bill, step_row, last


def approve(db: Session, user: CurrentUser, bill_id: str, body: s.DecisionIn) -> None:
    bill, step, last = _decide(db, user, bill_id, body.row_version, "approved", body.comment)
    before = bill.status
    if last:
        bill.status = "approved"
    bill.updated_at = utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_APPROVED,
           entity_type="bill", entity_id=bill_id, on_behalf_of=step.delegated_from, comment=body.comment,
           before={"status": before, "step_no": step.step_no},
           after={"status": bill.status, "step_no": step.step_no, "step_role": step.role, "final": last})


def reject(db: Session, user: CurrentUser, bill_id: str, body: s.RejectIn) -> None:
    bill, step, _ = _decide(db, user, bill_id, body.row_version, "rejected", body.comment)
    bill.status, bill.updated_at = "rejected", utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_REJECTED,
           entity_type="bill", entity_id=bill_id, on_behalf_of=step.delegated_from, comment=body.comment,
           before={"status": "pending_approval", "step_no": step.step_no},
           after={"status": "rejected", "step_no": step.step_no})


def assign_step(db: Session, user: CurrentUser, bill_id: str, step_no: int, body: s.AssignIn) -> None:
    """Fill a step routing left UNASSIGNED (nobody eligible). The new assignee must hold a role that may sign
    that kind of step; can_approve still checks everything else (limit, self-approval) when they act."""
    bill = get_bill_for(db, user, bill_id)
    check_row_version(bill.row_version, body.row_version, "bill")
    if bill.status not in ("needs_review", "on_hold", "pending_approval"):
        raise invalid_state("bill", bill.status, ("needs_review", "on_hold", "pending_approval"))
    run = latest_run(db, bill_id)
    step = db.get(models.ApprovalRouteStep, (run.run_id, step_no)) if run else None
    if step is None:
        raise not_found("route_step", f"{bill_id}/{step_no}")
    if step.user_id is not None:
        raise ApiError(409, "route_step.already_assigned", f"Step {step_no} is already assigned to {step.user_id}.")
    assignee = db.get(models.User, body.user_id)
    if assignee is None or assignee.status != "active" or assignee.role not in STEP_ROLES.get(step.role, ()):
        raise ApiError(422, "route_step.bad_assignee",
                       f"{body.user_id} must be an active user whose role can sign a {step.role} step.")
    step.user_id = body.user_id
    bill.updated_at = utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action="bill.step_assigned", entity_type="bill",
           entity_id=bill_id, before={"step_no": step_no, "user_id": None},
           after={"step_no": step_no, "user_id": body.user_id})
