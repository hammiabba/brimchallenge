"""route(bill, ref, flags) -> list[ApprovalStep]
can_approve(user_id, step, bill, ref, route=...) -> PermissionDecision
can_release(user_id, amount_cad, approver_ids, flags, approval_complete, ref, bill=...) -> PermissionDecision

All thresholds and role chains come from approval_policies (ref.policies), so an
admin can edit the rules without touching code.
"""
from __future__ import annotations

from decimal import Decimal

from app.shared.schemas import ApprovalStep, DraftBill, Flag, PermissionDecision, Severity

from .refdata import RefData, currency, is_credit, vendor_id
from .validate import amount_for_limits, has_blocking
from .wording import flag_titles, human_date, role_group

APPROVER_ROLES = {"approver", "finance_manager", "controller_admin"}
# Which user roles may sign a step of each kind. Escalation only goes up, so higher roles may sign lower steps.
STEP_ROLES = {
    "dept_manager": APPROVER_ROLES,
    "finance_manager": {"finance_manager", "controller_admin"},
    "controller_admin": {"controller_admin"},
    "cfo": {"controller_admin"},
}

EXTRA_REASON = {
    "P05": "Vendor is new or pending review",
    "P06": "Legal vendor needs finance approval",
    "P12": "Invoice is over the PO's remaining balance",
}


# ---------------------------------------------------------------------------
# Who holds each role
# ---------------------------------------------------------------------------
def _role_holder(role: str, dept_id: str | None, ref: RefData) -> str | None:
    if role == "dept_manager":
        dept = ref.departments.get(dept_id or "")
        return dept["manager_user_id"] if dept else None
    if role == "cfo":
        u = next((u for u in ref.users.values() if "Chief Financial" in u["title"]), None)
        return u["user_id"] if u else None
    if role == "controller_admin":
        # The controller, not the CFO (the CFO is also controller_admin but sits above).
        u = next((u for u in ref.users_with_role("controller_admin") if "Chief Financial" not in u["title"]), None)
        return u["user_id"] if u else None
    u = next((u for u in ref.users_with_role(role) if u["status"] == "active"), None)
    return u["user_id"] if u else None


def _manager_of(user_id: str, ref: RefData) -> str | None:
    return ref.users[user_id]["manager_id"] or None


# ---------------------------------------------------------------------------
# Building the chain
# ---------------------------------------------------------------------------
def _amount_tier(amount: Decimal, ref: RefData) -> tuple[str, list[str], str]:
    """Picks the highest P01..P04 rule the amount falls under. Returns (rule_id, [roles], reason)."""
    tiers = [p for p in ref.policies.values()
             if p.rule_type == "approval" and p.threshold is not None and p.condition.startswith("Invoice total")]
    over = [p for p in tiers if "over" in p.condition and amount > p.threshold]
    if over:
        best = max(over, key=lambda p: p.threshold)            # e.g. $60k matches P02 and P03 -> P03
        reason = f"Total ${amount:,.2f} > ${best.threshold:,.0f}"
    else:
        best = next(p for p in tiers if "up to" in p.condition)  # P01
        reason = f"Total ${amount:,.2f} ≤ ${best.threshold:,.0f}"
    roles = [r.strip() for r in best.required.split(">")]
    return best.rule_id, roles, reason


def _extra_finance_reasons(bill: DraftBill, ref: RefData, flags: list[Flag]) -> list[str]:
    reasons = []
    v = ref.vendors.get(vendor_id(bill) or "")
    if v is None or v["status"] == "pending_review":
        reasons.append("P05")
    if v and v["category"] == "Legal":
        reasons.append("P06")
    if any(f.code == "PO_OVER_BALANCE" for f in flags):
        reasons.append("P12")
    return reasons


