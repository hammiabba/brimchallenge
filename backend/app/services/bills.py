"""Bill reads: the scoped list and the one-screen detail (header, lines and coding, taxes, latest controls run with
flags and route, every approval decision, payments and the bill's audit history)."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.auth.deps import CurrentUser
from app.db import models
from app.services import approvals, audit, views
from app.services.money import cents
from app.services.pagination import paginate
from app.services.scope import get_bill_for, visible_bills

# Entity type for bills in the audit log (the DB layer's convention: entity_type="bill").
AUDIT_ENTITY = "bill"


def list_bills(db: Session, user: CurrentUser, *, status: list[str] | None, vendor_id: str | None,
               department_id: str | None, q: str | None, limit: int, offset: int) -> s.Page[s.BillSummary]:
    stmt = visible_bills(user)
    if status:
        stmt = stmt.where(models.Bill.status.in_(status))
    if vendor_id:
        stmt = stmt.where(models.Bill.vendor_id == vendor_id)
    if department_id:
        stmt = stmt.where(models.Bill.department_id == department_id)
    if q:
        like = f"%{q.strip()}%"
        vendor_match = select(models.Vendor.vendor_id).where(models.Vendor.legal_name.ilike(like))
        stmt = stmt.where(or_(models.Bill.bill_id.ilike(like), models.Bill.vendor_invoice_number.ilike(like),
                              models.Bill.vendor_id.in_(vendor_match)))
    stmt = stmt.order_by(models.Bill.received_date.desc(), models.Bill.bill_id.desc())
    rows, total = paginate(db, stmt, limit=limit, offset=offset)
    return s.Page[s.BillSummary](items=views.bill_summaries(db, rows), total=total, limit=limit, offset=offset)


def _latest_run_out(db: Session, bill_id: str) -> s.ControlsRunOut | None:
    run = approvals.latest_run(db, bill_id)
    if run is None:
        return None
    flags = db.scalars(select(models.BillFlag).where(models.BillFlag.run_id == run.run_id)
                       .order_by(models.BillFlag.id))
    decided = approvals.run_decisions(db, run.run_id)
    route = []
    for step in approvals.route_steps(db, run.run_id):
        d = decided.get(step.step_no)
        route.append(s.RouteStepOut(step_no=step.step_no, role=step.role, user_id=step.user_id,
                                    policy_ids=step.policy_ids or [], reason=step.reason,
                                    delegated_from=step.delegated_from, escalated_from=step.escalated_from,
                                    decision=d.decision if d else None, decided_by=d.actor_user_id if d else None,
                                    decided_at=d.acted_at if d else None))
    return s.ControlsRunOut(run_id=run.run_id, version=run.version, evaluated_at=run.evaluated_at,
                            can_auto_proceed=run.can_auto_proceed, recommendation=run.recommendation,
                            flags=[views.flag_out(f) for f in flags], route=route)


def bill_detail(db: Session, user: CurrentUser, bill_id: str) -> s.BillDetail:
    bill = get_bill_for(db, user, bill_id)
    summary = views.bill_summary(bill, views.vendor_names(db, {bill.vendor_id}).get(bill.vendor_id))
    lines = db.scalars(select(models.BillLine).where(models.BillLine.bill_id == bill.bill_id)
                       .order_by(models.BillLine.line_no))
    taxes = db.scalars(select(models.BillTax).where(models.BillTax.bill_id == bill.bill_id)
                       .order_by(models.BillTax.id))
    decisions = db.scalars(select(models.ApprovalDecision).where(models.ApprovalDecision.bill_id == bill.bill_id)
                           .order_by(models.ApprovalDecision.acted_at, models.ApprovalDecision.step_no))
    payments = list(db.scalars(select(models.Payment).where(models.Payment.bill_id == bill.bill_id)
                               .order_by(models.Payment.scheduled_date)))
    return s.BillDetail(
        **summary.model_dump(),
        subtotal=cents(bill.subtotal_cents), fx_rate_to_cad=bill.fx_rate_to_cad, fx_rate_date=bill.fx_rate_date,
        ship_to_province=bill.ship_to_province, po_id=bill.po_id, contract_id=bill.contract_id,
        source_email_id=bill.source_email_id, file_hash=bill.file_hash, created_at=bill.created_at,
        created_by=bill.created_by, updated_at=bill.updated_at, extracted=views.extracted_for(user.role, bill),
        lines=[views.line_out(ln) for ln in lines], taxes=[views.tax_out(t) for t in taxes],
        latest_run=_latest_run_out(db, bill.bill_id), decisions=[views.decision_out(d) for d in decisions],
        payments=views.payment_summaries(db, payments), audit=audit.entity_history(db, AUDIT_ENTITY, bill.bill_id))
