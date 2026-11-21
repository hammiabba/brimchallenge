"""Unseen layouts: one invoice rendered five ways (tests/fixtures/synthetic/make_layouts.py) must extract the
same core fields. Offline on the recorded model output for each layout; `RUN_LIVE_LLM=1 pytest -m live` runs the
same assertions against the real model.

Re-record after a prompt change:
    python tests/fixtures/synthetic/make_layouts.py /tmp/synth
    (extract each file once with the real model, then)
    python scripts/record_fixtures.py --dir /tmp/synth --out tests/fixtures/synthetic/raw
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import get_settings
from app.extraction import pipeline
from tests.conftest import FixtureClient
from tests.fixtures.synthetic.make_layouts import EXPECTED, LAYOUTS, file_name, render

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "raw"
_API_KEY = get_settings().anthropic_api_key  # read at import, before conftest blanks it per test


def core(d) -> dict:
    return dict(vendor_id=d.vendor.vendor_id, invoice_number=d.invoice_number,
                invoice_date=d.invoice_date.isoformat(), due_date=d.due_date.isoformat() if d.due_date else None,
                currency=d.currency, subtotal=d.subtotal, taxes=sorted((t.code.value, t.amount) for t in d.taxes),
                total=d.total, province=d.ship_to_province, lines=len(d.lines))


def check(out, layout: str):
    assert out.status == "ok", out.error
    want = dict(EXPECTED[layout], taxes=sorted(EXPECTED[layout]["taxes"]))
    assert core(out.draft) == want
    # Every layout adds up, so the only warning allowed is the French one's: it prints "$" and never says which
    # dollar, so CAD is an assumption (correctly, from the Canadian vendor) and the clerk is told.
    allowed = ["currency not printed on the totals line; assumed CAD"] if layout == "french" else []
    assert out.draft.extraction_warnings == allowed
    assert min(v for k, v in out.draft.field_confidence.items() if not (allowed and k == "currency")) >= 0.9


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_layout_renders_with_its_values_in_the_text_layer(layout):
    from app.extraction import text_layer

    tr = text_layer.get_text(render(layout), file_name(layout))
    assert tr.method == "pdfplumber"
    e = EXPECTED[layout]
    assert e["invoice_number"] in tr.text
    assert f"{e['total']:,.2f}".replace(",", " ").replace(".", ",") in tr.text or f"{e['total']:,.2f}" in tr.text


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_layout_extracts_the_same_core_fields(layout, repo):
    out = pipeline.extract_outcome(render(layout), file_name(layout), repo=repo, client=FixtureClient(RECORDED))
    check(out, layout)


def test_the_four_cad_layouts_agree_with_each_other(repo):
    client = FixtureClient(RECORDED)
    cores = {name: core(pipeline.extract_outcome(render(name), file_name(name), repo=repo, client=client).draft)
             for name in LAYOUTS if name != "usd"}
    assert len({repr(c) for c in cores.values()}) == 1, cores


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1" or not _API_KEY,
                    reason="set RUN_LIVE_LLM=1 and ANTHROPIC_API_KEY to run live LLM tests")
@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_live_layout_extracts_the_same_core_fields(layout, repo, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", _API_KEY)  # cache_dir is already a temp dir
    check(pipeline.extract_outcome(render(layout), file_name(layout), repo=repo), layout)