def route(bill: DraftBill, ref: RefData, flags: list[Flag] | None = None,
          amount_cad: Decimal | None = None) -> list[ApprovalStep]:
    """Returns the ordered approval steps for a bill.

    amount_cad: pass the combined amount when find_split() flagged a split, so the
    group is routed as one bill (run_controls does this).
    """
    flags = flags or []
    fx_note = None
    if amount_cad is None:
        amount_cad, converted = amount_for_limits(bill, ref)
        if not converted:
            fx_note = (f"CAD amount unknown (no {currency(bill)}/CAD rate); routed on the face amount. "
                       f"Re-route once converted.")
    amount = abs(amount_cad)
    requester = bill.requester_user_id
    dept = bill.department_id or (ref.users[requester]["department_id"] if requester in ref.users else None)

    tier_rule, roles, tier_reason = _amount_tier(amount, ref)
    planned: list[tuple[str, list[str], list[str]]] = [(r, [tier_rule], [tier_reason]) for r in roles]

    extra = _extra_finance_reasons(bill, ref, flags)
    if extra:
        extra_reasons = [EXTRA_REASON[p] for p in extra]
        fm = next((p for p in planned if p[0] == "finance_manager"), None)
        if fm:
            fm[1].extend(extra)
            fm[2].extend(extra_reasons)
        else:
            planned.insert(1 if planned and planned[0][0] == "dept_manager" else 0,
                           ("finance_manager", list(extra), extra_reasons))

    steps: list[ApprovalStep] = []
    used: set[str] = set()
    for n, (role, policies, reasons) in enumerate(planned, 1):
        r = _resolve(_role_holder(role, dept, ref), amount, n == len(planned), requester, used, ref)
        if r.uid:
            used.add(r.uid)
        else:
            r.notes.append("No eligible approver found. AP needs to assign one manually.")
        steps.append(ApprovalStep(step_no=n, role=role, user_id=r.uid or "UNASSIGNED",
                                  policy_ids=policies + [p for p in r.policies if p not in policies],
                                  reason="; ".join(reasons + r.notes + ([fx_note] if fx_note else [])),
                                  delegated_from=r.delegated_from, escalated_from=r.escalated_from))
    return steps


class _Resolution:
    def __init__(self) -> None:
        self.uid: str | None = None
        self.notes: list[str] = []
        self.policies: list[str] = []
        self.delegated_from: str | None = None
        self.escalated_from: str | None = None


def _resolve(uid: str | None, amount: Decimal, is_last: bool, requester: str | None,
             used: set[str], ref: RefData) -> _Resolution:
    """Walks up from the role holder until someone can legally sign this step."""
    r = _Resolution()

    def escalate(to: str | None) -> str | None:
        r.delegated_from = None  # whoever signs now is not acting as anyone's delegate
        return to

    for _ in range(10):  # org chart is shallow, this just prevents infinite loops
        if not uid or uid not in ref.users:
            return r
        u = ref.users[uid]
        if uid == requester:
            r.notes.append(f"{u['full_name']} requested this bill, so it escalates to their manager.")
            r.policies.append("P07")
            r.escalated_from = uid
            uid = escalate(_manager_of(uid, ref))
            continue
        if u["status"] == "terminated":
            r.notes.append(f"{u['full_name']} no longer works here; escalated to their manager.")
            uid = escalate(_manager_of(uid, ref))
            continue
        if u["status"] == "on_leave":
            if u["delegate_user_id"]:
                r.notes.append(f"{u['full_name']} is on leave (since {human_date(u['status_since'])}), so "
                               f"{ref.users[u['delegate_user_id']]['full_name']} approves as delegate.")
                r.policies.append("P08")
                r.delegated_from = uid
                uid = u["delegate_user_id"]
            else:
                r.notes.append(f"{u['full_name']} is on leave with no delegate; escalated.")
                uid = escalate(_manager_of(uid, ref))
            continue
        if uid in used:
            r.notes.append(f"{u['full_name']} already signs another step on this bill; "
                           f"one person can't fill two steps, so it goes to their manager.")
            uid = escalate(_manager_of(uid, ref))
            continue
        # Only the final signer needs a limit that covers the whole bill; earlier steps are reviews.
        if is_last and Decimal(u["approval_limit_cad"] or 0) < amount:
            r.notes.append(f"{u['full_name']}'s limit (${Decimal(u['approval_limit_cad'] or 0):,.0f}) "
                           f"is below ${amount:,.2f}; escalated.")
            uid = escalate(_manager_of(uid, ref))
            continue
        r.uid = uid
        return r
    return r


