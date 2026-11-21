"""Person A's pipeline output goes straight into Person B's run_controls (no fixtures: hand-written model output)."""
from app.controls import run_controls
from app.extraction import pipeline
from tests.extraction.test_pipeline import HARLOW, FakeClient, raw_invoice


def _codes(result) -> set[str]:
    return {f.code for f in result.flags}


def test_harlow_lookalike_is_flagged(repo):
    bill = pipeline.extract(HARLOW.read_bytes(), HARLOW.name, email_id="EM-026",
                            sender="ar@harlowandstern-llp.example", repo=repo, client=FakeClient(raw_invoice()))
    assert bill.vendor.vendor_id == "V052"
    assert "VENDOR_LOOKALIKE" in _codes(run_controls(bill, [bill]))


def test_extraction_arithmetic_error_reaches_controls(repo):
    bill = pipeline.extract(HARLOW.read_bytes(), HARLOW.name, repo=repo,
                            client=FakeClient(raw_invoice(total="$6,552.30")))
    assert any("total says 6552.30" in w for w in bill.extraction_warnings)
    assert "TOTAL_MISMATCH" in _codes(run_controls(bill))


def test_unknown_vendor_reaches_controls_as_not_found(repo):
    raw = raw_invoice(vendor_name="Blue Heron Couriers", vendor_gst_number="999999999RT0001",
                      bank_institution=None, bank_transit=None, bank_account=None)
    bill = pipeline.extract(HARLOW.read_bytes(), "Invoice 4443.pdf", sender="billing@blueheron.example", repo=repo,
                            client=FakeClient(raw))
    assert bill.vendor.vendor_id is None
    assert "VENDOR_NOT_FOUND" in _codes(run_controls(bill))
