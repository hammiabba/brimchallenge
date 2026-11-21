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


# ---- near duplicates need alike numbers or the same service period (incoming batch false alarm) ----
def test_two_phases_billed_the_same_day_are_not_duplicates(ref, make_bill):
    # Orion 279 and 281 (EM-029): same vendor and day, amounts 0.5% apart, but different numbers and work
    a = make_bill(vendor_id="V029", number="279", amount="4300.00", when=date(2026, 10, 28), file_hash="o279",
                  description="Consulting hours - Network audit phase 1")
    b = make_bill(vendor_id="V029", number="281", amount="4320.00", when=date(2026, 10, 28), file_hash="o281",
                  description="Consulting hours - Network audit phase 2")
    assert [m for m in find_duplicates(a, ref, [a, b]) if m.kind == "near"] == []


def test_same_service_period_still_matches_with_a_new_number(ref, make_bill):
    a = make_bill(vendor_id="V029", number="279", when=date(2026, 10, 28), file_hash="p1",
                  description="Advisory retainer - October")
    b = make_bill(vendor_id="V029", number="9134", when=date(2026, 10, 30), file_hash="p2",
                  description="Advisory retainer - October")
    [m] = [m for m in find_duplicates(a, ref, [a, b]) if m.kind == "near"]
    assert "same service period" in m.reasons


def test_service_period_reads_months_in_english_french_and_dates():
    from app.controls.duplicates import service_period
    assert service_period(["Energy - October"]) == {10}
    assert service_period(["Loyer de base - novembre"]) == {11}
    assert service_period(["Hosting 2026-09-01 to 2026-09-30"]) == {9}
    assert service_period(["Consulting hours - phase 1"]) == frozenset()


# ---- fixed-monthly vendors: next month's bill isn't a likely duplicate (incoming false alarm 3) ----
def test_subscription_bill_is_not_a_likely_duplicate_of_next_months(ref, make_bill):
    # Cloudbarn (V015, fixed monthly C001): INV-01561 re-sent on 2026-10-09; INV-01567 (AP-00411) is October's
    bill = make_bill(vendor_id="V015", province="AB", amount="2400.00", number="INV-01561", when=date(2026, 10, 9),
                     description="Cloudbarn Workspace subscription (24 seats)")
    found = kinds(find_duplicates(bill, ref))
    assert ("exact", "AP-00370") in found  # September's INV-01561, already paid: still caught
    assert not any(kind == "near" for kind, _ in found)


def test_subscription_bills_for_the_same_month_still_match(ref, make_bill):
    a = make_bill(vendor_id="V015", province="AB", amount="2400.00", number="INV-09001", when=date(2026, 10, 9),
                  file_hash="s1", description="Cloudbarn Workspace subscription - October")
    b = make_bill(vendor_id="V015", province="AB", amount="2400.00", number="X-77", when=date(2026, 10, 12),
                  file_hash="s2", description="Cloudbarn Workspace subscription - October")
    assert any(m.kind == "near" for m in find_duplicates(a, ref, [a, b]))
