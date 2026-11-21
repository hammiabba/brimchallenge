from datetime import date
from decimal import Decimal as D

from app.controls import bill_from_history, duplicate_flags, find_duplicates, find_split
from app.shared.schemas import Severity


def kinds(matches):
    return {(m.kind, m.matched_invoice_id or m.matched_card_txn_id) for m in matches}


def test_exact_duplicate(ref):
    # AP-00034 and AP-00023: Lakeshore Hydro INV-02990, both PAID (money to recover)
    assert ("exact", "AP-00023") in kinds(find_duplicates(bill_from_history(ref, "AP-00034"), ref))


def test_leading_zeros_duplicate(ref):
    # 604 vs 000604 from Northbound Couriers
    assert ("normalized", "AP-00073") in kinds(find_duplicates(bill_from_history(ref, "AP-00077"), ref))


def test_prefix_and_suffix_duplicate(ref):
    # 1655-A vs FA-001655 from Redline Fleet Cards
    assert ("normalized", "AP-00136") in kinds(find_duplicates(bill_from_history(ref, "AP-00155"), ref))


def test_monthly_rent_is_not_a_duplicate(ref):
    # Granville rent is $8,137.50 every month. Same amount, different month: NOT a duplicate.
    assert find_duplicates(bill_from_history(ref, "AP-00042"), ref) == []


def test_near_duplicate_new_number(ref, make_bill):
    # Same vendor, same amount, 3 days later, slightly different number
    orig = bill_from_history(ref, "AP-00023")
    bill = make_bill(vendor_id=orig.vendor.vendor_id, number="INV-02991", when=date(2026, 1, 14))
    bill.total = orig.total
    assert any(m.kind == "near" for m in find_duplicates(bill, ref))


def test_same_bank_under_lookalike_vendor(ref, make_bill):
    # A bill under V051 for the same amount as a V001 invoice: same bank account, different vendor record
    orig = next(i for i in ref.invoices.values() if i["vendor_id"] == "V001")
    bill = make_bill(vendor_id="V051", number="X-1", when=date.fromisoformat(orig["invoice_date"]))
    bill.total = D(orig["total"])
    assert ("cross_vendor", orig["invoice_id"]) in kinds(find_duplicates(bill, ref))


def test_already_paid_by_employee_card(ref):
    # AP-00015 Paper Trail: an employee card charge for the same amount a few days apart
    matches = find_duplicates(bill_from_history(ref, "AP-00015"), ref)
    assert ("card_paid", "CT-00017") in kinds(matches)


# ---- matches become flags ----
def test_duplicate_kinds_map_to_schema_flags(ref):
    flags = {f.code: f for f in duplicate_flags(find_duplicates(bill_from_history(ref, "AP-00215"), ref))}
    # Alpenglow AL26-0663: billed twice AND charged to an employee card
    assert flags["DUPLICATE_EXACT"].severity == Severity.BLOCK
    assert flags["DUPLICATE_EXACT"].evidence["matches"] == ["AP-00224"]
    assert flags["ALREADY_PAID_BY_CARD"].severity == Severity.BLOCK


def test_near_and_cross_vendor_are_likely_not_exact(ref, make_bill):
    orig = bill_from_history(ref, "AP-00023")
    bill = make_bill(vendor_id=orig.vendor.vendor_id, number="INV-02991", when=date(2026, 1, 14))
    bill.total = orig.total
    flags = duplicate_flags(find_duplicates(bill, ref))
    assert [(f.code, f.severity) for f in flags] == [("DUPLICATE_LIKELY", Severity.WARN)]


def test_credit_note_is_not_a_duplicate_of_its_invoice(ref, make_bill):
    invoice = make_bill(number="INV-1001", file_hash="inv")
    credit = make_bill(number="CN-1001", file_hash="cn")
    credit.is_credit_note = True
    assert find_duplicates(credit, ref, [invoice, credit]) == []


# ---- splits ----
def test_split_invoices(ref):
    # Torque Industrial: 3 bills in a week, each under $10k, ~$14k together, no PO
    flag = find_split(bill_from_history(ref, "AP-00206"), ref)
    assert flag and flag.code == "POSSIBLE_SPLIT" and flag.severity == Severity.WARN


def test_rent_is_not_a_split(ref):
    # V037 has 11 bills between $8k and $10k, but it's monthly rent
    for iid, i in ref.invoices.items():
        if i["vendor_id"] == "V037":
            assert find_split(bill_from_history(ref, iid), ref) is None
