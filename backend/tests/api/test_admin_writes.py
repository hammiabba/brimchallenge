"""Delegation, absences, user and policy administration."""
from __future__ import annotations

from sqlalchemy import select

from app.db import models


def test_approver_delegates_while_away(act_as, fresh_db):
    r = act_as("U007").put("/me/delegation", json={"delegate_user_id": "U003", "starts_on": "2026-11-01"})
    assert r.status_code == 200 and r.json()["status"] == "on_leave"
    with fresh_db() as s:
        u = s.get(models.User, "U007")
        assert (u.status, u.delegate_user_id) == ("on_leave", "U003")
    acting_for = {a["user_id"] for a in act_as("U003").get("/auth/me").json()["acting_for"]}
    assert acting_for == {"U012", "U007"}


def test_future_absence_is_stored_without_changing_status(act_as, fresh_db):
    r = act_as("U007").put("/me/delegation", json={"delegate_user_id": "U003", "starts_on": "2026-12-01",
                                                   "ends_on": "2026-12-15"})
    assert r.json()["status"] == "active"
    with fresh_db() as s:
        assert s.scalars(select(models.UserAbsence).where(models.UserAbsence.user_id == "U007")).one()


def test_delegate_must_be_an_active_approver(act_as):
    r = act_as("U007").put("/me/delegation", json={"delegate_user_id": "U013", "starts_on": "2026-11-05"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "absence.bad_delegate"
    r = act_as("U011").put("/me/delegation", json={"delegate_user_id": "U012", "starts_on": "2026-11-05"})
    assert r.status_code == 422  # U012 is on leave himself


def test_admin_cannot_change_their_own_role_or_status(act_as):
    r = act_as("U002").patch("/admin/users/U002", json={"role": "auditor"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "user.self_lockout"


def test_terminating_a_user_ends_their_session(act_as, fresh_client):
    act_as("U013")
    employee_cookie = dict(fresh_client.cookies)
    act_as("U002").patch("/admin/users/U013", json={"status": "terminated"})
    fresh_client.cookies.clear()
    fresh_client.cookies.update(employee_cookie)
    assert fresh_client.get("/auth/me").status_code == 401


def test_user_edit_is_audited_with_before_and_after(act_as, fresh_db):
    r = act_as("U002").patch("/admin/users/U007", json={"approval_limit_cad": "30000.00"})
    assert r.json()["approval_limit_cad"] == "30000.00"
    with fresh_db() as s:
        e = s.scalars(select(models.AuditEvent).where(models.AuditEvent.request_id == r.headers["x-request-id"])).one()
    assert e.action == "user.updated" and e.after_json == {"approval_limit_cad": "30000.00"}


def test_policy_threshold_cannot_be_removed(act_as):
    client = act_as("U002")
    r = client.patch("/admin/policies/P02", json={"condition": "Invoice total is large"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "policy.threshold_required"
    r = client.patch("/admin/policies/P02", json={"condition": "Invoice total over $15,000 CAD"})
    assert r.status_code == 200 and r.json()["updated_by"] == "U002"


def test_unknown_references_are_refused(act_as):
    r = act_as("U002").patch("/admin/users/U013", json={"manager_id": "U999"})
    assert r.status_code == 422
