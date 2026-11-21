"""End to end on app bills: edit and code, flags, submit, approve (incl. delegation and P07), schedule, release
(idempotency, P11, limits), cancel, void."""
from __future__ import annotations

from sqlalchemy import select

from app.db import models
from tests.api.factories import app_bill

KEY = "release-key-0001"


def detail(client, bill_id):
    return client.get(f"/bills/{bill_id}").json()


def submit(client, bill_id):
    return client.post(f"/bills/{bill_id}/submit", json={"row_version": detail(client, bill_id)["row_version"]})


def decide(client, bill_id, action="approve", **extra):
    return client.post(f"/bills/{bill_id}/{action}", json={"row_version": detail(client, bill_id)["row_version"],
                                                          **extra})


def events(db, **where):
    with db() as s:
        q = select(models.AuditEvent)
        for k, v in where.items():
            q = q.where(getattr(models.AuditEvent, k) == v)
        return list(s.scalars(q.order_by(models.AuditEvent.seq)))


def test_full_happy_path(fresh_engine, act_as, fresh_db):
    bill = app_bill(fresh_engine)
    clerk = act_as("U004")
    d = detail(clerk, bill)
    assert d["status"] == "needs_review" and d["latest_run"]["route"][0]["user_id"] == "U007"

    r = clerk.patch(f"/bills/{bill}/lines/1", json={"row_version": d["row_version"], "gl_account": "5010",
                                                    "department_id": "D01"})
    assert r.status_code == 200 and r.json()["lines"][0]["coding_status"] in ("accepted", "overridden")
    assert r.json()["row_version"] == d["row_version"] + 1
    assert r.json()["latest_run"]["version"] == d["latest_run"]["version"] + 1  # controls re-ran

    assert submit(clerk, bill).json()["status"] == "pending_approval"
    assert [b["bill_id"] for b in act_as("U007").get("/approvals/queue").json()] == [bill]
    r = decide(act_as("U007"), bill)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["latest_run"]["route"][0]["decision"] == "approved"

    r = act_as("U004").post(f"/bills/{bill}/payments", json={"scheduled_date": "2026-11-05"})
    assert r.status_code == 201
    payment = r.json()["payment_id"]
    assert r.json()["status"] == "scheduled" and r.json()["amount"] == "1130.00"

    fm = act_as("U003")
    r = fm.post(f"/payments/{payment}/release", headers={"Idempotency-Key": KEY})
    assert r.status_code == 200 and r.json()["status"] == "released" and r.json()["released_by"] == "U003"
    assert detail(fm, bill)["status"] == "paid"
    actions = [e.action for e in events(fresh_db, entity_id=bill)] + \
              [e.action for e in events(fresh_db, entity_id=payment)]
    for a in ("bill.coding_changed", "bill.submitted", "bill.approved", "payment.scheduled", "payment.released"):
        assert actions.count(a) == 1, a


def test_release_is_idempotent(fresh_engine, act_as, fresh_db):
    bill = app_bill(fresh_engine)
    submit(act_as("U004"), bill)
    decide(act_as("U007"), bill)
    payment = act_as("U004").post(f"/bills/{bill}/payments", json={"scheduled_date": "2026-11-05"}).json()["payment_id"]
    fm = act_as("U003")
    first = fm.post(f"/payments/{payment}/release", headers={"Idempotency-Key": KEY})
    again = fm.post(f"/payments/{payment}/release", headers={"Idempotency-Key": KEY})
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true"
    assert again.json()["released_at"] == first.json()["released_at"]
    assert len(events(fresh_db, entity_id=payment, action="payment.released")) == 1
    other = fm.post(f"/payments/{payment}/release", headers={"Idempotency-Key": "another-key-0002"})
    assert other.status_code == 409  # already released
    assert fm.post(f"/payments/{payment}/release").status_code == 422  # key is required


def test_key_reused_on_another_payment_is_refused(fresh_engine, act_as):
    payments = []
    for n in ("APP-1", "APP-2"):
        bill = app_bill(fresh_engine, number=n)
        submit(act_as("U004"), bill)
        decide(act_as("U007"), bill)
        payments.append(act_as("U004").post(f"/bills/{bill}/payments",
                                            json={"scheduled_date": "2026-11-05"}).json()["payment_id"])
    fm = act_as("U003")
    assert fm.post(f"/payments/{payments[0]}/release", headers={"Idempotency-Key": KEY}).status_code == 200
    r = fm.post(f"/payments/{payments[1]}/release", headers={"Idempotency-Key": KEY})
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment.idempotency_key_reused"


def test_approver_cannot_release_their_own_approval_p11(fresh_engine, act_as):
    bill = app_bill(fresh_engine, amount="15000.00")  # dept manager then finance manager
    submit(act_as("U004"), bill)
    assert decide(act_as("U007"), bill).json()["status"] == "pending_approval"
    assert decide(act_as("U003"), bill).json()["status"] == "approved"
    payment = act_as("U004").post(f"/bills/{bill}/payments", json={"scheduled_date": "2026-11-05"}).json()["payment_id"]
    r = act_as("U003").post(f"/payments/{payment}/release", headers={"Idempotency-Key": KEY})
    assert r.status_code == 403 and "P11" in r.json()["error"]["message"]
    assert act_as("U002").post(f"/payments/{payment}/release", headers={"Idempotency-Key": KEY}).status_code == 200


