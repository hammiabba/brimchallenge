"""Early-payment discounts: terms parsing, the discount amount, pay-date suggestions, and the history."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.controls.early_pay import (
    PENDING_STATUSES,
    discount_amount,
    discount_history,
    parse_terms,
    suggest_pay_dates,
)
from app.controls.history import load_approvals_and_payments

TODAY = date(2026, 11, 2)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["2/10 net 30", "2/10 n/30", "2/10, net 30", "2% 10 net 30", "2%/10 Net30",
                                  "2/10 net 30 days", " 2 / 10  NET 30 "])
def test_discount_formats(text):
    t = parse_terms(text, "30")
    assert (t.discount_pct, t.discount_days, t.net_days, t.note) == (D("2"), 10, 30, None)


def test_fractional_percent_and_other_windows():
    t = parse_terms("1.5/15 net 45", "45")
    assert (t.discount_pct, t.discount_days, t.net_days) == (D("1.5"), 15, 45)


def test_blank_text_uses_payment_terms_days():
    # Every vendor without a discount in the dataset: blank text, net 0 / 15 / 21 / 30.
    assert parse_terms("", "21") == parse_terms(None, "21")
    t = parse_terms("", "21")
    assert (t.has_discount, t.net_days) == (False, 21)
    assert parse_terms("", "0").describe() == "due on receipt"


@pytest.mark.parametrize("text,net", [("net 45", 45), ("n/60", 60), ("Net30", 30), ("due on receipt", 0)])
def test_net_only_text(text, net):
    t = parse_terms(text, "30")
    assert (t.has_discount, t.net_days) == (False, net)


def test_written_net_wins_over_payment_terms_days_and_says_so():
    t = parse_terms("2/10 net 45", "30")
    assert t.net_days == 45 and "payment_terms_days is 30" in t.note


@pytest.mark.parametrize("text", ["2/30 net 30", "0/10 net 30", "120/10 net 30"])
def test_nonsense_terms_give_no_discount(text):
    t = parse_terms(text, "30")
    assert not t.has_discount and t.net_days == 30 and "don't make sense" in t.note


def test_unrecognised_terms_give_no_discount_rather_than_a_guess():
    t = parse_terms("2/10 EOM", "30")
    assert not t.has_discount and t.net_days == 30 and "not recognised" in t.note


def test_every_vendor_term_in_the_dataset_parses_cleanly(ref):
    terms = [parse_terms(v["early_pay_discount"], v["payment_terms_days"]) for v in ref.vendors.values()]
    assert all(t.note is None for t in terms)
    assert sorted(v for v, t in zip(ref.vendors, terms, strict=True) if t.has_discount) == ["V010", "V024", "V033"]


def test_annual_rate_of_skipping_2_10_net_30():
    assert parse_terms("2/10 net 30", "30").annual_rate == D("0.3724")  # 2/98 for 20 days, about 37% a year


# ---------------------------------------------------------------------------
# The discount amount matches every discount the history actually took
# ---------------------------------------------------------------------------
def test_discount_is_two_percent_of_the_subtotal_as_taken_in_history(ref):
    _, payments = load_approvals_and_payments()
    taken = [p for p in payments if p["discount_taken"] not in ("", "0.00")]
    assert len(taken) == 9
    terms = parse_terms("2/10 net 30", "30")
    for p in taken:
        assert discount_amount(terms, D(ref.invoices[p["invoice_id"]]["subtotal"])) == D(p["discount_taken"])


# ---------------------------------------------------------------------------
# Suggestions, on one made-up open bill (V024 Paper Trail Office Supply: 2/10 net 30, pays by EFT)
# ---------------------------------------------------------------------------
def with_bill(ref, **over):
    inv = {"invoice_id": "AP-90001", "vendor_id": "V024", "vendor_invoice_number": "2217",
           "invoice_date": "2026-10-26", "received_date": "2026-10-26", "due_date": "2026-11-25", "currency": "CAD",
           "subtotal": "547.00", "gst_hst_amount": "71.11", "pst_qst_amount": "0.00", "total": "618.11",
           "fx_rate_to_cad": "1", "total_cad": "618.11", "department_id": "D03", "requester_user_id": "",
           "po_id": "", "contract_id": "", "ship_to_province": "ON", "status": "approved", **over}
    return replace(ref, invoices={"AP-90001": inv})


def only(ref, payments=(), **kw):
    [s] = suggest_pay_dates(ref, list(payments), today=kw.pop("today", TODAY), **kw)
    return s


def scheduled(on, method="EFT"):
    return {"payment_id": "PAY-90001", "invoice_id": "AP-90001", "vendor_id": "V024", "method": method,
            "scheduled_date": on, "paid_date": "", "status": "scheduled"}


def test_open_discount_is_paid_the_day_before_it_ends(ref):
    s = only(with_bill(ref))
    assert (s.discount_deadline, s.pay_on, s.action) == (date(2026, 11, 5), date(2026, 11, 4), "take_discount")
    assert (s.saving, s.saving_cad, s.pay_amount) == (D("10.94"), D("10.94"), D("607.17"))
    assert "save $10.94" in s.reason and "37% a year" in s.reason


def test_cheque_goes_out_earlier_and_card_on_the_deadline(ref):
    assert only(with_bill(ref), [scheduled("2026-11-04", "CHEQUE")]).pay_on == date(2026, 11, 2)
    assert only(with_bill(ref), [scheduled("2026-11-04", "CARD")]).pay_on == date(2026, 11, 5)


def test_last_day_of_the_window_means_pay_today(ref):
    s = only(with_bill(ref), today=date(2026, 11, 5))
    assert (s.pay_on, s.action, s.saving) == (date(2026, 11, 5), "take_discount", D("10.94"))


def test_scheduled_after_the_discount_ends_is_moved(ref):
    s = only(with_bill(ref), [scheduled("2026-11-25")])
    assert s.action == "reschedule" and s.scheduled_date == date(2026, 11, 25)
    assert "Move it to Nov 4, 2026 to save $10.94" in s.reason


def test_closed_discount_pays_on_the_due_date_and_names_what_was_missed(ref):
    s = only(with_bill(ref), today=date(2026, 11, 10))
    assert (s.pay_on, s.action, s.saving) == (date(2026, 11, 25), "pay_on_due_date", D("0.00"))
    assert "discount ($10.94) ended Nov 5, 2026" in s.reason


def test_overdue_bill_is_paid_now(ref):
    s = only(with_bill(ref), today=date(2026, 12, 1))
    assert (s.pay_on, s.action) == (date(2026, 12, 1), "pay_now") and "Overdue since" in s.reason


def test_payment_scheduled_after_the_due_date_is_moved(ref):
    s = only(with_bill(ref, vendor_id="V001"), [scheduled("2026-11-30")], today=date(2026, 11, 10))
    assert s.action == "reschedule" and "after the Nov 25, 2026 due date" in s.reason


def test_usd_saving_is_also_given_in_cad(ref):
    s = only(with_bill(ref, currency="USD", fx_rate_to_cad="1.35"))
    assert (s.saving, s.saving_cad) == (D("10.94"), D("14.77"))


def test_credit_notes_and_other_statuses_are_skipped(ref):
    assert suggest_pay_dates(with_bill(ref, total="-618.11", subtotal="-547.00"), [], today=TODAY) == []
    assert suggest_pay_dates(with_bill(ref, status="paid"), [], today=TODAY) == []
    assert suggest_pay_dates(with_bill(ref, status="pending_approval"), [], today=TODAY) == []
    assert only(with_bill(ref, status="pending_approval"), statuses=PENDING_STATUSES).saving == D("10.94")


def test_due_date_that_disagrees_with_the_terms_is_noted(ref):
    s = only(with_bill(ref, due_date="2026-11-10"))
    assert s.due_date == date(2026, 11, 10) and "isn't 2% off" in s.notes[0]


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def payments():
    return load_approvals_and_payments()[1]


def test_open_bills_in_the_dataset(ref, payments):
    out = suggest_pay_dates(ref, payments)
    assert len(out) == 20  # 18 scheduled + 2 approved
    assert all(s.saving == 0 for s in out)  # none is from a vendor with a discount
    overdue = next(s for s in out if s.invoice_id == "AP-00399")  # due 2026-11-01, today is 2026-11-02
    assert overdue.action == "pay_now" and overdue.pay_on == TODAY


def test_history_took_nine_discounts_and_missed_ten(ref, payments):
    h = discount_history(ref, payments)
    assert (len(h.taken), h.taken_cad) == (9, D("296.18"))
    assert (len(h.missed), h.missed_cad) == (10, D("827.77"))
    assert all(x.days_to_pay <= 10 for x in h.taken) and all(x.days_to_pay >= 30 for x in h.missed)
    assert max(h.missed, key=lambda x: x.discount_cad).invoice_id == "AP-00180"  # $201.93 on Ironwood's $10,096
