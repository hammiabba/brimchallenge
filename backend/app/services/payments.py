"""Payment reads: list, dashboard and the audit-ready trace (payment -> bill, coding, approval chain, the bank
account version it went to, and the audit events). Writes (schedule, release, cancel) arrive with log_event."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import not_found
from app.config import get_settings
from app.db import models
from app.services import audit, views
from app.services.money import cents
from app.services.pagination import paginate

OPEN_STATUSES = ("scheduled", "outstanding")


def list_payments(db: Session, *, status: list[str] | None, vendor_id: str | None, limit: int,
                  offset: int) -> s.Page[s.PaymentSummary]:
    stmt = select(models.Payment)
    if status:
        stmt = stmt.where(models.Payment.status.in_(status))
    if vendor_id:
        stmt = stmt.where(models.Payment.vendor_id == vendor_id)
    stmt = stmt.order_by(models.Payment.scheduled_date.desc(), models.Payment.payment_id.desc())
    rows, total = paginate(db, stmt, limit=limit, offset=offset)
    return s.Page[s.PaymentSummary](items=views.payment_summaries(db, rows), total=total, limit=limit, offset=offset)


def dashboard(db: Session) -> s.PaymentDashboard:
    as_of = get_settings().as_of_date
    by_status = [s.StatusTotal(status=st, count=n, total_cad=cents(int(total or 0)))
                 for st, n, total in db.execute(
                     select(models.Payment.status, func.count(), func.sum(models.Payment.amount_cad_cents))
                     .group_by(models.Payment.status).order_by(models.Payment.status))]

    def count_sum(*where) -> tuple[int, Decimal]:
        n, total = db.execute(select(func.count(), func.sum(models.Payment.amount_cad_cents)).where(*where)).one()
        return n, cents(int(total or 0))

    due_n, due_cad = count_sum(models.Payment.status.in_(OPEN_STATUSES),
                               models.Payment.scheduled_date >= as_of,
                               models.Payment.scheduled_date <= as_of + timedelta(days=7))
    overdue_n, overdue_cad = count_sum(models.Payment.status.in_(OPEN_STATUSES),
                                       models.Payment.scheduled_date < as_of)
    return s.PaymentDashboard(as_of=as_of, by_status=by_status, due_next_7_days_count=due_n,
                              due_next_7_days_cad=due_cad, overdue_count=overdue_n, overdue_cad=overdue_cad)


def _account_paid_to(db: Session, p: models.Payment) -> models.VendorBankAccount | None:
    """The bank account version the payment went to: recorded on app payments; for history, the vendor account
    that was valid on the payment (or scheduled) date."""
    if p.bank_account_id is not None:
        return db.get(models.VendorBankAccount, p.bank_account_id)
    on = p.paid_date or p.scheduled_date
    return db.scalars(select(models.VendorBankAccount).where(
        models.VendorBankAccount.vendor_id == p.vendor_id, models.VendorBankAccount.valid_from <= on,
        or_(models.VendorBankAccount.valid_to.is_(None), models.VendorBankAccount.valid_to >= on))
        .order_by(models.VendorBankAccount.valid_from.desc()).limit(1)).first()


def payment_detail(db: Session, role: str, payment_id: str) -> s.PaymentDetail:
    p = db.get(models.Payment, payment_id)
    if p is None:
        raise not_found("payment", payment_id)
    bill = db.get(models.Bill, p.bill_id)
    names = views.vendor_names(db, {p.vendor_id, bill.vendor_id})
    lines = db.scalars(select(models.BillLine).where(models.BillLine.bill_id == bill.bill_id)
                       .order_by(models.BillLine.line_no))
    decisions = db.scalars(select(models.ApprovalDecision).where(models.ApprovalDecision.bill_id == bill.bill_id)
                           .order_by(models.ApprovalDecision.acted_at))
    events = audit.entity_history(db, "payment", p.payment_id) + audit.entity_history(db, "bill", bill.bill_id)
    summary = views.payment_summary(p, names.get(p.vendor_id))
    return s.PaymentDetail(
        **summary.model_dump(), fx_rate_to_cad=p.fx_rate_to_cad, fx_rate_date=p.fx_rate_date,
        discount_taken=cents(p.discount_taken_cents),
        bank_account=views.bank_account_out(role, _account_paid_to(db, p)),
        bill=views.bill_summary(bill, names.get(bill.vendor_id)), lines=[views.line_out(ln) for ln in lines],
        decisions=[views.decision_out(d) for d in decisions], audit=sorted(events, key=lambda e: e.seq))
