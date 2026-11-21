from datetime import date
from decimal import Decimal as D

from app.extraction.selfcheck import check
from app.shared.schemas import DraftBill, InvoiceLine, LineType, SourceInfo, TaxCode, TaxLine, VendorOnInvoice


def make_bill(lines, subtotal, taxes, total, **kw) -> DraftBill:
    return DraftBill(
        source=SourceInfo(file_name="t.pdf", file_hash="x"),
        vendor=VendorOnInvoice(name_on_invoice="Test"),
        invoice_number="1", invoice_date=date(2026, 10, 1),
        lines=[InvoiceLine(line_no=i + 1, description="x", quantity=D(q), unit_price=D(p), amount=D(a),
                           line_type=lt)
               for i, (q, p, a, lt) in enumerate(lines)],
        subtotal=D(subtotal), taxes=taxes, total=D(total), total_cad=D(total), **kw,
    )


GST = lambda amt: TaxLine(code=TaxCode.GST5, rate=D("0.05"), amount=D(amt))  # noqa: E731
HST = lambda amt: TaxLine(code=TaxCode.HST13, rate=D("0.13"), amount=D(amt))  # noqa: E731
SVC = LineType.SERVICES


def test_clean_bill_has_no_warnings():
    bill = make_bill([("12", "450.00", "5400.00", SVC), ("1", "310.00", "310.00", SVC)],
                     "5710.00", [HST("742.30")], "6452.30")
    conf, warnings = check(bill)
    assert warnings == []
    assert conf["total"] == 0.95


def test_wrong_total_is_reported_not_fixed():
    # evergreenenergyu_000850.pdf: 3,180 + 159 = 3,339 but the invoice says 3,439
    bill = make_bill([("1", "3180.00", "3180.00", SVC)], "3180.00", [GST("159.00")], "3439.00")
    conf, warnings = check(bill)
    assert bill.total == D("3439.00")
    assert any("3339.00" in w and "3439.00" in w for w in warnings)
    assert conf["total"] < 0.6


def test_wrong_line_math_is_reported():
    # northstarmediabu_NO261773.pdf: 24 × 150 = 3,600 but the line says 3,800
    bill = make_bill([("24", "150.00", "3800.00", SVC)], "3800.00", [HST("494.00")], "4294.00")
    conf, warnings = check(bill)
    assert any("3600.00" in w and "3800.00" in w for w in warnings)
    assert conf["lines"] < 0.6
    assert conf["total"] == 0.95  # the rest of the invoice is internally consistent


def test_credit_note_negative_amounts_pass():
    bill = make_bill([("1", "-1042.76", "-1042.76", SVC), ("1", "-385.74", "-385.74", SVC)],
                     "-1428.50", [HST("-185.71")], "-1614.21", is_credit_note=True)
    assert check(bill)[1] == []


def test_ocr_lowers_base_confidence():
    bill = make_bill([("1", "100", "100", SVC)], "100", [GST("5")], "105")
    conf, _ = check(bill, was_ocr=True, ocr_fixed_fields={"vendor"})
    assert conf["total"] == 0.75
    assert conf["vendor"] == 0.6


def test_wrong_tax_amount_flagged():
    bill = make_bill([("1", "1000", "1000", SVC)], "1000", [GST("60.00")], "1060.00")
    conf, warnings = check(bill)
    assert any("GST5" in w for w in warnings)
    assert conf["taxes"] < 0.95
