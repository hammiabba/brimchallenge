"""Approval reads: the current step of a bill and the signed-in user's queue.

Write functions (approve, reject, assign) arrive with the DB adapters: they need log_event and RefData from the
database to call controls.can_approve.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser
from app.db import models


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