# ---------------------------------------------------------------------------
# Permission checks (call these on the server for every action)
# ---------------------------------------------------------------------------
def can_approve(user_id: str, step: ApprovalStep, bill: DraftBill, ref: RefData, *,
                route: list[ApprovalStep], amount_cad: Decimal | None = None) -> PermissionDecision:
    """May `user_id` sign `step` of `route` now? Re-checks the user's current record, not just the route.

    amount_cad: the amount the route was built for (the combined amount for a split); defaults to the bill's.
    Only the final signer's limit has to cover the amount, the same rule route() uses.
    """
    u = ref.users.get(user_id)
    if not u or u["status"] != "active":
        return PermissionDecision(allowed=False, reason=f"{user_id} is not an active user.")
    if user_id == bill.requester_user_id:
        return PermissionDecision(allowed=False,
                                  reason=f"{user_id} requested this bill, so they can't approve it (P07).")
    if user_id != step.user_id:
        return PermissionDecision(allowed=False, reason=f"This step is assigned to {step.user_id}.")
    allowed_roles = STEP_ROLES.get(step.role, APPROVER_ROLES)
    if u["role"] not in allowed_roles:
        return PermissionDecision(allowed=False,
                                  reason=f"{user_id}'s role '{u['role']}' can't sign a {step.role} step.")
    if route and step.step_no == max(s.step_no for s in route):
        amount = abs(amount_cad if amount_cad is not None else amount_for_limits(bill, ref)[0])
        limit = Decimal(u["approval_limit_cad"] or 0)
        if limit < amount:
            return PermissionDecision(allowed=False,
                                      reason=f"{user_id}'s approval limit (${limit:,.0f}) is below ${amount:,.2f}.")
    if step.delegated_from:
        return PermissionDecision(allowed=True,
                                  reason=f"{user_id} approves as delegate for {step.delegated_from} (P08).")
    return PermissionDecision(allowed=True, reason=f"{user_id} is the assigned approver for step {step.step_no}.")


def _release_threshold(ref: RefData) -> Decimal:
    p = next(p for p in ref.policies.values() if p.rule_type == "payment_release" and p.required == "finance_manager")
    return p.threshold


def can_release(user_id: str, amount_cad: Decimal, approver_ids: set[str], flags: list[Flag],
                approval_complete: bool, ref: RefData, *, bill: DraftBill) -> PermissionDecision:
    """flags must include the duplicate/split flags (run_controls(...).flags does), or duplicates won't hold payment.

    bill is required: the requester check and the credit-note check need it.

    The reasons speak to `user_id` ("You approved this bill ..."): they are shown to the person asking to release,
    as a refusal or as the reason the Release button is missing.
    """
    u = ref.users.get(user_id)
    if not u or u["status"] != "active":
        return PermissionDecision(allowed=False, reason="Your account isn't active, so you can't release payments.")
    if is_credit(bill) or amount_cad < 0 or any(f.code == "CREDIT_NOTE" for f in flags):
        return PermissionDecision(allowed=False,
                                  reason="This is a credit note: apply it against an open invoice, don't pay it.")
    if user_id == bill.requester_user_id:
        return PermissionDecision(allowed=False,
                                  reason="You requested this bill, so someone else must release its payment.")
    if not approval_complete:
        return PermissionDecision(allowed=False, reason="The bill isn't fully approved yet.")
    if has_blocking(flags):
        open_blocks = [f.code for f in flags if f.severity == Severity.BLOCK]
        return PermissionDecision(allowed=False,
                                  reason=f"On hold until these flags are cleared: {flag_titles(open_blocks)}.")
    if user_id in approver_ids:
        return PermissionDecision(allowed=False,
                                  reason="You approved this bill, so another finance manager or the controller must "
                                         "release it (policy P11).")
    limit = _release_threshold(ref)
    if u["role"] == "finance_manager":
        if abs(amount_cad) <= limit:
            return PermissionDecision(allowed=True, reason=f"Finance manager may release up to ${limit:,.0f} (P09).")
        return PermissionDecision(allowed=False, reason=f"Payments over ${limit:,.0f} need the controller (P10).")
    if u["role"] == "controller_admin":
        return PermissionDecision(allowed=True, reason="Controller may release any amount (P10).")
    return PermissionDecision(allowed=False, reason=f"{role_group(u['role'])} can't release payments.")
