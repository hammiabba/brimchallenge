"""
Database rows -> API response models. Every response that carries money or bank numbers is built here, so the two
presentation rules apply everywhere: amounts become Decimal (serialized as "742.30") and bank account numbers are
masked for roles without full access.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.db import models
from app.services.masking import account_for, can_see_full_bank, mask_draft
from app.services.money import cents


def vendor_names(db: Session, vendor_ids: set[str]) -> dict[str, str]:
    ids = {v for v in vendor_ids if v}
    if not ids:
        return {}
    rows = db.execute(select(models.Vendor.vendor_id, models.Vendor.legal_name)
                      .where(models.Vendor.vendor_id.in_(ids)))
    return dict(rows.all())


def bill_summary(bill: models.Bill, vendor_name: str | None) -> s.BillSummary:
    return s.BillSummary(
        bill_id=bill.bill_id, status=bill.status, origin=bill.origin, vendor_id=bill.vendor_id,
        vendor_name=vendor_name, vendor_invoice_number=bill.vendor_invoice_number, invoice_date=bill.invoice_date,
        due_date=bill.due_date, received_date=bill.received_date, currency=bill.currency,
        total=cents(bill.total_cents), total_cad=cents(bill.total_cad_cents), is_credit_note=bill.is_credit_note,
        department_id=bill.department_id, requester_user_id=bill.requester_user_id, row_version=bill.row_version)


_SEVERITY_RANK = {"block": 0, "warn": 1, "info": 2}


def _flag_overview(db: Session, bill_ids: list[str]) -> dict[str, tuple[s.OpenFlagCounts, str | None]]:
    """Open-flag counts and the most severe open flag code from each bill's latest controls run, in two queries."""
    if not bill_ids:
        return {}
    latest = (select(models.ControlsRun.bill_id, func.max(models.ControlsRun.version).label("v"))
              .where(models.ControlsRun.bill_id.in_(bill_ids)).group_by(models.ControlsRun.bill_id).subquery())
    runs = dict(db.execute(select(models.ControlsRun.run_id, models.ControlsRun.bill_id).join(
        latest, (latest.c.bill_id == models.ControlsRun.bill_id) & (latest.c.v == models.ControlsRun.version))).all())
    out: dict[str, tuple[s.OpenFlagCounts, str | None]] = {}
    if not runs:
        return out
    rows = db.execute(select(models.BillFlag.run_id, models.BillFlag.severity, models.BillFlag.code, models.BillFlag.id)
                      .where(models.BillFlag.run_id.in_(runs), models.BillFlag.resolution == "open"))
    grouped: dict[str, list[tuple[str, str, int]]] = {}
    for run_id, severity, code, flag_id in rows:
        grouped.setdefault(runs[run_id], []).append((severity, code, flag_id))
    for bill_id, flags in grouped.items():
        counts = s.OpenFlagCounts(**{sev: sum(1 for f in flags if f[0] == sev) for sev in _SEVERITY_RANK})
        top = min(flags, key=lambda f: (_SEVERITY_RANK.get(f[0], 9), f[2]))[1]
        out[bill_id] = (counts, top)
    return out


def bill_summaries(db: Session, bills: list[models.Bill]) -> list[s.BillSummary]:
    """Summaries with the queue fields: open flags, the top flag and, for pending bills, the current step."""
    from app.services.approvals import current_step  # approvals imports this module's helpers indirectly

    names = vendor_names(db, {b.vendor_id for b in bills})
    flags = _flag_overview(db, [b.bill_id for b in bills])
    out = []
    for b in bills:
        summary = bill_summary(b, names.get(b.vendor_id))
        if b.bill_id in flags:
            summary.open_flags, summary.top_flag_code = flags[b.bill_id]
        if b.status == "pending_approval" and (step := current_step(db, b.bill_id)) is not None:
            summary.current_step = s.CurrentStepOut(step_no=step.step_no, role=step.role, user_id=step.user_id,
                                                    delegated_from=step.delegated_from)
        out.append(summary)
    return out


def line_out(line: models.BillLine) -> s.BillLineOut:
    return s.BillLineOut(
        line_no=line.line_no, description=line.description, quantity=line.quantity, unit_price=line.unit_price,
        amount=cents(line.amount_cents), line_type=line.line_type, gst_hst_code=line.gst_hst_code,
        pst_qst_code=line.pst_qst_code, gl_account=line.gl_account, department_id=line.department_id,
        suggested_gl_account=line.suggested_gl_account, suggested_department_id=line.suggested_department_id,
        suggestion_confidence=line.suggestion_confidence, suggestion_reason=line.suggestion_reason,
        coding_status=line.coding_status, coded_by=line.coded_by, coded_at=line.coded_at)


