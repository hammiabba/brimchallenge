from datetime import date

from app.extraction import pipeline
from app.extraction.recheck import recheck
from tests.extraction.test_pipeline import HARLOW, FakeClient, raw_invoice


def _draft(repo, **raw):
    return pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo, client=FakeClient(raw_invoice(**raw)))


def test_confirmed_date_gets_full_confidence_and_loses_its_warning(repo):
    d = _draft(repo, invoice_date="03/04/2026", due_date=None, payment_terms=None)
    assert d.field_confidence["invoice_date"] <= 0.5
    edited = d.model_copy(update={"invoice_date": date(2026, 3, 4)})
    conf, warnings = recheck(edited, {"invoice_date"})
    assert conf["invoice_date"] == 1.0
    assert not any(w.startswith("invoice date ") for w in warnings)


def test_arithmetic_warnings_are_recomputed_not_duplicated(repo):
    d = _draft(repo, total="$6,500.00")
    [old] = [w for w in d.extraction_warnings if "total says" in w]
    conf, warnings = recheck(d, set())
    assert warnings.count(old) == 1
    assert conf == d.field_confidence


def test_unconfirmed_warnings_are_kept(repo):
    d = _draft(repo, po_field_present=True, po_number="")
    _, warnings = recheck(d, {"invoice_date"})
    assert any(w.startswith("PO field ") for w in warnings)
    _, warnings = recheck(d, {"po_number"})
    assert not any(w.startswith("PO field ") for w in warnings)
