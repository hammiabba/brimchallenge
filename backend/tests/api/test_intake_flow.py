"""Submissions and the inbox run, with a fake extractor (tests never OCR files or call the LLM)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.db import models
from app.extraction.pipeline import ExtractionOutcome
from app.services import intake as intake_service
from app.services import jobs as jobs_service
from app.shared.schemas import CodingSuggestion
from tests.api.factories import draft

PDF = ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")


def good_extract(data, filename, **_):
    return ExtractionOutcome(filename, f"sha256:{filename}", "ok", draft=draft(number=f"SUB-{filename[:20]}",
                                                                              requester=None, dept=None))


def test_employee_submission_becomes_a_bill_in_their_department(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome", good_extract)
    client = act_as("U013")
    r = client.post("/submissions", files={"file": PDF})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    [item] = client.get("/submissions").json()
    assert item["status"] == "ok" and item["bill_id"]
    bill = client.get(f"/bills/{item['bill_id']}").json()
    assert bill["status"] == "needs_review" and bill["department_id"] == "D01"
    assert bill["requester_user_id"] == "U013" and bill["latest_run"] is not None


def test_employee_cannot_submit_for_another_department(act_as):
    r = act_as("U013").post("/submissions", files={"file": PDF}, data={"department_id": "D05"})
    assert r.status_code == 403


def test_unsupported_file_type_is_refused(act_as):
    r = act_as("U013").post("/submissions", files={"file": ("notes.docx", b"x", "application/octet-stream")})
    assert r.status_code == 415


def test_failed_extraction_is_kept_for_ap_to_see(act_as):
    client = act_as("U004")
    client.post("/submissions", files={"file": PDF})
    [item] = client.get("/submissions").json()
    assert item["status"] == "llm_skipped" and item["bill_id"] is None and item["error"]


def test_inbox_run_is_a_background_job_and_does_not_repeat(act_as, monkeypatch, fresh_db):
    monkeypatch.setattr(jobs_service, "extract_outcome", good_extract)
    clerk = act_as("U004")
    r = clerk.post("/intake/inbox/jobs")
    assert r.status_code == 202
    job = clerk.get(f"/intake/inbox/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done" and job["processed_emails"] == 59 and job["items"]
    with fresh_db() as s:
        triaged = s.scalar(select(func.count()).select_from(models.Email).where(models.Email.email_class.isnot(None)))
        bills = s.scalar(select(func.count()).select_from(models.Bill).where(models.Bill.origin == "app"))
    assert triaged == 59 and bills == len([i for i in job["items"] if i["bill_id"]])
    again = clerk.post("/intake/inbox/jobs").json()
    assert clerk.get(f"/intake/inbox/jobs/{again['job_id']}").json()["processed_emails"] == 0


def coded_extract(data, filename, **_):
    """A draft with no department or requester, whose line coding suggests D03 (as the coding step would)."""
    d = draft(number=f"DEP-{filename[:20]}", requester=None, dept=None)
    line = d.lines[0].model_copy(update={"coding": CodingSuggestion(gl_account="6420", department_id="D03",
                                                                    confidence=0.9, reason="test")})
    return ExtractionOutcome(filename, f"sha256:{filename}", "ok", draft=d.model_copy(update={"lines": [line]}))


def test_inbox_bill_without_department_gets_the_coding_suggestion(act_as, monkeypatch):
    monkeypatch.setattr(jobs_service, "extract_outcome", coded_extract)
    clerk = act_as("U004")
    job_id = clerk.post("/intake/inbox/jobs").json()["job_id"]
    bill_id = next(i["bill_id"] for i in clerk.get(f"/intake/inbox/jobs/{job_id}").json()["items"] if i["bill_id"])
    bill = clerk.get(f"/bills/{bill_id}").json()
    assert bill["department_id"] == "D03" and bill["department_source"] == "coding"
    assert bill["extracted"]["department_id"] is None  # the document as read is untouched
    assert bill["latest_run"]["route"][0]["user_id"] == "U009"  # D03's manager, so routing has someone
    r = clerk.patch(f"/bills/{bill_id}", json={"row_version": bill["row_version"], "department_id": "D03"})
    assert r.json()["department_source"] == "user"  # a person confirmed it


def test_employee_submission_department_is_marked_submitter(act_as, monkeypatch):
    monkeypatch.setattr(intake_service, "extract_outcome", coded_extract)
    client = act_as("U013")
    client.post("/submissions", files={"file": PDF})
    [item] = client.get("/submissions").json()
    bill = client.get(f"/bills/{item['bill_id']}").json()
    assert bill["department_id"] == "D01" and bill["department_source"] == "submitter"


def test_history_bills_are_marked_history(as_role):
    assert as_role("ap_clerk").get("/bills/AP-00024").json()["department_source"] == "history"
