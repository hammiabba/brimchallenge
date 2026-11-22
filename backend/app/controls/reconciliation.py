"""Bank reconciliation: matches each bank statement line to the payment behind it and explains everything else.

reconcile(bank_rows, payment_rows, ref) -> Reconciliation

Inputs are rows shaped like the dataset CSVs (bank_statement.csv, payments.csv: dicts of strings), so the CSV loader
and a database adapter can both feed it, the same way build_refdata() works. `ref` supplies vendors, invoices, card
transactions and bank changes. Deterministic, no database, no network.

How a line is matched:
- "EFT PMT <payee> <ref>": the last 6 digits of an EFT payment's reference. If no reference matches, an unmatched
  EFT payment with the same amount and payee within EFT_WINDOW_DAYS is used, and the line says so.
- "CHEQUE <no> CLEARED": cheque references don't carry the cheque number, so by amount: the unmatched cheque payment
  issued closest before the clearing date (within CHEQUE_WINDOW_DAYS). Exact amounts are paired first, then amounts
  within NEAR_AMOUNT, which are reported as a difference.
- Fee lines ("... FEE", "SERVICE CHARGE"): bank fees.
- Anything else, including pre-authorized debits: unexplained.

Each line and each payment carries issues (code, severity, message). "review" means someone has to act, "info" is
a note. Issue codes are listed in ISSUES.
"""
from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.config import get_settings

from .duplicates import CARD_DAYS, _close_amount, _similar, norm_invoice_no
from .history import check_unverified_bank_changes
from .refdata import RefData, d, money
from .validate import _norm_name
from .wording import human_date, status_label

EFT_REF_DIGITS = 6
EFT_WINDOW_DAYS = 5         # an EFT posts a day after it's paid; the fallback match allows a few days
EFT_POST_DAYS = 3           # a settled EFT older than this with no bank line is missing from the statement
CHEQUE_WINDOW_DAYS = 60     # a cheque clears within two months of being issued
STALE_CHEQUE_DAYS = 90      # an uncleared cheque older than this is stale
NEAR_AMOUNT = Decimal("1.00")  # a cheque that cleared for a few cents more or less is still that cheque
CENT = Decimal("0.01")

_EFT = re.compile(r"^EFT PMT\s+(?P<payee>.*?)\s+(?P<ref>\d{4,})$")
_CHEQUE = re.compile(r"^CHEQUE\s+(?P<no>\d+)\s+CLEARED$")
_FEE = re.compile(r"\b(FEE|FEES|SERVICE CHARGE)\b")
_WIRE_FEE = re.compile(r"\bWIRE\b")
_PREAUTH = re.compile(r"^PREAUTH")

# code -> (severity, what it means). Line statuses are separate: matched / bank_fee / unexplained.
ISSUES = {
    "AMOUNT_DIFFERS": ("review", "The bank took a different amount than the payment record."),
    "DOUBLE_PAYMENT": ("review", "This payment pays a bill that was already paid (duplicate invoice or card)."),
    "DOUBLE_PAYMENT_AT_RISK": ("review", "A scheduled payment would pay a bill that is already paid or scheduled."),
    "PAID_AFTER_UNVERIFIED_BANK_CHANGE": ("review", "Sent after the vendor's bank account changed with no callback."),
    "STATUS_NOT_UPDATED": ("review", "The bank shows the payment cleared, but the payment record wasn't updated."),
    "MATCHED_WITHOUT_REFERENCE": ("review", "Matched by amount and payee because the reference matched nothing."),
    "PAYEE_DIFFERS": ("review", "The payee on the bank line isn't the vendor the payment was for."),
    "UNEXPLAINED_DEBIT": ("review", "Money left the account with no payment, bill or fee behind it."),
    "UNEXPLAINED_CREDIT": ("review", "Money came in with nothing to explain it."),
    "WIRE_FEE_WITHOUT_WIRE": ("review", "A wire fee was charged, but no payment was sent by wire."),
    "NOT_ON_STATEMENT": ("review", "Settled in the payment records, but not on the bank statement."),
    "STALE_CHEQUE": ("review", f"Cheque issued over {STALE_CHEQUE_DAYS} days ago and never cleared."),
    "OUTSTANDING_CHEQUE": ("info", "Cheque issued, not cleared yet."),
    "SCHEDULED": ("info", "Scheduled, not sent yet."),
    "IN_TRANSIT": ("info", "Sent in the last few days, not posted by the bank yet."),
    "PAID_BY_CARD": ("info", "Paid by card: settles on the card account, not this bank account."),
    "BANK_FEE": ("info", "Bank fee."),
}


