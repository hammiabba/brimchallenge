"""
Turn strings as printed on an invoice into typed values.

Owner: Person A.
Inputs: raw strings from the LLM ("4 362,67 $", "Oct 27, 2026", "TPS (5 %)").
Outputs: Decimal, date, TaxCode, province codes, and OCR-corrected IDs.

Every function is pure and layout-agnostic: it knows about number/date/tax
*conventions* (EN and FR Canadian), never about a particular vendor's template.
To change safely: add a case to tests/extraction/test_normalize.py first.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.shared.schemas import TaxCode

# ---------------------------------------------------------------- money

_SPACES = re.compile(r"[\s   ']")  # incl. NBSP, narrow NBSP, thin space, Swiss apostrophe
_CURRENCY = re.compile(r"(CAD|USD|EUR|CA\$|US\$|C\$|\$|€|£)", re.IGNORECASE)
_MINUS_CHARS = "-−–"  # hyphen, unicode minus, en dash


def parse_money(raw: str | int | float | Decimal | None) -> Decimal | None:
    """Parse a printed amount into Decimal. Returns None if it is not a number.

    Handles "$1,234.56", "-$1,042.76", "($1,042.76)", "1,042.76-", "4 362,67 $",
    "1.234,56", "USD 1,950.00". A comma followed by exactly 1-2 digits at the end is a
    decimal comma; otherwise commas are thousands separators.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int | float):
        return Decimal(str(raw))
    s = raw.strip()
    if not s:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = _CURRENCY.sub("", s)
    s = _SPACES.sub("", s)
    if s and s[0] in _MINUS_CHARS:
        negative, s = True, s[1:]
    if s and s[-1] in _MINUS_CHARS:
        negative, s = True, s[:-1]
    s = s.lstrip("+")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None

    if "," in s and "." in s:
        # Whichever separator comes last is the decimal mark.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")  # "1.234.567" = thousands dots

    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_rate(raw: str | None) -> Decimal | None:
    """'13%', '9,975 %', '0.05' or '5' → fraction (0.13, 0.09975, 0.05, 0.05)."""
    if raw is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(raw))
    if not m:
        return None
    value = Decimal(m.group().replace(",", "."))
    # Anything above 1 must be a percentage; tax rates are never 100%+.
    return value / 100 if value > 1 or "%" in str(raw) else value


# ---------------------------------------------------------------- dates

_MONTHS = {
    # English
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # French
    "janv": 1, "janvier": 1, "févr": 2, "fevr": 2, "février": 2, "fevrier": 2, "mars": 3, "avr": 4,
    "avril": 4, "mai": 5, "juin": 6, "juil": 7, "juillet": 7, "août": 8, "aout": 8, "déc": 12,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}


def parse_date(raw: str | None) -> date | None:
    """Parse ISO, d/m/y, y/m/d, 'Oct 27, 2026', '27 octobre 2026', '1er novembre 2026'.

    Slash dates with both parts ≤ 12 are read day-first (the Canadian/French
    convention). That case is ambiguous, so callers should lower confidence.
    """
    if not raw:
        return None
    s = raw.strip().lower().replace(",", " ").replace(".", " ")
    s = re.sub(r"\b(\d{1,2})(er|st|nd|rd|th)\b", r"\1", s)

    if m := re.search(r"\b(\d{4})[-/ ](\d{1,2})[-/ ](\d{1,2})\b", s):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", s):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            return _safe_date(y, b, a)
        if b > 12:
            return _safe_date(y, a, b)
        return _safe_date(y, b, a)

    words = re.findall(r"[a-zéû]+|\d+", s)
    month = next((_MONTHS[w] for w in words if w in _MONTHS), None)
    nums = [int(w) for w in words if w.isdigit()]
    year = next((n for n in nums if n > 1900), None)
    day = next((n for n in nums if 1 <= n <= 31), None)
    if month and year and day:
        return _safe_date(year, month, day)
    return None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


# ---------------------------------------------------------------- province

PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
_PROVINCE_NAMES = {
    "alberta": "AB", "british columbia": "BC", "colombie-britannique": "BC", "manitoba": "MB",
    "new brunswick": "NB", "nouveau-brunswick": "NB", "newfoundland": "NL", "terre-neuve": "NL",
    "nova scotia": "NS", "nouvelle-écosse": "NS", "ontario": "ON", "prince edward island": "PE",
    "île-du-prince-édouard": "PE", "quebec": "QC", "québec": "QC", "saskatchewan": "SK",
    "yukon": "YT", "nunavut": "NU", "northwest territories": "NT",
}
_POSTAL_FIRST_LETTER = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC", "J": "QC", "K": "ON", "L": "ON",
    "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK", "T": "AB", "V": "BC", "Y": "YT",
}
_POSTAL = r"[A-Z]\d[A-Z]\s?\d[A-Z]\d"


