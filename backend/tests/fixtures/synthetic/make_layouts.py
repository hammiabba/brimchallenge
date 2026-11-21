"""One invoice rendered in layouts the dataset never uses, to test extraction on unseen formats.

Owner: Person A.   python tests/fixtures/synthetic/make_layouts.py [OUT_DIR]   writes synthetic_<layout>.pdf

Four layouts carry the same Laurentian Logistics invoice (V005, billed to Montreal, GST + QST): no table,
right-aligned totals, French labels with decimal commas, totals before the lines. The fifth is a USD invoice
from a US vendor (Tessera, V016). EXPECTED holds the values extraction must produce for each.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

from fpdf import FPDF

LINES = [("LTL shipment Montreal-Quebec", 2, D("612.50")), ("Pallet storage - October", 10, D("18.75")),
         ("Fuel surcharge", 1, D("98.83"))]
SUBTOTAL, GST, QST, TOTAL = D("1511.33"), D("75.57"), D("150.76"), D("1737.66")
VENDOR = ["Laurentian Logistics Inc.", "1502 Centre St", "Montreal QC G9V 5B6"]
TAX_IDS = "GST/HST 790628686RT0001   QST 1745206219TQ0001"
BILL_TO = ["Harborline Logistics Inc.", "1250 Rene-Levesque O, Bureau 2200, Montreal QC H3B 4W8"]
BANK = "Inst. 001  Transit 85308  Acct 177982930"

CORE = dict(vendor_id="V005", invoice_number="LL-77031", invoice_date="2026-10-14", due_date="2026-11-13",
            currency="CAD", subtotal=SUBTOTAL, taxes=[("GST5", GST), ("QST9975", QST)], total=TOTAL,
            province="QC", lines=3)
EXPECTED = {
    "table_less": CORE, "right_aligned": CORE, "french": CORE, "totals_first": CORE,
    "usd": dict(vendor_id="V016", invoice_number="TA-55120", invoice_date="2026-10-14", due_date="2026-11-13",
                currency="USD", subtotal=D("1450.00"), taxes=[("FOREIGN", D("0"))], total=D("1450.00"),
                province="BC", lines=2),
}


def money(d: D) -> str:
    return f"${d:,.2f}"


def money_fr(d: D) -> str:
    return f"{d:,.2f}".replace(",", " ").replace(".", ",") + " $"


def _pdf() -> FPDF:
    pdf = FPDF(format="Letter")
    pdf.set_creation_date(datetime(2026, 10, 14, tzinfo=UTC))  # same bytes on every run
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    return pdf


def _text(pdf: FPDF, lines: list[str], h: float = 5, align: str = "L", bold: bool = False):
    pdf.set_font("Helvetica", "B" if bold else "", 10)
    for ln in lines:
        pdf.cell(0, h, ln, align=align, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)


def table_less() -> FPDF:
    """No table: header as prose, each line as a short paragraph."""
    pdf = _pdf()
    _text(pdf, VENDOR + [TAX_IDS], bold=False)
    pdf.ln(6)
    _text(pdf, ["Statement of charges for invoice LL-77031, issued October 14, 2026.",
                "Please pay within 30 days, by November 13, 2026.", "",
                "Charged to: " + ", ".join(BILL_TO), ""])
    for i, (desc, qty, price) in enumerate(LINES, 1):
        _text(pdf, [f"Item {i}. {desc}", f"    quantity {qty} at {money(price)} each, for {money(qty * price)}"])
    pdf.ln(4)
    _text(pdf, [f"Charges before tax come to {money(SUBTOTAL)}.",
                f"GST at 5% adds {money(GST)} and QST at 9.975% adds {money(QST)}.",
                f"Amount to pay: {money(TOTAL)} Canadian dollars.", "", f"Pay by EFT to {BANK}."])
    return pdf


def right_aligned() -> FPDF:
    """Header block on the right, table, totals right-aligned in a narrow column."""
    pdf = _pdf()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "INVOICE", align="R", new_x="LMARGIN", new_y="NEXT")
    _text(pdf, VENDOR + [TAX_IDS], align="R")
    _text(pdf, ["Number LL-77031", "Dated 2026-10-14", "Payable by 2026-11-13 (30 days)"], align="R")
    pdf.ln(6)
    _text(pdf, ["Sold to"] + BILL_TO)
    pdf.ln(4)
    widths = (100, 20, 35, 35)
    for row in [("Service", "Units", "Rate", "Extended")] + [
            (d, str(q), money(p), money(q * p)) for d, q, p in LINES]:
        for w, v, a in zip(widths, row, "LRRR", strict=True):
            pdf.cell(w, 6, v, align=a)
        pdf.ln()
    pdf.ln(4)
    for label, v in [("Net amount", SUBTOTAL), ("GST 5%", GST), ("QST 9.975%", QST), ("Balance due (CAD)", TOTAL)]:
        pdf.cell(155, 6, label, align="R")
        pdf.cell(35, 6, money(v), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    _text(pdf, ["Remittance: EFT " + BANK])
    return pdf


def french() -> FPDF:
    """French labels, decimal commas, spaced thousands, dates written out."""
    pdf = _pdf()
    _text(pdf, ["FACTURE"], bold=True)
    _text(pdf, VENDOR + ["TPS/TVH 790628686RT0001   TVQ 1745206219TQ0001"])
    pdf.ln(4)
    _text(pdf, ["Facture n° : LL-77031", "Date de facturation : 14 octobre 2026",
                "Date d'échéance : 13 novembre 2026", "Modalités : 30 jours net"])
    pdf.ln(4)
    _text(pdf, ["Facturé à"] + BILL_TO)
    pdf.ln(4)
    for row in [("Description", "Qté", "Prix unitaire", "Montant")] + [
            (d, str(q), money_fr(p), money_fr(q * p)) for d, q, p in LINES]:
        for w, v, a in zip((100, 20, 35, 35), row, "LRRR", strict=True):
            pdf.cell(w, 6, v, align=a)
        pdf.ln()
    pdf.ln(4)
    for label, v in [("Sous-total", SUBTOTAL), ("TPS (5 %)", GST), ("TVQ (9,975 %)", QST), ("Total à payer", TOTAL)]:
        pdf.cell(155, 6, label, align="R")
        pdf.cell(35, 6, money_fr(v), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    _text(pdf, ["Paiement par virement : Inst. 001  Transit 85308  Compte 177982930"])
    return pdf


def totals_first() -> FPDF:
    """A summary box with the amounts at the top, the line detail after it."""
    pdf = _pdf()
    _text(pdf, VENDOR + [TAX_IDS])
    pdf.ln(4)
    _text(pdf, ["ACCOUNT SUMMARY"], bold=True)
    _text(pdf, [f"Total due CAD {money(TOTAL)}", f"Subtotal {money(SUBTOTAL)}",
                f"GST (5%) {money(GST)}", f"QST (9.975%) {money(QST)}"])
    pdf.ln(4)
    _text(pdf, ["Invoice LL-77031    Invoice date 2026-10-14    Due 2026-11-13    Net 30"])
    _text(pdf, ["Customer: " + ", ".join(BILL_TO)])
    pdf.ln(4)
    _text(pdf, ["DETAIL OF CHARGES"], bold=True)
    for d, q, p in LINES:
        _text(pdf, [f"{d}    {q}    {money(p)}    {money(q * p)}"])
    pdf.ln(4)
    _text(pdf, ["Remit by EFT: " + BANK])
    return pdf


def usd() -> FPDF:
    """A US vendor billing in USD, no Canadian taxes."""
    pdf = _pdf()
    _text(pdf, ["Tessera Analytics Inc.", "351 King St W", "Seattle, WA 43465", "United States"])
    pdf.ln(4)
    _text(pdf, ["INVOICE TA-55120"], bold=True)
    _text(pdf, ["Invoice date: Oct 14, 2026", "Due date: Nov 13, 2026", "Terms: Net 30"])
    pdf.ln(4)
    _text(pdf, ["Bill to", BILL_TO[0], "1055 W Hastings St, Suite 900, Vancouver BC V6E 2E9"])
    pdf.ln(4)
    for row in [("Description", "Qty", "Unit price", "Amount"),
                ("Tessera Analytics Pro - seats", "8", "$125.00", "$1,000.00"),
                ("Onboarding workshop", "1", "$450.00", "$450.00")]:
        for w, v, a in zip((100, 20, 35, 35), row, "LRRR", strict=True):
            pdf.cell(w, 6, v, align=a)
        pdf.ln()
    pdf.ln(4)
    for label, v in [("Subtotal", "$1,450.00"), ("Sales tax", "$0.00"), ("Total (USD)", "$1,450.00")]:
        pdf.cell(155, 6, label, align="R")
        pdf.cell(35, 6, v, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    _text(pdf, ["Amounts in US dollars. Pay by credit card at our online portal."])
    return pdf


LAYOUTS = {"table_less": table_less, "right_aligned": right_aligned, "french": french,
           "totals_first": totals_first, "usd": usd}


def file_name(layout: str) -> str:
    return f"synthetic_{layout}.pdf"


def render(layout: str) -> bytes:
    return bytes(LAYOUTS[layout]().output())


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name in LAYOUTS:
        (out / file_name(name)).write_bytes(render(name))
    print(f"{len(LAYOUTS)} layouts written to {out}")
