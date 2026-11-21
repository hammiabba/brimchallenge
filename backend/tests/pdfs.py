"""Build small PDFs in tests (multi-page, multi-invoice, encrypted) without committing binary fixtures."""
from __future__ import annotations

from fpdf import FPDF


def make_pdf(pages: list[list[str]], *, user_password: str | None = None) -> bytes:
    """One PDF page per entry; each string is one line of text. Encrypted when user_password is set."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for lines in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        for line in lines:
            pdf.cell(text=line, new_x="LMARGIN", new_y="NEXT")
    if user_password is not None:
        pdf.set_encryption(owner_password="owner", user_password=user_password)
    return bytes(pdf.output())


def invoice_page(number: str, total: str = "1,130.00") -> list[str]:
    return [
        "Acme Supplies Ltd.", "100 King St W, Toronto ON M5H 1A1", "GST/HST No: 123456789RT0001",
        "INVOICE", f"Invoice No: {number}", "Invoice Date: 2026-10-01", "Due Date: 2026-10-31",
        "Bill to: Harborline Logistics Inc., 88 Queens Quay W, Toronto ON M5J 0B8",
        "Description                 Qty   Unit price   Amount",
        "Pallet wrap                  10      100.00   1,000.00",
        "Subtotal 1,000.00", "HST 13% 130.00", f"Total {total}",
    ]
