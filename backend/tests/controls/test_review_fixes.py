"""One test group per fix from the controls review (b/controls-fixes)."""
from datetime import date
from decimal import Decimal as D

from app.controls import bill_from_history, can_approve, can_release, find_duplicates, find_split, route, run_controls
from app.controls.validate import to_cad, validate
from app.shared.schemas import ApprovalStep, Flag, MatchMethod, Severity


def codes(flags):
    return {f.code for f in flags}


def unknown_vendor(bill, name="Acme Widget Works"):
    bill.vendor.vendor_id = None
    bill.vendor.match_method = MatchMethod.NONE
    bill.vendor.match_score = 0.0
    bill.vendor.name_on_invoice = name
    return bill


# ---- 1. credit notes can't be released ----
def test_credit_note_cannot_be_released(ref, make_bill):
    credit = make_bill(amount="-500.00")
    credit.is_credit_note = True
    decision = can_release("U003", credit.total, {"U007"}, [], True, ref, bill=credit)
    assert not decision.allowed and "credit note" in decision.reason


def test_credit_note_flag_also_blocks_release(ref, make_bill):
    flags = [Flag(code="CREDIT_NOTE", severity=Severity.INFO, message="x")]
    assert not can_release("U003", D("500"), {"U007"}, flags, True, ref, bill=make_bill()).allowed


# ---- 2. Redstone: only the fee line is compared to the fixed fee ----
def test_redstone_overage_is_not_an_overcharge(ref):
    # AP-00004: committed base $4,800 (= contract fee) + $324.23 data-transfer overage
    flags = [f for f in validate(bill_from_history(ref, "AP-00004"), ref) if f.code == "OVER_CONTRACT_RATE"]
    assert [f.evidence["kind"] for f in flags] == ["overage"]
    assert flags[0].severity == Severity.WARN


def test_fee_line_above_contract_fee_still_flagged(ref, make_bill):
    bill = make_bill(vendor_id="V021", currency="USD", amount="5200.00", description="Compute and storage - base")
    kinds = [f.evidence["kind"] for f in validate(bill, ref) if f.code == "OVER_CONTRACT_RATE"]
    assert kinds == ["fee"]


# ---- 3. split detection ----
def test_bills_on_their_own_pos_are_not_a_split(ref):
    # Deskhive AP-00120 / 00129 / 00131: three furniture orders, each on its own PO
    assert find_split(bill_from_history(ref, "AP-00120"), ref) is None


def test_duplicate_pair_is_not_a_split(ref):
    # Redline FA-001655 / 1655-A is one invoice entered twice (a duplicate), not two pieces of one purchase
    assert find_split(bill_from_history(ref, "AP-00136"), ref) is None


def test_bills_six_days_apart_are_not_a_split(ref):
    # Redline monthly fuel AP-00260 (Jun 26) and AP-00272 (Jul 2): outside the 3-day window
    assert find_split(bill_from_history(ref, "AP-00260"), ref) is None


def test_torque_is_still_a_split(ref):
    flag = find_split(bill_from_history(ref, "AP-00206"), ref)
    assert flag and set(flag.evidence["related"]) == {"AP-00200", "AP-00207"}


def test_small_split_is_caught(ref, make_bill):
    # Four $2,500 bills (each 25% of the limit) in two days, same department: $11,300 with HST
    bills = [make_bill(vendor_id="V003", amount="2500.00", number=f"SM-{n}", file_hash=f"sm{n}",
                       when=date(2026, 10, 30 + n % 2)) for n in range(4)]
    flag = find_split(bills[0], ref, bills)
    assert flag and flag.evidence["combined_cad"] == "11300.00"


def test_split_needs_same_department(ref, make_bill):
    a = make_bill(vendor_id="V003", amount="6000.00", number="DP-1", file_hash="dp1", dept="D01")
    b = make_bill(vendor_id="V003", amount="6000.00", number="DP-2", file_hash="dp2", dept="D03")
    assert find_split(a, ref, [a, b]) is None
    c = make_bill(vendor_id="V003", amount="6000.00", number="DP-3", file_hash="dp3", dept="D01")
    assert find_split(a, ref, [a, b, c]) is not None


# ---- 4. missing bank fields aren't a mismatch ----
def test_missing_bank_field_is_not_a_mismatch(ref, make_bill):
    bill = make_bill()
    bill.vendor.bank.institution = None  # invoice shows transit + account only
    assert "BANK_DETAILS_MISMATCH" not in codes(validate(bill, ref))


def test_present_bank_field_that_differs_is_a_mismatch(ref, make_bill):
    bill = make_bill()
    bill.vendor.bank.institution = None
    bill.vendor.bank.transit = "99999"
    flag = next(f for f in validate(bill, ref) if f.code == "BANK_DETAILS_MISMATCH")
    assert flag.evidence["fields"] == ["transit"] and flag.severity == Severity.BLOCK


# ---- 5. hourly only when the description says so ----
def test_quantity_alone_is_not_hourly(ref, make_bill):
    # C022 caps Harlow & Stern at $520/hr; 5 x $600 filing packages are not hours
    bill = make_bill(vendor_id="V026", amount="3000.00", qty="5", description="Court filing packages")
    assert "OVER_CONTRACT_RATE" not in codes(validate(bill, ref))


def test_hr_hrs_and_heures_are_hourly(ref, make_bill):
    for desc in ["Legal advice 5 hr", "Contract review - 5 hrs", "Conseil juridique (5 heures)"]:
        bill = make_bill(vendor_id="V026", amount="3000.00", qty="5", description=desc)
        assert "OVER_CONTRACT_RATE" in codes(validate(bill, ref)), desc


