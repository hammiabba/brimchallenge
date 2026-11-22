"""Bank reconciliation: each matching rule on small hand-made statements, then the real statement and payments."""
from decimal import Decimal as D

import pytest

from app.controls.history import replay
from app.controls.reconciliation import load_bank_and_payments, reconcile


def bank(txn, day, text, debit="", credit=""):
    return {"bank_txn_id": txn, "posted_date": day, "description": text, "debit": debit, "credit": credit}


def pay(pid, inv, vendor, method, amount, paid="", sched="2026-03-01", ref="", status="settled"):
    return {"payment_id": pid, "invoice_id": inv, "vendor_id": vendor, "method": method, "scheduled_date": sched,
            "paid_date": paid, "currency": "CAD", "amount": amount, "fx_rate_to_cad": "1", "amount_cad": amount,
            "reference": ref, "status": status}


def codes(x):
    return [i.code for i in x.issues]


def line(r, txn):
    return next(ln for ln in r.lines if ln.bank_txn_id == txn)


def payment(r, pid):
    return next(p for p in r.payments if p.payment_id == pid)


# ---------------------------------------------------------------------------
# Rules, on hand-made rows (V001 Polar Freight Lines, V002 Great Lakes Carriers)
# ---------------------------------------------------------------------------
def test_eft_matches_on_the_last_six_digits_of_the_reference(ref):
    r = reconcile([bank("B1", "2026-03-02", "EFT PMT POLAR FREIGHT LINES LTD. 123456", "100.00")],
                  [pay("P1", "AP-00001", "V001", "EFT", "100.00", "2026-03-01", ref="BRIM-EFT-99123456")], ref)
    ln = line(r, "B1")
    assert (ln.status, ln.payment_ids, ln.issues) == ("matched", ["P1"], [])


def test_eft_with_an_unknown_reference_falls_back_to_amount_and_payee(ref):
    r = reconcile([bank("B1", "2026-03-02", "EFT PMT POLAR FREIGHT LINES LTD. 000000", "100.00")],
                  [pay("P1", "AP-00001", "V001", "EFT", "100.00", "2026-03-01", ref="BRIM-EFT-99123456")], ref)
    assert line(r, "B1").status == "matched" and codes(line(r, "B1")) == ["MATCHED_WITHOUT_REFERENCE"]


def test_eft_to_a_different_payee_is_reported(ref):
    r = reconcile([bank("B1", "2026-03-02", "EFT PMT SOMEONE ELSE ENTIRELY 123456", "100.00")],
                  [pay("P1", "AP-00001", "V001", "EFT", "100.00", "2026-03-01", ref="BRIM-EFT-99123456")], ref)
    assert codes(line(r, "B1")) == ["PAYEE_DIFFERS"]


def test_amount_difference_is_reported_with_its_sign(ref):
    r = reconcile([bank("B1", "2026-03-02", "EFT PMT POLAR FREIGHT LINES LTD. 123456", "100.01")],
                  [pay("P1", "AP-00001", "V001", "EFT", "100.00", "2026-03-01", ref="BRIM-EFT-99123456")], ref)
    ln = line(r, "B1")
    assert ln.difference == D("0.01") and codes(ln) == ["AMOUNT_DIFFERS"]
    assert "(+$0.01)" in ln.issues[0].message


def test_identical_cheques_go_to_the_closest_issue_date_before_clearing(ref):
    # Two rent cheques for the same amount: each clearing goes to the cheque issued just before it.
    payments = [pay("JAN", "AP-00001", "V001", "CHEQUE", "500.00", "2026-01-05", status="outstanding"),
                pay("FEB", "AP-00002", "V001", "CHEQUE", "500.00", "2026-02-05", status="outstanding")]
    r = reconcile([bank("B2", "2026-02-15", "CHEQUE 102 CLEARED", "500.00"),
                   bank("B1", "2026-01-15", "CHEQUE 101 CLEARED", "500.00")], payments, ref)
    assert line(r, "B1").payment_ids == ["JAN"] and line(r, "B2").payment_ids == ["FEB"]
    assert codes(line(r, "B1")) == ["STATUS_NOT_UPDATED"]  # cleared, but still "outstanding" in the records


