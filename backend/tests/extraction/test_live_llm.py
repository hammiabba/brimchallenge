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
