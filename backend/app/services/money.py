"""Money in and out of the API. Wraps app.db.types so there is exactly one conversion path, and no float ever
appears: amounts arrive as strings like "742.30", are stored as integer cents and leave as two-decimal strings."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.api.errors import ApiError
from app.db.types import from_cents, to_cents


def parse_money(text: str, field: str = "amount") -> Decimal:
    """'742.30' -> Decimal('742.30'). The request models already restrict the format; this is the last check."""
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError) as exc:
        raise ApiError(422, "request.invalid_money", f"{field} must be an amount like '742.30'.") from exc
    if not value.is_finite() or value.as_tuple().exponent < -2:
        raise ApiError(422, "request.invalid_money", f"{field} must have at most two decimals.")
    return value


def money_to_cents(text: str, field: str = "amount") -> int:
    return to_cents(parse_money(text, field))


def cents(value: int | None) -> Decimal | None:
    """Integer cents from the database -> Decimal with two places (serialized as "742.30" by the Money type)."""
    return None if value is None else from_cents(value)
