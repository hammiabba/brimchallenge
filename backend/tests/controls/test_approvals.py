from decimal import Decimal as D

from app.controls import can_approve, can_release, route
from app.shared.schemas import Flag, PermissionDecision, Severity


def chain(steps):
    return [s.user_id for s in steps]


# ---- amount tiers (P01-P04) ----
def test_small_bill_goes_to_dept_manager(ref, make_bill):
    steps = route(make_bill(amount="5000.00"), ref)
    assert chain(steps) == ["U007"] and steps[0].policy_ids == ["P01"]
    assert steps[0].reason.startswith("Total $5,650.00 ≤ $10,000")


def test_over_10k_adds_finance_manager(ref, make_bill):
    assert chain(route(make_bill(amount="20000.00"), ref)) == ["U007", "U003"]


def test_over_50k_adds_controller(ref, make_bill):
    assert chain(route(make_bill(amount="60000.00"), ref)) == ["U007", "U003", "U002"]


def test_over_250k_adds_cfo(ref, make_bill):
    assert chain(route(make_bill(amount="300000.00"), ref)) == ["U007", "U003", "U002", "U001"]


# ---- extra steps (P05, P06) ----
def test_legal_vendor_adds_finance(ref, make_bill):
    steps = route(make_bill(vendor_id="V026", amount="3000.00", description="Legal services"), ref)
    assert chain(steps) == ["U007", "U003"] and "P06" in steps[1].policy_ids


def test_pending_vendor_adds_finance(ref, make_bill):
    steps = route(make_bill(vendor_id="V055", amount="3000.00"), ref)
    assert chain(steps) == ["U007", "U003"] and "P05" in steps[1].policy_ids


# ---- self-approval (P07) ----
def test_manager_cannot_approve_own_request(ref, make_bill):
    # Dev Malhotra (U007) is Operations manager and requested the bill -> escalates to his manager U001
    steps = route(make_bill(requester="U007"), ref)
    assert chain(steps) == ["U001"] and "P07" in steps[0].policy_ids and steps[0].escalated_from == "U007"


def test_finance_manager_requests_big_bill(ref, make_bill):
    # U003 requests a $20k Finance bill: dept manager U002, then finance manager = requester -> escalate.
    # U003's manager is U002, who already has step 1, so it goes up again to U001.
    steps = route(make_bill(amount="20000.00", requester="U003", dept="D04"), ref)
    assert chain(steps) == ["U002", "U001"] and steps[1].escalated_from == "U003"


# ---- leave and delegation (P08) ----
def test_on_leave_goes_to_delegate(ref, make_bill):
    # Facilities manager U012 is on leave, delegate is U003
    steps = route(make_bill(dept="D07", requester="U037"), ref)
    assert chain(steps) == ["U003"] and steps[0].delegated_from == "U012" and "P08" in steps[0].policy_ids


def test_delegate_cannot_fill_two_steps(ref, make_bill):
    # $20k Facilities bill: step 1 is U003 (as U012's delegate), step 2 is finance manager = U003 again.
    # One person can't sign twice, so step 2 goes to U003's manager, the controller U002.
    steps = route(make_bill(amount="20000.00", dept="D07", requester="U037"), ref)
    assert chain(steps) == ["U003", "U002"]


def test_delegate_escalated_away_is_not_marked_as_delegate(ref, make_bill):
    # U012's delegate U003 requested the bill, so it goes to U002, who is NOT acting for U012.
    steps = route(make_bill(dept="D07", requester="U003"), ref)
    assert chain(steps) == ["U002"] and steps[0].delegated_from is None and steps[0].escalated_from == "U003"


def test_every_step_is_a_different_person(ref, make_bill):
    for amount in ["500", "15000", "75000", "400000"]:
        for dept, req in [("D01", "U013"), ("D07", "U037"), ("D04", "U003"), ("D08", "U040")]:
            c = chain(route(make_bill(amount=amount, dept=dept, requester=req), ref))
            people = [u for u in c if u != "UNASSIGNED"]
            # In a 40-person company a huge bill can run out of eligible people (e.g. the CFO already
            # signed step 2). Then the step stays UNASSIGNED for a manual decision; nobody signs twice.
            assert len(people) == len(set(people)), (amount, dept, c)
            assert req not in c


# ---- can_approve ----
def test_requester_cannot_approve(ref, make_bill):
    bill = make_bill(requester="U007")
    decision = can_approve("U007", route(bill, ref)[0], bill, ref)
    assert isinstance(decision, PermissionDecision) and not decision.allowed and "P07" in decision.reason


def test_assigned_approver_can_approve(ref, make_bill):
    bill = make_bill()
    assert can_approve("U007", route(bill, ref)[0], bill, ref).allowed


def test_delegate_approval_says_so(ref, make_bill):
    bill = make_bill(dept="D07", requester="U037")
    decision = can_approve("U003", route(bill, ref)[0], bill, ref)
    assert decision.allowed and "U012" in decision.reason and "P08" in decision.reason


# ---- can_release (P09-P11) ----
def test_finance_manager_releases_under_100k(ref):
    assert can_release("U003", D("50000"), {"U007"}, [], True, ref).allowed


def test_finance_manager_cannot_release_over_100k(ref):
    assert not can_release("U003", D("150000"), {"U007"}, [], True, ref).allowed


def test_controller_releases_over_100k(ref):
    assert can_release("U002", D("150000"), {"U007", "U003"}, [], True, ref).allowed


def test_approver_cannot_release(ref):
    decision = can_release("U003", D("20000"), {"U007", "U003"}, [], True, ref)
    assert not decision.allowed and "P11" in decision.reason


def test_ap_clerk_cannot_release(ref):
    assert not can_release("U004", D("100"), {"U007"}, [], True, ref).allowed


def test_blocking_flag_holds_payment(ref):
    flags = [Flag(code="BANK_CHANGE_UNVERIFIED", severity=Severity.BLOCK, message="x")]
    decision = can_release("U003", D("1000"), {"U007"}, flags, True, ref)
    assert not decision.allowed and "BANK_CHANGE_UNVERIFIED" in decision.reason


def test_not_fully_approved(ref):
    assert not can_release("U003", D("1000"), {"U007"}, [], False, ref).allowed
