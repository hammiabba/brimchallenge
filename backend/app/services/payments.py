"""Payments: list, dashboard and the audit-ready trace (payment -> bill, coding, approval chain, the bank account
version it went to, and the audit events), plus schedule, idempotent release and cancel."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError, not_found
from app.auth.deps import CurrentUser
from app.config import get_settings
from app.controls.approvals import can_release
from app.controls.refdata import bill_from_history
from app.db import models
from app.db.audit import AuditAction
from app.db.bills import approver_ids_for_bill, latest_controls_run, load_draft_bill
from app.db.refdata_db import refdata_from_db
from app.db.types import from_cents, utcnow
from app.services import audit, controls_runner, vendors, views
from app.services.events import record
from app.services.guards import invalid_state, next_id
from app.services.money import cents
from app.services.pagination import paginate
from app.services.scope import get_bill_for

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


def payment_detail(db: Session, user: CurrentUser, payment_id: str) -> s.PaymentDetail:
    from app.services.actions import payment_actions  # actions builds on this module's checks

    role = user.role
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
        decisions=[views.decision_out(d) for d in decisions], audit=sorted(events, key=lambda e: e.seq),
        allowed_actions=payment_actions(db, user, p))


# ---------------------------------------------------------------- writes

OPEN_PAYMENT = ("scheduled", "released")


def _payment(db: Session, payment_id: str) -> models.Payment:
    p = db.get(models.Payment, payment_id)
    if p is None:
        raise not_found("payment", payment_id)
    return p


def schedule_check(db: Session, bill: models.Bill, method: str = "EFT"):
    """Whether this bill can be scheduled for payment now, without writing. Raises ApiError with the reason;
    returns (vendor, open bank account)."""
    if bill.status != "approved":
        raise invalid_state("bill", bill.status, "approved")
    if bill.is_credit_note or bill.total_cents <= 0:
        raise ApiError(409, "payment.credit_note", "A credit note is applied against an open invoice, not paid.")
    vendor = db.get(models.Vendor, bill.vendor_id) if bill.vendor_id else None
    if vendor is None or vendor.status != "active":
        raise ApiError(409, "payment.vendor_not_active", "The vendor must be in the master and active to be paid.")
    pending = db.scalars(select(models.BankChangeRequest.change_id).where(
        models.BankChangeRequest.vendor_id == vendor.vendor_id,
        models.BankChangeRequest.status == "pending_verification")).first()
    if pending:
        raise ApiError(409, "payment.bank_change_pending",
                       f"Bank change {pending} for this vendor isn't verified yet.", {"change_id": pending})
    account = vendors.open_account(db, vendor.vendor_id)
    if method == "EFT" and account is None:
        raise ApiError(409, "payment.no_bank_account", "The vendor has no bank account on file for EFT.")
    existing = db.scalars(select(models.Payment.payment_id).where(models.Payment.bill_id == bill.bill_id,
                                                                  models.Payment.status.in_(OPEN_PAYMENT))).first()
    if existing:
        raise ApiError(409, "payment.already_exists", f"Payment {existing} already covers this bill.",
                       {"payment_id": existing})
    return vendor, account


def schedule(db: Session, user: CurrentUser, bill_id: str, body: s.ScheduleIn) -> str:
    """An AP clerk prepares the payment of an approved bill. Records which bank account version it will go to, so
    a bank change after scheduling is caught at release."""
    bill = get_bill_for(db, user, bill_id)
    as_of = get_settings().as_of_date
    if body.scheduled_date < as_of:
        raise ApiError(422, "payment.date_in_past", f"Schedule on or after {as_of.isoformat()}.")
    vendor, account = schedule_check(db, bill, body.method)
    payment = models.Payment(
        payment_id=next_id(db, models.Payment.payment_id, "PAY-", 5), bill_id=bill_id, vendor_id=vendor.vendor_id,
        method=body.method, currency=bill.currency, amount_cents=bill.total_cents, fx_rate_to_cad=bill.fx_rate_to_cad,
        fx_rate_date=bill.fx_rate_date, amount_cad_cents=bill.total_cad_cents, scheduled_date=body.scheduled_date,
        status="scheduled", prepared_by=user.user_id,
        bank_account_id=account.id if (account and body.method == "EFT") else None, origin="app")
    db.add(payment)
    bill.status, bill.updated_at = "scheduled", utcnow()
    db.flush()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.PAYMENT_SCHEDULED,
           entity_type="payment", entity_id=payment.payment_id,
           after={"bill_id": bill_id, "amount": from_cents(bill.total_cents), "currency": bill.currency,
                  "scheduled_date": body.scheduled_date, "method": body.method,
                  "bank_account_id": payment.bank_account_id})
    return payment.payment_id


def _draft_and_ref(db: Session, bill: models.Bill):
    """The DraftBill and RefData controls need. App bills are rebuilt by the DB layer (RefData excludes the bill
    itself); history bills are built by controls from RefData, so there the bill must stay in."""
    if bill.origin == "history":
        ref = refdata_from_db(db)
        return bill_from_history(ref, bill.bill_id), ref
    ref = controls_runner.refdata_for(db, bill.bill_id)
    return load_draft_bill(db, bill.bill_id), ref


def release_check(db: Session, user: CurrentUser, p: models.Payment):
    """Whether `user` may release this payment now, without writing. Raises ApiError with the reason; returns
    (permission, bill). Used by the release and by allowed_actions."""
    if p.status != "scheduled":
        raise invalid_state("payment", p.status, "scheduled")
    if p.prepared_by == user.user_id:
        raise ApiError(403, "payment.preparer_cannot_release",
                       "You prepared this payment, so someone else releases it.")
    if p.bank_account_id is not None:
        current = vendors.open_account(db, p.vendor_id)
        if current is None or current.id != p.bank_account_id:
            raise ApiError(409, "payment.bank_account_changed",
                           "The vendor's bank account changed after this payment was scheduled. Cancel and reschedule.")
    bill = db.get(models.Bill, p.bill_id)
    draft, ref = _draft_and_ref(db, bill)
    permission = can_release(user.user_id, from_cents(p.amount_cad_cents), approver_ids_for_bill(db, bill.bill_id),
                             controls_runner.open_flags(latest_controls_run(db, bill.bill_id)),
                             bill.status in ("approved", "scheduled"), ref, bill=draft)
    if not permission.allowed:
        raise ApiError(403, "payment.release_refused", permission.reason)
    return permission, bill


def release(db: Session, user: CurrentUser, payment_id: str, idempotency_key: str) -> tuple[str, bool]:
    """Release a scheduled payment (simulated EFT). Returns (payment_id, replayed).

    Idempotency: the key is stored on the payment. The same key for the same payment returns the stored result and
    changes nothing; a key already used for a different payment is refused. The write lock makes check-then-set
    safe, and the UNIQUE index on idempotency_key backs it up.

    Permission is controls.can_release, fed only from stored data: approvers from approval_decisions (never the
    request), only the flags still open in the latest stored run, approval completeness from the bill's status
    (a bill reaches approved only through its final approval step).
    """
    used = db.scalars(select(models.Payment).where(models.Payment.idempotency_key == idempotency_key)).first()
    if used is not None:
        if used.payment_id != payment_id:
            raise ApiError(409, "payment.idempotency_key_reused", "This Idempotency-Key was used for another payment.")
        return payment_id, True
    p = _payment(db, payment_id)
    permission, bill = release_check(db, user, p)
    as_of = get_settings().as_of_date
    p.status, p.released_by, p.released_at = "released", user.user_id, utcnow()
    p.paid_date, p.idempotency_key = as_of, idempotency_key
    p.reference = p.reference or f"EFT-SIM-{p.payment_id}"
    bill.status, bill.updated_at = "paid", utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.PAYMENT_RELEASED,
           entity_type="payment", entity_id=payment_id, before={"status": "scheduled"},
           after={"status": "released", "bill_id": bill.bill_id, "amount_cad": from_cents(p.amount_cad_cents),
                  "reference": p.reference, "rule": permission.reason})
    return payment_id, False


def cancel(db: Session, user: CurrentUser, payment_id: str, comment: str | None) -> None:
    p = _payment(db, payment_id)
    if p.status != "scheduled":
        raise invalid_state("payment", p.status, "scheduled")
    p.status = "cancelled"
    bill = db.get(models.Bill, p.bill_id)
    if bill.status == "scheduled":
        bill.status, bill.updated_at = "approved", utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.PAYMENT_CANCELLED,
           entity_type="payment", entity_id=payment_id, before={"status": "scheduled"},
           after={"status": "cancelled", "bill_status": bill.status}, comment=comment)
