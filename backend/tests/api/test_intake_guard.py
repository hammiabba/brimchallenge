"""The intake lane's router is mounted behind a role guard in app/main.py. These were in tests/test_api.py before
the guard existed; they now sign in as an AP clerk first."""
from __future__ import annotations

from tests.conftest import INCOMING


def test_intake_requires_a_session(client):
    client.cookies.clear()
    assert client.post("/intake/inbox/run").status_code == 401


def test_employee_cannot_use_the_intake_router(as_role):
    client = as_role("employee")
    assert client.post("/intake/inbox/run").status_code == 403


def test_upload_without_key_is_503(as_role):
    client = as_role("ap_clerk")
    f = INCOMING / "Invoice HA26-2766.pdf"
    r = client.post("/intake/upload", files={"file": (f.name, f.read_bytes(), "application/pdf")})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert r.json()["error"]["code"] == "http.503"


def test_upload_rejects_unsupported_type(as_role):
    client = as_role("ap_clerk")
    r = client.post("/intake/upload", files={"file": ("notes.docx", b"x", "application/octet-stream")})
    assert r.status_code == 415
