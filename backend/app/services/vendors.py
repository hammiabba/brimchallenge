"""Vendors and bank changes: reads (bank numbers masked per role in views.py) and the controlled writes."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError, not_found
from app.auth.deps import CurrentUser
from app.config import get_settings
from app.controls.refdata import RefData
from app.controls.validate import suspicious_lookalikes
from app.db import models
from app.db.audit import AuditAction
from app.db.refdata_db import refdata_from_db
from app.db.types import utcnow
from app.services import controls_runner, views
from app.services.events import record
from app.services.guards import invalid_state, next_id
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
    ref = refdata_from_db(db)
    items = [views.vendor_summary(v).model_copy(update={"lookalike_of": lookalikes(ref, v.vendor_id)}) for v in rows]
    return s.Page[s.VendorSummary](items=items, total=total, limit=limit, offset=offset)


def lookalikes(ref: RefData, vendor_id: str) -> list[s.LookalikeOut]:
    """The vendor records `vendor_id` is a suspicious copy of, by the VENDOR_LOOKALIKE control's own rule
    (controls.validate.suspicious_lookalikes), so the vendor screens mark exactly the records whose bills get flagged.
    Empty for a vendor the controls' reference data doesn't know yet."""
    if vendor_id not in ref.vendors:
        return []
    return [s.LookalikeOut(vendor_id=other, legal_name=ref.vendors[other]["legal_name"], why=why)
            for other, why in suspicious_lookalikes(ref, vendor_id)]


def open_account(db: Session, vendor_id: str) -> models.VendorBankAccount | None:
    return db.scalars(select(models.VendorBankAccount).where(models.VendorBankAccount.vendor_id == vendor_id,
                                                             models.VendorBankAccount.valid_to.is_(None))).first()


def vendor_detail(db: Session, role: str, vendor_id: str) -> s.VendorDetail:
    v = db.get(models.Vendor, vendor_id)
    if v is None:
        raise not_found("vendor", vendor_id)
    changes = db.scalars(select(models.BankChangeRequest).where(models.BankChangeRequest.vendor_id == vendor_id)
                         .order_by(models.BankChangeRequest.requested_at.desc()))
    summary = views.vendor_summary(v).model_dump(exclude={"lookalike_of"})
    return s.VendorDetail(
        **summary, lookalike_of=lookalikes(refdata_from_db(db), v.vendor_id), address=v.address,
        gst_hst_number=v.gst_hst_number,
        qst_number=v.qst_number, default_gl_account=v.default_gl_account, early_pay_discount=v.early_pay_discount,
        accepts_card_payment=v.accepts_card_payment, ap_contact_email=v.ap_contact_email,
        onboarded_at=v.onboarded_at, origin=v.origin,
        bank_account=views.bank_account_out(role, open_account(db, v.vendor_id)),
        bank_changes=[views.bank_change_out(role, c, v.legal_name) for c in changes])


def bank_change(db: Session, role: str, change_id: str) -> s.BankChangeOut:
    c = db.get(models.BankChangeRequest, change_id)
    if c is None:
        raise not_found("bank_change", change_id)
    vendor = db.get(models.Vendor, c.vendor_id)
    return views.bank_change_out(role, c, vendor.legal_name if vendor else None)


def list_bank_changes(db: Session, role: str, *, status: str | None) -> list[s.BankChangeOut]:
    stmt = select(models.BankChangeRequest)
    if status:
        stmt = stmt.where(models.BankChangeRequest.status == status)
    rows = list(db.scalars(stmt.order_by(models.BankChangeRequest.requested_at.desc())))
    # Vendor names in one query, for every row.
    ids = {c.vendor_id for c in rows}
    names = {vid: name for vid, name in db.execute(
        select(models.Vendor.vendor_id, models.Vendor.legal_name).where(models.Vendor.vendor_id.in_(ids)))}
    return [views.bank_change_out(role, c, names.get(c.vendor_id)) for c in rows]


# When a vendor's bank change is decided, the bills still in review re-run their controls, so a flag about the change
# (BANK_CHANGE_UNVERIFIED) reflects the decision at once instead of blocking until some unrelated edit. Bills further
# on keep their stored run: re-running one mid-approval could change its route under the approvers, and history bills
# keep their point-in-time run.
RECHECK_STATUSES = ("needs_review", "on_hold")


def _recheck_open_bills(db: Session, vendor_id: str) -> list[str]:
    """Re-run the controls on the vendor's app bills in review; returns their ids."""
    db.flush()
    bill_ids = list(db.scalars(select(models.Bill.bill_id).where(
        models.Bill.vendor_id == vendor_id, models.Bill.origin == "app",
        models.Bill.status.in_(RECHECK_STATUSES)).order_by(models.Bill.bill_id)))
    for bill_id in bill_ids:
        controls_runner.rerun(db, bill_id)
    return bill_ids