def tax_out(tax: models.BillTax) -> s.BillTaxOut:
    return s.BillTaxOut(tax_code=tax.tax_code, rate=tax.rate, amount=cents(tax.amount_cents))


def flag_out(flag: models.BillFlag) -> s.FlagOut:
    return s.FlagOut(id=flag.id, code=flag.code, severity=flag.severity, field=flag.field, message=flag.message,
                     evidence=flag.evidence_json or {}, resolution=flag.resolution, resolved_by=flag.resolved_by,
                     resolved_at=flag.resolved_at, resolution_comment=flag.resolution_comment)


def decision_out(d: models.ApprovalDecision) -> s.DecisionOut:
    return s.DecisionOut(decision_id=d.decision_id, step_no=d.step_no, actor_user_id=d.actor_user_id,
                         actor_role=d.actor_role, step_role=d.step_role, on_behalf_of=d.on_behalf_of,
                         decision=d.decision, comment=d.comment, acted_at=d.acted_at, origin=d.origin)


def payment_summary(p: models.Payment, vendor_name: str | None) -> s.PaymentSummary:
    return s.PaymentSummary(
        payment_id=p.payment_id, bill_id=p.bill_id, vendor_id=p.vendor_id, vendor_name=vendor_name, method=p.method,
        currency=p.currency, amount=cents(p.amount_cents), amount_cad=cents(p.amount_cad_cents),
        scheduled_date=p.scheduled_date, paid_date=p.paid_date, status=p.status, reference=p.reference,
        prepared_by=p.prepared_by, released_by=p.released_by, released_at=p.released_at)


def payment_summaries(db: Session, payments: list[models.Payment]) -> list[s.PaymentSummary]:
    names = vendor_names(db, {p.vendor_id for p in payments})
    return [payment_summary(p, names.get(p.vendor_id)) for p in payments]


def bank_account_out(role: str, acct: models.VendorBankAccount | None) -> s.BankAccountOut | None:
    if acct is None:
        return None
    return s.BankAccountOut(id=acct.id, institution=acct.institution, transit=acct.transit,
                            account=account_for(role, acct.account), account_last4=acct.account_last4,
                            masked=not can_see_full_bank(role), valid_from=acct.valid_from, valid_to=acct.valid_to)


def bank_change_out(role: str, c: models.BankChangeRequest, vendor_name: str | None = None) -> s.BankChangeOut:
    """A bank-change request for `role` (full account numbers only for roles that may see them), with the vendor's
    name when the caller has it."""
    return s.BankChangeOut(
        change_id=c.change_id, vendor_id=c.vendor_id, vendor_name=vendor_name, requested_at=c.requested_at,
        requested_by=c.requested_by,
        request_channel=c.request_channel, old_account_last4=c.old_account_last4,
        new_account_last4=c.new_account_last4, new_institution=c.new_institution, new_transit=c.new_transit,
        new_account=account_for(role, c.new_account), verified_by_callback=c.verified_by_callback, status=c.status,
        verified_by=c.verified_by, verified_at=c.verified_at, origin=c.origin)


def vendor_summary(v: models.Vendor) -> s.VendorSummary:
    return s.VendorSummary(vendor_id=v.vendor_id, legal_name=v.legal_name, category=v.category,
                           province_or_state=v.province_or_state, country=v.country, status=v.status,
                           preferred_payment_method=v.preferred_payment_method,
                           payment_terms_days=v.payment_terms_days, requires_po=v.requires_po)


def extracted_for(role: str, bill: models.Bill) -> dict | None:
    return mask_draft(role, bill.draft_json)


def user_out(u: models.User) -> s.UserOut:
    return s.UserOut(user_id=u.user_id, full_name=u.full_name, email=u.email, title=u.title,
                     department_id=u.department_id, manager_id=u.manager_id, role=u.role,
                     approval_limit_cad=cents(u.approval_limit_cad_cents), work_province=u.work_province,
                     status=u.status, status_since=u.status_since, delegate_user_id=u.delegate_user_id,
                     hire_date=u.hire_date)
