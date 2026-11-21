"""Controls on the incoming batch: every extracted bill, checked together, plus a report.

Used by scripts/run_incoming.py. That script does the extraction (Person A's intake/extraction code);
this module takes the results, runs run_controls() on all bills as ONE batch (so duplicates and splits inside the
batch are caught), sorts problem bills first and renders the report. No LLM or network here.

Department: invoices don't print one, so DraftBill.department_id is usually None and routing would have no
department manager. When it's missing, the department the line coding suggestions give the most money to is used,
and the report marks it as suggested.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from app.shared.schemas import ControlsResult, DraftBill, Severity

from .engine import run_controls
from .refdata import RefData, bill_id, currency, default_refdata, is_credit

# Report order: worst first
LEVELS = ["unreadable", "hold", "review", "ok"]
LEVEL_TITLE = {
    "unreadable": "COULD NOT BE READ (extraction failed: nothing was checked)",
    "hold": "HOLD (at least one block flag)",
    "review": "REVIEW (warnings only)",
    "ok": "CAN PROCEED",
}


@dataclass
class IncomingItem:
    """One attachment from the inbox (or a loose file), before and after controls."""
    file_name: str
    status: str                               # extraction status: "ok" | "failed" | "llm_skipped"
    bill: DraftBill | None = None
    email_id: str | None = None
    email_class: str | None = None            # "invoice" | "credit_note" | ... from the email triage
    sender: str | None = None
    error: str | None = None
    department_source: str | None = None      # "invoice" | "coding" | None
    result: ControlsResult | None = None
    extraction_warnings: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        if self.bill is None or self.result is None:
            return "unreadable"
        if any(f.severity == Severity.BLOCK for f in self.result.flags):
            return "hold"
        if any(f.severity == Severity.WARN for f in self.result.flags):
            return "review"
        return "ok"


def with_department(bill: DraftBill) -> tuple[DraftBill, str | None]:
    """Fills department_id from the line coding suggestions when the invoice gives none.

    Picks the department the suggestions assign the most money to. Returns (bill, source).
    """
    if bill.department_id:
        return bill, "invoice"
    weight: Counter = Counter()
    for line in bill.lines:
        if line.coding and line.coding.department_id:
            weight[line.coding.department_id] += abs(line.amount)
    if not weight:
        return bill, None
    dept = max(sorted(weight), key=lambda k: weight[k])
    return bill.model_copy(update={"department_id": dept}), "coding"


def run_batch(items: list[IncomingItem], ref: RefData | None = None) -> list[IncomingItem]:
    """Runs run_controls on every readable bill, with all readable bills as the batch. Sorted worst first."""
    ref = ref or default_refdata()
    for it in items:
        if it.bill is not None:
            it.bill, it.department_source = with_department(it.bill)
            it.extraction_warnings = list(it.bill.extraction_warnings)
    batch = [it.bill for it in items if it.bill is not None]
    for it in items:
        if it.bill is not None:
            it.result = run_controls(it.bill, batch, ref=ref)
    return sorted(items, key=lambda it: (LEVELS.index(it.level), it.email_id or "~", it.file_name))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _money(bill: DraftBill) -> str:
    return f"{currency(bill)} {bill.total:,.2f}"


def _vendor(it: IncomingItem) -> str:
    if it.bill is None:
        return "?"
    v = it.bill.vendor
    return f"{v.vendor_id or 'NOT IN MASTER'} {v.name_on_invoice}"


def _names(its: list[IncomingItem], limit: int = 10) -> str:
    names = [it.file_name for it in its]
    return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")


def top_findings(items: list[IncomingItem]) -> list[str]:
    """Short lines for the top of the report: unreadable files, then each block code with its bills."""
    out = []
    unreadable = [it for it in items if it.level == "unreadable"]
    if unreadable:
        out.append(f"{len(unreadable)} file(s) could not be read, so nothing was checked: {_names(unreadable)}")
    by_code: dict[str, list[IncomingItem]] = {}
    for it in items:
        if it.result:
            for code in dict.fromkeys(f.code for f in it.result.flags if f.severity == Severity.BLOCK):
                by_code.setdefault(code, []).append(it)
    for code, its in sorted(by_code.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append(f"{code}: {len(its)} bill(s): {_names(its)}")
    batch_dups = [it for it in items if it.result and any(
        m.matched_invoice_id and not m.matched_invoice_id.startswith("AP-") for m in it.result.duplicates)]
    if batch_dups:
        out.append(f"Duplicates inside this batch: {len(batch_dups)} bill(s): {_names(batch_dups)}")
    return out


def summary(items: list[IncomingItem]) -> dict:
    levels = Counter(it.level for it in items)
    flags: Counter = Counter()
    for it in items:
        if it.result:
            for code in {f.code for f in it.result.flags}:
                flags[code] += 1
    readable = [it for it in items if it.bill is not None]
    return {
        "files": len(items),
        "readable": len(readable),
        "levels": {lv: levels.get(lv, 0) for lv in LEVELS},
        "credit_notes": sum(1 for it in readable if is_credit(it.bill)),
        "foreign_currency": sum(1 for it in readable if currency(it.bill) != "CAD"),
        "unknown_vendor": sum(1 for it in readable if not it.bill.vendor.vendor_id),
        "department_from_coding": sum(1 for it in readable if it.department_source == "coding"),
        "no_department": sum(1 for it in readable if it.department_source is None),
        "flags": dict(flags.most_common()),
        "total_cad_on_hold": sum((it.bill.total_cad for it in readable if it.level == "hold"), Decimal("0")),
    }


def _readable_ids(items: list[IncomingItem]) -> dict[str, str]:
    """Batch bills are matched by their internal id (a file hash); the report shows the file name instead."""
    return {bill_id(it.bill): it.file_name for it in items if it.bill is not None}


def _named(text: str, names: dict[str, str]) -> str:
    for bid, name in names.items():
        text = text.replace(bid, name)
    return text


def _bill_block(it: IncomingItem, names: dict[str, str] | None = None) -> list[str]:
    names = names or {}
    head = f"{it.file_name}  [{it.email_id or 'no email'}]"
    if it.bill is None:
        return [head, f"    extraction {it.status}: {it.error or 'no detail'}"]
    b, r = it.bill, it.result
    lines = [head,
             f"    vendor   {_vendor(it)}",
             f"    invoice  {b.invoice_number}  dated {b.invoice_date}  total {_money(b)}"
             + (f" (CAD {b.total_cad:,.2f})" if currency(b) != "CAD" else "")
             + ("  CREDIT NOTE" if is_credit(b) else "")]
    if it.sender:
        lines.append(f"    sender   {it.sender}")
    for f in r.flags:
        lines.append(f"    {f.severity.value.upper():5} {f.code}: {_named(f.message, names)}")
    for m in r.duplicates:
        lines.append(_named(f"    dup   {m.kind} {m.matched_invoice_id or m.matched_card_txn_id} "
                            f"(score {m.score:.2f}): {'; '.join(m.reasons)}", names))
    if is_credit(b):
        lines.append("    route    none: credit note, apply it against an open invoice")
    else:
        dept = f"{b.department_id or 'none'}" + (" (suggested by coding)" if it.department_source == "coding" else "")
        lines.append(f"    route    department {dept}: "
                     + " → ".join(f"{s.role} {s.user_id}" + (f" (for {s.delegated_from})" if s.delegated_from else "")
                                  for s in r.route))
    lines.append(f"    proceed  {'yes' if r.can_auto_proceed else 'NO: ' + (r.recommendation or '')}")
    for w in it.extraction_warnings:
        lines.append(f"    extract  {w}")
    return lines


def render_report(items: list[IncomingItem], no_bill_emails: Iterable[tuple[str, str, str]] = ()) -> str:
    """items must come from run_batch (sorted worst first). no_bill_emails: (email_id, class, reason)."""
    names = _readable_ids(items)
    out = [f"Incoming batch: {len(items)} file(s), checked together as one batch", "", "TOP FINDINGS", ""]
    out += [f"  - {line}" for line in top_findings(items)] or ["  - nothing on hold"]
    for level in LEVELS:
        group = [it for it in items if it.level == level]
        if not group:
            continue
        out += ["", "", f"{LEVEL_TITLE[level]}: {len(group)}", ""]
        for it in group:
            out += _bill_block(it, names) + [""]
    no_bill = list(no_bill_emails)
    if no_bill:
        out += ["", "EMAILS WITH NO BILL", ""]
        out += [f"  {eid}  {cls:20} {reason}" for eid, cls, reason in no_bill]
    s = summary(items)
    out += ["", "SUMMARY", "",
            f"  Files                              {s['files']}",
            f"  Read by extraction                 {s['readable']}",
            *[f"  {LEVEL_TITLE[lv].split(' (')[0].title():34} {s['levels'][lv]}" for lv in LEVELS],
            f"  Credit notes                       {s['credit_notes']}",
            f"  Foreign currency                   {s['foreign_currency']}",
            f"  Vendor not in master               {s['unknown_vendor']}",
            f"  Department from coding / none      {s['department_from_coding']} / {s['no_department']}",
            f"  Total on hold (CAD)                {s['total_cad_on_hold']:,.2f}",
            "", "  Bills per flag code:"]
    out += [f"    {code:28} {n}" for code, n in s["flags"].items()]
    return "\n".join(out)
