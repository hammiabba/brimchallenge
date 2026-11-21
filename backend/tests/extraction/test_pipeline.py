"""Pipeline tests with a fake LLM client: the network is never touched."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.extraction import pipeline, text_layer
from app.extraction.llm_parser import LLMUnavailableError, RawInvoice, RawLine, RawTax
from app.shared.schemas import MatchMethod, TaxCode
from tests.conftest import INCOMING


class FakeClient:
    """Mimics `anthropic.Anthropic().messages.parse` and records each call."""

    def __init__(self, raw: RawInvoice, stop_reason: str = "end_turn"):
        self.calls: list[dict] = []
        self._resp = SimpleNamespace(stop_reason=stop_reason, parsed_output=raw)
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._resp


def raw_invoice(**overrides) -> RawInvoice:
    base = dict(
        document_type="invoice", vendor_name="Harlow and Stern LLP",
        vendor_address="1422 Granville St, Toronto ON M8E 7A1", vendor_gst_number="503486760RT0001",
        vendor_qst_number=None, vendor_email=None, invoice_number="HA26-2766", invoice_date="2026-10-27",
        due_date="2026-11-26", payment_terms="Net 30", currency="CAD",
        bill_to_name="Harborline Logistics Inc.",
        bill_to_address="88 Queens Quay W, Suite 1400, Toronto ON M5J 0B8", ship_to_address=None,
        po_number=None, po_field_present=False, contract_reference=None,
        lines=[RawLine(description="Legal services - Commercial lease review", quantity="12",
                       unit_price="$450.00", amount="$5,400.00", line_type="services"),
               RawLine(description="Disbursements and filing fees", quantity="1", unit_price="$310.00",
                       amount="$310.00", line_type="services")],
        subtotal="$5,710.00", taxes=[RawTax(label="HST (13%)", rate="13%", amount="$742.30")],
        total="$6,452.30", bank_institution="010", bank_transit="40238", bank_account="593014216",
    )
    base.update(overrides)
    return RawInvoice(**base)


HARLOW = INCOMING / "Invoice HA26-2766.pdf"


def test_full_pipeline_on_text_pdf(repo):
    client = FakeClient(raw_invoice())
    out = pipeline.extract_outcome(HARLOW.read_bytes(), HARLOW.name, email_id="EM-026",
                                   sender="ar@harlowandstern-llp.example", repo=repo, client=client)
    assert out.status == "ok", out.error
    bill = out.draft
    assert bill.vendor.vendor_id == "V052" and bill.vendor.match_method == MatchMethod.GST_NUMBER
    assert bill.invoice_date == date(2026, 10, 27) and bill.payment_terms_days == 30
    assert bill.total == D("6452.30") and bill.total_cad == D("6452.30")
    assert bill.taxes[0].code == TaxCode.HST13
    assert bill.ship_to_province == "ON"
    assert bill.source.sender_address == "ar@harlowandstern-llp.example"
    assert bill.extraction_warnings == []
    # The text layer was used, so the model received text, not an image.
    sent = client.calls[0]["messages"][0]["content"][0]
    assert sent["type"] == "text" and "HA26-2766" in sent["text"]


def test_second_run_hits_cache_without_key(repo):
    data = HARLOW.read_bytes()
    pipeline.extract_outcome(data, HARLOW.name, repo=repo, client=FakeClient(raw_invoice()))
    # No client and no key: a cached result must still be served.
    out = pipeline.extract_outcome(data, HARLOW.name, repo=repo)
    assert out.status == "ok"
    assert out.draft.invoice_number == "HA26-2766"


def test_no_key_and_no_cache_skips_llm(repo):
    out = pipeline.extract_outcome(HARLOW.read_bytes(), HARLOW.name, repo=repo)
    assert out.status == "llm_skipped"
    assert "HA26-2766" in out.text  # the text layer still ran
    with pytest.raises(LLMUnavailableError):
        pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo)


def test_french_amounts_and_quebec_taxes(repo):
    raw = raw_invoice(
        vendor_name="Laurentian Logistics Inc.", vendor_gst_number="790628686RT0001",
        invoice_number="FA-002399", invoice_date="2026-10-25", due_date="2026-11-24",
        bill_to_address="1250 Rene-Levesque O, Bureau 2200, Montreal QC H3B 4W8",
        lines=[RawLine(description="LTL shipment Ottawa-Regina", quantity="1", unit_price="4 362,67 $",
                       amount="4 362,67 $", line_type="services")],
        subtotal="4 362,67 $",
        taxes=[RawTax(label="TPS (5 %)", rate="5 %", amount="218,13 $"),
               RawTax(label="TVQ (9,975 %)", rate="9,975 %", amount="435,18 $")],
        total="5 015,98 $", bank_institution="001", bank_transit="85308", bank_account="177982930",
    )
    f = INCOMING / "laurentianlogist_FA002399.pdf"
    bill = pipeline.extract(f.read_bytes(), f.name, repo=repo, client=FakeClient(raw))
    assert [t.code for t in bill.taxes] == [TaxCode.GST5, TaxCode.QST9975]
    assert bill.taxes[1].rate == D("0.09975")
    assert bill.total == D("5015.98") and bill.ship_to_province == "QC"
    assert bill.source.language == "fr"


def test_usd_foreign_vendor_gets_fx_and_foreign_code(repo):
    raw = raw_invoice(
        vendor_name="Sparkgrid CRM Inc.", vendor_address="7348 Rue Sainte-Catherine, Austin TX 35030",
        vendor_gst_number=None, invoice_number="FA-002342", invoice_date="2026-10-26", currency="USD",
        bill_to_address="1055 W Hastings St, Suite 900, Vancouver BC V6E 2E9",
        lines=[RawLine(description="Sparkgrid CRM Enterprise (15 seats)", quantity="1",
                       unit_price="$1,950.00", amount="$1,950.00", line_type="services")],
        subtotal="$1,950.00", taxes=[], total="$1,950.00",
        bank_institution=None, bank_transit=None, bank_account=None,
    )
    f = INCOMING / "sparkgridcrminc_FA002342.pdf"
    bill = pipeline.extract(f.read_bytes(), f.name, sender="ar@sparkgridcrm.example", repo=repo,
                            client=FakeClient(raw))
    rate = repo.fx_rate(date(2026, 10, 26))
    assert bill.currency == "USD" and bill.fx_rate_to_cad == rate
    assert bill.total_cad == (D("1950.00") * rate).quantize(D("0.01"))
    assert [t.code for t in bill.taxes] == [TaxCode.FOREIGN]


def test_credit_note_and_wrong_total_kept_as_printed(repo):
    raw = raw_invoice(document_type="credit_note", invoice_number="CN-FA-000413",
                      lines=[RawLine(description="Credit - Dock door repair", quantity="1",
                                     unit_price="-$1,042.76", amount="-$1,042.76", line_type="services")],
                      subtotal="-$1,042.76", taxes=[RawTax(label="HST (13%)", rate="13%", amount="-$135.56")],
                      total="-$1,200.00")
    bill = pipeline.extract(HARLOW.read_bytes(), "cn.pdf", repo=repo, client=FakeClient(raw))
    assert bill.is_credit_note and bill.total == D("-1200.00")
    assert any("total says -1200.00" in w for w in bill.extraction_warnings)


def test_scan_without_ocr_goes_to_vision_with_id_fixes(repo, monkeypatch):
    monkeypatch.setattr(text_layer, "ocr_available", lambda: False)
    raw = raw_invoice(vendor_name="Cascadia Cartage Ltd.", vendor_gst_number="669086667RT000!",
                      invoice_number="1624", bank_institution="003", bank_transit="$2968",
                      bank_account="953389679")
    f = INCOMING / "scan_8049.png"
    client = FakeClient(raw)
    out = pipeline.extract_outcome(f.read_bytes(), f.name, repo=repo, client=client)
    assert out.status == "ok", out.error
    assert client.calls[0]["messages"][0]["content"][0]["type"] == "image"
    bill = out.draft
    assert bill.source.was_ocr
    assert bill.vendor.gst_number == "669086667RT0001" and bill.vendor.bank.transit == "52968"
    assert bill.vendor.vendor_id == "V004"
    assert sum("OCR fix" in w for w in bill.extraction_warnings) == 2
    assert bill.field_confidence["vendor"] < 0.75


def test_missing_invoice_date_fails_cleanly(repo):
    out = pipeline.extract_outcome(HARLOW.read_bytes(), HARLOW.name, repo=repo,
                                   client=FakeClient(raw_invoice(invoice_date=None)))
    assert out.status == "failed" and "invoice date" in out.error


def test_blank_po_field_is_noted(repo):
    bill = pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo,
                            client=FakeClient(raw_invoice(po_field_present=True, po_number="  ")))
    assert bill.po_number is None
    assert any("PO field" in w for w in bill.extraction_warnings)
