"""Person A: the same file submitted twice links to the bill it already made (idempotent intake)."""
from __future__ import annotations

import hashlib

from sqlalchemy import func, select

from app.db import models
from app.extraction.pipeline import ExtractionOutcome
from app.services import intake as intake_service
from tests.api.factories import draft


def content_extract(data, filename, **_):
    """Like the real pipeline: the hash comes from the bytes, not the name."""
    h = hashlib.sha256(data).hexdigest()
    d = draft(number=f"RCV-{h[:8]}", requester=None, dept=None)
    d = d.model_copy(update={"source": d.source.model_copy(update={"file_hash": h, "file_name": filename})})
    return ExtractionOutcome(filename, h, "ok", draft=d)


def _app_bills(fresh_db) -> int:
    with fresh_db() as s:
        return s.scalar(select(func.count()).select_from(models.Bill).where(models.Bill.origin == "app"))


def test_same_file_twice_returns_the_existing_bill(act_as, monkeypatch, fresh_db):
    monkeypatch.setattr(intake_service, "extract_outcome", content_extract)
    clerk = act_as("U004")
    pdf = ("invoice.pdf", b"%PDF-1.4 same bytes", "application/pdf")
    clerk.post("/submissions", files={"file": pdf})
    clerk.post("/submissions", files={"file": ("renamed-copy.pdf", pdf[1], pdf[2])})
    second, first = clerk.get("/submissions").json()  # newest first
    assert first["bill_id"] and second["bill_id"] == first["bill_id"]
    assert any(w.startswith("already_received") and first["bill_id"] in w for w in second["warnings"])
    assert _app_bills(fresh_db) == 1


def test_different_file_makes_a_new_bill(act_as, monkeypatch, fresh_db):
    monkeypatch.setattr(intake_service, "extract_outcome", content_extract)
    clerk = act_as("U004")
    clerk.post("/submissions", files={"file": ("a.pdf", b"%PDF-1.4 one", "application/pdf")})
    clerk.post("/submissions", files={"file": ("b.pdf", b"%PDF-1.4 two", "application/pdf")})
    second, first = clerk.get("/submissions").json()
    assert second["bill_id"] != first["bill_id"]
    assert not any(w.startswith("already_received") for w in second["warnings"])
    assert _app_bills(fresh_db) == 2


def test_a_voided_bill_does_not_block_a_resend(act_as, monkeypatch, fresh_db):
    monkeypatch.setattr(intake_service, "extract_outcome", content_extract)
    clerk = act_as("U004")
    pdf = ("invoice.pdf", b"%PDF-1.4 read wrong the first time", "application/pdf")
    clerk.post("/submissions", files={"file": pdf})
    [first] = clerk.get("/submissions").json()
    bill = clerk.get(f"/bills/{first['bill_id']}").json()
    r = clerk.post(f"/bills/{first['bill_id']}/void", json={"row_version": bill["row_version"], "comment": "misread"})
    assert r.status_code == 200, r.text
    clerk.post("/submissions", files={"file": pdf})
    second, _ = clerk.get("/submissions").json()
    assert second["bill_id"] and second["bill_id"] != first["bill_id"]


def test_the_link_is_audited(act_as, monkeypatch, fresh_db):
    monkeypatch.setattr(intake_service, "extract_outcome", content_extract)
    clerk = act_as("U004")
    pdf = ("invoice.pdf", b"%PDF-1.4 audited", "application/pdf")
    clerk.post("/submissions", files={"file": pdf})
    clerk.post("/submissions", files={"file": pdf})
    with fresh_db() as s:
        events = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "intake.already_received")).all()
    assert len(events) == 1
