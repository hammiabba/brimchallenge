from datetime import date

from app.controls import bill_from_history, can_release, run_controls
from app.shared.schemas import ControlsResult


def codes(result):
    return {f.code for f in result.flags}


def test_returns_schema_result(ref, make_bill):
    result = run_controls(make_bill(), ref=ref)
    assert isinstance(result, ControlsResult)
    assert result.flags == [] and result.duplicates == [] and result.can_auto_proceed
    assert [s.user_id for s in result.route] == ["U007"] and result.recommendation is None


def test_duplicate_holds_payment(ref):
    # AP-00034 is a second copy of AP-00023. Before, nothing stopped its release.
    result = run_controls(bill_from_history(ref, "AP-00034"), ref=ref)
    assert "DUPLICATE_EXACT" in codes(result) and not result.can_auto_proceed
    assert result.recommendation.startswith("Hold: Possible duplicate of AP-00023")
    decision = can_release("U003", bill_from_history(ref, "AP-00034").total, {"U007"}, result.flags, True, ref)
    assert not decision.allowed and "DUPLICATE_EXACT" in decision.reason


def test_card_payment_holds_payment(ref):
    result = run_controls(bill_from_history(ref, "AP-00015"), ref=ref)
    assert "ALREADY_PAID_BY_CARD" in codes(result) and not result.can_auto_proceed


def test_duplicate_inside_the_batch(ref, make_bill):
    # Two different PDFs, same vendor and invoice number, arriving in the same batch
    a = make_bill(number="NEW-777", file_hash="sha256:aaa")
    b = make_bill(number="NEW-777", file_hash="sha256:bbb")
    batch = [a, b]
    result = run_controls(a, batch, ref=ref)
    assert [(m.kind, m.matched_invoice_id) for m in result.duplicates] == [("exact", "sha256:bbb")]
    assert "DUPLICATE_EXACT" in codes(result)
    assert run_controls(a, [a], ref=ref).can_auto_proceed  # alone in its batch: clean


def test_same_file_submitted_twice(ref, make_bill):
    # Same PDF forwarded twice: two bills with the same file_hash still match each other
    a = make_bill(number="NEW-778", file_hash="sha256:same")
    b = make_bill(number="NEW-778", file_hash="sha256:same")
    assert "DUPLICATE_EXACT" in codes(run_controls(a, [a, b], ref=ref))


def test_split_inside_the_batch_is_routed_as_one_bill(ref, make_bill):
    # Prairie Express (no contract, no PO rule): three $4,000 bills in two days = $13,560 with HST.
    # (Oct 30-31: nothing from V003 in history within 7 days.)
    bills = [make_bill(vendor_id="V003", amount="4000.00", number=f"PX-{n}", file_hash=f"px{n}",
                       when=date(2026, 10, 30 + n % 2)) for n in range(3)]
    result = run_controls(bills[0], bills, ref=ref)
    split = next(f for f in result.flags if f.code == "POSSIBLE_SPLIT")
    assert split.evidence["combined_cad"] == "13560.00"
    assert [s.role for s in result.route] == ["dept_manager", "finance_manager"]  # P02, not P01
