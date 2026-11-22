"""Early-payment discounts for the API: reads payments from the database in the dataset's CSV row shape and hands
them, with RefData built from the same database, to app.controls.early_pay. Read-only."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.controls.early_pay import OPEN_STATUSES, PENDING_STATUSES, discount_history, suggest_pay_dates
from app.db import models
from app.db.refdata_db import refdata_from_db
from app.db.types import from_cents
from app.services.controls_runner import open_blocking_codes


def _date(value) -> str:
    return value.isoformat() if value else ""


def payment_rows(db: Session) -> list[dict[str, str]]:
    return [{"payment_id": p.payment_id, "invoice_id": p.bill_id, "vendor_id": p.vendor_id, "method": p.method,
             "scheduled_date": _date(p.scheduled_date), "paid_date": _date(p.paid_date), "currency": p.currency,
             "amount": str(from_cents(p.amount_cents)), "fx_rate_to_cad": p.fx_rate_to_cad,
             "amount_cad": str(from_cents(p.amount_cad_cents)),
             "discount_taken": str(from_cents(p.discount_taken_cents)), "reference": p.reference or "",
             "status": p.status}
            for p in db.scalars(select(models.Payment).order_by(models.Payment.payment_id))]


def early_pay_report(db: Session, *, include_pending: bool = False) -> s.EarlyPayReport:
    """The pay-date suggestions (bills held by a blocking flag left out) and the discount history."""
    ref = refdata_from_db(db)
    payments = payment_rows(db)
    statuses = OPEN_STATUSES + (PENDING_STATUSES if include_pending else ())
    # A bill with an open blocking flag (a duplicate, a closed PO, an unverified bank change) is on hold: never advise
    # paying it now or early. Its flags say what to do instead, on the bill and in reconciliation.
    found = [x for x in suggest_pay_dates(ref, payments, statuses=statuses)
             if not open_blocking_codes(db, x.invoice_id)]
    history = discount_history(ref, payments)
    names = {vid: v["legal_name"] for vid, v in ref.vendors.items()}
    return s.EarlyPayReport(
        as_of=ref.as_of,
        summary=s.EarlyPaySummary(
            bills=len(found), with_discount_open=sum(1 for x in found if x.saving > 0),
            saving_cad=sum((x.saving_cad for x in found), Decimal("0")),
            to_reschedule=sum(1 for x in found if x.action == "reschedule"),
            pay_now=sum(1 for x in found if x.action == "pay_now")),
        suggestions=[s.EarlyPaySuggestionOut(
            bill_id=x.invoice_id, vendor_id=x.vendor_id, vendor_name=names.get(x.vendor_id), status=x.status,
            terms=x.terms.describe(), method=x.method, invoice_date=x.invoice_date, due_date=x.due_date,
            discount_deadline=x.discount_deadline, pay_on=x.pay_on, scheduled_date=x.scheduled_date,
            currency=x.currency, total=x.total, saving=x.saving, saving_cad=x.saving_cad, pay_amount=x.pay_amount,
            action=x.action, reason=x.reason, notes=x.notes) for x in found],
        history=s.EarlyPayHistory(
            taken=len(history.taken), taken_cad=history.taken_cad, missed=len(history.missed),
            missed_cad=history.missed_cad,
            missed_payments=[s.PastDiscountOut(payment_id=m.payment_id, bill_id=m.invoice_id, vendor_id=m.vendor_id,
                                               vendor_name=names.get(m.vendor_id),
                                               invoice_date=m.invoice_date, paid_date=m.paid_date,
                                               days_to_pay=m.days_to_pay, discount_cad=m.discount_cad)
                             for m in history.missed]),
    )
