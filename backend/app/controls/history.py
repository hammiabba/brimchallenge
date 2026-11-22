"""Replaying the historical invoices: what the engine would have caught, judged as of each bill's own date.

Used by scripts/replay_history.py. Three rules keep the numbers honest:

1. **Point in time.** Each bill only sees what was true on its invoice date: bank changes and user status changes
   (terminated, on leave) count only if they happened before it, and it is compared only to invoices that came
   before it (earlier date, or same date and an earlier invoice id).
2. **Once per problem.** Because each bill only looks backwards, a duplicate pair or a split group is reported on
   its later bill only, so it's counted once.
3. **What actually happened.** approvals.csv and payments.csv are checked too: self-approvals, PO overruns that
   skipped the finance manager (P12), approve-and-release by one person, and payments after an unverified bank change.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.config import get_settings
from app.shared.schemas import ControlsResult, Severity

from .engine import run_controls
from .refdata import RefData, bill_from_history, d, money
from .wording import channel_phrase, human_date, status_label


# ---------------------------------------------------------------------------
# Point-in-time view of the reference data
# ---------------------------------------------------------------------------
def _order(inv: dict) -> tuple[date, str]:
    """Arrival order: invoice date, then invoice id (ids were assigned as bills were entered)."""
    return d(inv["invoice_date"]), inv["invoice_id"]


def ref_as_of_invoice(ref: RefData, invoice_id: str) -> RefData:
    """RefData as it stood when `invoice_id` arrived.

    - invoices: only those that came before it (so duplicates and splits look backwards only)
    - bank_changes: only changes made before its invoice date
    - users: a status (terminated / on_leave) that started on or after the invoice date is undone
    - as_of: the bill's received date, for the date checks
    """
    inv = ref.invoices[invoice_id]
    key = _order(inv)
    when = key[0]
    invoices = {i: row for i, row in ref.invoices.items() if _order(row) < key}
    bank_changes = [c for c in ref.bank_changes if d(c["changed_at"]) < when]
    users = {}
    for uid, u in ref.users.items():
        since = d(u.get("status_since") or "")
        if u["status"] != "active" and since and since >= when:
            u = {**u, "status": "active", "status_since": "", "delegate_user_id": ""}
        users[uid] = u
    return replace(ref, invoices=invoices, bank_changes=bank_changes, users=users,
                   as_of=d(inv["received_date"]) or when)


def replay_bill(ref: RefData, invoice_id: str) -> ControlsResult:
    """run_controls on one historical bill, judged as of its own date."""
    point = ref_as_of_invoice(ref, invoice_id)
    return run_controls(bill_from_history(ref, invoice_id), ref=point)


# ---------------------------------------------------------------------------
# approvals.csv / payments.csv
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    kind: str                 # "self_approval" | "po_over_balance_no_finance" | "approved_and_released"
                              # | "paid_after_unverified_bank_change" | "due_after_unverified_bank_change"
    invoice_id: str
    message: str
    amount_cad: Decimal = Decimal("0")
    evidence: dict = field(default_factory=dict)


def _read(name: str, data_dir: Path | None = None) -> list[dict]:
    p = (data_dir or get_settings().dataset_dir / "data") / name
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_approvals_and_payments(data_dir: Path | None = None) -> tuple[list[dict], list[dict]]:
    return _read("approvals.csv", data_dir), _read("payments.csv", data_dir)


def check_approvals(ref: RefData, approvals: list[dict], payments: list[dict],
                    results: dict[str, ControlsResult]) -> list[Finding]:
    """What the approval records show: self-approval (P07), PO overrun without the finance step (P12),
    and the same person approving and releasing (P11). `results` is replay_bill output per invoice."""
    approved_by: dict[str, list[dict]] = {}
    for a in approvals:
        if a["action"] == "approved":
            approved_by.setdefault(a["invoice_id"], []).append(a)
    out: list[Finding] = []
    for iid, inv in ref.invoices.items():
        steps = approved_by.get(iid, [])
        amount = money(inv["total_cad"])
        for a in steps:
            if a["approver_user_id"] and a["approver_user_id"] == inv["requester_user_id"]:
                out.append(Finding("self_approval", iid,
                                   f"{a['approver_user_id']} requested {iid} and approved it themselves "
                                   f"(step {a['step_no']}, P07).",
                                   amount, {"user": a["approver_user_id"]}))
        over_po = any(f.code == "PO_OVER_BALANCE" for f in results.get(iid, ControlsResult(
            flags=[], duplicates=[], route=[], can_auto_proceed=True)).flags)
        if over_po and steps and not any(a["approver_role"] == "finance_manager" for a in steps):
            out.append(Finding("po_over_balance_no_finance", iid,
                               f"{iid} went over the remaining balance of {inv['po_id']} but was approved without "
                               f"the finance manager step (P12).",
                               amount, {"po": inv["po_id"], "approvers": [a["approver_user_id"] for a in steps]}))
    for p in payments:
        approvers = {a["approver_user_id"] for a in approved_by.get(p["invoice_id"], [])}
        if p["released_by"] and p["released_by"] in approvers:
            out.append(Finding("approved_and_released", p["invoice_id"],
                               f"{p['released_by']} approved {p['invoice_id']} and also released its payment "
                               f"{p['payment_id']} (P11).",
                               money(p["amount_cad"]), {"user": p["released_by"], "payment": p["payment_id"]}))
    return out


def check_unverified_bank_changes(ref: RefData, payments: list[dict]) -> list[Finding]:
    """Money sent, or about to be sent, after a vendor's bank account changed without a callback.

    This is a payment-time check: the bill may predate the change, but the payment doesn't.
    """
    out: list[Finding] = []
    unverified = [c for c in ref.bank_changes if c["verified_by_callback"] != "yes"]
    paid_ids = {p["invoice_id"] for p in payments}
    for c in unverified:
        changed = d(c["changed_at"])
        name = ref.vendors.get(c["vendor_id"], {}).get("legal_name", c["vendor_id"])
        for p in payments:
            if p["vendor_id"] != c["vendor_id"]:
                continue
            paid = d(p["paid_date"])
            if paid and paid >= changed:
                days = (paid - changed).days
                out.append(Finding("paid_after_unverified_bank_change", p["invoice_id"],
                                   f"{p['invoice_id']} ({name}) was paid on {human_date(paid)}, {days} days after its "
                                   f"bank account changed on {human_date(changed)} by "
                                   f"{channel_phrase(c['request_channel'])}, without a callback "
                                   f"(…{c['old_account_last4']} → …{c['new_account_last4']}).",
                                   money(p["amount_cad"]),
                                   {"change": c["change_id"], "payment": p["payment_id"], "days_after": days}))
            elif not paid and p["status"] in ("scheduled", "outstanding"):
                out.append(Finding("due_after_unverified_bank_change", p["invoice_id"],
                                   f"{p['invoice_id']} ({name}) is {status_label(p['status'])} for "
                                   f"{human_date(p['scheduled_date'])}, after an unverified bank change on "
                                   f"{human_date(changed)}. Hold it.",
                                   money(p["amount_cad"]), {"change": c["change_id"], "payment": p["payment_id"]}))
        for iid, inv in ref.invoices.items():
            if inv["vendor_id"] == c["vendor_id"] and inv["status"] == "approved" and iid not in paid_ids:
                out.append(Finding("due_after_unverified_bank_change", iid,
                                   f"{iid} ({name}) is approved and next in line to be paid, after an unverified bank "
                                   f"change on {changed}. Hold it.",
                                   money(inv["total_cad"]), {"change": c["change_id"]}))
    return out


# ---------------------------------------------------------------------------
# Double payments
# ---------------------------------------------------------------------------
@dataclass
class DoublePayment:
    """One bill that went out more than once: its copies (invoices and card charges) and the extra money."""
    ids: list[str]            # invoice ids, then card transaction ids, for the same bill
    paid: int                 # payments that actually went out (settled AP payments + card charges)
    pending: int              # AP payments scheduled or outstanding
    extra_paid_cad: Decimal   # money paid beyond the first payment
    at_risk_cad: Decimal      # pending payments that would also be extra

    @property
    def confirmed(self) -> bool:
        """Two AP invoices with the same (normalized) number. Card matches are by name, amount and date: likely."""
        return sum(1 for x in self.ids if x.startswith("AP-")) >= 2

    @property
    def status(self) -> str:
        times = {2: "twice", 3: "three times"}
        if self.paid >= 2:
            return f"paid {times.get(self.paid, f'{self.paid} times')}"
        return f"set to be paid {times.get(self.paid + self.pending, f'{self.paid + self.pending} times')}"


def double_payments(ref: RefData, results: dict[str, ControlsResult], payments: list[dict]) -> list[DoublePayment]:
    """Groups exact/normalized duplicates and card charges for the same bill, then counts the payments.

    AP-00215, AP-00224 and card charge CT-00324 are one bill paid three times: one group, two extra payments.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for iid, res in results.items():
        for m in res.duplicates:
            other = m.matched_invoice_id if m.kind in ("exact", "normalized") else \
                m.matched_card_txn_id if m.kind == "card_paid" else None
            if other:
                parent[find(iid)] = find(other)

    pay = {p["invoice_id"]: p for p in payments}
    cards = {t["txn_id"]: t for t in ref.card_txns}
    groups: dict[str, list[str]] = {}
    for x in parent:
        groups.setdefault(find(x), []).append(x)

    out = []
    for members in groups.values():
        events = []  # (date, id, amount_cad, settled?)
        for x in members:
            if x in cards:
                events.append((d(cards[x]["posted_date"]), x, money(cards[x]["amount_cad"]), True))
            elif x in pay:
                p = pay[x]
                when = d(p["paid_date"]) or d(p["scheduled_date"])
                events.append((when, x, money(p["amount_cad"]), p["status"] == "settled"))
        events.sort(key=lambda e: (e[0] or date.max, e[1]))
        settled = [e for e in events if e[3]]
        pending = [e for e in events if not e[3]]
        if len(events) < 2:
            continue
        first = settled[0] if settled else events[0]
        extra = sum((e[2] for e in settled if e is not first), Decimal("0"))
        risk = sum((e[2] for e in pending if e is not first), Decimal("0"))
        out.append(DoublePayment(sorted(members), len(settled), len(pending), extra, risk))
    return sorted(out, key=lambda g: -(g.extra_paid_cad + g.at_risk_cad))


# ---------------------------------------------------------------------------
# Whole replay
# ---------------------------------------------------------------------------
@dataclass
class Replay:
    results: dict[str, ControlsResult]
    findings: list[Finding]
    doubles: list[DoublePayment]

    def flag_counts(self) -> Counter:
        """Bills per flag code (warn and block only). Each duplicate pair / split group counts once."""
        c: Counter = Counter()
        for res in self.results.values():
            for code in {f.code for f in res.flags if f.severity != Severity.INFO}:
                c[code] += 1
        return c


def replay(ref: RefData, data_dir: Path | None = None) -> Replay:
    approvals, payments = load_approvals_and_payments(data_dir)
    order = sorted(ref.invoices, key=lambda i: _order(ref.invoices[i]))
    results = {iid: replay_bill(ref, iid) for iid in order}
    findings = check_unverified_bank_changes(ref, payments) + check_approvals(ref, approvals, payments, results)
    return Replay(results, findings, double_payments(ref, results, payments))
