"""
Value helpers for the database layer: money as integer cents, exact decimals as TEXT, UTC timestamps.

Owner: DB team.

Why these exist:
- SQLite has no exact decimal type. SQLAlchemy's `Numeric` on SQLite is stored as REAL (a float), which breaks
  cent-exact tax checks and duplicate matching. So money is stored as INTEGER minor units in `*_cents` columns,
  and rates / quantities / unit prices are stored as TEXT holding the exact decimal string.
- SQLite also has no time zone support: an aware datetime is written without its offset, so 15:00-05:00 would be
  stored as 15:00 (the wrong instant). Timestamps are therefore stored as naive UTC; `to_utc()` does the conversion.

Rules:
- These are plain functions, not custom SQLAlchemy column types, on purpose: columns stay ordinary INTEGER / TEXT,
  so the schema reads the same in `sqlite3 .schema`, in migrations and in any future Postgres port.
- Nothing here ever goes through `float`. Floats are rejected with TypeError.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Two decimal places: the unit every `*_cents` column is counted in.
CENT = Decimal("0.01")


# ---------------------------------------------------------------- validation shared by the helpers

def _require_finite_decimal(value: object, what: str) -> Decimal:
    """Accept only a finite Decimal. Floats, ints-as-money, NaN and infinity are all refused."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{what} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{what} must be a finite number, got {value}")
    return value


# ---------------------------------------------------------------- money <-> integer cents

def to_cents(amount: Decimal) -> int:
    """Decimal money -> integer cents, e.g. Decimal("742.30") -> 74230, Decimal("-15.00") -> -1500.

    The amount is first quantized to 2 places with ROUND_HALF_UP (so 0.005 -> 0.01 and -0.005 -> -0.01),
    then shifted two places left. Raises TypeError for non-Decimal input and ValueError for NaN / infinity
    or a value too large to quantize.
    """
    _require_finite_decimal(amount, "amount")
    try:
        quantized = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:  # more digits than the decimal context can hold
        raise ValueError(f"amount {amount} cannot be quantized to cents") from exc
    # scaleb(2) moves the decimal point exactly (no multiplication rounding); the result is integral.
    return int(quantized.scaleb(2))


def from_cents(cents: int) -> Decimal:
    """Integer cents -> Decimal money with exactly 2 places, e.g. 74230 -> Decimal("742.30")."""
    # bool is a subclass of int; True/False are never valid money.
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError(f"cents must be an int, got {type(cents).__name__}")
    return Decimal(cents).scaleb(-2).quantize(CENT)


# ---------------------------------------------------------------- exact decimals <-> TEXT

def dec_to_text(value: Decimal) -> str:
    """Decimal -> TEXT for rate / quantity / unit price columns, e.g. Decimal("0.09975") -> "0.09975".

    Uses fixed-point formatting, so tiny or huge values never come out in exponent form ("1E-7"), and keeps the
    value's own precision: "0.13" stays "0.13", "1.3700" stays "1.3700". text_to_dec() reverses it exactly.
    """
    _require_finite_decimal(value, "value")
    return format(value, "f")


def text_to_dec(text: str) -> Decimal:
    """TEXT from a rate / quantity / unit price column -> Decimal. ValueError for anything not a finite number."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty string is not a decimal")
    try:
        value = Decimal(stripped)
    except InvalidOperation as exc:  # "1,234", "abc", ...
        raise ValueError(f"not a decimal: {text!r}") from exc
    if not value.is_finite():
        raise ValueError(f"not a finite decimal: {text!r}")
    return value


# ---------------------------------------------------------------- timestamps

def utcnow() -> datetime:
    """Current time as naive UTC, the form every DateTime column stores.

    Use this for created_at / updated_at / acted_at. Business dates ("today") still come from
    get_settings().as_of_date; this is only for recording when something happened.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc(value: datetime) -> datetime:
    """Normalize a datetime for storage: aware -> converted to UTC with tzinfo dropped; naive -> assumed UTC already."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
