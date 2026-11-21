"""
Bill persistence: store an extracted DraftBill, rebuild the current DraftBill, and store controls results.

Owner: DB team. The API services call these and write the audit events themselves (app.db.audit.log_event);
nothing here logs, commits or closes the session. Writers require a write session (database.get_write_session).

Data split (decision 27): `bills.draft_json` is the frozen snapshot of what the document said at intake. The bill's
columns, `bill_lines` and `bill_taxes` hold the current, editable state. `load_draft_bill` rebuilds the DraftBill a
controls run needs from both: document facts (source, vendor as printed, confidence, warnings) from the snapshot,
everything a clerk can correct from the columns and tables.

Extracted references can be wrong. A vendor, department, requester, PO or contract that doesn't exist in the
database is stored as NULL with a warning (the raw value stays in draft_json), so a bad reference never makes the
insert fail.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.controls.duplicates import norm_invoice_no
from app.db import models
from app.db.database import require_write_session
from app.db.types import CENT, dec_to_text, from_cents, text_to_dec, to_cents, utcnow
from app.shared.schemas import ApprovalStep, CodingSuggestion, ControlsResult, DraftBill, Severity

_BILL_ID = re.compile(r"^AP-(\d+)$")
CARRY_OVER_RESOLUTIONS = ("overridden", "resolved")  # flag resolutions a new controls run inherits
# schemas.Severity from lowest to highest. A resolution carries over only to a flag of the same or lower severity.
SEVERITY_RANK = {Severity.INFO.value: 0, Severity.WARN.value: 1, Severity.BLOCK.value: 2}
CLERK_CODING_REASON = "set by clerk"


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class CreatedBill:
    """What create_bill_from_draft stored: the new bill id and anything that had to be adjusted on the way in."""

    bill_id: str
    warnings: list[str]


@dataclass(frozen=True)
class StoredFlag:
    """One stored flag of a controls run, with how (and whether) a person resolved it."""

    id: int
    code: str
    severity: str
    field: str | None
    message: str
    evidence: dict[str, Any]
    resolution: str
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_comment: str | None


@dataclass(frozen=True)
class StoredControlsRun:
    """The latest controls run of a bill: the ControlsResult as computed, plus the stored flag rows."""

    run_id: int
    version: int
    evaluated_at: datetime
    result: ControlsResult
    flags: list[StoredFlag]


# ---------------------------------------------------------------- small lookups


def _bill(session: Session, bill_id: str) -> models.Bill:
    """The bill row, or LookupError."""
    bill = session.get(models.Bill, bill_id)
    if bill is None:
        raise LookupError(f"bill {bill_id} not found")
    return bill


def _exists(session: Session, column: Any, value: str) -> bool:
    """True when a row with `column == value` exists (used to check extracted references)."""
    return session.execute(select(column).where(column == value).limit(1)).first() is not None


def _cents(value: Decimal, field: str, warnings: list[str]) -> int:
    """Money -> cents. A value with more than 2 decimals is rounded half-up and reported in `warnings`."""
    cents = to_cents(value)
    if value != value.quantize(CENT):
        warnings.append(f"{field} {value} has more than 2 decimal places; stored as {from_cents(cents)}")
    return cents


def _canonical(evidence: Any) -> str:
    """Evidence as canonical JSON text, so two flags' evidence can be compared exactly."""
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------- ids


def next_bill_id(session: Session) -> str:
    """The next AP-##### id after the highest numeric bill id (history ends at AP-00426, so app bills start at
    AP-00427). Zero-padded to 5 digits. In a write session the write lock makes the id safe to use right away."""
    ids = session.execute(select(models.Bill.bill_id).where(models.Bill.bill_id.like("AP-%"))).scalars()
    highest = max((int(m.group(1)) for bid in ids if (m := _BILL_ID.match(bid))), default=0)
    return f"AP-{highest + 1:05d}"


# ---------------------------------------------------------------- create


