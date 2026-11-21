from app.extraction import text_layer
from tests.conftest import INCOMING
from tests.pdfs import invoice_page, make_pdf


def test_pdf_text_layer_french_invoice():
    data = (INCOMING / "laurentianlogist_FA002399.pdf").read_bytes()
    res = text_layer.get_text(data, "laurentianlogist_FA002399.pdf")
    assert res.method == "pdfplumber"
    assert not res.was_ocr
    assert "FA-002399" in res.text
    assert "4 362,67 $" in res.text


def test_text_is_compacted():
    data = (INCOMING / "Invoice HA26-2766.pdf").read_bytes()
    res = text_layer.get_text(data, "Invoice HA26-2766.pdf")
    assert "\n\n\n" not in res.text
    assert not any(line != line.rstrip() for line in res.text.splitlines())


def test_image_without_tesseract_returns_warning(monkeypatch):
    monkeypatch.setattr(text_layer, "ocr_available", lambda: False)
    data = (INCOMING / "scan_8049.png").read_bytes()
    res = text_layer.get_text(data, "scan_8049.png")
    assert res.text == ""
    assert any("OCR unavailable" in w for w in res.warnings)


def test_unsupported_file_type():
    res = text_layer.get_text(b"hello", "notes.docx")
    assert res.text == "" and res.warnings


# ---------------------------------------------------------------- several invoices in one file

def test_two_invoices_on_separate_pages_are_detected():
    res = text_layer.get_text(make_pdf([invoice_page("A-1001"), invoice_page("A-1002")]), "batch.pdf")
    assert res.invoice_numbers == ["A-1001", "A-1002"]
    assert any("appears to contain 2 invoices (A-1001, A-1002)" in w for w in res.warnings)
    assert len(res.pages) == 2 and "A-1002" in res.text


def test_multi_page_single_invoice_is_not_flagged():
    # Page 2 repeats the header (same number); page 3 is terms only.
    data = make_pdf([invoice_page("A-1001"), invoice_page("A-1001"), ["Terms and conditions", "Net 30"]])
    res = text_layer.get_text(data, "long.pdf")
    assert res.invoice_numbers == ["A-1001"]
    assert not any("appears to contain" in w for w in res.warnings)


def test_reference_to_original_invoice_lower_on_the_page_is_ignored():
    page = ["CREDIT NOTE", "Credit note No: CN-77", "Refers to original invoice no. 76", "Total -100.00"]
    assert text_layer.get_text(make_pdf([page]), "cn.pdf").invoice_numbers == ["CN-77"]


def test_invoice_label_variants():
    pages = ["INV NO : 000961", "Facture n° FA-002399", "Invoice # INV-01561", "Credit Note No. CN-FA-000413",
             "Northbound Courier\nInvoice No: 000639"]
    assert text_layer.invoice_numbers_by_page(pages) == ["000961", "FA-002399", "INV-01561", "CN-FA-000413",
                                                         "000639"]


def test_no_sample_pdf_is_flagged_as_multi_invoice():
    for f in sorted(INCOMING.glob("*.pdf")):
        res = text_layer.get_text(f.read_bytes(), f.name)
        assert len(res.invoice_numbers) <= 1, (f.name, res.invoice_numbers)