@dataclass(frozen=True)
class Issue:
    code: str
    message: str

    @property
    def severity(self) -> str:
        return ISSUES[self.code][0]


@dataclass
class LineResult:
    bank_txn_id: str
    posted_date: date
    description: str
    amount: Decimal                 # debit positive, credit negative
    status: str                     # "matched" | "bank_fee" | "unexplained"
    payment_ids: list[str] = field(default_factory=list)
    invoice_ids: list[str] = field(default_factory=list)
    vendor_id: str | None = None
    difference: Decimal | None = None   # bank amount minus payment amount, when they differ
    issues: list[Issue] = field(default_factory=list)


@dataclass
class PaymentResult:
    """A payment with no bank line, or one that needs a note (cards, scheduled, outstanding)."""
    payment_id: str
    invoice_id: str
    vendor_id: str
    method: str
    status: str
    amount_cad: Decimal
    date: date | None               # paid date, or scheduled date when not paid
    bank_txn_id: str | None = None
    issues: list[Issue] = field(default_factory=list)


@dataclass
class DoublePaymentGroup:
    """One bill paid more than once: the invoice copies and card charges, and the payments behind them."""
    invoice_ids: list[str]
    card_txn_ids: list[str]
    payment_ids: list[str]
    bank_txn_ids: list[str]
    extra_payment_ids: list[str]    # settled payments after the first: the money paid out twice
    at_risk_payment_ids: list[str]  # scheduled or outstanding payments that would pay it again
    confirmed: bool                 # two AP invoices with the same number (card matches are likely, not certain)
    extra_paid_cad: Decimal         # paid beyond the first payment
    at_risk_cad: Decimal            # scheduled or outstanding payments that would also be extra
    message: str


@dataclass
class Reconciliation:
    statement_from: date | None
    statement_to: date | None
    lines: list[LineResult]
    payments: list[PaymentResult]
    double_payments: list[DoublePaymentGroup]

    def summary(self) -> dict:
        debits = [ln for ln in self.lines if ln.amount > 0]

        def total(rows: Iterable[LineResult]) -> Decimal:
            return sum((ln.amount for ln in rows), Decimal("0"))

        by_status = {s: [ln for ln in self.lines if ln.status == s] for s in ("matched", "bank_fee", "unexplained")}
        issue_counts: dict[str, int] = {}
        for x in [*self.lines, *self.payments]:
            for i in x.issues:
                issue_counts[i.code] = issue_counts.get(i.code, 0) + 1
        return {
            "lines": len(self.lines), "debits_cad": total(debits),
            "matched": len(by_status["matched"]), "matched_cad": total(by_status["matched"]),
            "bank_fees": len(by_status["bank_fee"]), "bank_fees_cad": total(by_status["bank_fee"]),
            "unexplained": len(by_status["unexplained"]), "unexplained_cad": total(by_status["unexplained"]),
            "double_payments": len(self.double_payments),
            "double_paid_extra_cad": sum((g.extra_paid_cad for g in self.double_payments), Decimal("0")),
            "double_at_risk_cad": sum((g.at_risk_cad for g in self.double_payments), Decimal("0")),
            "needs_review": sum(1 for x in [*self.lines, *self.payments]
                                if any(i.severity == "review" for i in x.issues)),
            "issues": dict(sorted(issue_counts.items())),
        }


def _amt(x: Decimal) -> str:
    return f"${x:,.2f}"


def _issue(code: str, message: str | None = None) -> Issue:
    return Issue(code, message or ISSUES[code][1])


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _payee_matches(payee: str, vendor: dict) -> bool:
    """Bank payee names are upper-case and cut to ~24 characters."""
    bank, master = _norm_name(payee), _norm_name(vendor.get("legal_name", ""))
    return bool(bank) and (master.startswith(bank) or bank.startswith(master) or _similar(bank, master) >= 0.8)


def _days(a: date | None, b: date | None) -> int | None:
    return (a - b).days if a and b else None


def _match_eft(line: dict, m: re.Match, eft: list[dict], used: set[str]) -> tuple[dict | None, bool]:
    ref = m["ref"][-EFT_REF_DIGITS:]
    p = next((p for p in eft if p["payment_id"] not in used and (p["reference"] or "")[-EFT_REF_DIGITS:] == ref),
             None)
    if p:
        return p, True
    amount, posted = money(line["debit"]), d(line["posted_date"])
    for p in eft:
        lag = _days(posted, d(p["paid_date"]) or d(p["scheduled_date"]))
        if p["payment_id"] not in used and money(p["amount_cad"]) == amount and lag is not None \
                and 0 <= lag <= EFT_WINDOW_DAYS:
            return p, False
    return None, False