def create_bill_from_draft(session: Session, draft: DraftBill, *, created_by: str, received_date: date,
                           source_email_id: str | None = None) -> CreatedBill:
    """Store an extracted DraftBill as a new app bill (status needs_review) with its lines and taxes.

    Requires a write session. Never commits or logs. Extracted references that don't exist are stored as NULL with a
    warning; money with more than 2 decimals is rounded half-up with a warning; draft_json keeps the draft exactly as
    extracted. Raises LookupError if `created_by` isn't a user, and ValueError for a currency the schema can't store.
    """
    require_write_session(session, "create_bill_from_draft")
    if not _exists(session, models.User.user_id, created_by):
        raise LookupError(f"created_by user {created_by} not found")
    currency = (draft.currency or "CAD").strip().upper()
    if currency not in models.CURRENCIES:
        raise ValueError(f"currency {draft.currency!r} can't be stored: the bills table allows {models.CURRENCIES}")

    warnings: list[str] = []

    def reference(value: str | None, column: Any, label: str) -> str | None:
        """An extracted id if it exists in the database, else None plus a warning."""
        if value is None or not str(value).strip():
            return None
        if _exists(session, column, value):
            return value
        warnings.append(f"{label} {value!r} not found; stored as NULL")
        return None

    vendor_id = reference(draft.vendor.vendor_id, models.Vendor.vendor_id, "vendor_id")
    department_id = reference(draft.department_id, models.Department.department_id, "department_id")
    requester = reference(draft.requester_user_id, models.User.user_id, "requester_user_id")
    po_id = reference(draft.po_number, models.PurchaseOrder.po_id, "po_number")
    contract_id = reference(draft.contract_id, models.Contract.contract_id, "contract_id")

    province = draft.ship_to_province
    if province is not None and province not in models.PROVINCES:
        warnings.append(f"ship_to_province {province!r} is not a Canadian province code; stored as NULL")
        province = None

    fx_rate_date = None
    if currency == "USD":
        table_rate = session.execute(select(models.FxRate.usd_to_cad)
                                     .where(models.FxRate.rate_date == draft.invoice_date)).scalar()
        if table_rate is not None and text_to_dec(table_rate) == draft.fx_rate_to_cad:
            fx_rate_date = draft.invoice_date

    bill_id = next_bill_id(session)
    now = utcnow()
    session.add(models.Bill(
        bill_id=bill_id, origin="app", status="needs_review", vendor_id=vendor_id,
        vendor_invoice_number=draft.invoice_number, norm_invoice_number=norm_invoice_no(draft.invoice_number),
        invoice_date=draft.invoice_date, due_date=draft.due_date, currency=currency,
        subtotal_cents=_cents(draft.subtotal, "subtotal", warnings),
        total_cents=_cents(draft.total, "total", warnings),
        total_cad_cents=_cents(draft.total_cad, "total_cad", warnings),
        fx_rate_to_cad=dec_to_text(draft.fx_rate_to_cad), fx_rate_date=fx_rate_date,
        is_credit_note=draft.is_credit_note, ship_to_province=province, department_id=department_id,
        requester_user_id=requester, po_id=po_id, contract_id=contract_id, file_hash=draft.source.file_hash,
        source_email_id=source_email_id, draft_json=draft.model_dump(mode="json"), received_date=received_date,
        created_at=now, created_by=created_by, updated_at=now,
    ))

    line_numbers = [line.line_no for line in draft.lines]
    renumber = len(set(line_numbers)) != len(line_numbers)
    if renumber:
        warnings.append(f"line numbers {line_numbers} are not unique; lines stored as 1..{len(line_numbers)}")
    for position, line in enumerate(draft.lines, 1):
        coding = line.coding
        confidence = coding.confidence if coding is not None else None
        if confidence is not None and not 0 <= confidence <= 1:
            warnings.append(f"line {line.line_no}: suggestion confidence {confidence} is outside 0..1; stored as NULL")
            confidence = None
        session.add(models.BillLine(
            bill_id=bill_id, line_no=position if renumber else line.line_no, description=line.description,
            quantity=dec_to_text(line.quantity), unit_price=dec_to_text(line.unit_price),
            amount_cents=_cents(line.amount, f"lines[{line.line_no}].amount", warnings),
            line_type=line.line_type.value,
            suggested_gl_account=coding.gl_account if coding is not None else None,
            suggested_department_id=coding.department_id if coding is not None else None,
            suggestion_confidence=confidence,
            suggestion_reason=coding.reason if coding is not None else None,
            coding_status="suggested" if coding is not None else "none",
        ))
    for index, tax in enumerate(draft.taxes):
        session.add(models.BillTax(bill_id=bill_id, tax_code=tax.code.value, rate=dec_to_text(tax.rate),
                                   amount_cents=_cents(tax.amount, f"taxes[{index}].amount", warnings)))
    session.flush()
    return CreatedBill(bill_id=bill_id, warnings=warnings)


# ---------------------------------------------------------------- rebuild the current DraftBill


