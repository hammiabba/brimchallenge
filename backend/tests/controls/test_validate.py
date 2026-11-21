from datetime import date
from decimal import Decimal as D

from app.controls import bill_from_history, validate
from app.shared.schemas import FLAG_CODES, InvoiceLine, Severity, TaxCode, TaxLine


def codes(flags):
    return {f.code for f in flags}


def test_clean_bill_has_no_flags(ref, make_bill):
    assert validate(make_bill(), ref) == []


def test_every_flag_uses_the_schema_catalogue(ref):
    # Run all 426 historical invoices: every code and severity must come straight from FLAG_CODES.
    for iid in ref.invoices:
        for f in validate(bill_from_history(ref, iid), ref):
            assert f.code in FLAG_CODES and f.severity.value == FLAG_CODES[f.code], (iid, f.code, f.severity)


# ---- tax (real cases from history) ----
def test_quebec_missing_qst(ref):
    # AP-00098: Fibrewave billed Quebec with GST only, no QST
    assert "TAX_MISSING" in codes(validate(bill_from_history(ref, "AP-00098"), ref))


def test_hst_charged_in_alberta(ref):
    # AP-00253: Northbound Couriers charged 13% HST on an Alberta delivery (should be 5% GST)
    flags = [f for f in validate(bill_from_history(ref, "AP-00253"), ref) if f.field == "taxes"]
    assert [f.code for f in flags] == ["TAX_WRONG_FOR_PROVINCE"]  # one flag, not one per line


def test_no_tax_charged_in_ontario(ref):
    # AP-00325: Aurora Mobile charged no HST on an Ontario bill
    assert "TAX_MISSING" in codes(validate(bill_from_history(ref, "AP-00325"), ref))


def test_bc_pst_only_on_goods(ref, make_bill):
    tax_codes = {"TAX_MISSING", "TAX_WRONG_FOR_PROVINCE", "PST_ON_SERVICES"}
    assert not tax_codes & codes(validate(make_bill(province="BC", line_type="goods"), ref))
    assert not tax_codes & codes(validate(make_bill(province="BC", line_type="services"), ref))


def test_pst_charged_on_services(ref, make_bill):
    bill = make_bill(vendor_id="V004", province="BC", line_type="services")
    bill.taxes.append(TaxLine(code=TaxCode.PST7_BC, rate=D("0.07"), amount=D("70.00")))
    bill.total += D("70.00")
    assert "PST_ON_SERVICES" in codes(validate(bill, ref))


def test_foreign_vendor_no_canadian_tax(ref, make_bill):
    bill = make_bill(vendor_id="V021", currency="USD", description="Cloud hosting")  # Redstone, IL
    bill.taxes = [TaxLine(code=TaxCode.GST5, rate=D("0.05"), amount=D("50.00"))]
    bill.total += D("50.00")
    assert "TAX_WRONG_FOR_PROVINCE" in codes(validate(bill, ref))


# ---- arithmetic ----
def test_line_math_error(ref, make_bill):
    bill = make_bill()
    bill.lines[0].unit_price = D("999.00")  # 1 x 999 != 1000
    assert "LINE_MATH_ERROR" in codes(validate(bill, ref))


def test_subtotal_math_error(ref, make_bill):
    bill = make_bill()
    bill.subtotal += D("10")
    assert "SUBTOTAL_MISMATCH" in codes(validate(bill, ref))


def test_total_math_error(ref, make_bill):
    bill = make_bill()
    bill.total += D("100")
    assert "TOTAL_MISMATCH" in codes(validate(bill, ref))


# ---- vendor ----
def test_unknown_vendor_blocks(ref, make_bill):
    bill = make_bill()
    bill.vendor.vendor_id = None
    flags = [f for f in validate(bill, ref) if f.code == "VENDOR_NOT_FOUND"]
    assert flags and flags[0].severity == Severity.BLOCK


