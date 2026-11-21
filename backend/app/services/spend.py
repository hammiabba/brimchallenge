"""Spend analytics over committed bills (approved, scheduled, paid; credit notes net them down).

Department and vendor totals use the bill's CAD total. GL totals use line amounts converted with the bill's FX rate,
so they exclude tax (the tax sits on the tax GL accounts, not the expense accounts).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.auth.deps import CurrentUser
from app.auth.roles import APPROVER
from app.db import models
from app.db.types import from_cents, text_to_dec
from app.services.money import cents

COMMITTED = ("approved", "scheduled", "paid", "credit_open")
CENT = Decimal("0.01")


def report(db: Session, user: CurrentUser, *, group_by: str, from_date: date | None, to_date: date | None,
           department_id: str | None) -> s.SpendReport:
    # Approvers see their own department only, whatever they ask for.
    if user.role == APPROVER:
        department_id = user.department_id
    where = [models.Bill.status.in_(COMMITTED)]
    if from_date:
        where.append(models.Bill.invoice_date >= from_date)
    if to_date:
        where.append(models.Bill.invoice_date <= to_date)
    if department_id:
        where.append(models.Bill.department_id == department_id)

    if group_by == "gl_account":
        totals: dict[str, Decimal] = defaultdict(Decimal)
        bills_per: dict[str, set[str]] = defaultdict(set)
        rows = db.execute(select(models.BillLine.gl_account, models.BillLine.amount_cents, models.Bill.fx_rate_to_cad,
                                 models.Bill.bill_id)
                          .join(models.Bill, models.Bill.bill_id == models.BillLine.bill_id).where(*where))
        for gl, amount_cents, fx, bill_id in rows:
            key = gl or "uncoded"
            totals[key] += from_cents(amount_cents) * text_to_dec(fx)
            bills_per[key].add(bill_id)
        labels = dict(db.execute(select(models.GlAccount.account_number, models.GlAccount.name)).all())
        out = [s.SpendRow(key=k, label=labels.get(k, "Uncoded"), bill_count=len(bills_per[k]),
                          total_cad=v.quantize(CENT, rounding=ROUND_HALF_UP)) for k, v in totals.items()]
    else:
        key_col = models.Bill.department_id if group_by == "department" else models.Bill.vendor_id
        label_model, label_key, label_col = (
            (models.Department, models.Department.department_id, models.Department.name) if group_by == "department"
            else (models.Vendor, models.Vendor.vendor_id, models.Vendor.legal_name))
        labels = dict(db.execute(select(label_key, label_col)).all())
        rows = db.execute(select(key_col, func.count(), func.sum(models.Bill.total_cad_cents))
                          .where(*where).group_by(key_col))
        out = [s.SpendRow(key=k or "unknown", label=labels.get(k, "Unknown"), bill_count=n,
                          total_cad=cents(int(total or 0))) for k, n, total in rows]

    out.sort(key=lambda r: r.total_cad, reverse=True)
    return s.SpendReport(group_by=group_by, from_date=from_date, to_date=to_date, department_id=department_id,
                         rows=out, total_cad=sum((r.total_cad for r in out), Decimal("0.00")))
