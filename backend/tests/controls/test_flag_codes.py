"""The six flag codes added on b/flag-codes, one test each (checks that were dropped until the codes existed)."""
from datetime import date

from app.controls import validate
from app.shared.schemas import FLAG_CODES, Severity

NEW_CODES = {"VENDOR_PENDING_REVIEW": "warn", "GST_NUMBER_MISSING": "warn", "PO_NOT_FOUND": "block",
             "CURRENCY_UNSUPPORTED": "block", "REQUESTER_TERMINATED": "warn", "SENDER_DOMAIN_MISMATCH": "warn"}


def flags_of(bill, ref, code):
    return [f for f in validate(bill, ref) if f.code == code]


def test_new_codes_are_in_flag_codes_with_their_severity():
    assert {c: FLAG_CODES[c] for c in NEW_CODES} == NEW_CODES


def test_vendor_pending_review(ref, make_bill):
    # V054 Riverbend Catering is pending_review: warn and say why the finance step is added
    [f] = flags_of(make_bill(vendor_id="V054", province="BC"), ref, "VENDOR_PENDING_REVIEW")
    assert f.severity == Severity.WARN and f.evidence["policy"] == "P05"
    assert "VENDOR_NOT_ACTIVE" not in {x.code for x in validate(make_bill(vendor_id="V054", province="BC"), ref)}


def test_gst_number_missing(ref, make_bill):
    # Riverbend has no GST/HST number on file, and its invoice 1739 prints none
    assert flags_of(make_bill(vendor_id="V054", province="BC"), ref, "GST_NUMBER_MISSING")
    assert not flags_of(make_bill(), ref, "GST_NUMBER_MISSING")  # Polar has one
    usd = make_bill(vendor_id="V016", currency="USD", description="Tessera Analytics Pro - 12 seats")
    assert not flags_of(usd, ref, "GST_NUMBER_MISSING")  # foreign vendors don't register for GST


def test_po_not_found(ref, make_bill):
    bill = make_bill()
    bill.po_number = "PO-99999"
    [f] = flags_of(bill, ref, "PO_NOT_FOUND")
    assert f.severity == Severity.BLOCK and f.evidence["po"] == "PO-99999"
    # vendor that requires a PO: still PO_NOT_FOUND (it has a number, just not a real one), with P13
    needs_po = make_bill(vendor_id="V012")
    needs_po.po_number = "PO-99999"
    assert flags_of(needs_po, ref, "PO_NOT_FOUND")[0].evidence["policy"] == "P13"
    assert not flags_of(needs_po, ref, "PO_REQUIRED_MISSING")


def test_currency_unsupported_when_no_fx_rate(ref, make_bill):
    bill = make_bill()
    bill.currency = "EUR"  # no EUR rate on file and none on the bill
    [f] = flags_of(bill, ref, "CURRENCY_UNSUPPORTED")
    assert f.severity == Severity.BLOCK and "FX rate missing" in f.message
    assert not flags_of(bill, ref, "FOREIGN_CURRENCY")
    usd = make_bill(currency="USD", vendor_id="V016", description="Tessera Analytics Pro - 12 seats")
    assert not flags_of(usd, ref, "CURRENCY_UNSUPPORTED")  # rate on file: info only


def test_requester_terminated(ref, make_bill):
    # U015 was terminated on 2026-09-15
    [f] = flags_of(make_bill(requester="U015", when=date(2026, 10, 20)), ref, "REQUESTER_TERMINATED")
    assert f.severity == Severity.WARN and f.evidence["requester"] == "U015"
    assert not flags_of(make_bill(requester="U013"), ref, "REQUESTER_TERMINATED")


def test_sender_domain_mismatch(ref, make_bill):
    bill = make_bill()  # V001 Polar Freight, AP contact @polarfreight.example
    bill.source.sender_address = "ar@polar-freight-billing.example"
    [f] = flags_of(bill, ref, "SENDER_DOMAIN_MISMATCH")
    assert f.evidence == {"sender_domain": "polar-freight-billing.example", "known_domain": "polarfreight.example"}
    bill.source.sender_address = "AR@PolarFreight.example"
    assert not flags_of(bill, ref, "SENDER_DOMAIN_MISMATCH")


# ---- small suppliers: Canadian vendor with no GST/HST number on file or on the invoice (PR #23 review) ----
def small_supplier_bill(make_bill, charge_gst):
    bill = make_bill(vendor_id="V054", province="BC")  # Riverbend: CA, no GST number in the master
    bill.vendor.gst_number = None
    if not charge_gst:
        bill.taxes, bill.total = [], bill.subtotal
        bill.total_cad = bill.total
    return bill


def test_small_supplier_charging_no_tax_is_clean(ref, make_bill):
    codes = {f.code for f in validate(small_supplier_bill(make_bill, charge_gst=False), ref)}
    assert not codes & {"TAX_MISSING", "TAX_WRONG_FOR_PROVINCE", "GST_NUMBER_MISSING"}


def test_small_supplier_charging_gst_gets_a_warning_not_a_tax_block(ref, make_bill):
    flags = validate(small_supplier_bill(make_bill, charge_gst=True), ref)
    [f] = [x for x in flags if x.code == "GST_NUMBER_MISSING"]
    assert f.severity == Severity.WARN and "can't be claimed back" in f.message and "fake invoice" in f.message
    assert not {x.code for x in flags} & {"TAX_MISSING", "TAX_WRONG_FOR_PROVINCE"}


def test_gst_number_printed_on_the_invoice_means_registered(ref, make_bill):
    bill = small_supplier_bill(make_bill, charge_gst=False)
    bill.vendor.gst_number = "123456789RT0001"  # master is missing it, but the invoice shows one
    assert "TAX_MISSING" in {f.code for f in validate(bill, ref)}