def test_cheque_that_cleared_for_a_few_cents_more_is_still_matched(ref):
    r = reconcile([bank("B1", "2026-01-15", "CHEQUE 101 CLEARED", "500.05")],
                  [pay("P1", "AP-00001", "V001", "CHEQUE", "500.00", "2026-01-05")], ref)
    assert line(r, "B1").payment_ids == ["P1"] and line(r, "B1").difference == D("0.05")


def test_cheque_never_matches_one_issued_after_it_cleared(ref):
    r = reconcile([bank("B1", "2026-01-15", "CHEQUE 101 CLEARED", "500.00")],
                  [pay("P1", "AP-00001", "V001", "CHEQUE", "500.00", "2026-01-20", status="outstanding")], ref)
    assert line(r, "B1").status == "unexplained" and codes(payment(r, "P1")) == ["OUTSTANDING_CHEQUE"]


def test_fees_and_wire_fees_without_a_wire(ref):
    r = reconcile([bank("B1", "2026-03-28", "MONTHLY ACCOUNT FEE", "29.50"),
                   bank("B2", "2026-03-11", "WIRE FEE", "15.00")], [], ref)
    assert line(r, "B1").status == line(r, "B2").status == "bank_fee"
    assert codes(line(r, "B1")) == ["BANK_FEE"]
    assert codes(line(r, "B2")) == ["BANK_FEE", "WIRE_FEE_WITHOUT_WIRE"]


def test_unexplained_debit_and_credit(ref):
    r = reconcile([bank("B1", "2026-03-11", "PREAUTH DEBIT 913114", "174.90"),
                   bank("B2", "2026-03-12", "DEPOSIT", credit="50.00")], [], ref)
    assert codes(line(r, "B1")) == ["UNEXPLAINED_DEBIT"] and "Pre-authorized debit" in line(r, "B1").issues[0].message
    assert codes(line(r, "B2")) == ["UNEXPLAINED_CREDIT"] and line(r, "B2").amount == D("-50.00")


def test_payments_with_no_bank_line(ref):
    payments = [pay("OLD", "AP-00001", "V001", "EFT", "10.00", "2026-01-01", ref="BRIM-EFT-11111111"),
                pay("NEW", "AP-00002", "V001", "EFT", "10.00", "2026-03-01", ref="BRIM-EFT-22222222"),
                pay("SCH", "AP-00003", "V001", "EFT", "10.00", sched="2026-03-05", status="scheduled"),
                pay("CHQ", "AP-00004", "V001", "CHEQUE", "10.00", "2025-11-01", status="outstanding"),
                pay("CARD", "AP-00005", "V001", "CARD", "10.00", "2026-01-01", ref="BRIM-VC-1")]
    r = reconcile([bank("B1", "2026-03-02", "MONTHLY ACCOUNT FEE", "29.50")], payments, ref)
    assert codes(payment(r, "OLD")) == ["NOT_ON_STATEMENT"]  # settled two months before the statement ends
    assert codes(payment(r, "NEW")) == ["IN_TRANSIT"]        # sent the day before: not posted yet
    assert codes(payment(r, "SCH")) == ["SCHEDULED"]
    assert codes(payment(r, "CHQ")) == ["STALE_CHEQUE"]
    assert codes(payment(r, "CARD")) == ["PAID_BY_CARD"]


def test_cancelled_payments_are_ignored(ref):
    r = reconcile([], [pay("P1", "AP-00001", "V001", "EFT", "10.00", status="cancelled")], ref)
    assert r.payments == []


# ---------------------------------------------------------------------------
# The real statement and payments
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real(ref):
    return reconcile(*load_bank_and_payments(), ref)


def test_every_debit_is_matched_a_fee_or_unexplained(real):
    s = real.summary()
    assert (s["lines"], s["matched"], s["bank_fees"], s["unexplained"]) == (354, 333, 16, 5)
    assert s["matched_cad"] + s["bank_fees_cad"] + s["unexplained_cad"] == s["debits_cad"] == D("1742643.22")
    assert (real.statement_from.isoformat(), real.statement_to.isoformat()) == ("2026-01-05", "2026-11-02")


