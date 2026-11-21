"""find_duplicates(bill, ref, batch) -> list[DuplicateMatch]
duplicate_flags(matches) -> list[Flag]
find_split(bill, ref, batch) -> Flag | None

Compares a new bill against history and against the other bills in the same batch.
Every match carries a score and the reasons, so the UI can show *why*.
Matches are also turned into flags so a duplicate holds the payment like any other BLOCK.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from app.shared.schemas import DraftBill, DuplicateMatch, Flag

from .refdata import RefData, bill_id, currency, d, is_credit, money, vendor_id
from .validate import _norm_name, flag, to_cad

NEAR_AMOUNT_PCT = Decimal("0.01")  # amounts within 1%
NEAR_DAYS = 14
NEAR_NUMBER_SIM = 0.6  # a near duplicate needs invoice numbers this alike, or the same service period
CARD_DAYS = 45
SPLIT_WINDOW_DAYS = 3

# DuplicateMatch.kind -> flag code
DUP_FLAG = {
    "exact": "DUPLICATE_EXACT",
    "normalized": "DUPLICATE_EXACT",     # 604 vs 000604 from the same vendor is the same invoice
    "near": "DUPLICATE_LIKELY",
    "cross_vendor": "DUPLICATE_LIKELY",
    "card_paid": "ALREADY_PAID_BY_CARD",
}


def norm_invoice_no(s: str) -> str:
    """FA-000583 -> 583, 000903-A -> 903, INV-02990 -> 2990. Keeps digits only, drops leading zeros."""
    digits = re.sub(r"[^0-9]", "", s or "")
    return digits.lstrip("0")


_MONTHS = {
    m: i + 1 for i, names in enumerate([
        ("january", "janvier"), ("february", "février", "fevrier"), ("march", "mars"), ("april", "avril"),
        ("may", "mai"), ("june", "juin"), ("july", "juillet"), ("august", "août", "aout"),
        ("september", "septembre"), ("october", "octobre"), ("november", "novembre"),
        ("december", "décembre", "decembre")])
    for m in names
}
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b", re.IGNORECASE)
_YM_RE = re.compile(r"\b20\d\d-(0[1-9]|1[0-2])\b")


def service_period(descriptions: Iterable[str]) -> frozenset[int]:
    """Months named in the line descriptions ("Energy - October", "2026-10-01 to 2026-10-31"). Empty if none."""
    months: set[int] = set()
    for text in descriptions:
        months |= {_MONTHS[m.lower()] for m in _MONTH_RE.findall(text or "")}
        months |= {int(m) for m in _YM_RE.findall(text or "")}
    return frozenset(months)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.upper(), b.upper()).ratio()


def _close_amount(a: Decimal, b: Decimal) -> bool:
    if a == b:
        return True
    big = max(abs(a), abs(b))
    return big > 0 and abs(a - b) / big <= NEAR_AMOUNT_PCT


@dataclass
class _Cand:
    """One existing invoice, flattened so history rows and batch bills look the same."""
    id: str
    vendor_id: str
    number: str
    invoice_date: date | None
    total: Decimal
    total_cad: Decimal | None   # None when a batch bill has no reliable FX rate
    status: str
    credit: bool
    name: str = ""              # normalized vendor name: how unknown vendors are compared
    department_id: str = ""
    po: str = ""
    period: frozenset[int] = frozenset()  # months named in the lines, see service_period()


def _doc_key(vendor: str | None, number: str | None, invoice_date: date | None, total: Decimal) -> tuple:
    """What identifies one invoice document across RefData rows and batch bills (they share no id)."""
    return (vendor or "", (number or "").strip().upper(), invoice_date, total)


def _candidates(bill: DraftBill, ref: RefData, batch: Iterable[DraftBill]) -> list[_Cand]:
    """History (minus rejected) plus the other bills in the batch.

    The bill itself may be in `batch`; it is skipped by identity, not by file_hash, so the same
    PDF submitted twice (two bills, one hash) still matches as a duplicate.

    A batch bill that is already in the reference data (same vendor, invoice number, date and total) is skipped:
    the API stores each bill of an inbox run before checking the next, so earlier bills are in both places, and
    counting them twice inflates splits and repeats duplicate matches. Nothing is lost, because the reference row
    still takes part in every check.
    """
    me = bill_id(bill)
    out = [
        _Cand(i["invoice_id"], i["vendor_id"], i["vendor_invoice_number"], d(i["invoice_date"]),
              money(i["total"]), money(i["total_cad"]), i["status"], money(i["total"]) < 0,
              _norm_name(ref.vendors.get(i["vendor_id"], {}).get("legal_name", "")),
              i["department_id"], i["po_id"],
              service_period(ln["description"] for ln in ref.invoice_lines.get(i["invoice_id"], [])))
        for i in ref.invoices.values()
        if i["invoice_id"] != me and i["status"] != "rejected"
    ]
    known = {_doc_key(c.vendor_id, c.number, c.invoice_date, c.total) for c in out}
    for b in batch:
        if b is not bill and _doc_key(vendor_id(b), b.invoice_number, b.invoice_date, b.total) not in known:
            out.append(_Cand(bill_id(b), vendor_id(b) or "", b.invoice_number, b.invoice_date,
                             b.total, to_cad(b, ref)[0], "in_batch", is_credit(b),
                             _norm_name(b.vendor.name_on_invoice), b.department_id or "", b.po_number or "",
                             service_period(ln.description for ln in b.lines)))
    return out


def _same_vendor(bill: DraftBill, c: _Cand) -> bool:
    """Same vendor record; for two bills from vendors not in the master, the same name on the invoice."""
    vid = vendor_id(bill)
    if vid:
        return c.vendor_id == vid
    me = _norm_name(bill.vendor.name_on_invoice)
    return not c.vendor_id and bool(me) and c.name == me


def _is_recurring_vendor(ref: RefData, vid: str) -> bool:
    """Rent, SaaS, insurance etc. bill the same amount every month. Same amount alone is NOT a duplicate for them."""
    c = next((c for c in ref.contracts.values() if c["vendor_id"] == vid), None)
    return bool(c and c["billing_type"] == "fixed_monthly")


def find_duplicates(bill: DraftBill, ref: RefData, batch: Iterable[DraftBill] = ()) -> list[DuplicateMatch]:
    matches: list[DuplicateMatch] = []
    vid = vendor_id(bill)
    my_no = norm_invoice_no(bill.invoice_number)
    vendor = ref.vendors.get(vid or "")
    bank = bill.vendor.bank
    my_bank = (bank.transit, bank.account) if bank.account else \
        ((vendor["bank_transit"], vendor["bank_account"]) if vendor and vendor["bank_account"] else None)
    credit = is_credit(bill)
    my_period = service_period(ln.description for ln in bill.lines)

    for c in _candidates(bill, ref, batch):
        if c.credit != credit:
            continue  # a credit note shares its invoice's number and amount by design; that's not a duplicate
        same_vendor = _same_vendor(bill, c)
        days = abs((c.invoice_date - bill.invoice_date).days) if c.invoice_date else 999
        status = f"{c.id} status: {c.status}"

        if same_vendor and c.number == bill.invoice_number:
            matches.append(DuplicateMatch(kind="exact", score=1.0, matched_invoice_id=c.id,
                                          reasons=["same vendor", f"same invoice number {c.number}",
                                                   f"total {c.total} vs {bill.total}", status]))
            continue
        if same_vendor and my_no and norm_invoice_no(c.number) == my_no:
            matches.append(DuplicateMatch(kind="normalized", score=0.95, matched_invoice_id=c.id,
                                          reasons=["same vendor",
                                                   f"invoice no {bill.invoice_number} == {c.number} after removing "
                                                   f"prefixes and leading zeros", status]))
            continue
        if same_vendor and _close_amount(c.total, bill.total) and days <= NEAR_DAYS:
            sim = _similar(norm_invoice_no(c.number), my_no)
            same_period = bool(my_period) and my_period == c.period
            # Same vendor and amount alone isn't enough: Orion 279 and 281 are two phases billed the same day.
            # The numbers must look alike, or both bills must name the same months (two "October" bills from one
            # vendor). This also keeps fixed-monthly vendors (rent, SaaS) from matching every month's bill.
            if sim < NEAR_NUMBER_SIM and not same_period:
                continue
            why = ["same vendor", f"amount {c.total} vs {bill.total}", f"{days} days apart",
                   f"invoice numbers {sim:.0%} similar"]
            if same_period:
                why.append("same service period")
            matches.append(DuplicateMatch(kind="near", score=round(0.6 + 0.3 * sim, 2), matched_invoice_id=c.id,
                                          reasons=why + [status]))
            continue
        if not same_vendor and my_bank and _close_amount(c.total, bill.total) and days <= 30:
            other = ref.vendors.get(c.vendor_id)
            if other and (other["bank_transit"], other["bank_account"]) == my_bank:
                matches.append(DuplicateMatch(kind="cross_vendor", score=0.85, matched_invoice_id=c.id,
                                              reasons=[f"same bank account as {c.vendor_id} {other['legal_name']}",
                                                       f"amount {c.total} vs {bill.total}", f"{days} days apart",
                                                       status]))

    if not credit:
        matches.extend(_card_matches(bill, ref))
    return sorted(matches, key=lambda m: -m.score)


def _card_matches(bill: DraftBill, ref: RefData) -> list[DuplicateMatch]:
    vendor = ref.vendors.get(vendor_id(bill) or "")
    if not vendor:
        return []
    total_cad, _ = to_cad(bill, ref)
    cur = currency(bill)
    name = _norm_name(vendor["legal_name"])
    out = []
    for t in ref.card_txns:
        if (t["memo"] or "").startswith("AP payment"):
            # An AP virtual card paying some invoice. If that invoice is a duplicate of this one,
            # the invoice-to-invoice checks above already catch it. Skipping avoids flagging next
            # month's identical SaaS bill as "paid by card".
            continue
        days = (d(t["posted_date"]) - bill.invoice_date).days
        if not (-CARD_DAYS <= days <= CARD_DAYS):
            continue
        if not ((total_cad is not None and _close_amount(money(t["amount_cad"]), total_cad)) or
                ((t["currency"] or "").upper() == cur and _close_amount(money(t["amount"]), bill.total))):
            continue
        sim = _similar(_norm_name(t["merchant_descriptor"]), name)
        if sim >= 0.6:
            charge = (f"{t['source']} charge {t['merchant_descriptor']} {t['currency']} {t['amount']} "
                      f"on {t['posted_date']}")
            out.append(DuplicateMatch(kind="card_paid", score=round(0.5 + 0.4 * sim, 2),
                                      matched_card_txn_id=t["txn_id"],
                                      reasons=[charge, f"merchant name {sim:.0%} similar",
                                               f"cardholder {t['cardholder_user_id']}"]))
    return out


def duplicate_flags(matches: list[DuplicateMatch]) -> list[Flag]:
    """One flag per code, carrying every match behind it. Severity comes from FLAG_CODES."""
    by_code: dict[str, list[DuplicateMatch]] = {}
    for m in matches:
        by_code.setdefault(DUP_FLAG[m.kind], []).append(m)
    flags = []
    for code, ms in by_code.items():
        best = max(ms, key=lambda m: m.score)
        ids = [m.matched_invoice_id or m.matched_card_txn_id for m in ms]
        best_id = best.matched_invoice_id or best.matched_card_txn_id
        more = f" (+{len(ms) - 1} more)" if len(ms) > 1 else ""
        what = "Already paid by card" if code == "ALREADY_PAID_BY_CARD" else "Possible duplicate of"
        flags.append(flag(code, f"{what} {best_id}: {', '.join(best.reasons)}{more}.",
                          evidence={"matches": ids, "kinds": [m.kind for m in ms], "best_score": best.score},
                          field="total" if code == "ALREADY_PAID_BY_CARD" else "invoice_number"))
    return flags


def _is_duplicate_pair(bill: DraftBill, c: _Cand) -> bool:
    """Same invoice number (exact or normalized): a duplicate, which find_duplicates reports, not a split."""
    my_no = norm_invoice_no(bill.invoice_number)
    return c.number == bill.invoice_number or bool(my_no and norm_invoice_no(c.number) == my_no)


def _split_member(bill: DraftBill, c: _Cand, limit: Decimal) -> bool:
    """Could candidate `c` be another piece of the same purchase as `bill`?"""
    if not _same_vendor(bill, c) or c.credit or not c.invoice_date or c.total_cad is None:
        return False
    if abs((c.invoice_date - bill.invoice_date).days) > SPLIT_WINDOW_DAYS:
        return False
    if not (0 < c.total_cad <= limit):
        return False
    if bill.department_id and c.department_id and bill.department_id != c.department_id:
        return False  # different departments buying from the same vendor isn't one purchase
    if bill.po_number and c.po and bill.po_number != c.po:
        return False  # each bill is covered by its own PO (e.g. Deskhive furniture orders)
    return not _is_duplicate_pair(bill, c)


def find_split(bill: DraftBill, ref: RefData, batch: Iterable[DraftBill] = (),
               limit: Decimal | None = None) -> Flag | None:
    """Several invoices from one vendor and department, each under the approval limit, within a few days,
    adding up to more than it. Duplicate pairs and bills on separate POs are not splits."""
    if limit is None:
        limit = ref.policies["P01"].threshold  # $10,000 from the policy table
    total_cad, _ = to_cad(bill, ref)
    if total_cad is None or total_cad > limit or total_cad <= 0 or is_credit(bill):
        return None
    if _is_recurring_vendor(ref, vendor_id(bill) or ""):
        return None  # e.g. V037 rent: 11 bills of $8,137.50 are monthly rent, not a split
    group = [c for c in _candidates(bill, ref, batch) if _split_member(bill, c, limit)]
    combined = total_cad + sum((c.total_cad for c in group), Decimal("0"))
    if group and combined > limit:
        return flag("POSSIBLE_SPLIT",
                    f"{len(group) + 1} invoices from this vendor within {SPLIT_WINDOW_DAYS} days, each under "
                    f"${limit:,.0f} but ${combined:,.2f} together. Route as if it were one ${combined:,.2f} bill.",
                    policy="P01", evidence={"related": [c.id for c in group], "combined_cad": str(combined)},
                    field="total")
    return None
