"""GET /early-pay: back-office roles only, read from the database, same answer as the CSV dataset."""
from __future__ import annotations

import re
from datetime import date

import pytest

from app.controls.early_pay import discount_history, suggest_pay_dates
from app.controls.history import load_approvals_and_payments
from app.controls.refdata import default_refdata
from tests.api.factories import app_bill

MONEY = re.compile(r"^-?\d+\.\d{2}$")
URL = "/early-pay"


@pytest.mark.parametrize("role", ["ap_clerk", "finance_manager", "controller_admin", "auditor"])
def test_back_office_can_read_it(as_role, role):
    assert as_role(role).get(URL).status_code == 200


@pytest.mark.parametrize("role", ["employee", "approver"])
def test_employee_and_approver_are_refused(as_role, role):
    r = as_role(role).get(URL)
    assert r.status_code == 403 and set(r.json()["error"]) == {"code", "message", "details"}


def test_database_gives_the_same_answer_as_the_dataset(as_role):
    body = as_role("auditor").get(URL).json()
    ref = default_refdata()
    _, payments = load_approvals_and_payments()
    want = suggest_pay_dates(ref, payments)
    got = [(x["bill_id"], x["pay_on"], x["action"], x["saving"]) for x in body["suggestions"]]
    assert got == [(s.invoice_id, s.pay_on.isoformat(), s.action, f"{s.saving:.2f}") for s in want]
    assert body["summary"]["bills"] == 20 and body["summary"]["saving_cad"] == "0.00"
    h = discount_history(ref, payments)
    assert (body["history"]["taken"], body["history"]["missed"]) == (len(h.taken), len(h.missed)) == (9, 10)
    assert body["history"]["missed_cad"] == f"{h.missed_cad:.2f}" == "827.77"


def test_money_is_a_string(as_role):
    body = as_role("ap_clerk").get(URL).json()
    s = body["suggestions"][0]
    assert all(MONEY.match(s[k]) for k in ("total", "saving", "saving_cad", "pay_amount"))
    assert body["as_of"] == "2026-11-02"


def test_pending_bill_from_a_discount_vendor_shows_what_approving_in_time_saves(fresh_engine, act_as):
    # Paper Trail Office Supply (V024) is 2/10 net 30. A $547.00 bill dated 2026-10-26 still in review.
    bill = app_bill(fresh_engine, vendor_id="V024", amount="547.00", number="2217", when=date(2026, 10, 26))
    client = act_as("U004")
    assert bill not in {x["bill_id"] for x in client.get(URL).json()["suggestions"]}  # not approved yet
    body = client.get(URL, params={"include_pending": "true"}).json()
    s = next(x for x in body["suggestions"] if x["bill_id"] == bill)
    assert (s["status"], s["action"], s["discount_deadline"], s["pay_on"]) == \
        ("needs_review", "take_discount", "2026-11-05", "2026-11-04")
    assert (s["saving"], s["pay_amount"]) == ("10.94", "607.17")
    assert s["terms"] == "2% off if paid within 10 days, net 30"
    assert body["suggestions"][0]["bill_id"] == bill  # biggest saving first
    assert body["summary"]["with_discount_open"] == 1 and body["summary"]["saving_cad"] == "10.94"


def test_bills_held_by_a_blocking_flag_are_left_out(fresh_engine, act_as):
    # Back-filled history: AP-00407 is a scheduled duplicate of AP-00394 on a closed PO (two open blocking flags), so
    # nobody should be told to pay it now. AP-00394, the original, still gets its suggestion.
    from sqlalchemy.orm import Session

    from app.db.backfill import backfill_history_controls
    from app.db.database import as_write_engine
    with Session(as_write_engine(fresh_engine)) as session:
        backfill_history_controls(session)
        session.commit()
    ids = [x["bill_id"] for x in act_as("U004").get(URL).json()["suggestions"]]
    assert "AP-00407" not in ids
    assert "AP-00394" in ids


def test_missed_discounts_name_their_vendor(as_role):
    missed = as_role("auditor").get(URL).json()["history"]["missed_payments"]
    assert missed and all(m["vendor_name"] for m in missed)
    assert {m["vendor_id"]: m["vendor_name"] for m in missed}["V010"]
