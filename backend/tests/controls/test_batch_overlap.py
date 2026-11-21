"""A bill that is both in the reference data and in the batch must count once.

The API's inbox job stores bills one at a time, then runs controls on each with the whole batch. By the time bill N
is checked, bills 1..N-1 are already in the database (so in RefData.invoices) and also in the batch. Counted twice,
two $4,000 bills look like a $12,000 split, and a duplicate pair shows "+1 more".
"""
from dataclasses import replace
from datetime import date

from app.controls import run_controls


def stored(ref, bill, bill_id):
    """The RefData invoice row the DB layer builds for an app bill (same columns as invoices.csv)."""
    row = dict(next(iter(ref.invoices.values())))
    row.update(invoice_id=bill_id, vendor_id=bill.vendor.vendor_id, vendor_invoice_number=bill.invoice_number,
               invoice_date=bill.invoice_date.isoformat(), received_date=bill.invoice_date.isoformat(),
               subtotal=str(bill.subtotal), total=str(bill.total), total_cad=str(bill.total_cad),
               department_id=bill.department_id or "", po_id="", contract_id="", status="needs_review")
    return replace(ref, invoices={**ref.invoices, bill_id: row})


def test_bill_in_refdata_and_batch_is_not_counted_twice_in_a_split(ref, make_bill):
    first = make_bill(vendor_id="V003", amount="4000.00", number="PX-1", when=date(2026, 10, 27), file_hash="h1")
    second = make_bill(vendor_id="V003", amount="4000.00", number="PX-2", when=date(2026, 10, 27), file_hash="h2")
    with_first = stored(ref, first, "B-0001")  # first is already saved, and still in the batch
    result = run_controls(second, [first, second], ref=with_first)
    assert "POSSIBLE_SPLIT" not in {f.code for f in result.flags}  # $8,000 together, under $10,000


def test_duplicate_pair_in_refdata_and_batch_matches_once(ref, make_bill):
    first = make_bill(number="INV-77", file_hash="h1")
    second = make_bill(number="INV-77", file_hash="h2")  # the same invoice sent twice
    result = run_controls(second, [first, second], ref=stored(ref, first, "B-0001"))
    [dup] = [f for f in result.flags if f.code == "DUPLICATE_EXACT"]
    assert dup.evidence["matches"] == ["B-0001"] and "more" not in dup.message


def test_batch_bills_not_in_refdata_still_count(ref, make_bill):
    # The CSV path (run_incoming.py): nothing is stored, so the batch is the only place the others are
    bills = [make_bill(vendor_id="V003", amount="4000.00", number=f"PX-{n}", when=date(2026, 10, 27),
                       file_hash=f"h{n}") for n in range(3)]
    assert "POSSIBLE_SPLIT" in {f.code for f in run_controls(bills[0], bills, ref=ref).flags}
