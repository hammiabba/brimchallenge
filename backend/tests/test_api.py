from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import INCOMING

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["as_of_date"] == "2026-11-02"


def test_openapi_docs():
    assert client.get("/openapi.json").status_code == 200


def test_upload_without_key_is_503():
    f = INCOMING / "Invoice HA26-2766.pdf"
    r = client.post("/intake/upload", files={"file": (f.name, f.read_bytes(), "application/pdf")})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_upload_rejects_unsupported_type():
    r = client.post("/intake/upload", files={"file": ("notes.docx", b"x", "application/octet-stream")})
    assert r.status_code == 415
