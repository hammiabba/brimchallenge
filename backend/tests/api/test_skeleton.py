"""Error envelope, request ids, CORS, CSRF origin check, body size limit and money input rules."""
from __future__ import annotations

from tests.api.conftest import ROLE_USERS


def test_unknown_route_uses_envelope(client):
    r = client.get("/no-such-route")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "http.404"
    assert body["request_id"] == r.headers["x-request-id"]


def test_request_id_is_echoed_when_safe(client):
    r = client.get("/health", headers={"X-Request-ID": "trace-12345678"})
    assert r.headers["x-request-id"] == "trace-12345678"
    r = client.get("/health", headers={"X-Request-ID": "bad id <script>"})
    assert r.headers["x-request-id"] != "bad id <script>"


def test_validation_errors_use_envelope_without_echoing_input(as_role):
    client = as_role("controller_admin")
    r = client.patch("/admin/users/U013", json={"approval_limit_cad": "12.345"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "request.invalid"
    assert all(set(d) == {"loc", "msg", "type"} for d in err["details"])


def test_money_must_be_a_string(as_role):
    client = as_role("controller_admin")
    assert client.patch("/admin/users/U013", json={"approval_limit_cad": 1000.5}).status_code == 422
    assert client.patch("/admin/users/U013", json={"approval_limit_cad": "1000.50"}).status_code == 501


def test_cors_allows_the_frontend_with_credentials(client):
    r = client.options("/bills", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_cors_does_not_allow_other_origins(client):
    r = client.options("/bills", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def test_writes_from_a_foreign_origin_are_refused(login):
    client = login(ROLE_USERS["ap_clerk"])
    r = client.post("/auth/logout", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.bad_origin"


def test_writes_from_the_frontend_or_same_origin_pass(login):
    client = login(ROLE_USERS["ap_clerk"])
    assert client.post("/auth/logout", headers={"Origin": "http://localhost:5173"}).status_code == 204
    client = login(ROLE_USERS["ap_clerk"])
    assert client.post("/auth/logout", headers={"Origin": "http://testserver"}).status_code == 204


def test_oversized_body_is_refused_with_413(as_role):
    client = as_role("employee")
    big = b"0" * (10 * 1024 * 1024 + 1)
    r = client.post("/submissions", files={"file": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "request.too_large"


def test_openapi_lists_every_endpoint(client):
    spec = client.get("/openapi.json").json()
    operations = sum(len(ops) for ops in spec["paths"].values())
    assert operations >= 50
    money = spec["components"]["schemas"]["BillSummary"]["properties"]["total"]
    assert money["type"] == "string"
