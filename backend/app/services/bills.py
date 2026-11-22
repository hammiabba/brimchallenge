"""Bills: the scoped list and the one-screen detail (header, lines and coding, taxes, latest controls run with
flags and route, every approval decision, payments and the bill's audit history), edits, flag resolution,
submit and void."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError, not_found
from app.auth.deps import CurrentUser
from app.auth.roles import CONTROLLER_ADMIN, FINANCE_MANAGER
from app.coding.feedback import learn_from_line
from app.coding.requester import recode_for_requester, requester_problem
from app.controls.duplicates import norm_invoice_no
from app.db import models
from app.db.audit import AuditAction
from app.db.bills import latest_controls_run
from app.db.types import utcnow
from app.extraction.recheck import recheck_bill
from app.services import approvals, audit, controls_runner, views
from app.services.events import record
from app.services.guards import check_row_version, invalid_state
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
                            flags=[views.flag_out(f) for f in flags], route=route,
                            duplicates=[s.DuplicateOut.model_validate(d)
                                        for d in (run.result_json or {}).get("duplicates", [])])


def department_source(bill: models.Bill, events: list[s.AuditEventOut]) -> str | None:
    """Where the bill's department came from, read from the bill and its own audit history: a person's edit wins,
    then what intake recorded when it created the bill, then the document itself."""
    if bill.origin == "history":
        return "history"
    if bill.department_id is None:
        return None
    if any(e.action == AuditAction.BILL_UPDATED and "department_id" in (e.after or {}) for e in events):
        return "user"
    created = next((e for e in events if e.action == AuditAction.BILL_CREATED), None)
    if created and (created.after or {}).get("department_source"):
        return created.after["department_source"]
    if (bill.draft_json or {}).get("department_id") == bill.department_id:
        return "invoice"
    return None


def bill_detail(db: Session, user: CurrentUser, bill_id: str) -> s.BillDetail:
    from app.services.actions import bill_actions  # actions builds on this module's rules

    bill = get_bill_for(db, user, bill_id)
    # The same summary as the bills list: open-flag counts, the top flag and, while pending, the current step.
    [summary] = views.bill_summaries(db, [bill])
    lines = db.scalars(select(models.BillLine).where(models.BillLine.bill_id == bill.bill_id)
                       .order_by(models.BillLine.line_no))
    taxes = db.scalars(select(models.BillTax).where(models.BillTax.bill_id == bill.bill_id)
                       .order_by(models.BillTax.id))
    decisions = db.scalars(select(models.ApprovalDecision).where(models.ApprovalDecision.bill_id == bill.bill_id)
                           .order_by(models.ApprovalDecision.acted_at, models.ApprovalDecision.step_no))
    payments = list(db.scalars(select(models.Payment).where(models.Payment.bill_id == bill.bill_id)
                               .order_by(models.Payment.scheduled_date)))
    events = audit.entity_history(db, AUDIT_ENTITY, bill.bill_id)
    return s.BillDetail(
        **summary.model_dump(),
        subtotal=cents(bill.subtotal_cents), fx_rate_to_cad=bill.fx_rate_to_cad, fx_rate_date=bill.fx_rate_date,
        ship_to_province=bill.ship_to_province, po_id=bill.po_id, contract_id=bill.contract_id,
        source_email_id=bill.source_email_id, file_hash=bill.file_hash, created_at=bill.created_at,
        created_by=bill.created_by, updated_at=bill.updated_at, extracted=views.extracted_for(user.role, bill),
        lines=[views.line_out(ln) for ln in lines], taxes=[views.tax_out(t) for t in taxes],
        latest_run=_latest_run_out(db, bill.bill_id), decisions=[views.decision_out(d) for d in decisions],
        payments=views.payment_summaries(db, payments), audit=events,
        department_source=department_source(bill, events), allowed_actions=bill_actions(db, user, bill))


# ---------------------------------------------------------------- writes
# Each runs in the route's write session with one audit event; the route commits. Edits re-run controls so the
# flags and route on screen always match the bill as it now stands.

EDITABLE = ("needs_review", "on_hold")
_HEADER_REFS = {"vendor_id": models.Vendor, "po_id": models.PurchaseOrder, "contract_id": models.Contract,
                "department_id": models.Department, "requester_user_id": models.User}


def _editable_bill(db: Session, user: CurrentUser, bill_id: str, row_version: int,
                   allowed: tuple[str, ...] = EDITABLE) -> models.Bill:
    bill = get_bill_for(db, user, bill_id)
    check_row_version(bill.row_version, row_version, "bill")
    if bill.status not in allowed:
        raise invalid_state("bill", bill.status, allowed)
    return bill


def _require_app_bill(bill: models.Bill) -> None:
    if bill.origin != "app":
        raise ApiError(409, "bill.history_read_only", "Bills loaded from the dataset history can't be edited.")


def update_header(db: Session, user: CurrentUser, bill_id: str, patch: s.BillHeaderPatch) -> None:
    bill = _editable_bill(db, user, bill_id, patch.row_version)
    _require_app_bill(bill)
    changes = patch.model_dump(exclude_unset=True, exclude={"row_version"})
    if not changes:
        raise ApiError(422, "request.empty", "Nothing to change.")
    for field, model in _HEADER_REFS.items():
        value = changes.get(field)
        if value is not None and db.get(model, value) is None:
            raise ApiError(422, f"bill.unknown_{field}", f"{value} doesn't exist.", {"field": field})
    if problem := requester_problem(db, changes.get("requester_user_id")):
        raise ApiError(422, "bill.requester_not_allowed", problem, {"field": "requester_user_id"})
    if "ship_to_province" in changes and changes["ship_to_province"] not in (None, *models.PROVINCES):
        raise ApiError(422, "bill.bad_province", "ship_to_province must be a Canadian province or territory code.")
    before = {k: getattr(bill, k) for k in changes}
    for key, value in changes.items():
        setattr(bill, key, value)
    if "vendor_invoice_number" in changes:
        bill.norm_invoice_number = norm_invoice_no(changes["vendor_invoice_number"])
    recode_for_requester(db, bill, changes)
    bill.updated_at = utcnow()
    recheck_bill(db, bill, changes)
    controls_runner.rerun(db, bill_id)
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_UPDATED,
           entity_type=AUDIT_ENTITY, entity_id=bill_id, before=before, after=changes)


def code_line(db: Session, user: CurrentUser, bill_id: str, line_no: int, patch: s.LineCodingPatch) -> None:
    bill = _editable_bill(db, user, bill_id, patch.row_version)
    _require_app_bill(bill)
    line = db.get(models.BillLine, (bill_id, line_no))
    if line is None:
        raise not_found("bill_line", f"{bill_id}/{line_no}")
    if db.get(models.GlAccount, patch.gl_account) is None:
        raise ApiError(422, "bill.unknown_gl_account", f"GL account {patch.gl_account} doesn't exist.")
    if db.get(models.Department, patch.department_id) is None:
        raise ApiError(422, "bill.unknown_department_id", f"Department {patch.department_id} doesn't exist.")
    before = {"gl_account": line.gl_account, "department_id": line.department_id,
              "coding_status": line.coding_status}
    accepted = (patch.gl_account, patch.department_id) == (line.suggested_gl_account, line.suggested_department_id)
    line.gl_account, line.department_id = patch.gl_account, patch.department_id
    line.coding_status = "accepted" if accepted else "overridden"
    line.coded_by, line.coded_at = user.user_id, utcnow()
    learn_from_line(bill, line)
    bill.updated_at = utcnow()  # bumps row_version: the bill as a whole changed
    controls_runner.rerun(db, bill_id)
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_CODING_CHANGED,
           entity_type=AUDIT_ENTITY, entity_id=bill_id, before={"line_no": line_no, **before},
           after={"line_no": line_no, "gl_account": patch.gl_account, "department_id": patch.department_id,
                  "coding_status": line.coding_status, "suggested_gl_account": line.suggested_gl_account})


# Flags that only their own workflow can clear: marking them resolved by hand is refused.
VERIFY_TO_CLEAR = frozenset({"BANK_CHANGE_UNVERIFIED"})


def resolve_flag(db: Session, user: CurrentUser, bill_id: str, flag_id: int, body: s.FlagResolveIn) -> None:
    """Resolve (fixed) or override (accepted as is, with a reason) one open flag of the latest controls run.
    Overriding a blocking flag needs finance or controller rights; an AP clerk can resolve anything and override
    warnings."""
    bill = _editable_bill(db, user, bill_id, body.row_version)
    stored = latest_controls_run(db, bill_id)
    flag = db.get(models.BillFlag, flag_id)
    if flag is None or stored is None or flag.run_id != stored.run_id:
        raise not_found("flag", str(flag_id))
    if flag.resolution != "open":
        raise invalid_state("flag", flag.resolution, "open")
    # An unverified bank change is fixed only by verifying it (a callback on a number already on file), which clears
    # the flag on the bill's next controls run. Marking it "resolved" by hand would let the bill through unverified;
    # finance or the controller can still override it with a reason.
    if body.resolution == "resolved" and flag.code in VERIFY_TO_CLEAR:
        raise ApiError(409, "flag.cleared_by_verification",
                       "Verify the bank change instead (Bank changes); that clears this flag. A finance manager or "
                       "the controller can override it with a reason.")
    if body.resolution == "overridden":
        if not body.comment:
            raise ApiError(422, "flag.comment_required", "Say why you're overriding this flag.")
        if flag.severity == "block" and user.role not in (FINANCE_MANAGER, CONTROLLER_ADMIN):
            raise ApiError(403, "flag.override_needs_finance",
                           "Only a finance manager or the controller can override a blocking flag.")
    flag.resolution, flag.resolved_by, flag.resolved_at = body.resolution, user.user_id, utcnow()
    flag.resolution_comment = body.comment
    bill.updated_at = utcnow()
    action = AuditAction.BILL_FLAG_OVERRIDDEN if body.resolution == "overridden" else AuditAction.BILL_FLAG_RESOLVED
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=action, entity_type=AUDIT_ENTITY,
           entity_id=bill_id, before={"flag_id": flag_id, "code": flag.code, "resolution": "open"},
           after={"flag_id": flag_id, "code": flag.code, "severity": flag.severity, "resolution": body.resolution},
           comment=body.comment)


def submit(db: Session, user: CurrentUser, bill_id: str, row_version: int) -> None:
    """needs_review / on_hold -> pending_approval. Controls run fresh first; if a blocking flag is still open the
    whole transaction is refused (409) and nothing changes."""
    bill = _editable_bill(db, user, bill_id, row_version)
    _require_app_bill(bill)
    result, _ = controls_runner.rerun(db, bill_id)
    blocking = controls_runner.open_blocking_codes(db, bill_id)
    if blocking:
        raise ApiError(409, "bill.blocked", "Resolve or override the blocking flags before submitting.",
                       {"open_blocking_flags": blocking})
    if not result.route:
        raise ApiError(409, "bill.no_route", "Controls produced no approval route for this bill.")
    before = bill.status
    bill.status, bill.updated_at = "pending_approval", utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_SUBMITTED,
           entity_type=AUDIT_ENTITY, entity_id=bill_id, before={"status": before},
           after={"status": "pending_approval", "route": [{"step_no": st.step_no, "role": st.role,
                                                           "user_id": st.user_id} for st in result.route]})


def void(db: Session, user: CurrentUser, bill_id: str, body: s.VoidIn) -> None:
    """Void instead of delete. AP can void bills still in review; the controller can also void bills awaiting or
    past approval, as long as no payment is scheduled."""
    allowed = EDITABLE + (("pending_approval", "approved") if user.role == CONTROLLER_ADMIN else ())
    bill = _editable_bill(db, user, bill_id, body.row_version, allowed)
    before = bill.status
    bill.status, bill.updated_at = "void", utcnow()
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_VOIDED,
           entity_type=AUDIT_ENTITY, entity_id=bill_id, before={"status": before}, after={"status": "void"},
           comment=body.comment)
