"""Fields and endpoints the UI asked for: allowed_actions, queue fields, limits on /auth/me, flag help, reference
lists, the inbox email view, duplicates on the controls run, and UTC timestamps with Z."""
from __future__ import annotations

import re

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import as_write_engine
from app.db.types import utcnow
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
    # The reason names the blocking flag by its title, not its code.
    assert not a["submit"]["allowed"] and "Bank details differ" in a["submit"]["reason"]
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


def test_bill_detail_carries_the_current_step_like_the_queue(fresh_engine, act_as):
    # D07's manager U012 is on leave, so step 1 goes to U003 as the delegate (P08).
    bill = app_bill(fresh_engine, dept="D07", requester="U037")
    clerk = act_as("U004")
    rv = detail(clerk, bill)["row_version"]
    submitted = clerk.post(f"/bills/{bill}/submit", json={"row_version": rv}).json()
    want = {"step_no": 1, "role": "dept_manager", "user_id": "U003", "delegated_from": "U012"}
    assert submitted["current_step"] == want  # the submit answer says who step 1 goes to
    fm = act_as("U003")
    shown = fm.get(f"/bills/{bill}").json()
    assert shown["current_step"] == want
    [row] = fm.get("/approvals/queue").json()
    assert row["current_step"] == shown["current_step"]
    assert shown["open_flags"] == row["open_flags"] and shown["top_flag_code"] == row["top_flag_code"]
    # Once the last step is signed there is no current step.
    fm.post(f"/bills/{bill}/approve", json={"row_version": shown["row_version"]})
    approved = fm.get(f"/bills/{bill}").json()
    assert approved["status"] == "approved" and approved["current_step"] is None


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


def test_view_document_needs_a_kept_file_and_a_role_that_may_open_files(fresh_engine, act_as):
    bill = app_bill(fresh_engine)  # the factory's "sha256:APP-0001" isn't a file intake kept
    assert detail(act_as("U004"), bill)["allowed_actions"]["view_document"] == {
        "allowed": False, "reason": "No original file for this bill."}

    # Give the bill an original file, as intake does: a sha256 hash that an intake item references.
    file_hash = "ab" * 32
    with Session(as_write_engine(fresh_engine)) as s:
        s.execute(update(models.Bill).where(models.Bill.bill_id == bill).values(file_hash=file_hash))
        s.add(models.IntakeItem(email_id=None, file_name="APP-0001.pdf", file_hash=file_hash, status="ok", error=None,
                                warnings=[], bill_id=bill, created_at=utcnow(), created_by="U004"))
        s.commit()

    # The roles GET /intake/files/{hash} admits (AP, finance, controller, auditor) may open it; others may not.
    for user_id in ("U004", "U003", "U001", "U006"):
        assert detail(act_as(user_id), bill)["allowed_actions"]["view_document"] == {"allowed": True, "reason": None}
    for user_id in ("U013", "U007"):  # the D01 employee and approver can see the bill but not the file
        assert detail(act_as(user_id), bill)["allowed_actions"]["view_document"] == {
            "allowed": False, "reason": "Your role can't open original files."}


def test_view_document_is_refused_for_history_bills(login):
    actions = login("U004").get("/bills/AP-00407").json()["allowed_actions"]
    assert actions["view_document"] == {"allowed": False, "reason": "No original file for this bill."}
