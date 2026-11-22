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


def test_mine_lists_only_the_callers_own_requests(as_role):
    # U013 (the employee) is the requester on some D01 bills; mine=true keeps exactly those, inside the usual scope.
    everything = as_role("employee").get("/bills", params={"limit": 200}).json()
    mine = as_role("employee").get("/bills", params={"limit": 200, "mine": "true"}).json()
    own = {b["bill_id"] for b in everything["items"] if b["requester_user_id"] == "U013"}
    assert own and {b["bill_id"] for b in mine["items"]} == own
    assert mine["total"] == len(own)


def test_mine_is_off_by_default(as_role):
    assert as_role("employee").get("/bills", params={"limit": 1, "mine": "false"}).json()["total"] == 148


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


def _scheduled(client, **params) -> list[dict]:
    """Every scheduled payment in one call (the seed has fewer than 200)."""
    return client.get("/payments", params={"status": "scheduled", "limit": 200, **params}).json()["items"]


def _date_then_id(payment: dict) -> tuple[str, str]:
    return payment["scheduled_date"], payment["payment_id"]


def test_payments_default_order_is_unchanged_newest_first(as_role):
    fm = as_role("finance_manager")
    default = _scheduled(fm)
    newest_first = sorted(default, key=_date_then_id, reverse=True)
    assert [p["payment_id"] for p in default] == [p["payment_id"] for p in newest_first]
    assert [p["payment_id"] for p in _scheduled(fm, sort="scheduled_desc")] == [p["payment_id"] for p in default]


def test_payments_sorted_oldest_first_start_at_pay_00391(as_role):
    items = _scheduled(as_role("finance_manager"), sort="scheduled_asc")
    assert (items[0]["payment_id"], items[0]["scheduled_date"]) == ("PAY-00391", "2026-11-01")
    assert [p["payment_id"] for p in items] == [p["payment_id"] for p in sorted(items, key=_date_then_id)]


def test_payment_pages_neither_overlap_nor_skip_across_a_tie(as_role):
    fm = as_role("finance_manager")
    for sort in ("scheduled_asc", "scheduled_desc"):
        whole = _scheduled(fm, sort=sort)
        paged: list[dict] = []
        offset = 0
        while True:
            params = {"status": "scheduled", "sort": sort, "limit": 3, "offset": offset}
            page = fm.get("/payments", params=params).json()
            paged.extend(page["items"])
            offset += 3
            if offset >= page["total"]:
                break
        ids = [p["payment_id"] for p in paged]
        assert ids == [p["payment_id"] for p in whole]
        assert len(set(ids)) == len(ids)
        # The payments scheduled on Nov 2 (four in the seed) straddle a page boundary of 3.
        tie = [i for i, p in enumerate(whole) if p["scheduled_date"] == "2026-11-02"]
        assert len(tie) >= 2 and tie[0] // 3 != tie[-1] // 3


def test_payments_sort_refuses_an_unknown_value_without_echoing_it(as_role):
    r = as_role("finance_manager").get("/payments", params={"sort": "bogus"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "request.invalid"
    assert [d["loc"] for d in err["details"]] == [["query", "sort"]]
    assert "bogus" not in r.text


def test_vendors_mark_the_suspicious_copy_of_a_lookalike_pair(as_role):
    # The VENDOR_LOOKALIKE control's own rule: V051/V052/V053 copy V001/V026/V002 by name; the real vendors are clean.
    page = as_role("ap_clerk").get("/vendors", params={"limit": 200}).json()
    marked = {v["vendor_id"]: [(o["vendor_id"], o["why"]) for o in v["lookalike_of"]]
              for v in page["items"] if v["lookalike_of"]}
    same_name = "same name once 'Ltd/Inc/&' are ignored"
    assert marked == {"V051": [("V001", same_name)], "V052": [("V026", same_name)], "V053": [("V002", same_name)]}
    detail = as_role("employee").get("/vendors/V053").json()
    assert detail["lookalike_of"] == [
        {"vendor_id": "V002", "legal_name": "Great Lakes Carriers Inc.", "why": same_name}]
    assert as_role("employee").get("/vendors/V002").json()["lookalike_of"] == []
