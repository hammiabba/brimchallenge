"""Person A's clerk loop through the real endpoints: learning from coding corrections, the requester's department,
requester checks and the self-check re-run on edits. Offline: extraction is a factory draft plus real coding."""
from __future__ import annotations

import hashlib
from datetime import date

from app.coding import suggest as coding
from app.extraction.pipeline import ExtractionOutcome
from app.reference.csv_repository import default_repository
from app.services import intake as intake_service
from tests.api.factories import draft


def coded_extract(**draft_kwargs):
    """An extractor that returns a factory draft, coded by the real coding module, hashed by content."""
    def extract(data, filename, **_):
        h = hashlib.sha256(data).hexdigest()
        d = draft(number=f"CL-{h[:8]}", requester=None, dept=None, **draft_kwargs)
        d = d.model_copy(update={"source": d.source.model_copy(update={"file_hash": h, "file_name": filename})})
        return ExtractionOutcome(filename, h, "ok", draft=coding.suggest(d, default_repository()))
    return extract


def submit(client, content: bytes) -> dict:
    client.post("/submissions", files={"file": ("polar.pdf", content, "application/pdf")})
    item = client.get("/submissions").json()[0]
    assert item["bill_id"], item
    return client.get(f"/bills/{item['bill_id']}").json()


def test_override_feeds_the_next_bill_from_the_same_vendor(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome", coded_extract(vendor_id="V001"))
    clerk = act_as("U004")
    first = submit(clerk, b"%PDF polar one")
    assert first["lines"][0]["suggested_gl_account"] == "5010"
    r = clerk.patch(f"/bills/{first['bill_id']}/lines/1",
                    json={"row_version": first["row_version"], "gl_account": "6630", "department_id": "D04"})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["coding_status"] == "overridden"

    second = submit(clerk, b"%PDF polar two")
    line = second["lines"][0]
    assert (line["suggested_gl_account"], line["suggested_department_id"]) == ("6630", "D04")
    assert "a clerk changed the coding of 'LTL shipment Toronto-Ottawa'" in line["suggestion_reason"]
    assert first["bill_id"] in line["suggestion_reason"]


def test_setting_the_requester_moves_suggested_departments(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome", coded_extract(vendor_id="V001"))
    clerk = act_as("U004")
    bill = submit(clerk, b"%PDF polar requester")
    assert bill["lines"][0]["suggested_department_id"] == "D01"
    r = clerk.patch(f"/bills/{bill['bill_id']}", json={"row_version": bill["row_version"],
                                                        "requester_user_id": "U033"})  # U033 is in D05
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["suggested_department_id"] == "D05"
    assert line["suggestion_reason"].endswith("; department D05 from requester U033 (replaces D01)")

    # Changing it again replaces the suffix instead of stacking a second one.
    r = clerk.patch(f"/bills/{bill['bill_id']}", json={"row_version": r.json()["row_version"],
                                                        "requester_user_id": "U022"})  # D02
    line = r.json()["lines"][0]
    assert line["suggested_department_id"] == "D02"
    assert line["suggestion_reason"].count("from requester") == 1


def test_terminated_requester_is_refused(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome", coded_extract(vendor_id="V001"))
    clerk = act_as("U004")
    bill = submit(clerk, b"%PDF polar terminated")
    r = clerk.patch(f"/bills/{bill['bill_id']}", json={"row_version": bill["row_version"],
                                                        "requester_user_id": "U015"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "bill.requester_not_allowed"
    assert "U015" in err["message"] and "terminated" in err["message"]


def test_editing_a_field_rechecks_its_confidence_and_warnings(act_as, monkeypatch):
    base = coded_extract(vendor_id="V001")

    def ambiguous(data, filename, **kw):
        out = base(data, filename, **kw)
        d = out.draft
        out.draft = d.model_copy(update={
            "field_confidence": {**d.field_confidence, "invoice_date": 0.5},
            "extraction_warnings": ["invoice date '03/04/2026' is ambiguous (2026-04-03 or 2026-03-04); "
                                    "read day-first as 2026-04-03, please confirm"]})
        return out

    monkeypatch.setattr(intake_service, "extract_outcome", ambiguous)
    clerk = act_as("U004")
    bill = submit(clerk, b"%PDF ambiguous date")
    assert bill["extracted"]["field_confidence"]["invoice_date"] == 0.5
    r = clerk.patch(f"/bills/{bill['bill_id']}", json={"row_version": bill["row_version"],
                                                        "invoice_date": "2026-03-04"})
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["invoice_date"] == "2026-03-04"
    assert after["extracted"]["field_confidence"]["invoice_date"] == 1.0
    assert not any(w.startswith("invoice date") for w in after["extracted"]["extraction_warnings"])
    # The values as extracted stay on record.
    assert after["extracted"]["as_extracted"]["field_confidence"]["invoice_date"] == 0.5
    assert date.fromisoformat(after["invoice_date"]) == date(2026, 3, 4)


def test_each_recheck_is_audited_and_as_extracted_is_written_once(act_as, monkeypatch, fresh_db):
    from sqlalchemy import select

    from app.db import models

    monkeypatch.setattr(intake_service, "extract_outcome", coded_extract(vendor_id="V001"))
    clerk = act_as("U004")
    bill = submit(clerk, b"%PDF recheck audit")
    original = bill["extracted"]["field_confidence"]
    r = clerk.patch(f"/bills/{bill['bill_id']}", json={"row_version": bill["row_version"],
                                                        "invoice_date": "2026-10-01"})
    r = clerk.patch(f"/bills/{bill['bill_id']}", json={"row_version": r.json()["row_version"],
                                                        "due_date": "2026-11-15"})
    assert r.status_code == 200, r.text
    extracted = r.json()["extracted"]
    assert extracted["as_extracted"]["field_confidence"] == original  # not overwritten by the second edit
    assert extracted["field_confidence"]["invoice_date"] == extracted["field_confidence"]["due_date"] == 1.0
    with fresh_db() as s:
        events = list(s.scalars(select(models.AuditEvent).where(models.AuditEvent.entity_id == bill["bill_id"],
                                                                 models.AuditEvent.action == "bill.rechecked")
                                .order_by(models.AuditEvent.seq)))
    assert len(events) == 2
    assert "invoice_date" in events[0].comment and "due_date" in events[1].comment


def _override_polar(act_as, monkeypatch) -> dict:
    monkeypatch.setattr(intake_service, "extract_outcome", coded_extract(vendor_id="V001"))
    clerk = act_as("U004")
    first = submit(clerk, b"%PDF polar before restart")
    r = clerk.patch(f"/bills/{first['bill_id']}/lines/1",
                    json={"row_version": first["row_version"], "gl_account": "6630", "department_id": "D04"})
    assert r.status_code == 200, r.text
    return first


def test_learned_codings_are_rebuilt_from_the_database(act_as, monkeypatch, fresh_db):
    from app.coding.feedback import replay_learned_codings
    from app.coding.history_index import corrections_for, forget_corrections

    first = _override_polar(act_as, monkeypatch)
    forget_corrections()  # what a restart does to process memory
    assert corrections_for("V001") == []
    with fresh_db() as s:
        assert replay_learned_codings(s) == 1
    [c] = corrections_for("V001")
    assert (c.gl_account, c.department_id, c.bill_id, c.overridden) == ("6630", "D04", first["bill_id"], True)
    second = submit(act_as("U004"), b"%PDF polar after restart")
    assert second["lines"][0]["suggested_gl_account"] == "6630"
    assert first["bill_id"] in second["lines"][0]["suggestion_reason"]


def test_replay_ignores_history_bills_and_unreviewed_lines(fresh_db):
    from app.coding.feedback import replay_learned_codings

    with fresh_db() as s:  # the seeded database: 426 history bills, no app bills yet
        assert replay_learned_codings(s) == 0


def test_app_start_up_replays_learned_codings(act_as, monkeypatch, fresh_engine):
    from app.coding.history_index import corrections_for, forget_corrections
    from tests.api.conftest import _client_on

    first = _override_polar(act_as, monkeypatch)
    forget_corrections()
    with _client_on(fresh_engine):  # a new app start on the same database
        assert [c.bill_id for c in corrections_for("V001")] == [first["bill_id"]]
