"""A bill's contract: an invoice rarely prints one, so a new bill gets its vendor's contract (the one the contract
checks use), and a vendor change carries the contract along. The bill screen then shows the contract its flags cite."""
from __future__ import annotations

from tests.api.factories import app_bill


def detail(client, bill_id: str) -> dict:
    r = client.get(f"/bills/{bill_id}")
    assert r.status_code == 200, r.text
    return r.json()


def patch(client, bill: dict, **changes) -> dict:
    r = client.patch(f"/bills/{bill['bill_id']}", json={"row_version": bill["row_version"], **changes})
    assert r.status_code == 200, r.text
    return r.json()


def cited_contracts(bill: dict) -> set[str]:
    """The contract ids the bill's latest flags cite in their evidence."""
    return {f["evidence"]["contract"] for f in bill["latest_run"]["flags"] if "contract" in (f["evidence"] or {})}


def test_the_bill_shows_the_contract_its_flags_cite(fresh_engine, act_as):
    # V023's fixed fee is $890.00/month (C009): a $1,180.00 invoice is flagged against C009.
    bill = detail(act_as("U004"), app_bill(fresh_engine, vendor_id="V023", amount="1180.00"))
    assert bill["contract_id"] == "C009"
    assert cited_contracts(bill) == {"C009"}


def test_a_vendor_change_carries_the_contract_along(fresh_engine, act_as):
    clerk = act_as("U004")
    bill = detail(clerk, app_bill(fresh_engine, vendor_id="V023", amount="1180.00"))
    moved = patch(clerk, bill, vendor_id="V044")
    assert moved["contract_id"] == "C025"  # V044's contract
    assert cited_contracts(moved) <= {"C025"}
    cleared = patch(clerk, moved, vendor_id="V052")
    assert cleared["contract_id"] is None  # V052 has no contract
    assert cited_contracts(cleared) == set()


def test_a_contract_set_in_the_same_edit_wins(fresh_engine, act_as):
    clerk = act_as("U004")
    bill = detail(clerk, app_bill(fresh_engine, vendor_id="V023", amount="1180.00"))
    assert patch(clerk, bill, vendor_id="V044", contract_id="C009")["contract_id"] == "C009"


def test_a_contract_of_another_vendor_stays_when_the_vendor_changes(fresh_engine, act_as):
    clerk = act_as("U004")
    bill = detail(clerk, app_bill(fresh_engine, vendor_id="V023", amount="1180.00"))
    set_on_purpose = patch(clerk, bill, contract_id="C018")  # V001's contract, on a V023 bill
    assert patch(clerk, set_on_purpose, vendor_id="V044")["contract_id"] == "C018"