def test_vendor_on_hold(ref):
    # AP-00109 was paid to V053, a lookalike Great Lakes record that is on hold
    c = codes(validate(bill_from_history(ref, "AP-00109"), ref))
    assert {"VENDOR_NOT_ACTIVE", "VENDOR_LOOKALIKE"} <= c


def test_bank_details_differ_from_master(ref, make_bill):
    bill = make_bill()
    bill.vendor.bank.account = "111222333"
    assert "BANK_DETAILS_MISMATCH" in codes(validate(bill, ref))


def test_unverified_bank_change(ref, make_bill):
    # V004 Cascadia changed bank details on 2026-10-27 by email, never verified by callback
    assert "BANK_CHANGE_UNVERIFIED" in codes(validate(make_bill(vendor_id="V004", province="BC"), ref))


def test_ocr_noise_in_gst_number_is_not_a_mismatch(ref, make_bill):
    bill = make_bill()
    bill.vendor.gst_number = "995133220RT000!"  # OCR read 1 as !
    assert "GST_NUMBER_MISMATCH" not in codes(validate(bill, ref))


def test_gst_number_mismatch_warns(ref, make_bill):
    bill = make_bill()
    bill.vendor.gst_number = "123456789RT0001"
    flags = [f for f in validate(bill, ref) if f.code == "GST_NUMBER_MISMATCH"]
    assert flags and flags[0].severity == Severity.WARN


def test_lookalike_record_blocks(ref, make_bill):
    # V051 "Polar Freight Lines Limited" shares V001's bank account and has fewer invoices
    flags = [f for f in validate(make_bill(vendor_id="V051"), ref) if f.code == "VENDOR_LOOKALIKE"]
    assert flags and flags[0].severity == Severity.BLOCK and flags[0].evidence["similar_vendor"] == "V001"


def test_brand_new_lookalike_record(ref, make_bill):
    # V052 "Harlow and Stern LLP" has no invoices yet; it resembles V026 "Harlow & Stern LLP"
    bill = make_bill(vendor_id="V052", description="Legal services")
    bill.source.sender_address = "billing@harlowandstern-llp.example"
    flags = [f for f in validate(bill, ref) if f.code == "VENDOR_LOOKALIKE"]
    assert flags and flags[0].evidence["similar_vendor"] == "V026"
    assert flags[0].evidence["known_domain"] == "harlow.example"


def test_real_vendor_is_not_called_a_lookalike(ref, make_bill):
    # V001, V002 and V026 are the genuine records that V051, V053 and V052 imitate
    assert "VENDOR_LOOKALIKE" not in codes(validate(make_bill(vendor_id="V001"), ref))
    assert "VENDOR_LOOKALIKE" not in codes(validate(make_bill(vendor_id="V026", description="Legal services"), ref))
    assert "VENDOR_LOOKALIKE" not in codes(validate(bill_from_history(ref, "AP-00239"), ref))  # V002


# ---- contracts ----
def test_fixed_fee_above_contract(ref):
    # AP-00287: Aurora Mobile billed 2,343.50 vs 2,150 contract fee
    assert "OVER_CONTRACT_RATE" in codes(validate(bill_from_history(ref, "AP-00287"), ref))


def test_fuel_surcharge_over_cap(ref, make_bill):
    bill = make_bill(vendor_id="V001", amount="1000.00")
    bill.lines.append(InvoiceLine(line_no=2, description="Fuel surcharge (14.5%)", quantity=D("1"),
                                  unit_price=D("145.00"), amount=D("145.00")))
    bill.subtotal = D("1145.00")
    bill.taxes = [TaxLine(code=TaxCode.HST13, rate=D("0.13"), amount=D("148.85"))]
    bill.total = D("1293.85")
    assert "OVER_FUEL_SURCHARGE_CAP" in codes(validate(bill, ref))  # C018 caps Polar at 12%


