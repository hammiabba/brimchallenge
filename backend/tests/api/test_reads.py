"""Read endpoints: department scope, 404 for out-of-scope objects, bank masking, money as strings, pagination."""
from __future__ import annotations

import re

from app.services.masking import mask_draft
from tests.api.conftest import IN_SCOPE_BILL, OUT_OF_SCOPE_BILL

MONEY = re.compile(r"^-?\d+\.\d{2}$")


def test_employee_sees_only_own_department(as_role):
    page = as_role("employee").get("/bills", params={"limit": 200}).json()
    assert page["total"] == 148  # D01 bills in the seed
    assert {b["department_id"] for b in page["items"]} == {"D01"}


def test_employee_cannot_widen_scope_with_a_filter(as_role):
    page = as_role("employee").get("/bills", params={"department_id": "D05"}).json()
    assert page["total"] == 0


def test_approver_sees_own_department(as_role):
    page = as_role("approver").get("/bills", params={"limit": 1}).json()
    assert page["total"] == 148


def test_back_office_sees_everything(as_role):
    for role in ("ap_clerk", "finance_manager", "controller_admin", "auditor"):
        assert as_role(role).get("/bills", params={"limit": 1}).json()["total"] == 426


def test_out_of_scope_bill_looks_like_a_missing_one(as_role):
    client = as_role("employee")
    hidden = client.get(f"/bills/{OUT_OF_SCOPE_BILL}")
    missing = client.get("/bills/AP-99999")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["code"] == missing.json()["error"]["code"] == "bill.not_found"


def test_bill_detail_has_lines_taxes_decisions_and_payments(as_role):
    d = as_role("employee").get(f"/bills/{IN_SCOPE_BILL}").json()
    assert d["bill_id"] == IN_SCOPE_BILL
    assert d["lines"] and d["decisions"] and d["payments"]
    assert MONEY.match(d["total"]) and MONEY.match(d["subtotal"]) and MONEY.match(d["lines"][0]["amount"])
    assert isinstance(d["row_version"], int)
    assert d["latest_run"] is None  # history bills have no controls run stored


def test_filters_and_pagination(as_role):
    client = as_role("ap_clerk")
    page = client.get("/bills", params={"status": "scheduled", "limit": 5}).json()
    assert page["total"] == 18 and len(page["items"]) == 5 and page["limit"] == 5
    assert {b["status"] for b in page["items"]} == {"scheduled"}
    nxt = client.get("/bills", params={"status": "scheduled", "limit": 5, "offset": 5}).json()
    assert {b["bill_id"] for b in page["items"]}.isdisjoint({b["bill_id"] for b in nxt["items"]})
    assert client.get("/bills", params={"limit": 500}).status_code == 422


def test_search_by_vendor_name(as_role):
    page = as_role("ap_clerk").get("/bills", params={"q": "Polar"}).json()
    assert page["total"] > 0
    assert {b["vendor_id"] for b in page["items"]} <= {"V001", "V051"}  # V051 is a lookalike vendor


def test_bank_numbers_are_masked_except_for_ap_finance_controller(as_role):
    full = {}
    for role in ("employee", "approver", "auditor", "ap_clerk", "finance_manager", "controller_admin"):
        acct = as_role(role).get("/vendors/V001").json()["bank_account"]
        full[role] = acct["account"]
        assert acct["masked"] == (role in ("employee", "approver", "auditor"))
    assert full["ap_clerk"] == full["finance_manager"] == full["controller_admin"]
    assert "*" not in full["ap_clerk"]
    for role in ("employee", "approver", "auditor"):
        assert full[role].startswith("*") and full[role][-4:] == full["ap_clerk"][-4:]
        assert full["ap_clerk"] not in full[role]


def test_payment_trace_masks_for_auditor(as_role):
    d = as_role("auditor").get("/payments/PAY-00001").json()
    assert d["bill"]["bill_id"] and d["decisions"]
    assert d["bank_account"] is None or d["bank_account"]["masked"] is True
    assert MONEY.match(d["amount"]) and MONEY.match(d["discount_taken"])


def test_extraction_snapshot_masks_invoice_bank_account():
    draft = {"vendor": {"bank": {"institution": "010", "transit": "40238", "account": "593014216"}}}
    assert mask_draft("auditor", draft)["vendor"]["bank"]["account"] == "*****4216"
    assert draft["vendor"]["bank"]["account"] == "593014216"  # original untouched
    assert mask_draft("ap_clerk", draft)["vendor"]["bank"]["account"] == "593014216"


def test_payment_dashboard_adds_up(as_role):
    d = as_role("finance_manager").get("/payments/summary").json()
    assert sum(r["count"] for r in d["by_status"]) == 415
    assert all(MONEY.match(r["total_cad"]) for r in d["by_status"])
    assert d["as_of"] == "2026-11-02"


def test_spend_is_limited_to_the_approvers_department(as_role):
    r = as_role("approver").get("/spend", params={"department_id": "D05"}).json()
    assert r["department_id"] == "D01"
    assert [row["key"] for row in r["rows"]] == ["D01"]
    assert MONEY.match(r["total_cad"])


def test_spend_by_gl_account(as_role):
    r = as_role("controller_admin").get("/spend", params={"group_by": "gl_account"}).json()
    assert r["rows"] and all(MONEY.match(row["total_cad"]) for row in r["rows"])


def test_vendor_list_and_bank_changes(as_role):
    client = as_role("ap_clerk")
    assert client.get("/vendors", params={"limit": 200}).json()["total"] == 56
    pending = client.get("/bank-changes", params={"status": "pending_verification"}).json()
    assert [c["change_id"] for c in pending] == ["BC-009"]


def test_admin_users_show_limits_as_money(as_role):
    users = {u["user_id"]: u for u in as_role("auditor").get("/admin/users").json()}
    assert users["U001"]["approval_limit_cad"] == "500000.00"
    assert users["U015"]["status"] == "terminated"


def test_audit_export_is_csv_and_is_itself_audited(as_role):
    client = as_role("auditor")
    r = client.get("/audit/export", params={"action": "auth.login"})
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("seq,event_id,at,actor_user_id")
    page = client.get("/audit", params={"action": "audit.exported", "limit": 500}).json()
    last = page["items"][-1]
    assert last["actor_user_id"] == "U006"
    assert last["after"]["filters"] == {"action": "auth.login"}
    assert last["after"]["chain_head"]["seq"] >= 1


def test_audit_list_pages_by_seq(as_role):
    client = as_role("controller_admin")
    first = client.get("/audit", params={"limit": 1}).json()
    assert len(first["items"]) == 1 and first["next_after_seq"] == first["items"][0]["seq"]
    second = client.get("/audit", params={"limit": 1, "after_seq": first["next_after_seq"]}).json()
    assert second["items"][0]["seq"] > first["items"][0]["seq"]
