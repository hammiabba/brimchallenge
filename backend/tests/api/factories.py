"""Builders for app bills in a test's private database: a clean DraftBill stored through the DB layer, with a
controls run, exactly as intake would leave it (status needs_review)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.controls.refdata import load_refdata
from app.db.bills import create_bill_from_draft
from app.db.database import as_write_engine
from app.services import controls_runner
from app.shared.schemas import (
    BankDetails,
    DraftBill,
    InvoiceLine,
    LineType,
    MatchMethod,
    SourceInfo,
    TaxCode,
    TaxLine,
    VendorOnInvoice,
)

_REF = None
RATES = {"GST5": D("0.05"), "HST13": D("0.13")}


def _ref():
    global _REF
    if _REF is None:
        _REF = load_refdata()
    return _REF


def draft(*, vendor_id: str = "V001", amount: str = "1000.00", province: str = "ON", requester: str = "U013",
          dept: str = "D01", number: str = "APP-0001", tax_code: str | None = None,
          when: date = date(2026, 10, 28), bank_account: str | None = None) -> DraftBill:
    v = _ref().vendors[vendor_id]
    amt = D(amount)
    code = tax_code or ("HST13" if province == "ON" else "GST5")
    tax = (amt * RATES[code]).quantize(D("0.01"))
    return DraftBill(
        source=SourceInfo(file_name=f"{number}.pdf", file_hash=f"sha256:{number}"),
        vendor=VendorOnInvoice(name_on_invoice=v["legal_name"], gst_number=v["gst_hst_number"] or None,
                               bank=BankDetails(institution=v["bank_institution"] or None,
                                                transit=v["bank_transit"] or None,
                                                account=bank_account or v["bank_account"] or None),
                               vendor_id=vendor_id, match_method=MatchMethod.GST_NUMBER, match_score=1.0),
        invoice_number=number, invoice_date=when, due_date=date(2026, 11, 27), currency="CAD",
        ship_to_province=province, requester_user_id=requester, department_id=dept,
        lines=[InvoiceLine(line_no=1, description="LTL shipment Toronto-Ottawa", quantity=D("1"), unit_price=amt,
                           amount=amt, line_type=LineType.SERVICES)],
        subtotal=amt, taxes=[TaxLine(code=TaxCode(code), rate=RATES[code], amount=tax)], total=amt + tax,
        total_cad=amt + tax)


def app_bill(engine: Engine, **kwargs) -> str:
    with Session(as_write_engine(engine), expire_on_commit=False) as s:
        created = create_bill_from_draft(s, draft(**kwargs), created_by="U004", received_date=date(2026, 11, 2))
        controls_runner.rerun(s, created.bill_id)
        s.commit()
        return created.bill_id
