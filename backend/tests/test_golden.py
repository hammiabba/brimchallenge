"""Golden files are well-formed, point at real files, and the eval comparison works."""
import json
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.shared.schemas import DraftBill, InvoiceLine, SourceInfo, TaxCode, TaxLine, VendorOnInvoice
from tests.conftest import INCOMING

GOLDEN = sorted((Path(__file__).parent / "golden").glob("*.json"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_extraction  # noqa: E402


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_golden_is_well_formed(path):
    g = json.loads(path.read_text())
    assert (INCOMING / g["file"]).is_file()
    assert {"verified", "expected"} <= g.keys()
    e = g["expected"]
    assert set(eval_extraction.SCALAR_FIELDS) <= e.keys()
    for t in e["taxes"]:
        TaxCode(t["code"])
    assert D(e["subtotal"]) + sum(D(t["amount"]) for t in e["taxes"]) == D(e["total"]) or "wrong" in g["notes"]


def test_compare_flags_differences():
    g = json.loads((Path(__file__).parent / "golden" / "invoice_ha26_2766.json").read_text())
    bill = DraftBill(
        source=SourceInfo(file_name="x", file_hash="x"),
        vendor=VendorOnInvoice(name_on_invoice="Harlow and Stern LLP", vendor_id="V026"),
        invoice_number="HA26-2766", invoice_date=date(2026, 10, 27), due_date=date(2026, 11, 26),
        ship_to_province="ON",
        lines=[InvoiceLine(line_no=i, description="x", quantity=D(1), unit_price=D(1), amount=D(1)) for i in (1, 2)],
        subtotal=D("5710.0"), taxes=[TaxLine(code=TaxCode.HST13, rate=D("0.13"), amount=D("742.30"))],
        total=D("6452.30"), total_cad=D("6452.30"),
    )
    bad = {f: (e, g_) for f, e, g_, ok in eval_extraction.compare(g["expected"], bill) if not ok}
    assert bad == {"vendor_id": ("V052", "V026")}
