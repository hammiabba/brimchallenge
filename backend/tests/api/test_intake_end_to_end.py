"""Person A end to end through the real API: a file is submitted, read by the real pipeline (model output faked),
stored as a bill by the DB lane and checked by Person B's controls, all in one flow."""
from __future__ import annotations

from functools import partial

from app.extraction import pipeline
from app.services import intake as intake_service
from tests.conftest import INCOMING
from tests.extraction.test_pipeline import FakeClient, raw_invoice

HARLOW = INCOMING / "Invoice HA26-2766.pdf"


def test_submitted_pdf_becomes_a_bill_with_controls_flags(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome",
                        partial(pipeline.extract_outcome, client=FakeClient(raw_invoice())))
    clerk = act_as("U004")
    r = clerk.post("/submissions", files={"file": (HARLOW.name, HARLOW.read_bytes(), "application/pdf")})
    assert r.status_code == 202
    item = clerk.get("/submissions").json()[0]
    assert item["status"] == "ok", item
    bill = clerk.get(f"/bills/{item['bill_id']}").json()
    assert bill["vendor_id"] == "V052" and bill["vendor_invoice_number"] == "HA26-2766"
    assert bill["total"] == "6452.30"
    assert bill["lines"][0]["suggested_gl_account"] and bill["lines"][0]["suggestion_reason"]
    codes = {f["code"] for f in bill["latest_run"]["flags"]}
    assert "VENDOR_LOOKALIKE" in codes


def test_unreadable_upload_is_a_clean_failed_item(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome", pipeline.extract_outcome)
    clerk = act_as("U004")
    clerk.post("/submissions", files={"file": ("locked.pdf", b"PK\x03\x04" + b"\0" * 64, "application/pdf")})
    item = clerk.get("/submissions").json()[0]
    assert item["status"] == "failed" and item["bill_id"] is None
    assert "Word/Excel document" in item["error"] and "Traceback" not in item["error"]