def test_only_the_assigned_approver_can_sign(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    submit(act_as("U004"), bill)
    r = decide(act_as("U003"), bill)  # finance manager, but step 1 is U007's
    assert r.status_code == 403 and r.json()["error"]["code"] == "approval.not_allowed"
    v = detail(act_as("U004"), bill)["row_version"]
    outsider = act_as("U008")  # D02 approver: the bill is outside their scope
    assert outsider.post(f"/bills/{bill}/approve", json={"row_version": v}).status_code == 404


def test_self_approval_escalates_to_the_manager_p07(fresh_engine, act_as):
    bill = app_bill(fresh_engine, requester="U007")
    route = detail(act_as("U004"), bill)["latest_run"]["route"]
    assert route[0]["user_id"] != "U007" and route[0]["escalated_from"] == "U007"


def test_delegate_approval_is_recorded_on_behalf_of(fresh_engine, act_as, fresh_db):
    bill = app_bill(fresh_engine, dept="D07", requester="U037")
    submit(act_as("U004"), bill)
    r = decide(act_as("U003"), bill)
    assert r.status_code == 200
    assert r.json()["decisions"][-1]["on_behalf_of"] == "U012"
    [event] = events(fresh_db, entity_id=bill, action="bill.approved")
    assert event.on_behalf_of == "U012"


def test_blocking_flag_stops_submit_until_finance_overrides(fresh_engine, act_as):
    bill = app_bill(fresh_engine, bank_account="999999999")
    clerk = act_as("U004")
    d = detail(clerk, bill)
    flag = next(f for f in d["latest_run"]["flags"] if f["code"] == "BANK_DETAILS_MISMATCH")
    r = submit(clerk, bill)
    assert r.status_code == 409 and "BANK_DETAILS_MISMATCH" in r.json()["error"]["details"]["open_blocking_flags"]
    assert detail(clerk, bill)["status"] == "needs_review"  # refused submit changed nothing
    r = clerk.post(f"/bills/{bill}/flags/{flag['id']}/resolve",
                   json={"row_version": d["row_version"], "resolution": "overridden", "comment": "ok"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "flag.override_needs_finance"
    fm = act_as("U003")
    r = fm.post(f"/bills/{bill}/flags/{flag['id']}/resolve",
                json={"row_version": d["row_version"], "resolution": "overridden",
                      "comment": "Confirmed new account by callback"})
    assert r.status_code == 200
    assert submit(act_as("U004"), bill).json()["status"] == "pending_approval"


def test_stale_row_version_is_a_conflict(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    clerk = act_as("U004")
    v = detail(clerk, bill)["row_version"]
    assert clerk.patch(f"/bills/{bill}", json={"row_version": v, "due_date": "2026-12-01"}).status_code == 200
    r = clerk.patch(f"/bills/{bill}", json={"row_version": v, "due_date": "2026-12-05"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict.stale"


def test_header_edit_validates_references(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    clerk = act_as("U004")
    r = clerk.patch(f"/bills/{bill}", json={"row_version": detail(clerk, bill)["row_version"], "po_id": "PO-NOPE"})
    assert r.status_code == 422


def test_bank_change_after_scheduling_blocks_release(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    submit(act_as("U004"), bill)
    decide(act_as("U007"), bill)
    payment = act_as("U004").post(f"/bills/{bill}/payments", json={"scheduled_date": "2026-11-05"}).json()["payment_id"]
    change = act_as("U005").post("/vendors/V001/bank-changes", json={
        "institution": "004", "transit": "05541", "account": "123456789", "request_channel": "vendor_portal"})
    act_as("U002").post(f"/bank-changes/{change.json()['change_id']}/verify", json={})
    r = act_as("U003").post(f"/payments/{payment}/release", headers={"Idempotency-Key": KEY})
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment.bank_account_changed"


def test_cancel_returns_the_bill_to_approved(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    submit(act_as("U004"), bill)
    decide(act_as("U007"), bill)
    clerk = act_as("U004")
    payment = clerk.post(f"/bills/{bill}/payments", json={"scheduled_date": "2026-11-05"}).json()["payment_id"]
    assert clerk.post(f"/payments/{payment}/cancel", json={"comment": "hold"}).json()["status"] == "cancelled"
    assert detail(clerk, bill)["status"] == "approved"


def test_reject_needs_a_comment_and_ends_the_bill(fresh_engine, act_as):
    bill = app_bill(fresh_engine)
    submit(act_as("U004"), bill)
    approver = act_as("U007")
    assert decide(approver, bill, "reject").status_code == 422
    r = decide(approver, bill, "reject", comment="Not our shipment")
    assert r.json()["status"] == "rejected"


def test_void_instead_of_delete(fresh_engine, act_as, fresh_db):
    bill = app_bill(fresh_engine)
    clerk = act_as("U004")
    r = clerk.post(f"/bills/{bill}/void", json={"row_version": detail(clerk, bill)["row_version"],
                                               "comment": "duplicate upload"})
    assert r.json()["status"] == "void"
    with fresh_db() as s:
        assert s.get(models.Bill, bill) is not None


def test_history_scheduled_payment_can_be_released(act_as):
    fm = act_as("U003")
    payment = fm.get("/payments", params={"status": "scheduled", "limit": 1}).json()["items"][0]
    r = fm.post(f"/payments/{payment['payment_id']}/release", headers={"Idempotency-Key": KEY})
    assert r.status_code in (200, 403)  # 403 only if U003 approved that history bill (P11) or it's over $100k
    if r.status_code == 403:
        assert any(p in r.json()["error"]["message"] for p in ("P10", "P11", "hold"))