def test_every_eft_and_cheque_that_left_is_on_the_statement(real):
    assert all("NOT_ON_STATEMENT" not in codes(p) for p in real.payments)
    matched = {pid for ln in real.lines for pid in ln.payment_ids}
    assert len(matched) == 333  # 313 EFT + 20 cheques, each on exactly one line


def test_rent_cheques_go_to_the_right_month(real):
    assert line(real, "BK-00006").payment_ids == ["PAY-00005"]   # cheque 5001, Jan
    assert line(real, "BK-00335").payment_ids == ["PAY-00389"]   # cheque 5020, Oct


def test_cheque_5018_cleared_five_cents_over(real):
    ln = line(real, "BK-00296")
    assert ln.payment_ids == ["PAY-00347"] and ln.difference == D("0.05")
    assert codes(ln) == ["AMOUNT_DIFFERS", "STATUS_NOT_UPDATED"]


def test_eft_lines_a_cent_over(real):
    over = {ln.bank_txn_id: ln.difference for ln in real.lines
            if "AMOUNT_DIFFERS" in codes(ln) and ln.description.startswith("EFT")}
    assert over == {"BK-00121": D("0.01"), "BK-00190": D("0.01"), "BK-00230": D("0.01")}


def test_all_twenty_cleared_cheques_are_still_outstanding_in_the_records(real):
    assert sum("STATUS_NOT_UPDATED" in codes(ln) for ln in real.lines) == 20


def test_fees_and_unexplained_debits(real):
    fees = [ln for ln in real.lines if ln.status == "bank_fee"]
    assert sum(ln.description == "MONTHLY ACCOUNT FEE" for ln in fees) == 10
    assert sum("WIRE_FEE_WITHOUT_WIRE" in codes(ln) for ln in fees) == 6  # no payment ever went by wire
    unexplained = [ln for ln in real.lines if ln.status == "unexplained"]
    assert {ln.bank_txn_id for ln in unexplained} == {"BK-00064", "BK-00088", "BK-00192", "BK-00193", "BK-00207"}
    assert all(ln.description.startswith("PREAUTH DEBIT") for ln in unexplained)


def test_double_payments_are_the_same_bills_as_the_history_replay(real, ref):
    mine = sorted((sorted(g.invoice_ids + g.card_txn_ids), g.extra_paid_cad, g.at_risk_cad)
                  for g in real.double_payments)
    theirs = sorted((sorted(g.ids), g.extra_paid_cad, g.at_risk_cad) for g in replay(ref).doubles)
    assert mine == theirs and len(mine) == 10


def test_double_payment_extra_copies_are_marked_on_the_bank(real):
    marked = {ln.bank_txn_id for ln in real.lines if "DOUBLE_PAYMENT" in codes(ln)}
    assert "BK-00112" in marked   # Redline FA-001655 paid again as 1655-A
    assert len(marked) == 7       # the other 3 extra copies were card charges, not on this account
    assert "DOUBLE_PAYMENT_AT_RISK" in codes(payment(real, "PAY-00399"))  # Summit, scheduled to pay twice
    assert "DOUBLE_PAYMENT_AT_RISK" not in codes(payment(real, "PAY-00386"))  # the first copy is fine


def test_the_at_risk_note_names_the_payment_to_cancel(real):
    [note] = [i.message for i in payment(real, "PAY-00399").issues if i.code == "DOUBLE_PAYMENT_AT_RISK"]
    assert note.endswith(" Cancel PAY-00399 before it is sent.")


def test_instalments_are_not_double_payments(real):
    # AP-00117 was paid in two parts (PAY-00113 + PAY-00114): one bill, one payment.
    assert not any("AP-00117" in g.invoice_ids for g in real.double_payments)


def test_payment_after_unverified_bank_change(real):
    assert "PAID_AFTER_UNVERIFIED_BANK_CHANGE" in codes(line(real, "BK-00347"))  # Cascadia AP-00388