# ---- 6. unknown vendors ----
def test_unknown_vendor_tax_is_still_checked(ref, make_bill):
    bill = unknown_vendor(make_bill())
    bill.taxes, bill.total = [], bill.subtotal  # ON delivery with no HST
    assert "TAX_MISSING" in codes(validate(bill, ref))


def test_unknown_foreign_currency_vendor_owes_no_canadian_tax(ref, make_bill):
    bill = unknown_vendor(make_bill(currency="USD"))
    bill.taxes, bill.total = [], bill.subtotal
    assert not codes(validate(bill, ref)) & {"TAX_MISSING", "TAX_WRONG_FOR_PROVINCE"}


def test_unknown_vendor_with_a_lookalike_name(ref, make_bill):
    bill = unknown_vendor(make_bill(), name="Polar Freight Lines Ltd")  # V001 is "Polar Freight Lines Ltd."
    flag = next(f for f in validate(bill, ref) if f.code == "VENDOR_LOOKALIKE")
    assert flag.severity == Severity.BLOCK and "V001" in flag.evidence["all_matches"]


def test_unknown_vendor_with_an_unrelated_name(ref, make_bill):
    bill = unknown_vendor(make_bill(), name="Acme Widget Works")
    assert codes(validate(bill, ref)) & {"VENDOR_LOOKALIKE"} == set()


# ---- 7. currency ----
def test_lowercase_currency(ref, make_bill):
    cad = make_bill()
    cad.currency = "cad"
    assert "FOREIGN_CURRENCY" not in codes(validate(cad, ref))
    usd = make_bill(currency="USD")
    usd.currency = "usd"
    total_cad, rate = to_cad(usd, ref)
    assert rate == ref.fx_rate(usd.invoice_date) and total_cad == (usd.total * rate).quantize(D("0.01"))


def test_rate_on_the_bill_is_used(ref, make_bill):
    bill = make_bill(currency="USD")
    bill.currency, bill.fx_rate_to_cad = "EUR", D("1.5000")
    assert to_cad(bill, ref) == ((bill.total * D("1.5")).quantize(D("0.01")), D("1.5000"))
    assert next(f for f in validate(bill, ref) if f.code == "FOREIGN_CURRENCY").evidence["rate_source"] == "bill"


def test_non_usd_is_never_converted_at_the_usd_rate(ref, make_bill):
    bill = make_bill()
    bill.currency = "EUR"  # no EUR rates on file, none on the bill
    assert to_cad(bill, ref) == (None, None)
    flag = next(f for f in validate(bill, ref) if f.code == "CURRENCY_UNSUPPORTED")
    assert "FX rate missing" in flag.message and flag.evidence["rate_source"] == "missing"
    assert all("CAD amount unknown" in s.reason for s in route(bill, ref))


def test_missing_usd_rate_is_flagged_not_replaced_by_one(ref, make_bill):
    bill = make_bill(when=date(2026, 12, 20))  # after the last rate on file
    bill.currency, bill.fx_rate_to_cad = "USD", D("1")
    assert to_cad(bill, ref) == (None, None)
    assert "FX rate missing" in next(f for f in validate(bill, ref) if f.code == "CURRENCY_UNSUPPORTED").message


# ---- 8. release and approval permissions ----
def test_requester_cannot_release_own_bill(ref, make_bill):
    bill = make_bill(requester="U003", dept="D04")
    decision = can_release("U003", D("1000"), {"U002"}, [], True, ref, bill=bill)
    assert not decision.allowed and "requested this bill" in decision.reason


def test_can_approve_rechecks_role(ref, make_bill):
    # A step (e.g. from a stale route) assigned to an employee: the role check refuses it
    bill = make_bill(requester="U014")
    step = ApprovalStep(step_no=1, role="dept_manager", user_id="U013", policy_ids=["P01"], reason="stale")
    decision = can_approve("U013", step, bill, ref, route=[step])
    assert not decision.allowed and "role" in decision.reason


def test_can_approve_rechecks_final_signer_limit(ref, make_bill):
    bill = make_bill(amount="15000.00")
    step = ApprovalStep(step_no=1, role="dept_manager", user_id="U007", policy_ids=["P01"], reason="stale")
    decision = can_approve("U007", step, bill, ref, route=[step])  # U007's limit is $10,000
    assert not decision.allowed and "limit" in decision.reason


def test_earlier_step_does_not_need_the_full_limit(ref, make_bill):
    bill = make_bill(amount="15000.00")
    steps = route(bill, ref)  # U007 then U003
    assert can_approve("U007", steps[0], bill, ref, route=steps).allowed


# ---- 9. unknown-vendor duplicate in the same batch ----
def test_unknown_vendor_duplicate_in_batch(ref, make_bill):
    a = unknown_vendor(make_bill(number="AW-100", file_hash="aw-a"))
    b = unknown_vendor(make_bill(number="AW-100", file_hash="aw-b"))
    assert [(m.kind, m.matched_invoice_id) for m in find_duplicates(a, ref, [a, b])] == [("exact", "aw-b")]
    assert "DUPLICATE_EXACT" in codes(run_controls(a, [a, b], ref=ref).flags)


def test_different_unknown_vendors_are_not_duplicates(ref, make_bill):
    a = unknown_vendor(make_bill(number="AW-100", file_hash="aw-a"), name="Acme Widget Works")
    b = unknown_vendor(make_bill(number="AW-100", file_hash="aw-b"), name="Zenith Paper Supply")
    assert find_duplicates(a, ref, [a, b]) == []

