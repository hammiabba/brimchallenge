"""Vision second opinion: OCR text whose totals don't add up gets one re-read of the image.

Offline. tesseract isn't needed: the text layer is replaced by OCR-like text with a misread digit, and the model
answers text requests with what that text says and image requests with the recorded vision output for the scan.
"""
from __future__ import annotations

import pytest

from app.extraction import pipeline
from app.extraction.text_layer import TextResult
from tests.conftest import INCOMING, FixtureClient
from tests.extraction.test_pipeline import raw_invoice, to_wire

SCAN = INCOMING / "scan_8749.png"

# What tesseract might return for scan_8749.png, with the total misread (4,719.28 → 4,779.28).
OCR_TEXT = """Prairie Natural Gas Utility
4251 Granville St
Calgary AB T9K 7B4
GST/HST 862863208RT0001
TAX INVOICE
Invoice No.: PR26-1012
Invoice date: 2026-10-22
Payment due: 2026-11-12
Payment terms: Net 21
Bill to
Harborline Logistics Inc.
250 6 Ave SW, Suite 700, Calgary AB T2P 3H7
Description Qty Unit price Amount
Energy - October 1 $4,494.55 $4,494.55
Subtotal $4,494.55
GST (5%) $224.73
Total CAD $4,779.28
Remit to
Inst. 006 Transit 55541 Acct 704593075
"""


def ocr_raw(total="$4,779.28", subtotal="$4,494.55"):
    """What the model reads from OCR_TEXT."""
    from app.extraction.llm_parser import RawLine, RawTax

    return raw_invoice(
        vendor_name="Prairie Natural Gas Utility", vendor_address="4251 Granville St, Calgary AB T9K 7B4",
        vendor_gst_number="862863208RT0001", invoice_number="PR26-1012", invoice_date="2026-10-22",
        due_date="2026-11-12", payment_terms="Net 21",
        bill_to_address="250 6 Ave SW, Suite 700, Calgary AB T2P 3H7",
        lines=[RawLine(description="Energy - October", quantity="1", unit_price="$4,494.55",
                       amount="$4,494.55", line_type="services")],
        subtotal=subtotal, taxes=[RawTax(label="GST (5%)", rate="5%", amount="$224.73")], total=total,
        bank_institution="006", bank_transit="55541", bank_account="704593075")


class SplitClient(FixtureClient):
    """Text requests get `text_raw`; image requests get the recorded vision output (or `vision_raw`, or fail)."""

    def __init__(self, text_raw, vision_raw=None, vision_fails=False):
        super().__init__()
        self.text_raw, self.vision_raw, self.vision_fails = text_raw, vision_raw, vision_fails
        self.kinds: list[str] = []

    def _parse(self, **kwargs):
        from types import SimpleNamespace

        is_image = any(b.get("type") == "image" for b in kwargs["messages"][0]["content"])
        self.kinds.append("vision" if is_image else "text")
        usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        if not is_image:
            self.calls.append(kwargs)
            return SimpleNamespace(stop_reason="end_turn", parsed_output=to_wire(self.text_raw), usage=usage)
        if self.vision_fails:
            raise RuntimeError("vision model unavailable")
        if self.vision_raw is not None:
            self.calls.append(kwargs)
            return SimpleNamespace(stop_reason="end_turn", parsed_output=to_wire(self.vision_raw), usage=usage)
        return super()._parse(**kwargs)


@pytest.fixture
def ocr_text(monkeypatch):
    def fake(text=OCR_TEXT):
        monkeypatch.setattr(pipeline.text_layer, "get_text",
                            lambda data, name: TextResult(text, was_ocr=True, method="ocr", pages=[text]))
    fake()
    return fake


def run(client, repo):
    return pipeline.extract_outcome(SCAN.read_bytes(), SCAN.name, repo=repo, client=client)


def test_ocr_misread_total_is_replaced_by_the_vision_read(ocr_text, repo):
    client = SplitClient(ocr_raw())
    out = run(client, repo)
    assert out.status == "ok", out.error
    assert client.kinds == ["text", "vision"]
    d = out.draft
    assert str(d.total) == "4719.28" and d.vendor.vendor_id == "V042"
    assert any("re-read the image with the vision model and used that result (0)" in w
               for w in d.extraction_warnings), d.extraction_warnings
    assert not any(" but the " in w for w in d.extraction_warnings)  # the OCR arithmetic warning is gone
    assert d.source.was_ocr


def test_both_reads_are_cached(ocr_text, repo):
    run(SplitClient(ocr_raw()), repo)
    again = SplitClient(ocr_raw())
    out = run(again, repo)
    assert again.kinds == []
    assert str(out.draft.total) == "4719.28"
    assert any("used that result" in w for w in out.draft.extraction_warnings)


def test_vision_no_better_keeps_the_ocr_result(ocr_text, repo):
    client = SplitClient(ocr_raw(), vision_raw=ocr_raw())
    out = run(client, repo)
    assert client.kinds == ["text", "vision"]
    assert str(out.draft.total) == "4779.28"
    assert any("vision re-read was no better (1), so the OCR result is kept" in w
               for w in out.draft.extraction_warnings)
    assert any("but the invoice total says 4779.28" in w for w in out.draft.extraction_warnings)


def test_vision_failure_keeps_the_ocr_result_with_a_warning(ocr_text, repo):
    client = SplitClient(ocr_raw(), vision_fails=True)
    out = run(client, repo)
    assert out.status == "ok"
    assert str(out.draft.total) == "4779.28"
    assert any("a vision re-read wasn't possible (RuntimeError: vision model unavailable)" in w
               for w in out.draft.extraction_warnings)


def test_consistent_ocr_is_not_re_read(ocr_text, repo):
    ocr_text(OCR_TEXT.replace("4,779.28", "4,719.28"))
    client = SplitClient(ocr_raw(total="$4,719.28"))
    out = run(client, repo)
    assert client.kinds == ["text"]
    assert not any("vision" in w for w in out.draft.extraction_warnings)


def test_small_line_slip_within_one_percent_is_not_re_read(ocr_text, repo):
    # Lines miss the subtotal by 0.40 on 4,494.55 (< 1%), total adds up: a vendor slip, not an OCR misread.
    from app.extraction.llm_parser import RawLine

    raw = ocr_raw(total="$4,719.28")
    raw = raw.model_copy(update={"lines": [RawLine(description="Energy - October", quantity="1",
                                                    unit_price="$4,494.15", amount="$4,494.15",
                                                    line_type="services")]})
    client = SplitClient(raw)
    run(client, repo)
    assert client.kinds == ["text"]


def test_text_layer_pdfs_never_get_a_vision_re_read(repo):
    # Evergreen's total really is wrong on the document; a re-read of a born-digital PDF can't fix that.
    f = INCOMING / "evergreenenergyu_000850.pdf"
    client = FixtureClient()
    out = pipeline.extract_outcome(f.read_bytes(), f.name, repo=repo, client=client)
    assert len(client.calls) == 1
    assert any("but the invoice total says 3439.00" in w for w in out.draft.extraction_warnings)
    assert not any("vision" in w for w in out.draft.extraction_warnings)
