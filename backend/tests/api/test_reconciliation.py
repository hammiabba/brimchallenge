"""GET /reconciliation/bank: controller and auditor only, read from the database, same answer as the CSV dataset."""
from __future__ import annotations

import re

import pytest

from app.controls.reconciliation import load_bank_and_payments, reconcile
from app.controls.refdata import default_refdata

MONEY = re.compile(r"^-?\d+\.\d{2}$")
URL = "/reconciliation/bank"


@pytest.fixture(scope="module")
def from_csv():
    return reconcile(*load_bank_and_payments(), default_refdata())


@pytest.mark.parametrize("role", ["controller_admin", "auditor"])
def test_controller_and_auditor_can_read_it(as_role, role):
    assert as_role(role).get(URL).status_code == 200


@pytest.mark.parametrize("role", ["employee", "ap_clerk", "approver", "finance_manager"])
def test_everyone_else_is_refused(as_role, role):
    r = as_role(role).get(URL)
    assert r.status_code == 403 and set(r.json()["error"]) == {"code", "message", "details"}


def test_database_gives_the_same_answer_as_the_dataset(as_role, from_csv):
    body = as_role("auditor").get(URL).json()
    s = from_csv.summary()
    assert body["summary"]["lines"] == s["lines"] == 354
    assert body["summary"]["matched"] == s["matched"]
    assert body["summary"]["unexplained_cad"] == f"{s['unexplained_cad']:.2f}"
    assert body["summary"]["double_paid_extra_cad"] == f"{s['double_paid_extra_cad']:.2f}"
    assert body["summary"]["issues"] == s["issues"]
    api_lines = {ln["bank_txn_id"]: (ln["status"], ln["payment_ids"], [i["code"] for i in ln["issues"]])
                 for ln in body["lines"]}
    csv_lines = {ln.bank_txn_id: (ln.status, ln.payment_ids, [i.code for i in ln.issues]) for ln in from_csv.lines}
    assert api_lines == csv_lines
    assert len(body["double_payments"]) == len(from_csv.double_payments) == 10


def test_money_is_a_string_and_bills_are_named_bill_ids(as_role):
    body = as_role("controller_admin").get(URL).json()
    ln = next(ln for ln in body["lines"] if ln["bank_txn_id"] == "BK-00296")  # cheque 5018, 5 cents over
    assert MONEY.match(ln["amount"]) and ln["difference"] == "0.05" and ln["bill_ids"]
    assert all(MONEY.match(v) for k, v in body["summary"].items() if k.endswith("_cad"))
    assert body["statement_from"] == "2026-01-05" and body["statement_to"] == "2026-11-02"


def test_only_issues_keeps_what_needs_review(as_role):
    client = as_role("auditor")
    full, short = client.get(URL).json(), client.get(URL, params={"only_issues": "true"}).json()
    assert len(short["lines"]) < len(full["lines"])
    assert all(any(i["severity"] == "review" for i in x["issues"]) for x in short["lines"] + short["payments"])
    assert short["summary"] == full["summary"]  # the totals always cover the whole statement
    assert short["summary"]["needs_review"] == len(short["lines"]) + len(short["payments"])
