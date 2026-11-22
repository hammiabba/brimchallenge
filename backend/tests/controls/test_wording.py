"""The plain-words helpers the controls write messages with (controls/wording.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.controls.wording import account_change, account_ending, human_date, money_text


def test_an_account_is_shown_by_its_last_four_digits_only():
    assert account_ending("9679") == "ending 9679"
    assert account_ending(None) == "not on file"
    assert account_change("7504", "9679") == "ending 7504 → ending 9679"


def test_dates_and_money_read_as_the_app_shows_them():
    assert human_date("2026-11-02") == "Nov 2, 2026"
    assert human_date(date(2026, 1, 9)) == "Jan 9, 2026"
    assert money_text(Decimal("-5")) == "-$5.00"
    assert money_text(Decimal("1234.5"), "USD") == "US$1,234.50"
