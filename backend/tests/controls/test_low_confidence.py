"""LOW_EXTRACTION_CONFIDENCE: key fields read with low confidence, or a scan that extraction left notes on."""
from decimal import Decimal as D

from app.controls import validate
from app.controls.validate import LOW_CONFIDENCE, check_extraction_confidence
from app.shared.schemas import Severity

TEXT = {"vendor": 0.95, "invoice_number": 0.95, "invoice_date": 0.95, "due_date": 0.95, "lines": 0.95,
        "subtotal": 0.95, "taxes": 0.95, "total": 0.95}
SCAN = {k: 0.75 for k in TEXT}
VISION_NOTE = "no usable text layer; extracted from the image by the vision model"


def low(bill, ref):
    return [f for f in validate(bill, ref) if f.code == "LOW_EXTRACTION_CONFIDENCE"]


def read_as(bill, conf, *, ocr=False, warnings=()):
    return bill.model_copy(update={"field_confidence": conf, "extraction_warnings": list(warnings),
                                   "source": bill.source.model_copy(update={"was_ocr": ocr})})


def test_threshold_sits_between_a_clean_scan_and_any_deduction():
    assert 0.75 - 0.15 < LOW_CONFIDENCE < 0.75


def test_clean_text_read_is_not_flagged(ref, make_bill):
    assert not low(read_as(make_bill(), TEXT), ref)


def test_clean_scan_without_notes_is_not_flagged(ref, make_bill):
    assert not low(read_as(make_bill(), SCAN, ocr=True), ref)


def test_bill_with_no_confidence_scores_is_not_flagged(ref, make_bill):
    # Bills from history or typed in by hand have no field_confidence at all.
    assert not low(make_bill(), ref)


def test_weak_key_fields_are_named_weakest_first(ref, make_bill):
    bill = read_as(make_bill(), {**SCAN, "invoice_date": 0.3, "total": 0.6}, ocr=True)
    [f] = low(bill, ref)
    assert f.severity == Severity.WARN
    assert f.message.startswith("Low extraction confidence on invoice date (0.30), total (0.60).")
    assert "Check the invoice date, total against the document" in f.message
    assert f.evidence["weak_fields"] == {"invoice_date": 0.3, "total": 0.6}
    assert f.field == "invoice_date"


def test_bank_details_count_when_extraction_scores_them(ref, make_bill):
    [f] = low(read_as(make_bill(), {**TEXT, "bank": 0.5}), ref)
    assert "bank details (0.50)" in f.message


def test_fields_that_are_not_key_fields_are_ignored(ref, make_bill):
    assert not low(read_as(make_bill(), {**TEXT, "due_date": 0.1, "lines": 0.2}), ref)


def test_scan_with_extraction_notes_is_flagged_and_quotes_them(ref, make_bill):
    [f] = low(read_as(make_bill(), SCAN, ocr=True, warnings=[VISION_NOTE]), ref)
    assert "Read from a scanned image, with 1 extraction note(s): " + VISION_NOTE in f.message
    assert "vendor, invoice number, date, amounts and bank details" in f.message
    assert f.evidence["was_ocr"] and f.evidence["scan_notes"] == [VISION_NOTE] and f.field is None


def test_notes_on_a_text_layer_bill_alone_are_not_flagged(ref, make_bill):
    # e.g. "PO field is printed on the invoice but left blank": not a reading problem
    assert not low(read_as(make_bill(), TEXT, warnings=["PO field is printed on the invoice but left blank"]), ref)


def test_wrong_total_on_a_text_layer_bill_is_left_to_total_mismatch(ref, make_bill):
    bill = make_bill()
    bill = read_as(bill.model_copy(update={"total": bill.total + D("100")}), {**TEXT, "total": 0.55})
    codes = {f.code for f in validate(bill, ref)}
    assert "TOTAL_MISMATCH" in codes and "LOW_EXTRACTION_CONFIDENCE" not in codes


def test_wrong_total_on_a_scan_may_be_a_misread_so_it_is_flagged(ref, make_bill):
    bill = make_bill()
    bill = read_as(bill.model_copy(update={"total": bill.total + D("100")}), {**SCAN, "total": 0.35}, ocr=True)
    [f] = low(bill, ref)
    assert "total (0.35)" in f.message


def test_unknown_vendor_is_left_to_vendor_not_found(ref, make_bill):
    bill = make_bill()
    bill = bill.model_copy(update={"vendor": bill.vendor.model_copy(update={"vendor_id": None})})
    bill = read_as(bill, {**TEXT, "vendor": 0.3})
    codes = {f.code for f in validate(bill, ref)}
    assert "VENDOR_NOT_FOUND" in codes and "LOW_EXTRACTION_CONFIDENCE" not in codes


def test_weak_vendor_match_on_a_known_vendor_is_flagged(ref, make_bill):
    [f] = low(read_as(make_bill(), {**TEXT, "vendor": 0.5}), ref)
    assert "vendor (0.50)" in f.message


def test_check_works_without_the_other_flags(ref, make_bill):
    assert check_extraction_confidence(read_as(make_bill(), {**TEXT, "total": 0.4}), ref)
