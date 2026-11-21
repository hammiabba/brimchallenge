"""Loads the reference data the checks need, plus small helpers for reading a DraftBill.

Reads the CSVs for now. A database loader passes the same rows to build_refdata()
(keyed by the names in REFDATA_FILES). The checks only see the RefData object,
so they don't care where it came from.

All bill types come from schemas.py (the team contract). Nothing here defines its own.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path

from app.config import get_settings
from app.shared.schemas import (
    BankDetails,
    DraftBill,
    InvoiceLine,
    LineType,
    MatchMethod,
    SourceInfo,
    TaxCode,
    TaxLine,
    VendorOnInvoice,
)

FEDERAL_TAX = {TaxCode.HST13.value, TaxCode.GST5.value}
PROVINCIAL_TAX = {TaxCode.PST7_BC.value, TaxCode.QST9975.value}


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def d(s: str) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def money(s: str) -> Decimal:
    return Decimal(s) if s not in ("", None) else Decimal("0")


# ---------------------------------------------------------------------------
# DraftBill helpers. schemas.DraftBill has no bill id, so source.file_hash is the id for now.
# ---------------------------------------------------------------------------
def bill_id(bill: DraftBill) -> str:
    return bill.source.file_hash


def vendor_id(bill: DraftBill) -> str | None:
    return bill.vendor.vendor_id


def currency(bill: DraftBill) -> str:
    """The bill's currency code, normalized: ' cad' -> 'CAD'. Missing means CAD."""
    return (bill.currency or "CAD").strip().upper() or "CAD"


def given_fx_rate(bill: DraftBill) -> Decimal | None:
    """The FX rate printed on / extracted from the bill, if one was actually given.

    fx_rate_to_cad defaults to 1 in the schema, so 1 on a foreign bill means "not given".
    """
    rate = bill.fx_rate_to_cad
    if "fx_rate_to_cad" not in bill.model_fields_set or rate is None or rate <= 0 or rate == 1:
        return None
    return rate


def is_credit(bill: DraftBill) -> bool:
    return bill.is_credit_note or bill.total < 0


def tax_amounts(bill: DraftBill) -> tuple[Decimal, Decimal]:
    """(GST/HST charged, PST/QST charged) from the bill's tax lines."""
    fed = sum((t.amount for t in bill.taxes if t.code.value in FEDERAL_TAX), Decimal("0"))
    prov = sum((t.amount for t in bill.taxes if t.code.value in PROVINCIAL_TAX), Decimal("0"))
    return fed, prov


@dataclass
class Policy:
    rule_id: str
    rule_type: str
    condition: str
    required: str
    threshold: Decimal | None   # parsed "$10,000" -> 10000, None if the rule has no amount


@dataclass
class RefData:
    vendors: dict[str, dict]
    users: dict[str, dict]
    departments: dict[str, dict]
    contracts: dict[str, dict]
    purchase_orders: dict[str, dict]
    tax_codes: dict[str, dict]
    fx: dict[date, Decimal]
    bank_changes: list[dict]
    invoices: dict[str, dict]
    invoice_lines: dict[str, list[dict]]
    card_txns: list[dict]
    policies: dict[str, Policy]
    as_of: date = field(default_factory=lambda: get_settings().as_of_date)  # the system's "today"

    # ---- small lookups used everywhere ----
    def fx_rate(self, on: date) -> Decimal | None:
        """USD->CAD rate for a date. Weekends/holidays fall back to the last earlier rate."""
        for back in range(0, 7):
            r = self.fx.get(on - timedelta(days=back))
            if r is not None:
                return r
        return None

    def contract_for(self, bill: DraftBill) -> dict | None:
        if bill.contract_id and bill.contract_id in self.contracts:
            return self.contracts[bill.contract_id]
        for c in self.contracts.values():
            if c["vendor_id"] == vendor_id(bill):
                return c
        return None

    def users_with_role(self, role: str) -> list[dict]:
        return [u for u in self.users.values() if u["role"] == role]


def parse_threshold(condition: str) -> Decimal | None:
    m = re.search(r"\$([\d,]+)", condition)
    return Decimal(m.group(1).replace(",", "")) if m else None


# The CSV stems load_refdata reads. A DB-backed loader supplies the same rows under the same names.
REFDATA_FILES: tuple[str, ...] = (
    "vendors", "users", "departments", "contracts", "purchase_orders", "tax_codes", "fx_rates",
    "bank_change_history", "invoices", "invoice_lines", "card_transactions", "approval_policies",
)


