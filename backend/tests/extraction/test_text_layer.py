import pytest

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


# ---------------------------------------------------------------- OCR and pdftotext, without the binaries

class _FakeTesseract:
    def __init__(self, langs=("eng", "fra"), text="Invoice No: OCR-1\nTotal CAD $10.00"):
        self.langs, self.text, self.calls = list(langs), text, []

    def get_tesseract_version(self):
        return "5.0"

    def get_languages(self, config=""):
        return self.langs

    def image_to_string(self, img, lang, config):
        self.calls.append((lang, config))
        return self.text


@pytest.fixture
def tesseract(monkeypatch):
    import sys

    fake = _FakeTesseract()
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    return fake


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_image_is_ocrd_in_english_and_french(tesseract):
    tr = text_layer.get_text(_png(), "scan.png")
    assert tr.was_ocr and tr.method == "ocr" and "OCR-1" in tr.text and tr.warnings == []
    assert tesseract.calls == [("eng+fra", "--psm 6")]


def test_missing_french_data_is_noted(tesseract):
    tesseract.langs = ["eng"]
    tr = text_layer.get_text(_png(), "scan.png")
    assert tr.warnings == ["French OCR data not installed; using English only"]


def test_languages_query_failing_means_english(tesseract, monkeypatch):
    def boom(config=""):
        raise RuntimeError("no tessdata")

    monkeypatch.setattr(tesseract, "get_languages", boom)
    assert text_layer.get_text(_png(), "scan.png").warnings == ["French OCR data not installed; using English only"]


def test_unreadable_image_is_a_warning_not_a_crash(tesseract):
    tr = text_layer.get_text(b"\x89PNG\r\n\x1a\nbroken", "scan.png")
    assert tr.text == "" and tr.warnings[0].startswith("Could not open image")


def test_pdf_without_text_is_ocrd_page_by_page(tesseract):
    tr = text_layer.get_text(make_pdf([[]]), "blank.pdf")
    assert tr.was_ocr and "OCR-1" in tr.text and len(tesseract.calls) == 1


def test_pdftotext_is_used_when_pdfplumber_finds_nothing(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    monkeypatch.setattr(text_layer.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(text_layer, "_pdfplumber_pages", lambda data, warnings: [])
    page = "Invoice No: PT-1\nSubtotal $100.00\nTotal CAD $105.00 " + "x" * 80
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=(page + "\f").encode()))
    tr = text_layer.get_text(b"%PDF-1.4 whatever", "x.pdf")
    assert tr.method == "pdftotext" and "PT-1" in tr.text


def test_pdftotext_failure_is_a_warning(monkeypatch):
    import subprocess

    def fail(*a, **k):
        raise subprocess.TimeoutExpired("pdftotext", 60)

    monkeypatch.setattr(text_layer.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(text_layer, "_pdfplumber_pages", lambda data, warnings: [])
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(text_layer, "ocr_available", lambda: False)
    tr = text_layer.get_text(b"%PDF-1.4 whatever", "x.pdf")
    assert any(w.startswith("pdftotext failed") for w in tr.warnings) and tr.text == ""
