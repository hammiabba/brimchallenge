"""History replay: point-in-time judging, counting once, and the approval/payment record checks."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.controls.history import check_approvals, ref_as_of_invoice, replay, replay_bill


@pytest.fixture(scope="module")
def history(ref):
    return replay(ref)


def codes(result):
    return {f.code for f in result.flags}


def kinds(history, kind):
    return sorted(f.invoice_id for f in history.findings if f.kind == kind)


# ---- point in time ----
def test_bank_change_only_counts_after_it_happened(ref):
    # Cascadia's unverified change BC-009 is dated 2026-10-27
    before = ref_as_of_invoice(ref, "AP-00426")  # invoice dated 2026-10-24
    assert "BC-009" not in {c["change_id"] for c in before.bank_changes}
    assert "BANK_CHANGE_UNVERIFIED" not in codes(replay_bill(ref, "AP-00426"))
    # No history invoice is dated after the change, so add a Cascadia bill dated 2026-10-30
    fake = {**ref.invoices["AP-00426"], "invoice_id": "AP-T1", "invoice_date": "2026-10-30",
            "received_date": "2026-10-30"}
    with_fake = replace(ref, invoices={**ref.invoices, "AP-T1": fake})
    assert "BC-009" in {c["change_id"] for c in ref_as_of_invoice(with_fake, "AP-T1").bank_changes}
    assert "BANK_CHANGE_UNVERIFIED" in codes(replay_bill(with_fake, "AP-T1"))


def test_termination_only_counts_after_it_happened(ref):
    # U015 was terminated on 2026-09-15
    early = next(i for i, inv in ref.invoices.items() if inv["invoice_date"] < "2026-09-15")
    late = next(i for i, inv in ref.invoices.items() if inv["invoice_date"] > "2026-09-15")
    assert ref_as_of_invoice(ref, early).users["U015"]["status"] == "active"
    assert ref_as_of_invoice(ref, late).users["U015"]["status"] == "terminated"


def test_bill_only_sees_earlier_invoices(ref):
    assert "AP-00034" not in ref_as_of_invoice(ref, "AP-00023").invoices
    assert "AP-00023" in ref_as_of_invoice(ref, "AP-00034").invoices
    assert ref_as_of_invoice(ref, "AP-00034").as_of == date.fromisoformat(ref.invoices["AP-00034"]["received_date"])


# ---- counted once ----
def test_duplicate_pair_is_reported_once(history):
    assert "DUPLICATE_EXACT" not in codes(history.results["AP-00023"])
    assert "DUPLICATE_EXACT" in codes(history.results["AP-00034"])


def test_same_day_duplicate_pair_is_still_caught_once(history):
    # Redline FA-001655 (AP-00136) and 1655-A (AP-00155) are both dated 2026-04-01
    assert "DUPLICATE_EXACT" not in codes(history.results["AP-00136"])
    assert "DUPLICATE_EXACT" in codes(history.results["AP-00155"])


def test_split_group_is_reported_once(history):
    # Torque AP-00200, AP-00206, AP-00207: only the bill that takes the group over $10k is flagged
    flagged = [i for i in ("AP-00200", "AP-00206", "AP-00207") if "POSSIBLE_SPLIT" in codes(history.results[i])]
    assert flagged == ["AP-00207"]


def test_double_payments_are_grouped_per_bill(history):
    groups = {tuple(g.ids): g for g in history.doubles}
    alpenglow = groups[("AP-00215", "AP-00224", "CT-00324")]  # billed twice and charged to a card
    assert alpenglow.status == "paid three times" and alpenglow.extra_paid_cad == D("5022.72")
    confirmed = [g for g in history.doubles if g.confirmed and g.paid >= 2]
    assert len(confirmed) == 4 and sum(g.extra_paid_cad for g in confirmed) == D("16813.66")
    summit = groups[("AP-00394", "AP-00407")]
    assert summit.status == "set to be paid twice" and summit.at_risk_cad == D("2457.19")


# ---- approval and payment records ----
def test_self_approvals(history):
    assert kinds(history, "self_approval") == ["AP-00092", "AP-00178", "AP-00235"]


def test_po_overrun_without_finance_step(history):
    assert kinds(history, "po_over_balance_no_finance") == ["AP-00159", "AP-00216"]


def test_approved_and_released_by_same_person(ref, history):
    assert kinds(history, "approved_and_released") == []  # none in the history
    approvals = [{"invoice_id": "AP-00001", "step_no": "1", "approver_user_id": "U003",
                  "approver_role": "finance_manager", "action": "approved"}]
    payments = [{"invoice_id": "AP-00001", "payment_id": "PAY-X", "released_by": "U003", "amount_cad": "2520.00"}]
    found = [f for f in check_approvals(ref, approvals, payments, history.results) if f.kind == "approved_and_released"]
    assert [(f.invoice_id, f.evidence["user"]) for f in found] == [("AP-00001", "U003")]


def test_rejected_approval_is_not_an_approval(ref, history):
    approvals = [{"invoice_id": "AP-00001", "step_no": "1", "approver_user_id": "U003",
                  "approver_role": "finance_manager", "action": "rejected"}]
    payments = [{"invoice_id": "AP-00001", "payment_id": "PAY-X", "released_by": "U003", "amount_cad": "2520.00"}]
    assert check_approvals(ref, approvals, payments, history.results) == []


def test_paid_after_unverified_bank_change(history):
    paid = [f for f in history.findings if f.kind == "paid_after_unverified_bank_change"]
    assert [(f.invoice_id, f.evidence["days_after"], f.amount_cad) for f in paid] == [("AP-00388", 2, D("3290.01"))]
    assert kinds(history, "due_after_unverified_bank_change") == ["AP-00426"]
