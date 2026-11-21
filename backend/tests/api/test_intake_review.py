"""Person A's intake reads through the real API, after a real inbox job (model output replayed from fixtures):
GET /intake/emails (suggested action on each row), GET /intake/emails/{email_id}, GET /intake/files/{file_hash}."""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from functools import partial

import pytest

from app.config import get_settings
from app.services import jobs as jobs_service
from tests.api.conftest import ROLE_USERS, TEST_AUDIT_HMAC_KEY, _client_on, _copy, _engine_on
from tests.conftest import INCOMING, replay_extract


@pytest.fixture(scope="module")
def api(seeded_template, tmp_path_factory) -> Iterator:
    """A client on a database where the whole inbox has been run; api("ap_clerk") signs in as that role."""
    from app.db.settings import get_db_settings

    s = get_settings()
    mp = pytest.MonkeyPatch()
    mp.setenv("AUDIT_HMAC_KEY", TEST_AUDIT_HMAC_KEY)
    get_db_settings.cache_clear()
    mp.setattr(s, "cache_dir", tmp_path_factory.mktemp("cache"))
    mp.setattr(s, "files_dir", tmp_path_factory.mktemp("files"))
    mp.setattr(s, "anthropic_api_key", None)
    mp.setattr(jobs_service, "extract_outcome", partial(replay_extract))
    jobs_service.reset_for_tests()
    engine = _engine_on(_copy(seeded_template, tmp_path_factory.mktemp("review")))
    try:
        with _client_on(engine) as c:
            def as_role(role: str):
                c.cookies.clear()
                assert c.post("/auth/login", json={"user_id": ROLE_USERS[role]}).status_code == 200
                return c

            as_role.files_dir = s.files_dir  # where the run kept the originals
            job_id = as_role("ap_clerk").post("/intake/inbox/jobs").json()["job_id"]
            assert c.get(f"/intake/inbox/jobs/{job_id}").json()["status"] == "done"
            yield as_role
    finally:
        engine.dispose()
        jobs_service.reset_for_tests()
        mp.undo()
        get_db_settings.cache_clear()


def email(api, email_id: str, role: str = "ap_clerk") -> dict:
    r = api(role).get(f"/intake/emails/{email_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_statement_is_reconciled_later(api):
    e = email(api, "EM-056")
    assert e["email_class"] == "statement" and e["triage_reason"]
    assert e["suggested_action"]["kind"] == "reconcile_later"
    assert e["bill_ids"] == [] and e["items"] == []


def test_payment_inquiry_is_answered_from_payment_history(api, repo):
    e = email(api, "EM-057")
    a = e["suggested_action"]
    assert e["email_class"] == "payment_inquiry" and a["kind"] == "answer_status"
    st = a["invoice_status"]
    assert (st["invoice_id"], st["status"]) == ("AP-00049", "paid")
    [p] = st["payments"]
    assert (p["paid_date"], p["method"], p["reference"]) == ("2026-03-09", "EFT", "BRIM-EFT-26388945")
    # The reply confirms the payment; it never repeats bank details, even masked ones.
    reply = a["reply_text"]
    assert "BRIM-EFT-26388945" in reply and "2026-03-09" in reply
    vendor = repo.vendor(a["vendor_id"])
    for number in (vendor["bank_institution"], vendor["bank_transit"], vendor["bank_account"]):
        assert number and number not in reply
    for word in ("transit", "institution", "acct"):
        assert word not in reply.lower()


def test_missing_attachment_gets_a_resend_reply(api):
    a = email(api, "EM-058")["suggested_action"]
    assert a["kind"] == "request_resend" and a["reply_text"]
    assert "attach" in a["reply_text"].lower() or "joindre" in a["reply_text"].lower()


def test_marketing_is_ignored(api):
    e = email(api, "EM-059")
    assert e["email_class"] == "not_ap" and e["suggested_action"]["kind"] == "ignore"


def test_one_email_with_two_invoices_links_both_bills(api):
    e = email(api, "EM-029")
    assert e["suggested_action"]["kind"] == "create_drafts"
    assert len(e["bill_ids"]) == 2 and len(e["items"]) == 2
    assert {i["file_name"] for i in e["items"]} == {"orionstrategypar-inv-029.pdf", "orionstrategypar_281.pdf"}


def test_list_shows_the_suggested_action_and_filters_by_class(api):
    page = api("ap_clerk").get("/intake/emails", params={"email_class": "payment_inquiry"}).json()
    assert [e["email_id"] for e in page["items"]] == ["EM-057"]
    assert page["items"][0]["suggested_action"]["invoice_status"]["invoice_id"] == "AP-00049"
    everything = api("ap_clerk").get("/intake/emails", params={"limit": 200}).json()["items"]
    assert len(everything) == 59 and all(e["suggested_action"] for e in everything)


@pytest.mark.parametrize("role", ["ap_clerk", "finance_manager", "controller_admin", "auditor"])
def test_back_office_can_read_an_email(api, role):
    assert email(api, "EM-001", role)["email_id"] == "EM-001"


@pytest.mark.parametrize("role", ["employee", "approver"])
def test_employee_and_approver_are_refused(api, role):
    c = api(role)
    assert c.get("/intake/emails/EM-001").status_code == 403
    assert c.get(f"/intake/files/{'0' * 64}").status_code == 403


def test_unknown_email_is_404(api):
    r = api("ap_clerk").get("/intake/emails/EM-999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "email.not_found"


@pytest.mark.parametrize("name,ctype", [("Invoice HA26-2766.pdf", "application/pdf"),
                                        ("scan_8749.png", "image/png")])
def test_original_file_is_served_with_its_type(api, monkeypatch, name, ctype):
    monkeypatch.setattr(get_settings(), "files_dir", api.files_dir)
    data = (INCOMING / name).read_bytes()
    h = hashlib.sha256(data).hexdigest()
    assert (api.files_dir / h).exists()  # served from the kept copy, not the inbox fallback
    r = api("auditor").get(f"/intake/files/{h}")
    assert r.status_code == 200
    assert r.content == data and r.headers["content-type"] == ctype
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == f'inline; filename="{name}"'


@pytest.mark.parametrize("bad", ["0" * 64, "..%2F..%2F.env", "abc"])
def test_unknown_or_malformed_file_hash_is_404(api, bad):
    assert api("ap_clerk").get(f"/intake/files/{bad}").status_code == 404


def test_file_falls_back_to_the_inbox_folder_when_no_copy_was_kept(api):
    # Bills made before originals were kept (this test's files_dir is empty): the file is found in the inbox
    # folder, and its hash is checked.
    assert not get_settings().files_dir.exists()
    data = (INCOMING / "Invoice 853.pdf").read_bytes()
    h = hashlib.sha256(data).hexdigest()
    r = api("ap_clerk").get(f"/intake/files/{h}")
    assert r.status_code == 200 and r.content == data