def test_hourly_rate_over_cap(ref, make_bill):
    # C022 caps Harlow & Stern at $520/hr
    bill = make_bill(vendor_id="V026", amount="3000.00", qty="5", description="Legal services - contract review (hrs)")
    assert "OVER_CONTRACT_RATE" in codes(validate(bill, ref))


def test_monthly_not_to_exceed(ref):
    # AP-00228: Harlow & Stern, $24,937 billed in one month vs a $20,000 cap
    assert "OVER_CONTRACT_NTE" in codes(validate(bill_from_history(ref, "AP-00228"), ref))


def test_expired_contract(ref):
    assert "CONTRACT_EXPIRED" in codes(validate(bill_from_history(ref, "AP-00121"), ref))


# ---- PO ----
def test_po_required_but_missing(ref):
    # AP-00200: Torque Industrial requires a PO, none given
    assert "PO_REQUIRED_MISSING" in codes(validate(bill_from_history(ref, "AP-00200"), ref))


def test_po_wrong_vendor(ref, make_bill):
    bill = make_bill(vendor_id="V011", province="BC")
    bill.po_number = "PO-2026-0051"  # 0051 belongs to V010
    assert "PO_CLOSED_OR_WRONG_VENDOR" in codes(validate(bill, ref))


def test_po_over_balance(ref, make_bill):
    bill = make_bill(vendor_id="V010", amount="5000.00")
    bill.po_number = "PO-2026-0051"  # PO is only 1,007.20
    assert "PO_OVER_BALANCE" in codes(validate(bill, ref))


# ---- FX, dates, credit notes ----
def test_usd_converted(ref):
    flags = [f for f in validate(bill_from_history(ref, "AP-00004"), ref) if f.code == "FOREIGN_CURRENCY"]
    assert flags and flags[0].severity == Severity.INFO and flags[0].evidence["rate"] == "1.3709"


def test_due_before_invoice(ref, make_bill):
    bill = make_bill()
    bill.due_date = date(2026, 10, 1)
    flags = [f for f in validate(bill, ref) if f.code == "DATE_ANOMALY"]
    assert flags and flags[0].evidence["kind"] == "due_before_invoice"


def test_future_dated_invoice(ref, make_bill):
    flags = [f for f in validate(make_bill(when=date(2026, 12, 15)), ref) if f.code == "DATE_ANOMALY"]
    assert flags and flags[0].evidence["kind"] == "future"


def test_credit_note_with_positive_amounts(ref, make_bill):
    # Most credit notes print positive numbers; the schema's is_credit_note flag says what it is
    bill = make_bill()
    bill.is_credit_note = True
    assert "CREDIT_NOTE" in codes(validate(bill, ref))


# ---- one-off work from a fixed-fee vendor (incoming batch false alarm: Lattice 557) ----
def test_one_off_charge_is_not_compared_to_the_monthly_fee(ref, make_bill):
    bill = make_bill(vendor_id="V019", amount="8200.00", description="Implementation and data migration")
    flags = [f for f in validate(bill, ref) if f.code == "OVER_CONTRACT_RATE"]
    assert [f.evidence["kind"] for f in flags] == ["one_off"]
    assert flags[0].severity == Severity.WARN
    assert "One-off charge of $8,200.00" in flags[0].message and "Fee billed" not in flags[0].message


def test_fee_line_next_to_a_one_off_line_is_still_checked(ref, make_bill):
    bill = make_bill(vendor_id="V019", amount="1500.00", description="Lattice Ledger accounting platform")
    bill.lines.append(InvoiceLine(line_no=2, description="Onboarding and training", quantity=D("1"),
                                  unit_price=D("900.00"), amount=D("900.00")))
    bill.subtotal += D("900.00")
    kinds = sorted(f.evidence["kind"] for f in validate(bill, ref) if f.code == "OVER_CONTRACT_RATE")
    assert kinds == ["fee", "one_off"]  # $1,500 platform fee vs $1,320 contract, plus the one-off line