# ---------------------------------------------------------------- writes
# Each runs inside the route's write session and records exactly one audit event; the route commits.

def _vendor(db: Session, vendor_id: str) -> models.Vendor:
    v = db.get(models.Vendor, vendor_id)
    if v is None:
        raise not_found("vendor", vendor_id)
    return v


def onboard(db: Session, user: CurrentUser, body: s.VendorIn) -> str:
    """New vendors start as pending_review: they can't be paid until finance approves them (P05 also adds a
    finance approval step to their bills)."""
    if body.default_gl_account and db.get(models.GlAccount, body.default_gl_account) is None:
        raise ApiError(422, "vendor.unknown_gl_account", f"GL account {body.default_gl_account} doesn't exist.")
    duplicate = db.scalars(select(models.Vendor.vendor_id).where(
        models.Vendor.legal_name.ilike(body.legal_name.strip()))).first()
    if duplicate:
        raise ApiError(409, "vendor.duplicate_name", f"Vendor {duplicate} already has this legal name.",
                       {"vendor_id": duplicate})
    vendor = models.Vendor(vendor_id=next_id(db, models.Vendor.vendor_id, "V", 3), status="pending_review",
                           onboarded_at=get_settings().as_of_date, origin="app", **body.model_dump())
    db.add(vendor)
    db.flush()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.VENDOR_CREATED,
           entity_type="vendor", entity_id=vendor.vendor_id, after=body.model_dump() | {"status": "pending_review"})
    return vendor.vendor_id


def approve(db: Session, user: CurrentUser, vendor_id: str, comment: str | None) -> None:
    v = _vendor(db, vendor_id)
    if v.status == "active":
        raise invalid_state("vendor", v.status, ("pending_review", "on_hold"))
    pending = db.scalars(select(models.BankChangeRequest.change_id).where(
        models.BankChangeRequest.vendor_id == vendor_id,
        models.BankChangeRequest.status == "pending_verification")).first()
    if pending:
        raise ApiError(409, "vendor.bank_change_pending",
                       f"Verify or reject bank change {pending} before activating this vendor.", {"change_id": pending})
    before = v.status
    v.status = "active"
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.VENDOR_APPROVED,
           entity_type="vendor", entity_id=vendor_id, before={"status": before}, after={"status": "active"},
           comment=comment)


def hold(db: Session, user: CurrentUser, vendor_id: str, comment: str | None) -> None:
    v = _vendor(db, vendor_id)
    if v.status == "on_hold":
        raise invalid_state("vendor", v.status, ("active", "pending_review"))
    before = v.status
    v.status = "on_hold"
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.VENDOR_STATUS_CHANGED,
           entity_type="vendor", entity_id=vendor_id, before={"status": before}, after={"status": "on_hold"},
           comment=comment)


