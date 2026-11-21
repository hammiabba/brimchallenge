"""Vendor and bank-change reads. Bank numbers are masked per role in views.py. Writes arrive with log_event."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import not_found
from app.db import models
from app.services import views
from app.services.pagination import paginate


def list_vendors(db: Session, *, status: list[str] | None, q: str | None, limit: int,
                 offset: int) -> s.Page[s.VendorSummary]:
    stmt = select(models.Vendor)
    if status:
        stmt = stmt.where(models.Vendor.status.in_(status))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(models.Vendor.legal_name.ilike(like), models.Vendor.vendor_id.ilike(like),
                              models.Vendor.category.ilike(like)))
    rows, total = paginate(db, stmt.order_by(models.Vendor.legal_name), limit=limit, offset=offset)
    return s.Page[s.VendorSummary](items=[views.vendor_summary(v) for v in rows], total=total, limit=limit,
                                   offset=offset)


def open_account(db: Session, vendor_id: str) -> models.VendorBankAccount | None:
    return db.scalars(select(models.VendorBankAccount).where(models.VendorBankAccount.vendor_id == vendor_id,
                                                             models.VendorBankAccount.valid_to.is_(None))).first()


def vendor_detail(db: Session, role: str, vendor_id: str) -> s.VendorDetail:
    v = db.get(models.Vendor, vendor_id)
    if v is None:
        raise not_found("vendor", vendor_id)
    changes = db.scalars(select(models.BankChangeRequest).where(models.BankChangeRequest.vendor_id == vendor_id)
                         .order_by(models.BankChangeRequest.requested_at.desc()))
    return s.VendorDetail(
        **views.vendor_summary(v).model_dump(), address=v.address, gst_hst_number=v.gst_hst_number,
        qst_number=v.qst_number, default_gl_account=v.default_gl_account, early_pay_discount=v.early_pay_discount,
        accepts_card_payment=v.accepts_card_payment, ap_contact_email=v.ap_contact_email,
        onboarded_at=v.onboarded_at, origin=v.origin,
        bank_account=views.bank_account_out(role, open_account(db, v.vendor_id)),
        bank_changes=[views.bank_change_out(role, c) for c in changes])


def list_bank_changes(db: Session, role: str, *, status: str | None) -> list[s.BankChangeOut]:
    stmt = select(models.BankChangeRequest)
    if status:
        stmt = stmt.where(models.BankChangeRequest.status == status)
    rows = db.scalars(stmt.order_by(models.BankChangeRequest.requested_at.desc()))
    return [views.bank_change_out(role, c) for c in rows]
