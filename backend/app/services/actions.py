"""
allowed_actions: what the signed-in user can do to a bill or payment right now, and why not.

The UI shows buttons from this. Each answer comes from the same checks the write endpoints run (decision_check,
schedule_check, release_check and the bill state rules), called without writing anything, so a button that says
"allowed" never leads to a refusal for a reason the UI wasn't told about. The role gate mirrors the routes'
require_role, which the permission-matrix test pins down. Optimistic-locking (row_version) isn't part of the answer:
it depends on what the client last loaded.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.api.schemas_api import ActionState
from app.auth.deps import CurrentUser
from app.auth.roles import AP_CLERK, BACK_OFFICE_READ, CONTROLLER_ADMIN, FINANCE_MANAGER, RELEASERS, SIGNERS
from app.controls.wording import flag_titles, role_group, status_label
from app.db import models
from app.db.bills import latest_controls_run
from app.services import approvals, controls_runner, payments
from app.services.bills import EDITABLE

BILL_ACTION_ROLES: dict[str, tuple[str, ...]] = {
    "edit": (AP_CLERK,),
    "code_lines": (AP_CLERK,),
    "resolve_flags": (AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN),
    "override_blocking_flags": (FINANCE_MANAGER, CONTROLLER_ADMIN),
    "submit": (AP_CLERK,),
    "approve": SIGNERS,
    "reject": SIGNERS,
    "assign_step": (FINANCE_MANAGER, CONTROLLER_ADMIN),
    "void": (AP_CLERK, CONTROLLER_ADMIN),
    "schedule_payment": (AP_CLERK,),
}
PAYMENT_ACTION_ROLES: dict[str, tuple[str, ...]] = {
    "release": RELEASERS,
    "cancel": (AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN),
}
_VERBS = {"edit": "edit bills", "code_lines": "code lines", "resolve_flags": "resolve flags",
          "override_blocking_flags": "override blocking flags", "submit": "submit bills", "approve": "approve bills",
          "reject": "reject bills", "assign_step": "assign approvers", "void": "void bills",
          "schedule_payment": "schedule payments", "release": "release payments", "cancel": "cancel payments"}


class _No(Exception):
    pass


def _answer(user: CurrentUser, action: str, roles: tuple[str, ...], check: Callable[[], str | None]) -> ActionState:
    if user.role not in roles:
        # In words, not the role code: "AP clerks can't approve bills."
        return ActionState(allowed=False, reason=f"{role_group(user.role)} can't {_VERBS[action]}.")
    try:
        return ActionState(allowed=True, reason=check())
    except ApiError as exc:
        return ActionState(allowed=False, reason=exc.message)
    except _No as exc:
        return ActionState(allowed=False, reason=str(exc))


# GET /intake/files/{hash} serves only a sha256 hash that an intake item references (app.intake.files.load); the same
# test decides whether a bill has an original file to open.
_SHA256 = re.compile(r"[0-9a-f]{64}")


def document_action(db: Session, user: CurrentUser, bill: models.Bill) -> ActionState:
    """view_document: may the caller open the bill's original file? Only roles that may call GET /intake/files/{hash}
    (BACK_OFFICE_READ, the constant that route's guard uses), and only when intake kept a file for this bill."""
    if user.role not in BACK_OFFICE_READ:
        return ActionState(allowed=False, reason="Your role can't open original files.")
    file_hash = bill.file_hash or ""
    if not _SHA256.fullmatch(file_hash) or not db.scalar(
            select(exists().where(models.IntakeItem.file_hash == file_hash))):
        return ActionState(allowed=False, reason="No original file for this bill.")
    return ActionState(allowed=True, reason=None)


def _editable(bill: models.Bill, app_only: bool = True) -> None:
    if bill.status not in EDITABLE:
        raise _No(f"The bill is {status_label(bill.status)}; it can only change while in review.")
    if app_only and bill.origin != "app":
        raise _No("Bills loaded from the dataset history can't be edited.")


def bill_actions(db: Session, user: CurrentUser, bill: models.Bill) -> dict[str, ActionState]:
    stored = latest_controls_run(db, bill.bill_id) if bill.origin == "app" else None
    open_flags = controls_runner.open_flags(stored)
    blocking = [f.code for f in open_flags if f.severity == "block"]

    def resolve() -> str:
        _editable(bill, app_only=False)
        if not open_flags:
            raise _No("There are no open flags.")
        return f"{len(open_flags)} open flag{'' if len(open_flags) == 1 else 's'}."

    def override_blocking() -> str:
        _editable(bill, app_only=False)
        if not blocking:
            raise _No("There are no open blocking flags.")
        return f"Blocking: {flag_titles(blocking)}."

    def submit() -> str:
        _editable(bill)
        if blocking:
            raise _No(f"Resolve or override first: {flag_titles(blocking)}.")
        if stored is None or not stored.result.route:
            raise _No("Controls haven't produced an approval route yet.")
        return "Ready for approval."

    decision: dict[str, ActionState] = {}

    def decide() -> str:
        if "result" not in decision:
            try:
                _, step, _ = approvals.decision_check(db, user, bill)
                decision["result"] = ActionState(
                    allowed=True, reason=f"Step {step.step_no} ({step.role}) is yours"
                    + (f", as delegate for {step.delegated_from}." if step.delegated_from else "."))
            except ApiError as exc:
                decision["result"] = ActionState(allowed=False, reason=exc.message)
        if not decision["result"].allowed:
            raise _No(decision["result"].reason)
        return decision["result"].reason

    def assign() -> str:
        step = approvals.current_step(db, bill.bill_id)
        if bill.status not in ("needs_review", "on_hold", "pending_approval") or step is None or step.user_id:
            raise _No("No approval step is waiting for an approver to be assigned.")
        return f"Step {step.step_no} ({step.role}) has no approver."

    def void() -> str:
        allowed = EDITABLE + (("pending_approval", "approved") if user.role == CONTROLLER_ADMIN else ())
        if bill.status not in allowed:
            raise _No(f"A {bill.status} bill can't be voided by your role.")
        return None

    def schedule() -> str:
        payments.schedule_check(db, bill)
        return None

    checks = {"edit": lambda: _editable(bill), "code_lines": lambda: _editable(bill), "resolve_flags": resolve,
              "override_blocking_flags": override_blocking, "submit": submit, "approve": decide, "reject": decide,
              "assign_step": assign, "void": void, "schedule_payment": schedule}
    actions = {name: _answer(user, name, BILL_ACTION_ROLES[name], check) for name, check in checks.items()}
    actions["view_document"] = document_action(db, user, bill)
    return actions


def payment_actions(db: Session, user: CurrentUser, p: models.Payment) -> dict[str, ActionState]:
    def release() -> str:
        permission, _ = payments.release_check(db, user, p)
        return permission.reason

    def cancel() -> str:
        if p.status != "scheduled":
            raise _No(f"The payment is {p.status}; only a scheduled payment can be cancelled.")
        return None

    checks = {"release": release, "cancel": cancel}
    return {name: _answer(user, name, PAYMENT_ACTION_ROLES[name], check) for name, check in checks.items()}
