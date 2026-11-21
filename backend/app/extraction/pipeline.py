"""
Extraction pipeline: one file → DraftBill.

Owner: Person A.
Public API:
  extract(data, filename, ...) -> DraftBill           raises on failure / missing API key
  extract_outcome(data, filename, ...) -> ExtractionOutcome   never raises; for batch runs

Steps: hash → text layer → LLM (cached) → normalize → vendor match → self-check → coding.

ExtractionOutcome exists because DraftBill requires invoice_number and invoice_date,
so "LLM skipped" or "couldn't read the date" can't be represented as a DraftBill
without changing the shared schema.

To change safely: keep each step in its own module and keep this file to orchestration.
New per-field rules belong in normalize.py, new arithmetic checks in selfcheck.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.coding import suggest as coding
from app.config import get_settings
from app.extraction import cache, filecheck, llm_parser, normalize, selfcheck, text_layer, vendor_match
from app.extraction.llm_parser import LLMUnavailableError, RawInvoice
from app.reference.csv_repository import default_repository
from app.reference.repository import ReferenceRepository
from app.shared.schemas import (
    BankDetails,
    DraftBill,
    InvoiceLine,
    LineType,
    SourceInfo,
    TaxCode,
    TaxLine,
    VendorOnInvoice,
)

CENT = Decimal("0.01")
# Confidence taken off a date that was ambiguous: settled by evidence, or still a day-first guess.
DATE_RESOLVED_PENALTY = 0.15
DATE_AMBIGUOUS_PENALTY = 0.45
MULTI_INVOICE_PENALTY = 0.5


class ExtractionIncomplete(ValueError):
    """The document was read but a field DraftBill requires (number, date, total) is missing."""


@dataclass
class ExtractionOutcome:
    file_name: str
    file_hash: str
    status: Literal["ok", "llm_skipped", "failed"]
    draft: DraftBill | None = None
    text: str = ""
    text_method: str = "none"
    was_ocr: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    usage: dict = field(default_factory=dict)   # LLM tokens spent on this file in this run ({} on a cache hit)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name, "file_hash": self.file_hash, "status": self.status,
            "text_method": self.text_method, "was_ocr": self.was_ocr, "warnings": self.warnings,
            "error": self.error,
            "draft": json.loads(self.draft.model_dump_json()) if self.draft else None,
            "text_preview": None if self.draft else self.text[:500],
        }


# ---------------------------------------------------------------- public API

def extract(data: bytes, filename: str, *, email_id: str | None = None, sender: str | None = None,
            repo: ReferenceRepository | None = None, client=None) -> DraftBill:
    out = extract_outcome(data, filename, email_id=email_id, sender=sender, repo=repo, client=client)
    if out.status == "llm_skipped":
        raise LLMUnavailableError(out.error)
    if out.draft is None:
        raise ExtractionIncomplete(out.error or f"Extraction failed for {filename}")
    return out.draft


def extract_outcome(data: bytes, filename: str, *, email_id: str | None = None, sender: str | None = None,
                    repo: ReferenceRepository | None = None, client=None) -> ExtractionOutcome:
    s = get_settings()
    repo = repo or default_repository()
    file_hash = cache.file_sha256(data)
    if problem := filecheck.problem(data, filename):
        return ExtractionOutcome(filename, file_hash, "failed", error=problem)
    read_as, renamed = filecheck.real_name(data, filename)
    try:
        tr = text_layer.get_text(data, read_as)
    except Exception as exc:  # a file that passed the checks but still breaks the reader
        msg = f"The file couldn't be read ({type(exc).__name__}); ask the sender to resend it."
        return ExtractionOutcome(filename, file_hash, "failed", error=msg)
    out = ExtractionOutcome(filename, file_hash, "failed", text=tr.text, text_method=tr.method,
                            was_ocr=tr.was_ocr, warnings=[*([renamed] if renamed else []), *tr.warnings])

    # LLM step, cached. A cache hit works even without an API key, which keeps demos offline-friendly.
    use_vision = not tr.text
    pv = llm_parser.prompt_version()
    cached = cache.get(file_hash, pv, s.llm_model)
    if cached:
        raw = RawInvoice.model_validate(cached["raw"])
        use_vision = cached.get("input") == "vision"
    elif client is None and not s.llm_enabled:
        out.status = "llm_skipped"
        out.error = "LLM skipped: ANTHROPIC_API_KEY not set"
        return out
    else:
        try:
            raw = llm_parser.parse_invoice(tr.text or None, file_bytes=data if use_vision else None,
                                           filename=read_as, client=client, usage=out.usage)
        except Exception as exc:  # one bad file must not stop the batch
            out.error = f"{type(exc).__name__}: {exc}"
            return out
        cache.put(file_hash, pv, s.llm_model, {"input": "vision" if use_vision else "text",
                                               "model": s.llm_model, "prompt_version": pv,
                                               "usage": out.usage, "raw": raw.model_dump()})
    if use_vision:
        out.warnings.append("no usable text layer; extracted from the image by the vision model")

    source = SourceInfo(
        email_id=email_id, sender_address=sender, file_name=filename, file_hash=file_hash,
        language=normalize.detect_language(tr.text or raw.model_dump_json()),
        was_ocr=tr.was_ocr or use_vision,
    )
    try:
        # Several invoices in one file: whichever one the model read, number and total are suspect.
        multi = {"invoice_number": MULTI_INVOICE_PENALTY, "total": MULTI_INVOICE_PENALTY} \
            if len(tr.invoice_numbers) > 1 else {}
        out.draft = build_draft(raw, source, repo, extra_warnings=out.warnings, extra_penalties=multi)
    except ExtractionIncomplete as exc:
        out.error = str(exc)
        return out
    try:
        out.draft = coding.suggest(out.draft, repo)
    except Exception as exc:  # a coding bug must not lose an otherwise good extraction
        out.draft.extraction_warnings.append(f"coding suggestions unavailable: {exc}")
    out.status = "ok"
    return out


# ---------------------------------------------------------------- RawInvoice → DraftBill

def _terms_days(terms: str | None) -> int | None:
    if not terms:
        return None
    t = terms.lower()
    if re.search(r"receipt|réception|reception|immediate|comptant", t):
        return 0
    m = re.search(r"(\d{1,3})", t)
    return int(m[1]) if m else None


def build_draft(raw: RawInvoice, source: SourceInfo, repo: ReferenceRepository,
                extra_warnings: list[str] | None = None,
                extra_penalties: dict[str, float] | None = None) -> DraftBill:
    warnings = list(extra_warnings or [])
    ocr_fixed: set[str] = set()
    missing: set[str] = set()

    if raw.document_type == "statement":
        raise ExtractionIncomplete("document is a statement of account, not an invoice")
    if not raw.invoice_number:
        raise ExtractionIncomplete("no invoice number found on the document")
    if normalize.parse_date(raw.invoice_date) is None:
        raise ExtractionIncomplete(f"could not read the invoice date ({raw.invoice_date!r})")

    # --- vendor identity, with OCR fixes on structured IDs only
    gst, w1 = normalize.fix_tax_number(raw.vendor_gst_number, "gst")
    qst, w2 = normalize.fix_tax_number(raw.vendor_qst_number, "qst")
    inst, w3 = normalize.fix_digit_field(raw.bank_institution, "institution", 3)
    transit, w4 = normalize.fix_digit_field(raw.bank_transit, "transit", 5)
    acct, w5 = normalize.fix_digit_field(raw.bank_account, "account")
    id_fixes = [w for w in (w1, w2, w3, w4, w5) if w]
    if id_fixes:
        warnings += id_fixes
        ocr_fixed.add("vendor")
    vendor = VendorOnInvoice(name_on_invoice=raw.vendor_name, gst_number=gst, qst_number=qst,
                             address=raw.vendor_address,
                             bank=BankDetails(institution=inst, transit=transit, account=acct))
    vendor, vm_warnings = vendor_match.resolve(vendor, source.sender_address, repo)
    warnings += vm_warnings
    master = repo.vendor(vendor.vendor_id) if vendor.vendor_id else None

    # --- dates: read together, so the due date and payment terms can settle a "03/04/2026"
    terms_days = _terms_days(raw.payment_terms)
    expected_terms = terms_days if terms_days is not None else _terms_days((master or {}).get("payment_terms_days"))
    dates = normalize.resolve_dates(raw.invoice_date, raw.due_date, expected_terms, get_settings().as_of_date)
    invoice_date, due_date = dates.invoice_date, dates.due_date
    warnings += dates.warnings
    penalties = dict(extra_penalties or {})
    penalties |= {f: DATE_RESOLVED_PENALTY for f in dates.resolved}
    penalties |= {f: DATE_AMBIGUOUS_PENALTY for f in dates.ambiguous}
    if due_date is None:
        missing.add("due_date")
    foreign = (master is not None and master.get("country", "CA") != "CA") or normalize.looks_foreign(
        raw.vendor_address)

    # --- currency
    currency = (raw.currency or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        currency = "USD" if foreign else "CAD"
        missing.add("currency")
        warnings.append(f"currency not printed on the totals line; assumed {currency}")

    # --- lines
    lines: list[InvoiceLine] = []
    for i, rl in enumerate(raw.lines, start=1):
        amount = normalize.parse_money(rl.amount)
        qty = normalize.parse_money(rl.quantity)
        price = normalize.parse_money(rl.unit_price)
        if amount is None and qty is not None and price is not None:
            amount = (qty * price).quantize(CENT)
            warnings.append(f"line {i}: amount not printed; computed {amount}")
        if amount is None:
            warnings.append(f"line {i}: no readable amount; line dropped ({rl.description!r})")
            continue
        if qty is None:
            qty = Decimal("1")
        if price is None:
            price = amount / qty if qty else amount
        lines.append(InvoiceLine(line_no=len(lines) + 1, description=rl.description, quantity=qty,
                                 unit_price=price, amount=amount, line_type=LineType(rl.line_type)))

    # --- taxes
    taxes: list[TaxLine] = []
    for rt in raw.taxes:
        amount = normalize.parse_money(rt.amount)
        rate = normalize.parse_rate(rt.rate) or normalize.parse_rate(
            m[0] if (m := re.search(r"\d+(?:[.,]\d+)?\s*%", rt.label)) else None)
        code = normalize.map_tax_label(rt.label, rate)
        if amount is None or code is None:
            warnings.append(f"unrecognised tax line {rt.label!r} {rt.amount!r}; not mapped to a tax code")
            continue
        taxes.append(TaxLine(code=code, rate=rate if rate is not None else normalize.STANDARD_RATES[code],
                             amount=amount))
    if not taxes and foreign:
        taxes = [TaxLine(code=TaxCode.FOREIGN, rate=Decimal("0"), amount=Decimal("0"))]

    # --- totals: printed values are kept even when they don't add up (selfcheck reports it)
    lines_sum = sum((ln.amount for ln in lines), Decimal("0"))
    subtotal = normalize.parse_money(raw.subtotal)
    if subtotal is None:
        subtotal = lines_sum
        missing.add("subtotal")
        warnings.append(f"subtotal not printed; using the sum of lines {subtotal}")
    total = normalize.parse_money(raw.total)
    if total is None:
        total = subtotal + sum((t.amount for t in taxes), Decimal("0"))
        missing.add("total")
        warnings.append(f"total not printed; computed {total}")

    # --- FX at the invoice-date rate (closest earlier date when the day is missing)
    fx = Decimal("1")
    if currency == "USD":
        rate = repo.fx_rate(invoice_date)
        if rate is None:
            warnings.append(f"no USD→CAD rate on or before {invoice_date}; total_cad uses 1.0")
        else:
            fx = rate
    elif currency != "CAD":
        warnings.append(f"no FX table for {currency}; total_cad uses 1.0")

    ship_to = normalize.province_from_address(raw.ship_to_address or raw.bill_to_address)
    if ship_to is None:
        missing.add("ship_to_province")

    contract_id = raw.contract_reference if raw.contract_reference and re.fullmatch(
        r"C\d{3}", raw.contract_reference.strip()) else None
    po = (raw.po_number or "").strip() or None
    if raw.po_field_present and po is None:
        warnings.append("PO field is printed on the invoice but left blank")

    bill = DraftBill(
        source=source, vendor=vendor,
        invoice_number=raw.invoice_number.strip(), invoice_date=invoice_date, due_date=due_date,
        payment_terms_days=terms_days, currency=currency,
        is_credit_note=raw.document_type == "credit_note" or total < 0,
        ship_to_province=ship_to, po_number=po, contract_id=contract_id,
        lines=lines, subtotal=subtotal, taxes=taxes, total=total,
        fx_rate_to_cad=fx, total_cad=(total * fx).quantize(CENT),
    )
    conf, check_warnings = selfcheck.check(bill, was_ocr=source.was_ocr, ocr_fixed_fields=ocr_fixed,
                                           missing_fields=missing, penalties=penalties)
    conf["vendor"] = round(min(conf["vendor"], max(vendor.match_score, 0.3)), 2)
    return bill.model_copy(update={"field_confidence": conf,
                                   "extraction_warnings": warnings + check_warnings})
