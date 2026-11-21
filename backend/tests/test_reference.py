from datetime import date
from decimal import Decimal


def test_ids_keep_leading_zeros(repo):
    v001 = repo.vendor("V001")
    assert v001["bank_institution"] == "004"
    assert v001["legal_name"] == "Polar Freight Lines Ltd."


def test_unknown_vendor_is_none(repo):
    assert repo.vendor("V999") is None


def test_fx_rate_exact_and_closest_earlier(repo):
    assert repo.fx_rate(date(2026, 1, 1)) == Decimal("1.3709")
    # Before the first rate there is nothing to fall back to.
    assert repo.fx_rate(date(2025, 12, 31)) is None
    # Any date inside the range resolves to some rate (weekends fall back).
    assert repo.fx_rate(date(2026, 10, 25)) is not None
