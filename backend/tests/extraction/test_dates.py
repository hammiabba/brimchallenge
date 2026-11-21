"""Ambiguous slash dates ("03/04/2026"): both readings are kept and evidence picks one, or we say we guessed."""
from datetime import date

import pytest

from app.extraction import pipeline
from app.extraction.normalize import date_readings, resolve_dates
from tests.extraction.test_pipeline import HARLOW, FakeClient, raw_invoice

AS_OF = date(2026, 11, 2)


@pytest.mark.parametrize("raw,expected", [
    ("2026-03-04", [date(2026, 3, 4)]),
    ("27/10/2026", [date(2026, 10, 27)]),              # day > 12: only one reading
    ("10/27/2026", [date(2026, 10, 27)]),              # month-first, also unambiguous
    ("03/04/2026", [date(2026, 4, 3), date(2026, 3, 4)]),
    ("05/05/2026", [date(2026, 5, 5)]),                # same either way
    ("Oct 3, 2026", [date(2026, 10, 3)]),
    ("3 octobre 2026", [date(2026, 10, 3)]),
    (None, []),
])
def test_date_readings(raw, expected):
    assert date_readings(raw) == expected


def test_unambiguous_dates_pass_through_without_warnings():
    r = resolve_dates("2026-10-27", "2026-11-26", 30, AS_OF)
    assert (r.invoice_date, r.due_date) == (date(2026, 10, 27), date(2026, 11, 26))
    assert not r.warnings and not r.ambiguous and not r.resolved


def test_payment_terms_pick_the_month_first_reading():
    # Both dates ambiguous. Day-first gives invoice 2026-10-09, due 2026-09-10 (due before invoice);
    # month-first gives 2026-09-10 → 2026-10-09, 29 days, which matches Net 30.
    r = resolve_dates("09/10/2026", "10/09/2026", 30, AS_OF)
    assert (r.invoice_date, r.due_date) == (date(2026, 9, 10), date(2026, 10, 9))
    assert r.resolved == {"invoice_date", "due_date"} and not r.ambiguous
    assert "payment terms" in r.warnings[0]


def test_unambiguous_due_date_fixes_the_convention():
    # "04/18/2026" can only be month-first, so "03/04/2026" on the same document is March 4.
    r = resolve_dates("03/04/2026", "04/18/2026", None, AS_OF)
    assert r.invoice_date == date(2026, 3, 4)
    assert r.resolved == {"invoice_date"} and "other date's format" in r.warnings[0]


def test_future_reading_is_rejected():
    # 11/03/2026: day-first 2026-03-11, month-first 2026-11-03 (after the as-of date).
    r = resolve_dates("11/03/2026", None, None, AS_OF)
    assert r.invoice_date == date(2026, 3, 11) and r.resolved == {"invoice_date"}


def test_no_evidence_keeps_day_first_and_warns():
    r = resolve_dates("03/04/2026", None, None, AS_OF)
    assert r.invoice_date == date(2026, 4, 3)
    assert r.ambiguous == {"invoice_date"}
    assert "ambiguous" in r.warnings[0] and "please confirm" in r.warnings[0]


def test_ambiguous_date_lowers_confidence_in_the_draft(repo):
    raw = raw_invoice(invoice_date="03/04/2026", due_date=None, payment_terms=None)
    bill = pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo, client=FakeClient(raw))
    assert bill.invoice_date == date(2026, 4, 3)
    assert bill.field_confidence["invoice_date"] <= 0.5
    assert any("ambiguous" in w for w in bill.extraction_warnings)


def test_terms_resolve_the_date_in_the_draft(repo):
    # Net 30 printed; due 2026-04-03 is ISO, so invoice "03/04/2026" must be March 4 (30 days before).
    raw = raw_invoice(invoice_date="03/04/2026", due_date="2026-04-03", payment_terms="Net 30")
    bill = pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo, client=FakeClient(raw))
    assert bill.invoice_date == date(2026, 3, 4)
    assert 0.5 < bill.field_confidence["invoice_date"] < 0.95
    assert any("payment terms" in w for w in bill.extraction_warnings)


def test_vendor_master_terms_used_when_none_printed(repo):
    # Harlow and Stern (V052) has 30-day terms in the master.
    assert repo.vendor("V052")["payment_terms_days"] == "30"
    raw = raw_invoice(invoice_date="03/04/2026", due_date="2026-04-03", payment_terms=None)
    bill = pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo, client=FakeClient(raw))
    assert bill.invoice_date == date(2026, 3, 4)