def _coding(line: models.BillLine) -> CodingSuggestion | None:
    """The line's coding as a CodingSuggestion: the final coding if a clerk set it, else the suggestion, else None."""
    if line.coding_status in ("accepted", "overridden"):
        return CodingSuggestion(
            gl_account=line.gl_account, department_id=line.department_id,
            confidence=line.suggestion_confidence if line.suggestion_confidence is not None else 1.0,
            reason=line.suggestion_reason or CLERK_CODING_REASON, accepted=True)
    if line.coding_status == "suggested":
        # A confidence stored as NULL (it was outside 0..1 at intake) comes back as 0.0: CodingSuggestion requires one.
        confidence = line.suggestion_confidence if line.suggestion_confidence is not None else 0.0
        return CodingSuggestion(gl_account=line.suggested_gl_account, department_id=line.suggested_department_id,
                                confidence=confidence, reason=line.suggestion_reason or "", accepted=False)
    return None


def load_draft_bill(session: Session, bill_id: str) -> DraftBill:
    """The current DraftBill of an app bill, for controls.

    Document facts come from draft_json (source, the vendor as printed, field_confidence, extraction_warnings,
    payment_terms_days); everything editable comes from the bill's columns, bill_lines and bill_taxes. Raises
    LookupError for an unknown bill and ValueError for a history bill (RefData builds those).
    """
    bill = _bill(session, bill_id)
    if bill.origin == "history":
        raise ValueError("history bills are built by RefData")
    snapshot = bill.draft_json
    if snapshot is None:
        raise ValueError(f"bill {bill_id} has no draft snapshot")

    lines = session.execute(select(models.BillLine).where(models.BillLine.bill_id == bill_id)
                            .order_by(models.BillLine.line_no)).scalars()
    taxes = session.execute(select(models.BillTax).where(models.BillTax.bill_id == bill_id)
                            .order_by(models.BillTax.id)).scalars()
    return DraftBill.model_validate({
        "source": snapshot["source"],
        "vendor": {**snapshot["vendor"], "vendor_id": bill.vendor_id},
        "invoice_number": bill.vendor_invoice_number,
        "invoice_date": bill.invoice_date,
        "due_date": bill.due_date,
        "payment_terms_days": snapshot.get("payment_terms_days"),
        "currency": bill.currency,
        "is_credit_note": bill.is_credit_note,
        "ship_to_province": bill.ship_to_province,
        "po_number": bill.po_id,
        "contract_id": bill.contract_id,
        "requester_user_id": bill.requester_user_id,
        "department_id": bill.department_id,
        "lines": [{"line_no": ln.line_no, "description": ln.description, "quantity": text_to_dec(ln.quantity),
                   "unit_price": text_to_dec(ln.unit_price), "amount": from_cents(ln.amount_cents),
                   "line_type": ln.line_type, "coding": _coding(ln)} for ln in lines],
        "subtotal": from_cents(bill.subtotal_cents),
        "taxes": [{"code": t.tax_code, "rate": text_to_dec(t.rate), "amount": from_cents(t.amount_cents)}
                  for t in taxes],
        "total": from_cents(bill.total_cents),
        "fx_rate_to_cad": text_to_dec(bill.fx_rate_to_cad),
        "total_cad": from_cents(bill.total_cad_cents),
        "field_confidence": snapshot.get("field_confidence", {}),
        "extraction_warnings": snapshot.get("extraction_warnings", []),
    })


# ---------------------------------------------------------------- controls runs


def _latest_run(session: Session, bill_id: str) -> models.ControlsRun | None:
    """The bill's controls run with the highest version, or None."""
    return session.execute(select(models.ControlsRun).where(models.ControlsRun.bill_id == bill_id)
                           .order_by(models.ControlsRun.version.desc()).limit(1)).scalar()


def _flags_of(session: Session, run_id: int) -> list[models.BillFlag]:
    """The stored flags of one run, in the order they were saved."""
    return list(session.execute(select(models.BillFlag).where(models.BillFlag.run_id == run_id)
                                .order_by(models.BillFlag.id)).scalars())


