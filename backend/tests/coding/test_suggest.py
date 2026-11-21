from datetime import date
from decimal import Decimal as D

from app.coding.suggest import suggest
from app.shared.schemas import DraftBill, InvoiceLine, MatchMethod, SourceInfo, VendorOnInvoice


def bill(vendor_id, descriptions, requester=None, name="Vendor") -> DraftBill:
    return DraftBill(
        source=SourceInfo(file_name="t.pdf", file_hash="x"),
        vendor=VendorOnInvoice(name_on_invoice=name, vendor_id=vendor_id,
                               match_method=MatchMethod.GST_NUMBER if vendor_id else MatchMethod.NONE),
        invoice_number="1", invoice_date=date(2026, 10, 1), requester_user_id=requester,
        lines=[InvoiceLine(line_no=i + 1, description=d, quantity=D(1), unit_price=D(100), amount=D(100))
               for i, d in enumerate(descriptions)],
        subtotal=D(100) * len(descriptions), total=D(100) * len(descriptions),
        total_cad=D(100) * len(descriptions),
    )


def test_vendor_history_wins(repo):
    out = suggest(bill("V001", ["LTL shipment Toronto-Montreal"]), repo)
    c = out.lines[0].coding
    assert (c.gl_account, c.department_id) == ("5010", "D01")
    assert c.confidence >= 0.8
    assert "past lines from Polar Freight Lines Ltd." in c.reason and "closest match" in c.reason


def test_vendor_with_mixed_history_uses_description(repo):
    # V010 codes both 5040 (packaging) and 5030 (warehousing): the description should decide.
    lines = repo.invoice_lines().merge(repo.invoices()[["invoice_id", "vendor_id"]], on="invoice_id")
    v010 = lines[lines["vendor_id"] == "V010"]
    for gl in ("5030", "5040"):
        sample = v010[v010["gl_account"] == gl].iloc[0]["description"]
        assert suggest(bill("V010", [sample]), repo).lines[0].coding.gl_account == gl


def test_unknown_vendor_falls_back_to_global_similarity(repo):
    out = suggest(bill(None, ["LTL shipment Vancouver-Calgary"], name="Blue Heron Couriers"), repo)
    c = out.lines[0].coding
    assert c.gl_account == "5010"
    assert c.confidence <= 0.6
    assert "no history for this vendor" in c.reason


def test_requester_department_overrides(repo):
    users = repo.users()
    sales_user = users[users["department_id"] == "D02"].iloc[0]["user_id"]
    c = suggest(bill("V001", ["LTL shipment"], requester=sales_user), repo).lines[0].coding
    assert c.department_id == "D02" and sales_user in c.reason


def test_every_line_gets_a_suggestion(repo):
    out = suggest(bill("V001", ["Fuel surcharge (9%)", "LTL shipment A-B"]), repo)
    assert all(ln.coding is not None for ln in out.lines)