def build_refdata(rows_by_file: dict[str, list[dict[str, str]]], as_of: date | None = None) -> RefData:
    """Builds RefData from rows keyed by CSV stem (see REFDATA_FILES), each row a dict of strings as csv gives.

    The CSV loader and a database loader both go through here, so the checks see identical data either way.
    as_of defaults to the fixed as-of date from settings.
    """
    rows = rows_by_file
    lines: dict[str, list[dict]] = {}
    for row in rows["invoice_lines"]:
        lines.setdefault(row["invoice_id"], []).append(row)

    policies = {
        r["rule_id"]: Policy(r["rule_id"], r["rule_type"], r["condition"], r["required"],
                             parse_threshold(r["condition"]))
        for r in rows["approval_policies"]
    }

    return RefData(
        vendors={r["vendor_id"]: r for r in rows["vendors"]},
        users={r["user_id"]: r for r in rows["users"]},
        departments={r["department_id"]: r for r in rows["departments"]},
        contracts={r["contract_id"]: r for r in rows["contracts"]},
        purchase_orders={r["po_id"]: r for r in rows["purchase_orders"]},
        tax_codes={r["code"]: r for r in rows["tax_codes"]},
        fx={d(r["date"]): Decimal(r["usd_to_cad"]) for r in rows["fx_rates"]},
        bank_changes=list(rows["bank_change_history"]),
        invoices={r["invoice_id"]: r for r in rows["invoices"]},
        invoice_lines=lines,
        card_txns=list(rows["card_transactions"]),
        policies=policies,
        as_of=as_of if as_of is not None else get_settings().as_of_date,
    )


def load_refdata(data_dir: Path | str | None = None) -> RefData:
    """Reads the dataset CSVs. Defaults to the repo's copy (settings.dataset_dir / "data")."""
    p = Path(data_dir) if data_dir is not None else get_settings().dataset_dir / "data"
    return build_refdata({stem: _read(p / f"{stem}.csv") for stem in REFDATA_FILES})


@cache
def default_refdata() -> RefData:
    """Loaded once per process, for callers that don't pass their own RefData."""
    return load_refdata()


def history_taxes(ref: RefData, inv: dict, lines: list[dict]) -> list[TaxLine]:
    """History stores tax as two amounts; the line tax codes say which code each amount is."""
    out = []
    for amount, codes, fallback in (
        (money(inv["gst_hst_amount"]), [ln["gst_hst_code"] for ln in lines],
         "HST13" if inv["ship_to_province"] == "ON" else "GST5"),
        (money(inv["pst_qst_amount"]), [ln["pst_qst_code"] for ln in lines],
         "QST9975" if inv["ship_to_province"] == "QC" else "PST7_BC"),
    ):
        if not amount:
            continue
        code = next((c for c in codes if c in FEDERAL_TAX | PROVINCIAL_TAX), fallback)
        out.append(TaxLine(code=TaxCode(code), rate=Decimal(ref.tax_codes[code]["rate"]), amount=amount))
    return out


_history_taxes = history_taxes  # old private name, kept so existing imports don't break


def bill_from_history(ref: RefData, invoice_id: str) -> DraftBill:
    """Turns a historical invoice into a DraftBill. Used for tests and the history replay.

    History has no bank details or GST number on the invoice, so we copy the
    vendor master values (i.e. assume the invoice matched the master). The exception is bank details on an invoice
    dated before a later bank change: the master's current account wasn't in use then, and only the old account's
    last 4 digits are on record, so the bank is left empty rather than invented.
    file_hash is set to the invoice id, so history rows and replayed bills share one id.
    """
    i = ref.invoices[invoice_id]
    v = ref.vendors.get(i["vendor_id"], {})
    rows = ref.invoice_lines.get(invoice_id, [])
    changed_later = any(c["vendor_id"] == i["vendor_id"] and c["changed_at"][:10] > i["invoice_date"][:10]
                        for c in ref.bank_changes)
    bank = BankDetails() if changed_later else BankDetails(institution=v.get("bank_institution") or None,
                                                           transit=v.get("bank_transit") or None,
                                                           account=v.get("bank_account") or None)
    return DraftBill(
        source=SourceInfo(file_name=f"{invoice_id}.pdf", file_hash=invoice_id),
        vendor=VendorOnInvoice(
            name_on_invoice=v.get("legal_name", ""),
            gst_number=v.get("gst_hst_number") or None,
            qst_number=v.get("qst_number") or None,
            bank=bank,
            vendor_id=i["vendor_id"],
            match_method=MatchMethod.GST_NUMBER if v.get("gst_hst_number") else MatchMethod.BANK_ACCOUNT,
            match_score=1.0,
        ),
        invoice_number=i["vendor_invoice_number"],
        invoice_date=d(i["invoice_date"]),
        due_date=d(i["due_date"]),
        payment_terms_days=int(v["payment_terms_days"]) if v.get("payment_terms_days") else None,
        currency=i["currency"],
        ship_to_province=i["ship_to_province"] or None,
        po_number=i["po_id"] or None,
        contract_id=i["contract_id"] or None,
        requester_user_id=i["requester_user_id"] or None,
        department_id=i["department_id"] or None,
        lines=[
            InvoiceLine(
                line_no=int(ln["line_no"]),
                description=ln["description"],
                quantity=money(ln["quantity"]),
                unit_price=money(ln["unit_price"]),
                amount=money(ln["amount"]),
                line_type=LineType(ln["line_type"] or "services"),
            )
            for ln in rows
        ],
        subtotal=money(i["subtotal"]),
        taxes=history_taxes(ref, i, rows),
        total=money(i["total"]),
        fx_rate_to_cad=money(i["fx_rate_to_cad"]) or Decimal("1"),
        total_cad=money(i["total_cad"]),
    )