def save_controls_run(session: Session, bill_id: str, result: ControlsResult) -> int:
    """Store one controls run for a bill (version = previous + 1) with its flags and route steps; returns run_id.

    Requires a write session. Never commits or logs. A flag keeps the resolution a person gave it in the previous
    run (overridden or resolved, with who, when and the comment) only when the previous flag had the same code,
    field and evidence (compared as canonical JSON) and a severity at least as high as the new one, judged by the
    stored `bill_flags.severity`, not today's FLAG_CODES. Every other flag starts open. The severity rule exists
    because who may override depends on severity: an AP clerk may override a warn but only finance or the
    controller may override a block, so a warn override must not silently cover the flag once it becomes a block.
    An override of a block still covers it as a warn. A route step whose user_id isn't a user (e.g. "UNASSIGNED")
    is stored with user_id NULL; result_json keeps the original value.
    """
    require_write_session(session, "save_controls_run")
    _bill(session, bill_id)
    previous = _latest_run(session, bill_id)
    version = previous.version + 1 if previous is not None else 1

    # Resolutions to carry over, keyed by (code, field, canonical evidence); a list in case a key repeats.
    inherited: dict[tuple[str, str | None, str], list[models.BillFlag]] = {}
    if previous is not None:
        for old in _flags_of(session, previous.run_id):
            if old.resolution in CARRY_OVER_RESOLUTIONS:
                inherited.setdefault((old.code, old.field, _canonical(old.evidence_json)), []).append(old)

    dumped = result.model_dump(mode="json")  # JSON-safe evidence (Decimals as strings, dates as ISO)
    run = models.ControlsRun(bill_id=bill_id, version=version, evaluated_at=utcnow(),
                             can_auto_proceed=result.can_auto_proceed, recommendation=result.recommendation,
                             result_json=dumped)
    session.add(run)
    session.flush()  # assigns run_id

    for flag_json in dumped["flags"]:
        key = (flag_json["code"], flag_json["field"], _canonical(flag_json["evidence"]))
        # The first matching earlier resolution made at the same or a higher severity. One made at a lower severity
        # doesn't cover this flag (the new flag starts open), but stays available for a later identical flag it does
        # cover. With an unchanged severity this is the first match, as before.
        candidates = inherited.get(key, [])
        rank = SEVERITY_RANK[flag_json["severity"]]
        old = next((c for c in candidates if SEVERITY_RANK[c.severity] >= rank), None)
        if old is not None:
            candidates.remove(old)
        session.add(models.BillFlag(
            run_id=run.run_id, code=flag_json["code"], severity=flag_json["severity"], field=flag_json["field"],
            message=flag_json["message"], evidence_json=flag_json["evidence"],
            resolution=old.resolution if old is not None else "open",
            resolved_by=old.resolved_by if old is not None else None,
            resolved_at=old.resolved_at if old is not None else None,
            resolution_comment=old.resolution_comment if old is not None else None,
        ))

    known_users = set(session.execute(select(models.User.user_id)).scalars())
    for step in result.route:
        session.add(models.ApprovalRouteStep(
            run_id=run.run_id, step_no=step.step_no, bill_id=bill_id, role=step.role,
            user_id=step.user_id if step.user_id in known_users else None, policy_ids=list(step.policy_ids),
            reason=step.reason, delegated_from=step.delegated_from, escalated_from=step.escalated_from,
        ))
    session.flush()
    return run.run_id


def latest_controls_run(session: Session, bill_id: str) -> StoredControlsRun | None:
    """The bill's newest controls run (result rebuilt from result_json, plus the stored flags), or None if none yet."""
    _bill(session, bill_id)
    run = _latest_run(session, bill_id)
    if run is None:
        return None
    flags = [StoredFlag(id=f.id, code=f.code, severity=f.severity, field=f.field, message=f.message,
                        evidence=f.evidence_json, resolution=f.resolution, resolved_by=f.resolved_by,
                        resolved_at=f.resolved_at, resolution_comment=f.resolution_comment)
             for f in _flags_of(session, run.run_id)]
    return StoredControlsRun(run_id=run.run_id, version=run.version, evaluated_at=run.evaluated_at,
                             result=ControlsResult.model_validate(run.result_json), flags=flags)


def route_for_bill(session: Session, bill_id: str) -> list[ApprovalStep]:
    """The latest run's approval route, rebuilt from result_json (so "UNASSIGNED" survives); [] if never run.

    This is the `route` argument controls.approvals.can_approve expects.
    """
    stored = latest_controls_run(session, bill_id)
    return list(stored.result.route) if stored is not None else []


def approver_ids_for_bill(session: Session, bill_id: str) -> set[str]:
    """Everyone who approved this bill: each approving actor plus each user they acted for (on_behalf_of).

    This is the `approver_ids` set controls.approvals.can_release needs (P11: an approver may not release). It comes
    from stored approval_decisions only, across every run of the bill; rejections don't count.
    """
    _bill(session, bill_id)
    rows = session.execute(select(models.ApprovalDecision.actor_user_id, models.ApprovalDecision.on_behalf_of)
                           .where(models.ApprovalDecision.bill_id == bill_id,
                                  models.ApprovalDecision.decision == "approved"))
    ids: set[str] = set()
    for actor, on_behalf_of in rows:
        ids.add(actor)
        if on_behalf_of is not None:
            ids.add(on_behalf_of)
    return ids
