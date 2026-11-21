from datetime import date
from decimal import Decimal as D

import pytest

from app.controls import load_refdata
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

RATES = {"HST13": D("0.13"), "GST5": D("0.05"), "PST7_BC": D("0.07"), "QST9975": D("0.09975")}
PROVINCE_TAX = {"ON": ["HST13"], "QC": ["GST5", "QST9975"], "BC": ["GST5"], "AB": ["GST5"]}


@pytest.fixture(scope="session")
def ref():
    return load_refdata()


@pytest.fixture
def make_bill(ref):
    """Builds a clean, valid schemas.DraftBill for a vendor; tests then break one thing at a time."""
    def _make(vendor_id="V001", amount="1000.00", province="ON", requester="U013", dept="D01",
              number="TEST-001", when=date(2026, 10, 20), currency="CAD", line_type="services",
              description="LTL shipment Toronto-Ottawa", qty="1", file_hash="sha256:test"):
        v = ref.vendors[vendor_id]
        amt = D(amount)
        codes = []
        if v["country"] == "CA" and v["category"] != "Insurance":
            codes = PROVINCE_TAX[province] + (["PST7_BC"] if province == "BC" and line_type == "goods" else [])
        taxes = [TaxLine(code=TaxCode(c), rate=RATES[c], amount=(amt * RATES[c]).quantize(D("0.01"))) for c in codes]
        total = amt + sum((t.amount for t in taxes), D("0"))
        fx = ref.fx_rate(when) if currency == "USD" else D("1")
        q = D(qty)
        return DraftBill(
            source=SourceInfo(file_name=f"{number}.pdf", file_hash=file_hash),
            vendor=VendorOnInvoice(
                name_on_invoice=v["legal_name"], gst_number=v["gst_hst_number"] or None,
                bank=BankDetails(institution=v["bank_institution"] or None, transit=v["bank_transit"] or None,
                                 account=v["bank_account"] or None),
                vendor_id=vendor_id, match_method=MatchMethod.GST_NUMBER, match_score=1.0),
            invoice_number=number, invoice_date=when, currency=currency,
            ship_to_province=province, requester_user_id=requester, department_id=dept,
            lines=[InvoiceLine(line_no=1, description=description, quantity=q,
                               unit_price=(amt / q).quantize(D("0.01")), amount=amt, line_type=LineType(line_type))],
            subtotal=amt, taxes=taxes, total=total,
            fx_rate_to_cad=fx, total_cad=(total * fx).quantize(D("0.01")),
        )
    return _make
