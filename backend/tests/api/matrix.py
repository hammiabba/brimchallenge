"""
The permission matrix: every endpoint x every role, with the expected status.

This is written out by hand from the role table in the hackathon brief, not derived from the route code, so the
test catches a route whose role gate drifts from the spec.

`allowed` lists the roles that pass the role gate (E employee, C ap_clerk, A approver, F finance_manager,
X controller_admin, Au auditor). Allowed roles expect `ok` (501 while an endpoint is a stub); every other role
expects 403. Without a session every endpoint returns 401 (checked separately for all operations in the spec).
`scoped` cases also list per-role statuses for out-of-scope objects (404), filled in as reads become real.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.api.conftest import IN_SCOPE_BILL, OUT_OF_SCOPE_BILL

TOKENS = {"E": "employee", "C": "ap_clerk", "A": "approver", "F": "finance_manager", "X": "controller_admin",
          "Au": "auditor"}
ALL = "E C A F X Au"
STUB = 501

PDF = ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")


@dataclass(frozen=True)
class Case:
    method: str
    path: str
    allowed: str
    ok: int = STUB
    kwargs: dict[str, Any] = field(default_factory=dict)
    # Overrides for specific roles, e.g. {"employee": 404} when the object is outside their scope.
    overrides: dict[str, int] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"

    def expected(self, role: str) -> int:
        if role in self.overrides:
            return self.overrides[role]
        allowed = {TOKENS[t] for t in self.allowed.split()}
        return self.ok if role in allowed else 403


B = IN_SCOPE_BILL
OUT = OUT_OF_SCOPE_BILL
RV = {"row_version": 1}

CASES: list[Case] = [
    # auth (the picker list and login are public)
    Case("GET", "/auth/me", ALL, ok=200),
    Case("POST", "/auth/logout", ALL, ok=204),
    # bills
    Case("GET", "/bills", ALL, ok=200),
    Case("GET", f"/bills/{B}", ALL, ok=200),
    # Out of scope for the D01 employee and approver: 404, never 403, so existence doesn't leak.
    Case("GET", f"/bills/{OUT}", ALL, ok=200, overrides={"employee": 404, "approver": 404}),
    Case("GET", "/bills/AP-99999", ALL, ok=404),
    Case("PATCH", f"/bills/{B}", "C", kwargs={"json": {**RV, "due_date": "2026-12-01"}}),
    Case("PATCH", f"/bills/{B}/lines/1", "C", kwargs={"json": {**RV, "gl_account": "5010", "department_id": "D01"}}),
    Case("POST", f"/bills/{B}/flags/1/resolve", "C F X",
         kwargs={"json": {**RV, "resolution": "overridden", "comment": "checked with vendor"}}),
    Case("POST", f"/bills/{B}/submit", "C", kwargs={"json": RV}),
    Case("POST", f"/bills/{B}/approve", "A F X", kwargs={"json": RV}),
    Case("POST", f"/bills/{B}/reject", "A F X", kwargs={"json": {**RV, "comment": "wrong department"}}),
    Case("POST", f"/bills/{B}/route/1/assign", "F X", kwargs={"json": {**RV, "user_id": "U007"}}),
    Case("POST", f"/bills/{B}/void", "C X", kwargs={"json": {**RV, "comment": "duplicate"}}),
    Case("GET", "/approvals/queue", "A F X", ok=200),
    # intake
    Case("POST", "/submissions", "E C", kwargs={"files": {"file": PDF}}),
    Case("GET", "/submissions", "E C", ok=200),
    Case("POST", "/intake/inbox/jobs", "C"),
    Case("GET", "/intake/inbox/jobs/job-1", "C F X Au"),
    Case("GET", "/intake/items", "C F X Au", ok=200),
    # payments
    Case("GET", "/payments", "C F X Au", ok=200),
    Case("GET", "/payments/summary", "C F X Au", ok=200),
    Case("GET", "/payments/PAY-00001", "C F X Au", ok=200),
    Case("GET", "/payments/PAY-99999", "C F X Au", ok=404),
    Case("POST", f"/bills/{B}/payments", "C", kwargs={"json": {"scheduled_date": "2026-11-10"}}),
    Case("POST", "/payments/PAY-00001/release", "F X", kwargs={"headers": {"Idempotency-Key": "release-test-0001"}}),
    Case("POST", "/payments/PAY-00001/cancel", "C F X", kwargs={"json": {"comment": "vendor asked to wait"}}),
    # vendors and bank changes
    Case("GET", "/vendors", ALL, ok=200),
    Case("GET", "/vendors/V001", ALL, ok=200),
    Case("GET", "/vendors/V999", ALL, ok=404),
    Case("POST", "/vendors", "C", ok=201, kwargs={"json": {
        "legal_name": "Test Supplies Inc.", "category": "Office Supplies", "address": "1 King St W, Toronto ON",
        "province_or_state": "ON", "country": "CA", "ap_contact_email": "ar@test-supplies.example"}}),
    Case("POST", "/vendors/V054/approve", "F X", ok=200, kwargs={"json": {}}),  # V054 is pending_review
    Case("POST", "/vendors/V001/hold", "C F X", ok=200, kwargs={"json": {"comment": "pending review"}}),
    Case("POST", "/vendors/V001/bank-changes", "C", ok=201, kwargs={"json": {
        "institution": "004", "transit": "05541", "account": "1234567", "request_channel": "phone_callback_verified"}}),
    Case("GET", "/bank-changes", "C F X Au", ok=200),
    Case("POST", "/bank-changes/BC-009/verify", "F X", ok=200, kwargs={"json": {}}),
    Case("POST", "/bank-changes/BC-009/reject", "F X", ok=200, kwargs={"json": {"comment": "no callback"}}),
    # spend, delegation, admin
    Case("GET", "/spend", "A C F X Au", ok=200),
    Case("PUT", "/me/delegation", "A F X", ok=200,
         kwargs={"json": {"delegate_user_id": "U001", "starts_on": "2026-11-10"}}),
    Case("GET", "/admin/policies", "X Au", ok=200),
    Case("PATCH", "/admin/policies/P01", "X", ok=200, kwargs={"json": {"notes": "reviewed"}}),
    Case("GET", "/admin/users", "X Au", ok=200),
    Case("PATCH", "/admin/users/U013", "X", ok=200, kwargs={"json": {"approval_limit_cad": "1000.00"}}),
    Case("GET", "/admin/absences", "X Au", ok=200),
    Case("POST", "/admin/absences", "X", ok=201, kwargs={"json": {
        "user_id": "U007", "delegate_user_id": "U003", "starts_on": "2026-11-10"}}),
    # audit
    Case("GET", "/audit", "X Au", ok=200),
    Case("GET", "/audit/bill/" + B, "X Au", ok=200),
    Case("GET", "/audit/export", "X Au", ok=200),
    # intake lane's router, guarded at mount time in app/main.py
    Case("GET", "/intake/drafts", "C F X", ok=200),
]
