"""Vendor onboarding, approval, hold, and controlled bank-detail changes."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.errors import ApiError
from app.auth.deps import load_current_user
from app.db import models
from app.main import app
from app.services import vendors

NEW_VENDOR = {"legal_name": "Test Supplies Inc.", "category": "Office Supplies", "address": "1 King St W, Toronto ON",
              "province_or_state": "ON", "country": "CA", "ap_contact_email": "ar@test-supplies.example"}
NEW_BANK = {"institution": "004", "transit": "05541", "account": "123456789", "request_channel": "vendor_portal"}


def events_for(db, request_id: str) -> list[models.AuditEvent]:
    with db() as s:
        return list(s.scalars(select(models.AuditEvent).where(models.AuditEvent.request_id == request_id)))


def test_onboarded_vendor_starts_pending_review_and_is_audited(act_as, fresh_db):
    r = act_as("U004").post("/vendors", json=NEW_VENDOR)
    assert r.status_code == 201
    body = r.json()
    assert body["vendor_id"] == "V057" and body["status"] == "pending_review" and body["origin"] == "app"
    [event] = events_for(fresh_db, r.headers["x-request-id"])
    assert (event.action, event.actor_user_id, event.entity_id) == ("vendor.created", "U004", "V057")


def test_onboarding_refuses_a_duplicate_legal_name(act_as):
    r = act_as("U004").post("/vendors", json={**NEW_VENDOR, "legal_name": "polar freight lines ltd."})
    assert r.status_code == 409 and r.json()["error"]["code"] == "vendor.duplicate_name"


def test_onboarding_refuses_unknown_gl_account(act_as):
    r = act_as("U004").post("/vendors", json={**NEW_VENDOR, "default_gl_account": "9999"})
    assert r.status_code == 422


def test_finance_approves_a_pending_vendor_once(act_as):
    client = act_as("U003")
    assert client.post("/vendors/V054/approve", json={}).json()["status"] == "active"
    again = client.post("/vendors/V054/approve", json={})
    assert again.status_code == 409 and again.json()["error"]["code"] == "vendor.invalid_state"


def test_bank_change_request_does_not_touch_the_account(act_as, fresh_db):
    client = act_as("U004")
    before = client.get("/vendors/V001").json()["bank_account"]
    r = client.post("/vendors/V001/bank-changes", json=NEW_BANK)
    assert r.status_code == 201 and r.json()["status"] == "pending_verification"
    assert client.get("/vendors/V001").json()["bank_account"] == before
    dup = client.post("/vendors/V001/bank-changes", json={**NEW_BANK, "account": "987654321"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "bank_change.already_pending"


def test_verification_swaps_the_account_version_and_never_logs_the_full_number(act_as, fresh_db):
    change_id = act_as("U004").post("/vendors/V001/bank-changes", json=NEW_BANK).json()["change_id"]
    r = act_as("U003").post(f"/bank-changes/{change_id}/verify", json={"comment": "called back on file number"})
    assert r.status_code == 200 and r.json()["status"] == "verified" and r.json()["verified_by"] == "U003"
    with fresh_db() as s:
        rows = s.scalars(select(models.VendorBankAccount).where(models.VendorBankAccount.vendor_id == "V001")
                         .order_by(models.VendorBankAccount.id)).all()
        assert [a.valid_to for a in rows] == [date(2026, 11, 2), None]
        assert rows[-1].account == "123456789" and rows[-1].source_change_id == change_id
        logged = json.dumps([e.after_json for e in s.scalars(select(models.AuditEvent))
                             .all() if e.entity_id == "V001"])
    assert "123456789" not in logged and "6789" in logged


def test_requester_cannot_verify_their_own_change(fresh_db, act_as):
    act_as("U004").post("/vendors/V001/bank-changes", json=NEW_BANK)
    with fresh_db() as s:
        requester = load_current_user(s, "U004")
        with pytest.raises(ApiError) as exc:
            vendors.verify_bank_change(s, requester, "BC-010", None)
    assert exc.value.status == 403 and exc.value.code == "bank_change.self_verification"


def test_rejecting_an_already_applied_change_puts_the_vendor_on_hold(act_as):
    client = act_as("U003")
    r = client.post("/bank-changes/BC-009/reject", json={"comment": "no callback was ever made"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.get("/vendors/V004").json()["status"] == "on_hold"


def test_history_change_without_full_number_verifies_without_new_account(act_as, fresh_db):
    with fresh_db() as s:
        before = s.scalar(select(func.count()).select_from(models.VendorBankAccount))
    assert act_as("U002").post("/bank-changes/BC-009/verify", json={}).status_code == 200
    with fresh_db() as s:
        assert s.scalar(select(func.count()).select_from(models.VendorBankAccount)) == before


def test_a_failed_audit_write_rolls_the_change_back(act_as, monkeypatch, fresh_db):
    signed_in = act_as("U003")
    client = TestClient(app, raise_server_exceptions=False, cookies=dict(signed_in.cookies))

    def boom(*args, **kwargs):
        raise RuntimeError("audit log unavailable")

    monkeypatch.setattr(vendors, "record", boom)
    r = client.post("/vendors/V054/approve", json={})
    assert r.status_code == 500 and r.json()["error"]["code"] == "server.error"
    assert "audit log unavailable" not in r.text
    with fresh_db() as s:
        assert s.get(models.Vendor, "V054").status == "pending_review"


def test_verifying_a_bank_change_rechecks_the_vendors_bills_in_review(fresh_engine, act_as, fresh_db):
    # A bill in review on Cascadia (V004), whose account came in through BC-009 and was never verified: blocked.
    from app.db.bills import latest_controls_run
    from tests.api.factories import app_bill
    bill = app_bill(fresh_engine, vendor_id="V004")
    with fresh_db() as s:
        codes = {f.code for f in latest_controls_run(s, bill).flags}
    assert "BANK_CHANGE_UNVERIFIED" in codes
    # Verifying BC-009 re-runs the controls on that bill straight away: the flag is gone without any other edit.
    verified = act_as("U002").post("/bank-changes/BC-009/verify", json={"comment": "called 604-555-0100"})
    assert verified.status_code == 200
    with fresh_db() as s:
        codes = {f.code for f in latest_controls_run(s, bill).flags}
    assert "BANK_CHANGE_UNVERIFIED" not in codes


def test_bank_changes_carry_the_vendor_name(as_role):
    rows = as_role("finance_manager").get("/bank-changes", params={"status": "pending_verification"}).json()
    assert rows and rows[0]["vendor_name"] == "Cascadia Cartage Ltd."


def test_an_unverified_bank_change_cannot_be_marked_resolved(fresh_engine, act_as):
    # Only verifying the change clears the flag; finance can still override it with a reason.
    from tests.api.factories import app_bill
    bill = app_bill(fresh_engine, vendor_id="V004")
    clerk = act_as("U004")
    d = clerk.get(f"/bills/{bill}").json()
    flag = next(f for f in d["latest_run"]["flags"] if f["code"] == "BANK_CHANGE_UNVERIFIED")
    r = clerk.post(f"/bills/{bill}/flags/{flag['id']}/resolve",
                   json={"row_version": d["row_version"], "resolution": "resolved", "comment": "looked fine"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "flag.cleared_by_verification"
    r = act_as("U003").post(f"/bills/{bill}/flags/{flag['id']}/resolve",
                            json={"row_version": d["row_version"], "resolution": "overridden",
                                  "comment": "Vendor confirmed by phone"})
    assert r.status_code == 200