def _pair_cheques(lines: list[dict], cheques: list[dict]) -> dict[str, dict]:
    """bank_txn_id -> cheque payment. Exact amounts first, then near ones; closest issue date before clearing wins."""
    out: dict[str, dict] = {}
    used: set[str] = set()
    for tolerance in (Decimal("0"), NEAR_AMOUNT):
        pairs = []
        for ln in lines:
            if ln["bank_txn_id"] in out:
                continue
            for p in cheques:
                if p["payment_id"] in used:
                    continue
                lag = _days(d(ln["posted_date"]), d(p["paid_date"]) or d(p["scheduled_date"]))
                diff = abs(money(ln["debit"]) - money(p["amount_cad"]))
                if lag is not None and 0 <= lag <= CHEQUE_WINDOW_DAYS and diff <= tolerance:
                    pairs.append((diff, lag, ln["bank_txn_id"], p["payment_id"], p))
        for _, _, line_id, pay_id, p in sorted(pairs, key=lambda x: x[:4]):
            if line_id not in out and pay_id not in used:
                out[line_id] = p
                used.add(pay_id)
    return out


# ---------------------------------------------------------------------------
# Double payments
# ---------------------------------------------------------------------------
def double_payment_groups(ref: RefData, payments: list[dict]) -> list[DoublePaymentGroup]:
    """Bills paid more than once, by the same rules as the duplicate checks (controls.duplicates):

    - two AP invoices from one vendor with the same invoice number after normalizing (583 == FA-000583), or
    - an AP invoice and an employee card charge: similar merchant name, amount within 1%, within CARD_DAYS days.
    Only invoices that have a payment count, and a credit note never pairs with an invoice.
    """
    paid = [p for p in payments if p["status"] not in ("cancelled", "failed")]
    paid_invoices = {p["invoice_id"] for p in paid}
    invoices = {i: ref.invoices[i] for i in paid_invoices if i in ref.invoices}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_number: dict[tuple, list[str]] = {}
    for iid, inv in invoices.items():
        no = norm_invoice_no(inv["vendor_invoice_number"])
        if no:
            by_number.setdefault((inv["vendor_id"], no, money(inv["total"]) < 0), []).append(iid)
    for ids in by_number.values():
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])

    cards = [t for t in ref.card_txns if not (t["memo"] or "").startswith("AP payment")]
    for iid, inv in invoices.items():
        name = _norm_name(ref.vendors.get(inv["vendor_id"], {}).get("legal_name", ""))
        when, total = d(inv["invoice_date"]), money(inv["total_cad"])
        if not name or total <= 0:
            continue
        for t in cards:
            if abs((d(t["posted_date"]) - when).days) <= CARD_DAYS and _close_amount(money(t["amount_cad"]), total) \
                    and _similar(_norm_name(t["merchant_descriptor"]), name) >= 0.6:
                parent[find(t["txn_id"])] = find(iid)

    members: dict[str, list[str]] = {}
    for x in parent:
        members.setdefault(find(x), []).append(x)
    by_invoice: dict[str, list[dict]] = {}
    for p in paid:
        by_invoice.setdefault(p["invoice_id"], []).append(p)
    card_by_id = {t["txn_id"]: t for t in cards}
    by_status = {p["payment_id"]: p["status"] for p in paid}

    out = []
    for ids in members.values():
        inv_ids = sorted(x for x in ids if x in invoices)
        card_ids = sorted(x for x in ids if x in card_by_id)
        if len(inv_ids) + len(card_ids) < 2:
            continue
        # One event per invoice (its payments together: instalments are one payment of that copy) or card charge.
        events = []  # (date, id, amount_cad, settled, payment ids)
        for iid in inv_ids:
            ps = by_invoice[iid]
            settled = all(p["status"] == "settled" for p in ps)
            when = min((d(p["paid_date"]) or d(p["scheduled_date"]) for p in ps), default=None)
            events.append((when, iid, sum((money(p["amount_cad"]) for p in ps), Decimal("0")), settled,
                           [p["payment_id"] for p in ps]))
        for tid in card_ids:
            t = card_by_id[tid]
            events.append((d(t["posted_date"]), tid, money(t["amount_cad"]), True, []))
        events.sort(key=lambda e: (e[0] or date.max, e[1]))
        settled = [e for e in events if e[3]]
        first = settled[0] if settled else events[0]
        extra = sum((e[2] for e in settled if e is not first), Decimal("0"))
        risk = sum((e[2] for e in events if not e[3] and e is not first), Decimal("0"))
        confirmed = len(inv_ids) >= 2
        vendor = ref.vendors.get(invoices[inv_ids[0]]["vendor_id"], {}).get("legal_name", "") if inv_ids else ""
        what = " / ".join(e[1] for e in events)
        how = "same invoice number" if confirmed else "AP payment and an employee card charge for the same amount"
        msg = (f"{vendor}: {what} are one bill ({how}). "
               + (f"{_amt(extra)} paid out extra" if extra else "")
               + (", " if extra and risk else "")
               + (f"{_amt(risk)} still scheduled to go out" if risk else "") + ".")
        out.append(DoublePaymentGroup(
            inv_ids, card_ids, sorted(p for e in events for p in e[4]), [],
            sorted(p for e in settled if e is not first for p in e[4]),
            sorted(p for e in events if not e[3] and e is not first for p in e[4]
                   if by_status.get(p) != "settled"),
            confirmed, extra, risk, msg))
    return sorted(out, key=lambda g: (-(g.extra_paid_cad + g.at_risk_cad), g.invoice_ids))


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------
def reconcile(bank_rows: list[dict], payment_rows: list[dict], ref: RefData) -> Reconciliation:
    """Matches statement lines to payments and classifies the rest. Rows are CSV-shaped dicts of strings."""
    lines = sorted(bank_rows, key=lambda r: (r["posted_date"], r["bank_txn_id"]))
    payments = sorted(payment_rows, key=lambda p: p["payment_id"])
    eft = [p for p in payments if p["method"] == "EFT" and p["status"] not in ("cancelled", "failed")]
    cheques = [p for p in payments if p["method"] == "CHEQUE" and p["status"] not in ("cancelled", "failed")]
    vendors = ref.vendors
    start = min((d(r["posted_date"]) for r in lines), default=None)
    end = max((d(r["posted_date"]) for r in lines), default=None)

    cheque_lines = [r for r in lines if _CHEQUE.match(r["description"].strip().upper()) and r["debit"]]
    cheque_pairs = _pair_cheques(cheque_lines, cheques)
    wire_dates = {d(p["paid_date"]) for p in payments if p["method"] == "WIRE"}

    used: set[str] = set()
    line_of_payment: dict[str, str] = {}
    results: list[LineResult] = []
    for r in lines:
        text = r["description"].strip().upper()
        debit, credit = money(r["debit"]), money(r["credit"])
        amount = debit if r["debit"] else -credit
        res = LineResult(r["bank_txn_id"], d(r["posted_date"]), r["description"], amount, "unexplained")
        p, by_ref = None, True
        if (m := _EFT.match(text)) and r["debit"]:
            p, by_ref = _match_eft(r, m, eft, used)
            if p and not by_ref:
                res.issues.append(_issue("MATCHED_WITHOUT_REFERENCE",
                                         f"Reference {m['ref']} matches no payment. Matched to {p['payment_id']} by "
                                         f"amount and payee. Check the reference with the bank."))
            if p and not _payee_matches(m["payee"], vendors.get(p["vendor_id"], {})):
                res.issues.append(_issue("PAYEE_DIFFERS",
                                         f"The bank paid '{m['payee']}', not "
                                         f"{vendors.get(p['vendor_id'], {}).get('legal_name') or p['vendor_id']}."))
        elif r["bank_txn_id"] in cheque_pairs:
            p = cheque_pairs[r["bank_txn_id"]]

        if p:
            used.add(p["payment_id"])
            line_of_payment[p["payment_id"]] = r["bank_txn_id"]
            res.status, res.payment_ids, res.invoice_ids, res.vendor_id = \
                "matched", [p["payment_id"]], [p["invoice_id"]], p["vendor_id"]
            diff = debit - money(p["amount_cad"])
            if diff:
                res.difference = diff
                res.issues.append(_issue("AMOUNT_DIFFERS",
                                         f"Bank took {_amt(debit)} but {p['payment_id']} is for "
                                         f"{_amt(money(p['amount_cad']))} ({'+' if diff > 0 else '-'}"
                                         f"{_amt(abs(diff))}). Ask the bank or the vendor which is right."))
            if p["status"] != "settled":
                res.issues.append(_issue("STATUS_NOT_UPDATED",
                                         f"{p['payment_id']} cleared the bank on {human_date(r['posted_date'])} but "
                                         f"is still marked {status_label(p['status'])}. Mark it settled."))
        elif _FEE.search(text) and r["debit"]:
            res.status = "bank_fee"
            res.issues.append(_issue("BANK_FEE"))
            if _WIRE_FEE.search(text) and d(r["posted_date"]) not in wire_dates:
                res.issues.append(_issue("WIRE_FEE_WITHOUT_WIRE",
                                         f"Wire fee of {_amt(debit)} on {human_date(r['posted_date'])}, but no "
                                         f"payment went out by wire. Ask the bank what it's for."))
        elif r["debit"]:
            kind = "pre-authorized debit" if _PREAUTH.match(text) else "debit"
            res.issues.append(_issue("UNEXPLAINED_DEBIT",
                                     f"{kind.capitalize()} of {_amt(debit)} with no payment, bill or fee behind it. "
                                     f"Find out who authorized it, and stop it if nobody did."))
        else:
            res.issues.append(_issue("UNEXPLAINED_CREDIT",
                                     f"Credit of {_amt(credit)} with nothing to explain it. Find out who sent it."))
        results.append(res)

    # Payments that should be on the statement, and payments the statement can't show.
    pay_results: list[PaymentResult] = []
    for p in payments:
        when = d(p["paid_date"]) or d(p["scheduled_date"])
        pr = PaymentResult(p["payment_id"], p["invoice_id"], p["vendor_id"], p["method"], p["status"],
                           money(p["amount_cad"]), when, line_of_payment.get(p["payment_id"]))
        if p["status"] in ("cancelled", "failed") or pr.bank_txn_id:
            if pr.bank_txn_id:
                pay_results.append(pr)
            continue
        if p["method"] == "CARD":
            pr.issues.append(_issue("PAID_BY_CARD"))
        elif p["status"] == "scheduled":
            pr.issues.append(_issue("SCHEDULED", f"Scheduled for {human_date(p['scheduled_date'])}, not sent yet."))
        elif p["method"] == "CHEQUE":
            age = _days(end, when)
            code = "STALE_CHEQUE" if age is not None and age > STALE_CHEQUE_DAYS else "OUTSTANDING_CHEQUE"
            pr.issues.append(_issue(code, f"Cheque issued {human_date(when)}, not cleared by {human_date(end)}"
                                    + (f" ({age} days). Contact the vendor and void or reissue it." if code ==
                                       "STALE_CHEQUE" else ".")))
        elif end and when and (end - when).days > EFT_POST_DAYS:
            pr.issues.append(_issue("NOT_ON_STATEMENT",
                                    f"{p['payment_id']} is marked {status_label(p['status'])} "
                                    f"(paid {human_date(when)}) but no bank line shows it. "
                                    f"Check whether the money actually left."))
        else:
            pr.issues.append(_issue("IN_TRANSIT", f"Sent {human_date(when)}, not posted by the bank yet."))
        pay_results.append(pr)

    # Double payments: mark the extra copies' bank lines and scheduled payments.
    groups = double_payment_groups(ref, payments)
    line_by_id = {ln.bank_txn_id: ln for ln in results}
    pay_by_id = {pr.payment_id: pr for pr in pay_results}
    for g in groups:
        g.bank_txn_ids = sorted(line_of_payment[pid] for pid in g.payment_ids if pid in line_of_payment)
        for pid in g.extra_payment_ids:
            if pid in line_of_payment:
                line_by_id[line_of_payment[pid]].issues.append(_issue("DOUBLE_PAYMENT", g.message))
        for pid in g.at_risk_payment_ids:
            if pid in pay_by_id:
                pay_by_id[pid].issues.append(_issue("DOUBLE_PAYMENT_AT_RISK", g.message + " Cancel it."))

    # Money sent after an unverified bank change (the payment-time check from the history replay).
    for f in check_unverified_bank_changes(ref, payments):
        pid = f.evidence.get("payment")
        if f.kind == "paid_after_unverified_bank_change" and pid in line_of_payment:
            line_by_id[line_of_payment[pid]].issues.append(_issue("PAID_AFTER_UNVERIFIED_BANK_CHANGE", f.message))
        elif pid in pay_by_id:
            pay_by_id[pid].issues.append(_issue("PAID_AFTER_UNVERIFIED_BANK_CHANGE", f.message))

    return Reconciliation(start, end, results, pay_results, groups)


# ---------------------------------------------------------------------------
# CSV loading (the database adapter in app/services/reconciliation.py builds the same rows)
# ---------------------------------------------------------------------------
def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_bank_and_payments(data_dir: Path | str | None = None) -> tuple[list[dict], list[dict]]:
    p = Path(data_dir) if data_dir is not None else get_settings().dataset_dir / "data"
    return _read(p / "bank_statement.csv"), _read(p / "payments.csv")
