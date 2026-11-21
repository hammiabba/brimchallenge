from app.extraction import text_layer
from tests.conftest import INCOMING


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
