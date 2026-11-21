"""Opt-in tests against the real LLM API.

Skipped unless RUN_LIVE_LLM=1 and ANTHROPIC_API_KEY is set (env or .env). Plain `pytest`
deselects them (see addopts in pyproject.toml). Run with:

    RUN_LIVE_LLM=1 pytest -m live -v

The cache is redirected to a temp dir, so every run really calls the API.
On failure, the assertion message includes the RawInvoice the model returned.
"""
import json
import os
from decimal import Decimal as D

import pytest

from app.config import get_settings
from app.extraction import cache, pipeline
from app.extraction.llm_parser import prompt_version
from tests.conftest import INCOMING

# Captured at import, before conftest's per-test fixture blanks the key.
_API_KEY = get_settings().anthropic_api_key

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1" or not _API_KEY,
                       reason="set RUN_LIVE_LLM=1 and ANTHROPIC_API_KEY to run live LLM tests"),
]


@pytest.fixture
def live_settings(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", _API_KEY)
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache")  # bypass any cached result
    return s


def _extract(file_name: str, sender: str, s, repo):
    out = pipeline.extract_outcome((INCOMING / file_name).read_bytes(), file_name, sender=sender, repo=repo)
    raw = cache.get(out.file_hash, prompt_version(), s.llm_model)
    debug = f"status={out.status} error={out.error}\nraw={json.dumps(raw, indent=2, ensure_ascii=False)}"
    assert out.status == "ok", debug
    return out.draft, debug


def _no_arithmetic_warnings(draft) -> bool:
    return not any(" but the " in w for w in draft.extraction_warnings)


def test_live_harlow_ha26_2766(live_settings, repo):
    d, debug = _extract("Invoice HA26-2766.pdf", "ar@harlowandstern-llp.example", live_settings, repo)
    assert d.invoice_number == "HA26-2766", debug
    assert d.vendor.vendor_id == "V052", debug
    assert d.currency == "CAD", debug
    assert d.ship_to_province == "ON", debug
    assert d.total == D("6452.30"), debug
    assert [(t.code.value, t.amount) for t in d.taxes] == [("HST13", D("742.30"))], debug
    assert len(d.lines) == 2, debug
    assert _no_arithmetic_warnings(d), f"{d.extraction_warnings}\n{debug}"


def test_live_french_laurentian_fa002399(live_settings, repo):
    d, debug = _extract("laurentianlogist_FA002399.pdf", "ar@laurentianlogistics.example", live_settings, repo)
    assert d.total == D("5015.98"), debug
    assert [t.code.value for t in d.taxes] == ["GST5", "QST9975"], debug
    assert _no_arithmetic_warnings(d), f"{d.extraction_warnings}\n{debug}"


# tesseract isn't installed where these were written, so the OCR text is simulated: what tesseract would return
# for each scan, with one digit of the total misread. The real model reads it, the totals don't add up, and the
# pipeline must re-read the image with the vision model and keep that result.
_MISREAD_OCR = {
    "scan_8749.png": ("""Prairie Natural Gas Utility
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
""", "V042", D("4719.28")),
    "scan_8049.png": ("""Cascadia Cartage Ltd.
7313 Rue Sainte-Catherine
Surrey BC V5K 5N1
GST/HST 669086667RT0001
INVOICE
Invoice #: 1624
Date: 2026-10-24
Due date: 2026-11-23
Terms: Net 30
Bill to
Harborline Logistics Inc.
1250 Rene-Levesque O, Bureau 2200, Montreal QC H3B 4W8
Description Qty Unit price Amount
LTL shipment Calgary-Edmonton 1 $1,682.26 $1,682.26
LTL shipment Calgary-Edmonton 1 $1,551.94 $1,551.94
LTL shipment Regina-Ottawa 1 $969.77 $969.77
LTL shipment Calgary-Regina 1 $1,233.47 $1,233.47
Fuel surcharge (7.07%) 1 $384.43 $384.43
Subtotal $5,821.87
GST (5%) $291.09
QST (9.975%) $580.73
Total CAD $6,893.69
Remit to
Inst. 003 Transit 92968 Acct 953389679
""", "V004", D("6693.69")),
}


@pytest.mark.parametrize("file_name", sorted(_MISREAD_OCR))
def test_live_vision_second_opinion_fixes_misread_ocr(live_settings, repo, monkeypatch, file_name):
    from app.extraction.text_layer import TextResult

    text, vendor_id, total = _MISREAD_OCR[file_name]
    monkeypatch.setattr(pipeline.text_layer, "get_text",
                        lambda data, name: TextResult(text, was_ocr=True, method="ocr", pages=[text]))
    out = pipeline.extract_outcome((INCOMING / file_name).read_bytes(), file_name, repo=repo)
    assert out.status == "ok", out.error
    d = out.draft
    debug = f"warnings={d.extraction_warnings}"
    assert d.total == total and d.vendor.vendor_id == vendor_id, debug
    assert any("used that result" in w for w in d.extraction_warnings), debug
    assert _no_arithmetic_warnings(d), debug
