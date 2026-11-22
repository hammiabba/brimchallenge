"""Early-payment discounts: parse vendor terms, suggest the best pay date, count what history saved or missed.

suggest_pay_dates(ref, payments) -> list[PaySuggestion]   bills that are approved or scheduled (by default)
discount_history(ref, payments)  -> DiscountHistory       discounts taken and missed on past payments

Inputs: RefData (vendors, invoices) and payment rows shaped like payments.csv, so the CSV loader and the database
adapter (app/services/early_pay.py) feed it the same way. Deterministic, no database, no network.

How the dataset applies "2/10 net 30" (checked on every payment to the three vendors with that term):
- the discount is 2% of the pre-tax subtotal (taxes are never discounted), in the bill's currency;
- the 10 days count from the invoice date: every discount taken was paid on day 9, the day before the deadline,
  so the money arrives in time (an EFT posts the next day; see controls.reconciliation);
- net 30 is due 30 days after the invoice date, which is the invoice's own due date.

Best pay date:
- discount still open: pay on the last day that still earns it (deadline minus the method's lead days, never
  before today). That keeps the cash as long as possible and still saves the discount;
- otherwise: pay on the due date. Paying earlier saves nothing; if it's already past, pay today.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .refdata import RefData, d, money
from .wording import human_date

CENT = Decimal("0.01")
# Days before the deadline a payment must go out to arrive in time. EFT: posts the next day (every discount in the
# history was paid on day 9 of 10). Cheque: mailing. Card: same day.
LEAD_DAYS = {"EFT": 1, "CHEQUE": 3, "CARD": 0}
OPEN_STATUSES = ("approved", "scheduled")
PENDING_STATUSES = ("needs_review", "on_hold", "pending_approval")  # not approved yet: shown only when asked

# "2/10 net 30", "2/10 n/30", "2/10, net 30", "2% 10 net 30", "1.5/15 net 45", "2%/10 Net30"
_DISCOUNT = re.compile(r"^\s*(?P<pct>\d+(?:\.\d+)?)\s*%?\s*[/ ]\s*(?P<days>\d+)\s*(?:days?)?\s*,?\s*"
                       r"(?:net|n)\s*/?\s*(?P<net>\d+)\s*(?:days?)?\s*$", re.IGNORECASE)
# "net 30", "n/30", "Net30", "net 30 days"
_NET = re.compile(r"^\s*(?:net|n)\s*/?\s*(?P<net>\d+)\s*(?:days?)?\s*$", re.IGNORECASE)
_ON_RECEIPT = re.compile(r"^\s*(?:due\s+(?:on|upon)\s+receipt|on\s+receipt|cod|immediate)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Terms:
    net_days: int
    discount_pct: Decimal | None = None   # 2 for "2/10 net 30"
    discount_days: int | None = None      # 10 for "2/10 net 30"
    text: str = ""
    note: str | None = None               # why the text was ignored or overridden

    @property
    def has_discount(self) -> bool:
        return self.discount_pct is not None

    @property
    def annual_rate(self) -> Decimal | None:
        """What skipping the discount costs, as a yearly rate: 2/10 net 30 is 2/98 for 20 days, about 37% a year."""
        if not self.has_discount or self.net_days <= (self.discount_days or 0):
            return None
        pct = self.discount_pct / 100
        return (pct / (1 - pct) * Decimal(365) / (self.net_days - self.discount_days)).quantize(Decimal("0.0001"))

    def describe(self) -> str:
        net = "due on receipt" if self.net_days == 0 else f"net {self.net_days}"
        if self.has_discount:
            return f"{self.discount_pct.normalize():f}% off if paid within {self.discount_days} days, {net}"
        return net


def parse_terms(text: str | None, terms_days: str | int | None = None) -> Terms:
    """Vendor master terms: early_pay_discount (e.g. "2/10 net 30", often blank) and payment_terms_days.

    Blank text means no discount and payment_terms_days as the net days (0 = due on receipt). When the text names
    its own net days and payment_terms_days disagrees, the text wins (it's the written term) and `note` says so.
    Text that can't be read gives no discount, with a note, rather than a guess.
    """
    days = int(terms_days) if str(terms_days or "").strip().isdigit() else 0
    raw = (text or "").strip()
    if not raw:
        return Terms(net_days=days)
    if m := _DISCOUNT.match(raw):
        pct, disc, net = Decimal(m["pct"]), int(m["days"]), int(m["net"])
        if not (0 < pct < 100) or disc >= net:
            return Terms(net_days=days, text=raw, note=f"terms '{raw}' don't make sense; no discount assumed")
        note = (f"terms say net {net} but payment_terms_days is {days}; using net {net}"
                if days and days != net else None)
        return Terms(net_days=net, discount_pct=pct, discount_days=disc, text=raw, note=note)
    if m := _NET.match(raw):
        return Terms(net_days=int(m["net"]), text=raw)
    if _ON_RECEIPT.match(raw):
        return Terms(net_days=0, text=raw)
    return Terms(net_days=days, text=raw, note=f"terms '{raw}' not recognised; no discount assumed")


def vendor_terms(ref: RefData, vendor_id: str) -> Terms:
    v = ref.vendors.get(vendor_id, {})
    return parse_terms(v.get("early_pay_discount"), v.get("payment_terms_days"))


def discount_amount(terms: Terms, subtotal: Decimal) -> Decimal:
    """The discount on a bill: a percentage of the pre-tax subtotal, rounded to the cent."""
    if not terms.has_discount or subtotal <= 0:
        return Decimal("0.00")
    return (subtotal * terms.discount_pct / 100).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Suggestions for open bills
# ---------------------------------------------------------------------------
@dataclass
class PaySuggestion:
    invoice_id: str
    vendor_id: str
    status: str
    terms: Terms
    method: str
    invoice_date: date
    due_date: date
    discount_deadline: date | None        # last day the money must arrive to earn the discount
    pay_on: date                          # suggested date to send the payment
    currency: str
    total: Decimal
    saving: Decimal                       # in the bill's currency, vs paying on the due date
    saving_cad: Decimal
    pay_amount: Decimal                   # total minus the saving
    scheduled_date: date | None = None    # the current scheduled payment, if any
    action: str = "pay_on_due_date"       # "take_discount" | "pay_on_due_date" | "pay_now" | "reschedule"
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def _fmt(x: Decimal, cur: str) -> str:
    return f"{cur} {x:,.2f}" if cur != "CAD" else f"${x:,.2f}"


def _suggest(ref: RefData, inv: dict, payment: dict | None, today: date) -> PaySuggestion | None:
    total, subtotal = money(inv["total"]), money(inv["subtotal"])
    if total <= 0:
        return None  # credit notes are applied, not paid
    terms = vendor_terms(ref, inv["vendor_id"])
    vendor = ref.vendors.get(inv["vendor_id"], {})
    method = (payment or {}).get("method") or vendor.get("preferred_payment_method") or "EFT"
    invoiced = d(inv["invoice_date"])
    due = d(inv["due_date"]) or invoiced + timedelta(days=terms.net_days)
    fx = money(inv["fx_rate_to_cad"]) or Decimal("1")
    cur = inv["currency"] or "CAD"
    scheduled = d((payment or {}).get("scheduled_date", ""))
    notes = [terms.note] if terms.note else []
    if d(inv["due_date"]) and d(inv["due_date"]) != invoiced + timedelta(days=terms.net_days):
        notes.append(f"Invoice due date {human_date(due)} isn't {terms.describe()} from the invoice date; the "
                     f"invoice's date is used.")

    deadline = invoiced + timedelta(days=terms.discount_days) if terms.has_discount else None
    saving = Decimal("0.00")
    lead = LEAD_DAYS.get(method, 1)
    if deadline and today <= deadline:
        saving = discount_amount(terms, subtotal)
        pay_on = max(today, deadline - timedelta(days=lead))
        action = "take_discount"
        rate = f" (skipping it costs about {terms.annual_rate * 100:.0f}% a year)" if terms.annual_rate else ""
        # Pay-by is the discount's last day less the time the method takes to arrive, so both dates are given.
        arrive = f", {lead} day{'s' if lead != 1 else ''} before the discount ends on {human_date(deadline)},"
        reason = (f"Pay by {human_date(pay_on)}{arrive if pay_on < deadline else ''} to take "
                  f"{terms.discount_pct.normalize():f}% off the {_fmt(subtotal, cur)} subtotal: save "
                  f"{_fmt(saving, cur)}{rate}.")
    else:
        pay_on = max(today, due)
        action = "pay_now" if due <= today else "pay_on_due_date"
        reason = (f"Overdue since {human_date(due)}: pay now." if due < today else
                  "Due today: pay today." if due == today else
                  f"Due {human_date(due)}. Paying earlier saves nothing.")
        if deadline:
            missed = discount_amount(terms, subtotal)
            reason += (f" The {terms.discount_pct.normalize():f}% discount ({_fmt(missed, cur)}) ended "
                       f"{human_date(deadline)}.")
    if scheduled and saving and scheduled > pay_on:
        action = "reschedule"
        reason = (f"Scheduled for {human_date(scheduled)}, after the discount ends. Move it to {human_date(pay_on)} "
                  f"to save {_fmt(saving, cur)}.")
    elif scheduled and scheduled > due:
        action = "reschedule"
        reason = (f"Scheduled for {human_date(scheduled)}, after the {human_date(due)} due date. Move it to "
                  f"{human_date(pay_on)}.")
    return PaySuggestion(
        inv["invoice_id"], inv["vendor_id"], inv["status"], terms, method, invoiced, due, deadline, pay_on, cur,
        total, saving, (saving * fx).quantize(CENT), total - saving, scheduled, action, reason, notes)


def suggest_pay_dates(ref: RefData, payments: list[dict], *, statuses: tuple[str, ...] = OPEN_STATUSES,
                      today: date | None = None) -> list[PaySuggestion]:
    """Best pay date for every bill in `statuses`, biggest saving first, then by pay date."""
    today = today or ref.as_of
    scheduled = {p["invoice_id"]: p for p in payments if p["status"] == "scheduled"}
    out = [s for inv in ref.invoices.values() if inv["status"] in statuses
           if (s := _suggest(ref, inv, scheduled.get(inv["invoice_id"]), today))]
    return sorted(out, key=lambda s: (-s.saving_cad, s.pay_on, s.invoice_id))


# ---------------------------------------------------------------------------
# History: discounts taken and missed
# ---------------------------------------------------------------------------
@dataclass
class PastDiscount:
    payment_id: str
    invoice_id: str
    vendor_id: str
    invoice_date: date
    paid_date: date
    days_to_pay: int
    discount_cad: Decimal       # taken, or what it would have been
    taken: bool


@dataclass
class DiscountHistory:
    taken: list[PastDiscount]
    missed: list[PastDiscount]

    @property
    def taken_cad(self) -> Decimal:
        return sum((x.discount_cad for x in self.taken), Decimal("0"))

    @property
    def missed_cad(self) -> Decimal:
        return sum((x.discount_cad for x in self.missed), Decimal("0"))


def discount_history(ref: RefData, payments: list[dict]) -> DiscountHistory:
    """Settled payments to vendors with a discount term: which took it, and which were paid too late for it."""
    taken, missed = [], []
    for p in payments:
        inv = ref.invoices.get(p["invoice_id"])
        if not inv or p["status"] != "settled" or not p["paid_date"]:
            continue
        terms = vendor_terms(ref, inv["vendor_id"])
        if not terms.has_discount or money(inv["total"]) <= 0:
            continue
        invoiced, paid = d(inv["invoice_date"]), d(p["paid_date"])
        fx = money(p["fx_rate_to_cad"]) or Decimal("1")
        got = money(p["discount_taken"])
        days = (paid - invoiced).days
        if got > 0:
            taken.append(PastDiscount(p["payment_id"], p["invoice_id"], inv["vendor_id"], invoiced, paid, days,
                                      (got * fx).quantize(CENT), True))
        elif days > terms.discount_days:
            amount = discount_amount(terms, money(inv["subtotal"]))
            missed.append(PastDiscount(p["payment_id"], p["invoice_id"], inv["vendor_id"], invoiced, paid, days,
                                       (amount * fx).quantize(CENT), False))
    return DiscountHistory(taken, missed)
