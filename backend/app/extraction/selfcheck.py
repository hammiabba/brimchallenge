"""
Arithmetic self-check of an extracted bill → per-field confidence + warnings.

Owner: Person A.
Input: a DraftBill built from printed values. Output: (field_confidence, warnings).

Checks: qty × unit price = line amount, Σ lines = subtotal, subtotal + taxes = total,
and each tax amount ≈ rate × base. Failures lower the confidence of the fields
involved and add a plain-English warning.

It **never changes printed values**. A vendor's wrong maths is a real finding that
controls turns into LINE_MATH_ERROR / SUBTOTAL_MISMATCH / TOTAL_MISMATCH flags. If we
"fixed" it here, nobody would see it.
"""
from __future__ import annotations

from decimal import Decimal

from app.shared.schemas import DraftBill, LineType, TaxCode

CENT = Decimal("0.01")
# Rounding differences of one or two cents are normal (per-line rounding vs total rounding).
TOLERANCE = Decimal("0.02")

FIELDS = ("vendor", "invoice_number", "invoice_date", "due_date", "currency", "ship_to_province",
          "po_number", "lines", "subtotal", "taxes", "total")


# Every warning check() writes contains one of these; used to replace them on a re-check.
_CHECK_MARKERS = (" but the line amount says ", " but the invoice subtotal says ", " but the invoice total says ",
                  " but the invoice says ", "looks like a credit note but its total is positive")


def is_check_warning(warning: str) -> bool:
    return any(m in warning for m in _CHECK_MARKERS)


def arithmetic_problems(bill: DraftBill) -> int:
    """How many arithmetic checks the bill fails (0 = everything adds up)."""
    return sum(1 for w in check(bill)[1] if is_check_warning(w))


def badly_inconsistent(bill: DraftBill) -> bool:
    """The total doesn't match subtotal + taxes, or the lines miss the subtotal by more than 1%.

    Used to decide whether OCR text is worth a second read by the vision model: small per-line slips are
    normal vendor errors, a broken total usually means the OCR misread a digit.
    """
    tax_sum = sum((t.amount for t in bill.taxes), Decimal("0"))
    if abs(bill.subtotal + tax_sum - bill.total) > TOLERANCE:
        return True
    if not bill.lines:
        return False
    lines_sum = sum((ln.amount for ln in bill.lines), Decimal("0"))
    return abs(lines_sum - bill.subtotal) > max(abs(bill.subtotal) * Decimal("0.01"), TOLERANCE)


def _fmt(d: Decimal) -> str:
    return f"{d.quantize(CENT)}"


def check(bill: DraftBill, *, was_ocr: bool = False, ocr_fixed_fields: set[str] | None = None,
          missing_fields: set[str] | None = None,
          penalties: dict[str, float] | None = None) -> tuple[dict[str, float], list[str]]:
    """`penalties` lowers named fields by a fixed amount (e.g. an ambiguous date that was read, not checked)."""
    base = 0.75 if was_ocr else 0.95
    conf = {f: base for f in FIELDS}
    warnings: list[str] = []

    def lower(field: str, by: float) -> None:
        conf[field] = round(max(0.05, conf[field] - by), 2)

    for f in ocr_fixed_fields or ():
        if f in conf:
            lower(f, 0.15)
    for f, by in (penalties or {}).items():
        if f in conf:
            lower(f, by)
    for f in missing_fields or ():
        if f in conf:
            conf[f] = 0.0

    # 1. line maths
    for line in bill.lines:
        expected = (line.quantity * line.unit_price).quantize(CENT)
        if abs(expected - line.amount) > TOLERANCE:
            lower("lines", 0.4)
            warnings.append(
                f"line {line.line_no}: {line.quantity.normalize():f} × {_fmt(line.unit_price)} = "
                f"{_fmt(expected)} but the line amount says {_fmt(line.amount)}"
            )

    # 2. lines vs subtotal
    if bill.lines:
        lines_sum = sum((ln.amount for ln in bill.lines), Decimal("0"))
        if abs(lines_sum - bill.subtotal) > TOLERANCE:
            lower("subtotal", 0.3)
            lower("lines", 0.3)
            warnings.append(
                f"sum of lines {_fmt(lines_sum)} but the invoice subtotal says {_fmt(bill.subtotal)}"
            )

    # 3. subtotal + taxes vs total
    tax_sum = sum((t.amount for t in bill.taxes), Decimal("0"))
    expected_total = bill.subtotal + tax_sum
    if abs(expected_total - bill.total) > TOLERANCE:
        lower("total", 0.4)
        lower("subtotal", 0.2)
        tax_part = " + ".join(f"{t.code.value} {_fmt(t.amount)}" for t in bill.taxes) or "no tax"
        warnings.append(
            f"subtotal {_fmt(bill.subtotal)} + {tax_part} = {_fmt(expected_total)} "
            f"but the invoice total says {_fmt(bill.total)}"
        )

    # 4. each tax ≈ rate × base. PST applies to goods only, so goods-only base is accepted too.
    goods_base = sum((ln.amount for ln in bill.lines if ln.line_type == LineType.GOODS), Decimal("0"))
    for t in bill.taxes:
        if t.code in (TaxCode.EXEMPT, TaxCode.FOREIGN) or t.rate == 0:
            continue
        candidates = [bill.subtotal] + ([goods_base] if t.code == TaxCode.PST7_BC and goods_base else [])
        if not any(abs((b * t.rate).quantize(CENT) - t.amount) <= TOLERANCE for b in candidates):
            lower("taxes", 0.3)
            warnings.append(
                f"{t.code.value} at {t.rate.normalize():%} of {_fmt(bill.subtotal)} = "
                f"{_fmt((bill.subtotal * t.rate).quantize(CENT))} but the invoice says {_fmt(t.amount)}"
            )

    # 5. sign consistency: a credit note should be negative throughout.
    if bill.is_credit_note and bill.total > 0:
        lower("total", 0.2)
        warnings.append("document looks like a credit note but its total is positive")

    return conf, warnings
