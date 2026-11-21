"""Bank account masking. Full numbers only for ap_clerk, finance_manager and controller_admin; every other role
sees the last 4 digits. Every serializer that can carry a bank number goes through this module, including the
frozen extraction snapshot (bills.draft_json), which holds the account number printed on the invoice."""
from __future__ import annotations

import copy
from typing import Any

from app.auth.roles import FULL_BANK_DETAILS


def can_see_full_bank(role: str) -> bool:
    return role in FULL_BANK_DETAILS


def mask_number(value: str | None) -> str | None:
    if value is None:
        return None
    digits = str(value)
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def account_for(role: str, value: str | None) -> str | None:
    return value if can_see_full_bank(role) else mask_number(value)


def mask_draft(role: str, draft: dict[str, Any] | None) -> dict[str, Any] | None:
    """A copy of a DraftBill JSON with vendor.bank.account masked for roles without full access."""
    if draft is None or can_see_full_bank(role):
        return draft
    masked = copy.deepcopy(draft)
    bank = (masked.get("vendor") or {}).get("bank")
    if isinstance(bank, dict) and bank.get("account"):
        bank["account"] = mask_number(bank["account"])
    return masked
