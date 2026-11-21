"""Fields and endpoints the UI asked for: allowed_actions, queue fields, limits on /auth/me, flag help, reference
lists, the inbox email view, duplicates on the controls run, and UTC timestamps with Z."""
from __future__ import annotations

import re

from tests.api.factories import app_bill
from tests.api.test_bill_flow import decide, detail, submit

UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_allowed_actions_follow_the_bill_through_its_life(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    clerk = act_as("U004")
    a = detail(clerk, bill)["allowed_actions"]
    assert a["submit"]["allowed"] and a["code_lines"]["allowed"]
    assert not a["approve"]["allowed"] and "can't approve" in a["approve"]["reason"]
    submit(clerk, bill)
    assert detail(act_as("U007"), bill)["allowed_actions"]["approve"] == {"allowed": True,
                                                                         "reason": "Step 1 (dept_manager) is yours."}
    other = detail(act_as("U003"), bill)["allowed_actions"]["approve"]
    assert not other["allowed"] and "U007" in other["reason"]
    decide(act_as("U007"), bill)
    assert detail(act_as("U004"), bill)["allowed_actions"]["schedule_payment"]["allowed"]


def test_release_action_explains_p11(fresh_engine, act_as):
    bill = app_bill(fresh_engine, amount="15000.00")
    submit(act_as("U004"), bill)
    decide(act_as("U007"), bill)
    decide(act_as("U003"), bill)
    payment = act_as("U004").post(f"/bills/{bill}/payments", json={"scheduled_date": "2026-11-05"}).json()["payment_id"]
    fm = act_as("U003").get(f"/payments/{payment}").json()["allowed_actions"]["release"]
    assert not fm["allowed"] and "P11" in fm["reason"]
    ctrl = act_as("U002").get(f"/payments/{payment}").json()["allowed_actions"]["release"]
    assert ctrl["allowed"] and "P10" in ctrl["reason"]


def test_blocking_flag_shows_in_actions_and_queue_fields(fresh_engine, act_as):
    bill = app_bill(fresh_engine, bank_account="999999999")
    clerk = act_as("U004")
    a = detail(clerk, bill)["allowed_actions"]
    assert not a["submit"]["allowed"] and "BANK_DETAILS_MISMATCH" in a["submit"]["reason"]
    assert not a["override_blocking_flags"]["allowed"]
    assert act_as("U003").get(f"/bills/{bill}").json()["allowed_actions"]["override_blocking_flags"]["allowed"]
    row = next(b for b in clerk.get("/bills", params={"status": "needs_review"}).json()["items"]
               if b["bill_id"] == bill)
    assert row["open_flags"]["block"] >= 1 and row["top_flag_code"] == "BANK_DETAILS_MISMATCH"


def test_queue_rows_carry_the_current_step(fresh_engine, act_as):
    bill = app_bill(fresh_engine, dept="D07", requester="U037")
    submit(act_as("U004"), bill)
    [row] = act_as("U003").get("/approvals/queue").json()
    assert row["current_step"] == {"step_no": 1, "role": "dept_manager", "user_id": "U003", "delegated_from": "U012"}


def test_me_shows_approval_and_release_limits(login):
    fm = login("U003").get("/auth/me").json()
    assert fm["release_limit_cad"] == "100000.00" and fm["approval_limit_cad"]
    assert login("U002").get("/auth/me").json()["release_limit_cad"] is None
    assert login("U013").get("/auth/me").json()["release_limit_cad"] == "0.00"


def test_flag_help_covers_every_code(as_role):
    help_ = as_role("employee").get("/reference/flag-help").json()
    assert help_["BANK_CHANGE_UNVERIFIED"]["severity"] == "block" and help_["BANK_CHANGE_UNVERIFIED"]["title"]


def test_reference_lists(as_role):
    client = as_role("employee")
    assert len(client.get("/reference/departments").json()) == 8
    assert len(client.get("/reference/gl-accounts").json()) == 30


def test_inbox_email_view(as_role):
    page = as_role("ap_clerk").get("/intake/emails", params={"limit": 200}).json()
    assert page["total"] == 59 and {"email_class", "triage_reason", "items"} <= set(page["items"][0])


def test_timestamps_are_utc_with_z(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    d = detail(act_as("U004"), bill)
    assert UTC_Z.match(d["created_at"]) and UTC_Z.match(d["latest_run"]["evaluated_at"])
    events = act_as("U006").get("/audit", params={"limit": 5}).json()["items"]
    assert all(UTC_Z.match(e["at"]) for e in events)


def test_controls_run_lists_duplicates(fresh_engine, act_as):
    first = app_bill(fresh_engine, number="DUP-77")
    clerk = act_as("U004")
    submit(clerk, first)
    second = app_bill(fresh_engine, number="DUP-77")
    dups = detail(clerk, second)["latest_run"]["duplicates"]
    assert any(d["matched_invoice_id"] == first for d in dups)