def request_bank_change(db: Session, user: CurrentUser, vendor_id: str, body: s.BankChangeIn) -> str:
    """Records the request only. The vendor's account is untouched until someone else verifies it."""
    _vendor(db, vendor_id)
    open_req = db.scalars(select(models.BankChangeRequest.change_id).where(
        models.BankChangeRequest.vendor_id == vendor_id,
        models.BankChangeRequest.status == "pending_verification")).first()
    if open_req:
        raise ApiError(409, "bank_change.already_pending",
                       f"Bank change {open_req} is already waiting for verification.", {"change_id": open_req})
    current = open_account(db, vendor_id)
    if current and (current.institution, current.transit, current.account) == (body.institution, body.transit,
                                                                                 body.account):
        raise ApiError(409, "bank_change.no_change", "These are already the vendor's bank details.")
    change = models.BankChangeRequest(
        change_id=next_id(db, models.BankChangeRequest.change_id, "BC-", 3), vendor_id=vendor_id,
        requested_at=utcnow(), requested_by=user.user_id, request_channel=body.request_channel,
        old_account_last4=current.account_last4 if current else None, new_account_last4=body.account[-4:],
        new_institution=body.institution, new_transit=body.transit, new_account=body.account,
        verified_by_callback=False, status="pending_verification", origin="app")
    db.add(change)
    db.flush()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.VENDOR_BANK_CHANGE_REQUESTED,
           entity_type="vendor", entity_id=vendor_id,
           before={"account": current.account} if current else None,
           after={"change_id": change.change_id, "institution": body.institution, "transit": body.transit,
                  "account": body.account, "request_channel": body.request_channel})
    return change.change_id


def _change(db: Session, change_id: str) -> models.BankChangeRequest:
    c = db.get(models.BankChangeRequest, change_id)
    if c is None:
        raise not_found("bank_change", change_id)
    if c.status != "pending_verification":
        raise invalid_state("bank_change", c.status, "pending_verification")
    return c


def verify_bank_change(db: Session, user: CurrentUser, change_id: str, comment: str | None) -> None:
    """The verifier confirms the new details by calling the vendor back on a number already on file. Then the old
    account row is closed and the new one opened, in the same transaction."""
    c = _change(db, change_id)
    if c.requested_by == user.user_id:
        raise ApiError(403, "bank_change.self_verification",
                       "You requested this change, so someone else has to verify it.")
    current = open_account(db, c.vendor_id)
    as_of = get_settings().as_of_date
    if c.new_account is None:
        # History requests only kept the last 4 digits. They can be verified only if that account is already open
        # (it was applied without verification, like BC-009); otherwise there are no full details to apply.
        if current is None or current.account_last4 != c.new_account_last4:
            raise ApiError(409, "bank_change.no_full_details",
                           "This request has no full account number to apply. Ask the vendor to resubmit it.")
    else:
        if current is not None:
            current.valid_to = as_of
            db.flush()  # close the old row first: only one open account per vendor is allowed
        db.add(models.VendorBankAccount(vendor_id=c.vendor_id, institution=c.new_institution, transit=c.new_transit,
                                        account=c.new_account, account_last4=c.new_account_last4, valid_from=as_of,
                                        source_change_id=c.change_id, origin="app"))
    c.status = "verified"
    c.verified_by = user.user_id
    c.verified_at = utcnow()
    c.verified_by_callback = True
    rechecked = _recheck_open_bills(db, c.vendor_id)
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.VENDOR_BANK_CHANGE_VERIFIED,
           entity_type="vendor", entity_id=c.vendor_id,
           before={"account": current.account} if current else None,
           after={"change_id": c.change_id, "account": c.new_account or c.new_account_last4,
                  "rechecked_bills": rechecked}, comment=comment)


def reject_bank_change(db: Session, user: CurrentUser, change_id: str, comment: str | None) -> None:
    """Rejects the request. If the vendor's open account is already the rejected one (applied without
    verification), the vendor goes on hold so nothing is paid to it."""
    c = _change(db, change_id)
    current = open_account(db, c.vendor_id)
    applied_unverified = current is not None and current.account_last4 == c.new_account_last4
    c.status = "rejected"
    c.verified_by = user.user_id
    c.verified_at = utcnow()
    after = {"change_id": c.change_id, "status": "rejected"}
    if applied_unverified:
        vendor = _vendor(db, c.vendor_id)
        after["vendor_status"] = vendor.status = "on_hold"
    after["rechecked_bills"] = _recheck_open_bills(db, c.vendor_id)
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.VENDOR_BANK_CHANGE_REJECTED,
           entity_type="vendor", entity_id=c.vendor_id, after=after, comment=comment)
