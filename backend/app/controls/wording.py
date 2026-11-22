"""Plain words for the text the controls write into flags, reasons and notes: dates as the app shows them
("Nov 2, 2026", never "2026-11-02"), money with its currency, and words for codes (payment and bill statuses,
bank-change request channels, roles, flag codes). Pure functions; nothing here reads the database.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from .flag_help import FLAG_HELP

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def human_date(value: date | datetime | str | None) -> str:
    """A date as the app shows it: "2026-11-02" (or a date or datetime) -> "Nov 2, 2026". An empty value gives "",
    and text that isn't an ISO date comes back unchanged."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"


def money_text(amount: Decimal, currency: str = "CAD") -> str:
    """"$1,234.50" for CAD, "US$1,234.50" for USD (the app's prefixes), with the minus sign in front: "-$5.00"."""
    prefix = "US$" if currency == "USD" else "$" if currency == "CAD" else f"{currency} "
    sign = "-" if amount < 0 else ""
    return f"{sign}{prefix}{abs(amount):,.2f}"


def account_ending(last4: str | None) -> str:
    """A bank account the one way the app shows it, inside a sentence: "ending 9679" (the screens write "Ending 9679"
    at the start of a field). Never the full number, and never "…9679"."""
    return f"ending {last4}" if last4 else "not on file"


def account_change(old_last4: str | None, new_last4: str | None) -> str:
    """A bank-account change in one phrase: "ending 7504 → ending 9679"."""
    return f"{account_ending(old_last4)} → {account_ending(new_last4)}"


# Payment and bill statuses, as the app's badges word them (lower case, to sit inside a sentence).
_STATUSES = {
    "needs_review": "needs review",
    "on_hold": "on hold",
    "pending_approval": "pending approval",
    "credit_open": "credit open",
}


def status_label(code: str) -> str:
    """A payment or bill status inside a sentence: "outstanding", "needs review", "pending approval"."""
    return _STATUSES.get(code, code.replace("_", " "))


# How a bank-change request came in, as a phrase after "by": "by email request".
_CHANNELS = {
    "email_request": "email request",
    "vendor_portal": "the vendor portal",
    "phone_callback_verified": "phone, confirmed by callback",
}


def channel_phrase(code: str) -> str:
    """"email_request" -> "email request", for "... changed by email request"."""
    return _CHANNELS.get(code, code.replace("_", " "))


# Roles as a group, to start a sentence: "AP clerks can't approve bills."
_ROLE_GROUPS = {
    "employee": "Employees",
    "ap_clerk": "AP clerks",
    "approver": "Approvers",
    "finance_manager": "Finance managers",
    "controller_admin": "Controllers",
    "auditor": "Auditors",
}


def role_group(code: str) -> str:
    """"ap_clerk" -> "AP clerks"; an unknown role keeps its code in words."""
    return _ROLE_GROUPS.get(code, code.replace("_", " ").capitalize() + "s")


def flag_title(code: str) -> str:
    """A flag code's short title from flag help ("Duplicate invoice"), or the code in words for an unknown one."""
    found = FLAG_HELP.get(code)
    return found.title if found else code.replace("_", " ").capitalize()


def flag_titles(codes: Iterable[str]) -> str:
    """Several flag titles in one phrase, each once, in order: "PO closed or wrong vendor; Duplicate invoice"."""
    seen: list[str] = []
    for code in codes:
        title = flag_title(code)
        if title not in seen:
            seen.append(title)
    return "; ".join(seen)
