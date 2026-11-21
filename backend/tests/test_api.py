from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["as_of_date"] == "2026-11-02"


def test_openapi_docs():
    assert client.get("/openapi.json").status_code == 200


# The intake upload tests moved to tests/api/test_intake_guard.py: the intake router now requires a session.
