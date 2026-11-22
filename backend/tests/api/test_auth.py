"""Sign-in, session cookie and identity rules."""
from __future__ import annotations

from sqlalchemy import select

from app.auth import session as signed_session
from app.auth.settings import get_auth_settings
from app.db import models
from tests.api.conftest import ON_LEAVE_USER, TERMINATED_USER, forge_cookie

COOKIE = get_auth_settings().session_cookie_name


def test_picker_lists_active_and_on_leave_but_not_terminated(client):
    users = {u["user_id"]: u for u in client.get("/auth/users").json()}
    assert len(users) == 39
    assert TERMINATED_USER not in users
    assert users[ON_LEAVE_USER]["status"] == "on_leave"


def test_picker_gives_each_user_their_department_name(client, db_factory):
    users = {u["user_id"]: u for u in client.get("/auth/users").json()}
    assert (users["U013"]["title"], users["U013"]["department_id"], users["U013"]["department_name"]) == (
        "Dispatcher", "D01", "Operations")
    assert users["U004"]["department_name"] == "Finance"
    with db_factory() as db:
        names = dict(db.execute(select(models.Department.department_id, models.Department.name)).all())
    assert all(u["department_name"] == names[u["department_id"]] for u in users.values())
    # Nothing else in the response changed.
    assert set(users["U013"]) == {"user_id", "full_name", "title", "role", "department_id", "department_name", "status"}


def test_picker_still_lists_a_user_whose_department_is_missing(fresh_client, fresh_engine):
    # Plant a dangling department id on this test's private copy. Foreign keys are on for every connection, so switch
    # them off on one raw (autocommit) connection for the update, and back on before it returns to the pool.
    raw = fresh_engine.raw_connection()
    try:
        cursor = raw.driver_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("UPDATE users SET department_id = 'D99' WHERE user_id = 'U013'")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()
    users = {u["user_id"]: u for u in fresh_client.get("/auth/users").json()}
    assert (users["U013"]["department_id"], users["U013"]["department_name"]) == ("D99", None)


def test_picker_is_public(client):
    client.cookies.clear()
    assert client.get("/auth/users").status_code == 200


def test_login_sets_http_only_lax_cookie(client):
    r = client.post("/auth/login", json={"user_id": "U004"})
    assert r.status_code == 200
    assert r.json()["role"] == "ap_clerk"
    cookie = r.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "secure" not in cookie  # plain-http localhost frontend by default


def test_me_returns_the_signed_in_user(login):
    client = login("U007")
    assert client.get("/auth/me").json()["user_id"] == "U007"


def test_terminated_user_cannot_log_in(client):
    r = client.post("/auth/login", json={"user_id": TERMINATED_USER})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.invalid_user"


def test_unknown_user_cannot_log_in(client):
    assert client.post("/auth/login", json={"user_id": "U999"}).status_code == 401


def test_terminated_user_with_a_valid_cookie_gets_401_and_cookie_cleared(client):
    forge_cookie(client, TERMINATED_USER)
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.inactive_user"
    assert f'{COOKIE}=""' in r.headers.get("set-cookie", "") or "max-age=0" in r.headers.get("set-cookie", "").lower()


def test_on_leave_user_can_sign_in(login):
    assert login(ON_LEAVE_USER).get("/auth/me").json()["status"] == "on_leave"


def test_delegate_sees_who_they_act_for(login):
    me = login("U003").get("/auth/me").json()
    assert [a["user_id"] for a in me["acting_for"]] == [ON_LEAVE_USER]


def test_identity_never_comes_from_headers_or_body(login):
    client = login("U013")  # employee
    r = client.get("/auth/me", headers={"X-User-Id": "U002", "X-Role": "controller_admin"})
    assert r.json()["user_id"] == "U013"
    r = client.post("/payments/PAY-00001/release", headers={"Idempotency-Key": "abcdefgh1", "X-User-Id": "U002"})
    assert r.status_code == 403


def test_login_body_rejects_extra_fields(client):
    r = client.post("/auth/login", json={"user_id": "U004", "role": "controller_admin"})
    assert r.status_code == 422


def test_tampered_cookie_is_rejected(client):
    token = signed_session.issue("U013")
    body, sig = token.split(".")
    forged = signed_session.issue("U002").split(".")[0] + "." + sig  # controller payload, employee signature
    client.cookies.set(COOKIE, forged)
    assert client.get("/auth/me").status_code == 401


def test_expired_cookie_is_rejected(client):
    client.cookies.set(COOKIE, signed_session.issue("U004", now=1_000_000))
    assert client.get("/auth/me").status_code == 401


def test_garbage_cookie_is_rejected(client):
    client.cookies.set(COOKIE, "not-a-session")
    assert client.get("/auth/me").json()["error"]["code"] == "auth.invalid_session"


def test_logout_clears_the_cookie(login):
    client = login("U004")
    r = client.post("/auth/logout")
    assert r.status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_session_round_trip_unit():
    secret = b"k" * 32
    token = signed_session.issue("U004", now=100, secret=secret)
    data = signed_session.verify(token, now=200, secret=secret)
    assert data and data.user_id == "U004"
    assert signed_session.verify(token, now=200, secret=b"x" * 32) is None
    assert signed_session.verify(token, now=100 + 8 * 3600, secret=secret) is None


def test_login_and_logout_are_audited(login, db_factory):
    from sqlalchemy import select

    from app.db import models

    client = login("U005")
    client.post("/auth/logout")
    with db_factory() as s:
        actions = s.scalars(select(models.AuditEvent.action).where(models.AuditEvent.actor_user_id == "U005")
                            .order_by(models.AuditEvent.seq.desc()).limit(2)).all()
    assert actions == ["auth.logout", "auth.login"]