def province_from_address(address: str | None) -> str | None:
    """Best-effort province code from a Canadian address; None if it isn't Canadian.

    Order: code right before a postal code → any standalone code → full name →
    postal-code first letter. The explicit code wins over the postal code because
    printed postal codes are sometimes wrong while the province is stated.
    """
    if not address:
        return None
    codes = "|".join(sorted(PROVINCES))
    if m := re.findall(rf"\b({codes})\b,?\s+{_POSTAL}\b", address):
        return m[-1]
    if m := re.findall(rf"\b({codes})\b", address):
        return m[-1]
    lowered = address.lower()
    for name, code in _PROVINCE_NAMES.items():
        if name in lowered:
            return code
    if m := re.findall(rf"\b({_POSTAL})\b", address):
        return _POSTAL_FIRST_LETTER.get(m[-1][0])
    return None


def looks_foreign(address: str | None) -> bool:
    """True when an address has no Canadian province but has a US state + ZIP or a country name."""
    if not address or province_from_address(address):
        return False
    return bool(
        re.search(r"\b[A-Z]{2}\s+\d{5}(-\d{4})?\b", address)
        or re.search(r"\b(USA|United States|U\.S\.A\.|UK|United Kingdom)\b", address, re.IGNORECASE)
    )


# ---------------------------------------------------------------- tax labels

_RATE_TO_CODE = {
    Decimal("0.13"): TaxCode.HST13,
    Decimal("0.05"): TaxCode.GST5,
    Decimal("0.09975"): TaxCode.QST9975,
    Decimal("0.07"): TaxCode.PST7_BC,
}


def map_tax_label(label: str | None, rate: Decimal | None = None) -> TaxCode | None:
    """Map a printed tax label (EN or FR) + rate to a TaxCode.

    'GST/HST' and 'TPS/TVH' are combined labels that tell us nothing on their own,
    so the rate decides. Returns None when neither label nor rate is recognisable.
    """
    lab = (label or "").upper()
    if re.search(r"EXEMPT|EXON[EÉ]R", lab):
        return TaxCode.EXEMPT
    if re.search(r"\b(QST|TVQ)\b", lab):
        return TaxCode.QST9975
    if re.search(r"\b(PST|TVP|RST)\b", lab):
        return TaxCode.PST7_BC
    has_gst = bool(re.search(r"\b(GST|TPS)\b", lab))
    has_hst = bool(re.search(r"\b(HST|TVH)\b", lab))
    if has_gst == has_hst:  # both (combined label) or neither
        return _RATE_TO_CODE.get(rate) if rate is not None else None
    return TaxCode.HST13 if has_hst else TaxCode.GST5


STANDARD_RATES = {code: rate for rate, code in _RATE_TO_CODE.items()}
STANDARD_RATES[TaxCode.EXEMPT] = Decimal("0")
STANDARD_RATES[TaxCode.FOREIGN] = Decimal("0")


# ---------------------------------------------------------------- OCR fixes for structured IDs
# Only IDs with a known shape are corrected: the shape tells us which characters must be
# digits, so the fix is checkable. Free text is never "corrected".

_DIGIT_LOOKALIKES = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "|": "1", "!": "1", "i": "1",
    "Z": "2", "S": "5", "s": "5", "$": "5", "B": "8", "G": "6", "g": "9",
})


def _digits(s: str) -> str:
    return s.translate(_DIGIT_LOOKALIKES)


def fix_tax_number(raw: str | None, kind: str = "gst") -> tuple[str | None, str | None]:
    """Normalise a GST/HST (`123456789RT0001`) or QST (`1234567890TQ0001`) number.

    Returns (value, warning). The warning is set only when characters were changed.
    If the result still doesn't fit the pattern, it's returned cleaned but unfixed.
    """
    if not raw:
        return None, None
    cleaned = re.sub(r"[\s\-]", "", raw).upper()
    head_len, marker = (9, "RT") if kind == "gst" else (10, "TQ")
    m = re.fullmatch(rf"(.{{{head_len}}})({marker})(.{{4}})", cleaned)
    if not m:
        return cleaned, None
    fixed = _digits(m[1]) + marker + _digits(m[3])
    if not re.fullmatch(rf"\d{{{head_len}}}{marker}\d{{4}}", fixed):
        return cleaned, None
    if fixed != cleaned:
        return fixed, f"OCR fix on {kind.upper()} number: '{raw}' read as '{fixed}'"
    return fixed, None


def fix_digit_field(raw: str | None, field: str, length: int | None = None) -> tuple[str | None, str | None]:
    """Bank institution (3), transit (5) and account (7-12) are digits only.

    Maps lookalike characters to digits ('$5541' → '55541'). Returns (value, warning).
    """
    if not raw:
        return None, None
    cleaned = re.sub(r"[\s\-]", "", raw)
    fixed = _digits(cleaned)
    if not fixed.isdigit() or (length and len(fixed) != length):
        return cleaned, None
    if fixed != cleaned:
        return fixed, f"OCR fix on bank {field}: '{raw}' read as '{fixed}'"
    return fixed, None


# ---------------------------------------------------------------- language

# "virement" is deliberately absent: English invoices in this dataset print "EFT / virement bancaire".
_FR_MARKERS = ("facture", "échéance", "echeance", "sous-total", "tps", "tvq", "montant", "qté",
               "merci", "facturer à", "note de crédit", "prix unitaire", "date d'échéance")


def detect_language(text: str) -> str:
    lowered = text.lower()
    hits = sum(1 for w in _FR_MARKERS if w in lowered)
    return "fr" if hits >= 3 else "en"
