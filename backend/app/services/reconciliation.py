"""Bank reconciliation for the API: reads the statement lines and payments from the database, in the dataset's CSV
row shape, and hands them to app.controls.reconciliation.reconcile() with RefData built from the same database.
Read-only."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.controls.reconciliation import Issue, reconcile
from app.db import models
from app.db.refdata_db import refdata_from_db
from app.db.types import from_cents


def _money(cents: int | None) -> str:
    return "" if cents is None else str(from_cents(cents))


def _date(value) -> str:
    return value.isoformat() if value else ""


def bank_rows(db: Session) -> list[dict[str, str]]:
    return [{"bank_txn_id": b.bank_txn_id, "posted_date": _date(b.posted_date), "description": b.description,
             "debit": _money(b.debit_cad_cents), "credit": _money(b.credit_cad_cents)}
            for b in db.scalars(select(models.BankStatementLine).order_by(models.BankStatementLine.bank_txn_id))]


def payment_rows(db: Session) -> list[dict[str, str]]:
    return [{"payment_id": p.payment_id, "invoice_id": p.bill_id, "vendor_id": p.vendor_id, "method": p.method,
             "scheduled_date": _date(p.scheduled_date), "paid_date": _date(p.paid_date), "currency": p.currency,
             "amount": _money(p.amount_cents), "fx_rate_to_cad": p.fx_rate_to_cad,
             "amount_cad": _money(p.amount_cad_cents), "reference": p.reference or "", "status": p.status,
             "prepared_by": p.prepared_by or "", "released_by": p.released_by or ""}
            for p in db.scalars(select(models.Payment).order_by(models.Payment.payment_id))]


def _issues(issues: list[Issue]) -> list[s.ReconIssueOut]:
    return [s.ReconIssueOut(code=i.code, severity=i.severity, message=i.message) for i in issues]


def bank_reconciliation(db: Session, *, only_issues: bool = False) -> s.BankReconciliation:
    r = reconcile(bank_rows(db), payment_rows(db), refdata_from_db(db))

    def keep(x) -> bool:
        return not only_issues or any(i.severity == "review" for i in x.issues)

    return s.BankReconciliation(
        statement_from=r.statement_from, statement_to=r.statement_to,
        summary=s.ReconSummaryOut(**r.summary()),
        lines=[s.ReconLineOut(bank_txn_id=ln.bank_txn_id, posted_date=ln.posted_date, description=ln.description,
                              amount=ln.amount, status=ln.status, payment_ids=ln.payment_ids,
                              bill_ids=ln.invoice_ids, vendor_id=ln.vendor_id, difference=ln.difference,
                              issues=_issues(ln.issues)) for ln in r.lines if keep(ln)],
        payments=[s.ReconPaymentOut(payment_id=p.payment_id, bill_id=p.invoice_id, vendor_id=p.vendor_id,
                                    method=p.method, status=p.status, amount_cad=p.amount_cad, on_date=p.date,
                                    bank_txn_id=p.bank_txn_id, issues=_issues(p.issues))
                  for p in r.payments if keep(p)],
        double_payments=[s.ReconDoublePaymentOut(
            bill_ids=g.invoice_ids, card_txn_ids=g.card_txn_ids, payment_ids=g.payment_ids,
            bank_txn_ids=g.bank_txn_ids, extra_payment_ids=g.extra_payment_ids,
            at_risk_payment_ids=g.at_risk_payment_ids, confirmed=g.confirmed, extra_paid_cad=g.extra_paid_cad,
            at_risk_cad=g.at_risk_cad, message=g.message) for g in r.double_payments],
    )
