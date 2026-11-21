"""
DB-backed RefData: render the database as the CSV rows controls.build_refdata reads, and let controls build it.

Owner: DB team.

Design rule: nothing here interprets the data. rows_as_csv() turns tables back into exactly the rows
load_refdata() reads from disk (one list of string dicts per stem in REFDATA_FILES, with the CSV column names), and
refdata_from_db() hands them to controls' own build_refdata(). Policy parsing, tax splitting and DraftBill
construction stay in app.controls.

Rendering rules (the inverse of the seed):
- money: cents -> 2 decimals ("742.30"). The CSVs sometimes write whole amounts without decimals ("500000");
  controls parses both with Decimal, so the value is the same.
- rates, quantities and unit prices: the stored exact text. Dates: ISO. Booleans: yes / no.
- tax_codes.recoverable NULL -> "n/a" (that's what NULL meant when seeded). Any other NULL -> "".
- vendors: bank columns from the vendor's open vendor_bank_accounts row; bank_details_updated_at = the date of the
  bank change that row came from (blank if none), which reproduces the CSV.
- bank_change_history: every history row; app rows only once verified (an app change reaches the vendor only after
  verification). A pending or rejected app request is left out, or controls would raise BANK_CHANGE_UNVERIFIED for
  a bank account that was never changed.
- invoices / invoice_lines: history and app bills, minus status 'void' and minus `exclude_bill_id`. Status passes
  through unchanged: controls only treats 'rejected' specially (duplicates.py, validate.py NTE and PO balance).
- approval_policies: from the policies table, so admin edits flow through.
Rows come out in primary-key order, which is the CSV order for every file controls iterates (tax_codes is the only
file not in key order on disk, and controls only looks tax codes up by key).

Read-only: queries run with autoflush off, so even pending changes in the caller's session are not flushed, and
nothing is ever written or committed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.controls import REFDATA_FILES, RefData, build_refdata
from app.controls.refdata import FEDERAL_TAX, PROVINCIAL_TAX
from app.db import models
from app.db.types import from_cents

CsvRow = dict[str, str]

# Column names of each dataset CSV, in file order. tests/db/test_refdata_parity.py checks them against the files.
CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "vendors": ("vendor_id", "legal_name", "category", "default_gl_account", "address", "province_or_state",
                "country", "gst_hst_number", "qst_number", "payment_terms_days", "early_pay_discount",
                "preferred_payment_method", "accepts_card_payment", "bank_institution", "bank_transit",
                "bank_account", "bank_details_updated_at", "ap_contact_email", "requires_po", "status",
                "onboarded_at"),
    "users": ("user_id", "full_name", "email", "title", "department_id", "manager_id", "role", "approval_limit_cad",
              "work_province", "status", "status_since", "delegate_user_id", "hire_date"),
    "departments": ("department_id", "name", "cost_centre", "annual_budget_cad", "manager_user_id"),
    "contracts": ("contract_id", "vendor_id", "description", "billing_type", "monthly_fee", "currency",
                  "hourly_rate_cap", "fuel_surcharge_cap_pct", "not_to_exceed_monthly", "start_date", "end_date",
                  "auto_renew", "status"),
    "purchase_orders": ("po_id", "vendor_id", "department_id", "requester_user_id", "issue_date", "description",
                        "total_amount", "currency", "status", "approved_by"),
    "tax_codes": ("code", "description", "rate", "applies_to", "recoverable", "gl_account"),
    "fx_rates": ("date", "usd_to_cad"),
    "bank_change_history": ("change_id", "vendor_id", "changed_at", "changed_by_user_id", "request_channel",
                            "verified_by_callback", "old_account_last4", "new_account_last4"),
    "invoices": ("invoice_id", "vendor_id", "vendor_invoice_number", "invoice_date", "received_date", "due_date",
                 "currency", "subtotal", "gst_hst_amount", "pst_qst_amount", "total", "fx_rate_to_cad", "total_cad",
                 "department_id", "requester_user_id", "po_id", "contract_id", "ship_to_province", "status"),
    "invoice_lines": ("invoice_id", "line_no", "description", "quantity", "unit_price", "amount", "gl_account",
                      "department_id", "gst_hst_code", "pst_qst_code", "line_type"),
    "card_transactions": ("txn_id", "card_id", "cardholder_user_id", "posted_date", "merchant_descriptor", "mcc",
                          "amount", "currency", "amount_cad", "source", "receipt_attached", "memo"),
    "approval_policies": ("rule_id", "rule_type", "condition", "required", "notes"),
}

EXCLUDED_BILL_STATUSES = ("void",)  # never visible to controls
CODED_STATUSES = ("accepted", "overridden")  # bill_lines whose gl_account / department_id are final


# ---------------------------------------------------------------- value rendering


def _text(value: Any) -> str:
    """Any value as CSV text; NULL -> ""."""
    return "" if value is None else str(value)


def _money(cents: int | None) -> str:
    """Integer cents as a 2-decimal amount ("742.30"); NULL -> ""."""
    return "" if cents is None else str(from_cents(cents))


def _date(value: date | datetime | None) -> str:
    """A date (or the date part of a timestamp) as ISO "YYYY-MM-DD"; NULL -> ""."""
    if value is None:
        return ""
    return (value.date() if isinstance(value, datetime) else value).isoformat()


def _yes_no(value: bool | None, *, null: str = "") -> str:
    """A boolean in the CSVs' yes / no form; NULL -> `null` ("" unless the CSV used something else)."""
    if value is None:
        return null
    return "yes" if value else "no"


def _rows(session: Session, table: Table) -> list[RowMapping]:
    """Every row of a table, in primary-key order."""
    return list(session.execute(select(table).order_by(*table.primary_key.columns)).mappings())


def _shape(stem: str, values: dict[str, str]) -> CsvRow:
    """One rendered row with exactly the CSV's columns, in file order. A missing or extra column is a bug here."""
    columns = CSV_COLUMNS[stem]
    if set(values) != set(columns):
        raise AssertionError(f"{stem}: rendered columns {sorted(values)} differ from the CSV's {sorted(columns)}")
    return {column: values[column] for column in columns}


# ---------------------------------------------------------------- one renderer per stem


def _vendors(session: Session) -> list[CsvRow]:
    """vendors.csv: the vendor master plus the bank details of each vendor's open bank account."""
    accounts = models.VendorBankAccount.__table__
    open_accounts = {a["vendor_id"]: a for a in session.execute(
        select(accounts).where(accounts.c.valid_to.is_(None))).mappings()}
    change_dates = {c.change_id: c.requested_at for c in session.execute(
        select(models.BankChangeRequest.change_id, models.BankChangeRequest.requested_at))}
    out = []
    for v in _rows(session, models.Vendor.__table__):
        account = open_accounts.get(v["vendor_id"])
        changed = change_dates.get(account["source_change_id"]) if account and account["source_change_id"] else None
        out.append(_shape("vendors", {
            "vendor_id": v["vendor_id"], "legal_name": v["legal_name"], "category": v["category"],
            "default_gl_account": _text(v["default_gl_account"]), "address": v["address"],
            "province_or_state": v["province_or_state"], "country": v["country"],
            "gst_hst_number": _text(v["gst_hst_number"]), "qst_number": _text(v["qst_number"]),
            "payment_terms_days": _text(v["payment_terms_days"]), "early_pay_discount": _text(v["early_pay_discount"]),
            "preferred_payment_method": v["preferred_payment_method"],
            "accepts_card_payment": _yes_no(v["accepts_card_payment"]),
            "bank_institution": _text(account["institution"]) if account else "",
            "bank_transit": _text(account["transit"]) if account else "",
            "bank_account": _text(account["account"]) if account else "",
            "bank_details_updated_at": _date(changed),
            "ap_contact_email": v["ap_contact_email"], "requires_po": _yes_no(v["requires_po"]),
            "status": v["status"], "onboarded_at": _date(v["onboarded_at"]),
        }))
    return out


def _users(session: Session) -> list[CsvRow]:
    """users.csv."""
    return [_shape("users", {
        "user_id": u["user_id"], "full_name": u["full_name"], "email": u["email"], "title": u["title"],
        "department_id": u["department_id"], "manager_id": _text(u["manager_id"]), "role": u["role"],
        "approval_limit_cad": _money(u["approval_limit_cad_cents"]), "work_province": u["work_province"],
        "status": u["status"], "status_since": _date(u["status_since"]),
        "delegate_user_id": _text(u["delegate_user_id"]), "hire_date": _date(u["hire_date"]),
    }) for u in _rows(session, models.User.__table__)]


def _departments(session: Session) -> list[CsvRow]:
    """departments.csv."""
    return [_shape("departments", {
        "department_id": d["department_id"], "name": d["name"], "cost_centre": d["cost_centre"],
        "annual_budget_cad": _money(d["annual_budget_cad_cents"]), "manager_user_id": d["manager_user_id"],
    }) for d in _rows(session, models.Department.__table__)]


def _contracts(session: Session) -> list[CsvRow]:
    """contracts.csv."""
    return [_shape("contracts", {
        "contract_id": c["contract_id"], "vendor_id": c["vendor_id"], "description": c["description"],
        "billing_type": c["billing_type"], "monthly_fee": _money(c["monthly_fee_cents"]), "currency": c["currency"],
        "hourly_rate_cap": _money(c["hourly_rate_cap_cents"]),
        "fuel_surcharge_cap_pct": _text(c["fuel_surcharge_cap_pct"]),
        "not_to_exceed_monthly": _money(c["not_to_exceed_monthly_cents"]), "start_date": _date(c["start_date"]),
        "end_date": _date(c["end_date"]), "auto_renew": _yes_no(c["auto_renew"]), "status": c["status"],
    }) for c in _rows(session, models.Contract.__table__)]


def _purchase_orders(session: Session) -> list[CsvRow]:
    """purchase_orders.csv."""
    return [_shape("purchase_orders", {
        "po_id": p["po_id"], "vendor_id": p["vendor_id"], "department_id": p["department_id"],
        "requester_user_id": p["requester_user_id"], "issue_date": _date(p["issue_date"]),
        "description": p["description"], "total_amount": _money(p["total_amount_cents"]), "currency": p["currency"],
        "status": p["status"], "approved_by": p["approved_by"],
    }) for p in _rows(session, models.PurchaseOrder.__table__)]


def _tax_codes(session: Session) -> list[CsvRow]:
    """tax_codes.csv. recoverable NULL is rendered "n/a" (EXEMPT, FOREIGN), as in the CSV."""
    return [_shape("tax_codes", {
        "code": t["code"], "description": t["description"], "rate": t["rate"], "applies_to": t["applies_to"],
        "recoverable": _yes_no(t["recoverable"], null="n/a"), "gl_account": _text(t["gl_account"]),
    }) for t in _rows(session, models.TaxCode.__table__)]


def _fx_rates(session: Session) -> list[CsvRow]:
    """fx_rates.csv (the stored exact rate text)."""
    return [_shape("fx_rates", {"date": _date(f["date"]), "usd_to_cad": f["usd_to_cad"]})
            for f in _rows(session, models.FxRate.__table__)]


def _bank_change_history(session: Session) -> list[CsvRow]:
    """bank_change_history.csv: every history row, plus app requests that were verified (never pending or rejected).

    A verified app request is rendered with verified_by_callback "yes": the app only applies a bank change to the
    vendor after verifying it, which is what controls reads this column for.
    """
    out = []
    for c in _rows(session, models.BankChangeRequest.__table__):
        if c["origin"] == "app" and c["status"] != "verified":
            continue
        verified = True if c["origin"] == "app" else c["verified_by_callback"]
        out.append(_shape("bank_change_history", {
            "change_id": c["change_id"], "vendor_id": c["vendor_id"], "changed_at": _date(c["requested_at"]),
            "changed_by_user_id": _text(c["requested_by"]), "request_channel": c["request_channel"],
            "verified_by_callback": _yes_no(verified), "old_account_last4": _text(c["old_account_last4"]),
            "new_account_last4": _text(c["new_account_last4"]),
        }))
    return out


def _tax_totals(session: Session) -> dict[str, tuple[int, int]]:
    """Per bill, (GST/HST cents, PST/QST cents) summed from bill_taxes: the inverse of controls' history_taxes.

    Codes are bucketed with controls' own FEDERAL_TAX / PROVINCIAL_TAX sets. EXEMPT and FOREIGN are in neither set and
    carry rate 0 (amount 0): history_taxes never builds them from the CSV either, so they add nothing here.
    """
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for bill_id, code, cents in session.execute(select(models.BillTax.bill_id, models.BillTax.tax_code,
                                                       models.BillTax.amount_cents)):
        if code in FEDERAL_TAX:
            totals[bill_id][0] += cents
        elif code in PROVINCIAL_TAX:
            totals[bill_id][1] += cents
    return {bill_id: (fed, prov) for bill_id, (fed, prov) in totals.items()}


def _invoices_and_lines(session: Session, exclude_bill_id: str | None) -> tuple[list[CsvRow], list[CsvRow]]:
    """invoices.csv and invoice_lines.csv from bills / bill_lines: history and app bills, minus void ones and the
    excluded bill. A line's gl_account / department_id are rendered only once its coding is final (accepted or
    overridden); a suggestion isn't coding."""
    taxes = _tax_totals(session)
    invoices, included = [], set()
    for b in _rows(session, models.Bill.__table__):
        if b["status"] in EXCLUDED_BILL_STATUSES or b["bill_id"] == exclude_bill_id:
            continue
        included.add(b["bill_id"])
        fed, prov = taxes.get(b["bill_id"], (0, 0))
        invoices.append(_shape("invoices", {
            "invoice_id": b["bill_id"], "vendor_id": _text(b["vendor_id"]),
            "vendor_invoice_number": b["vendor_invoice_number"], "invoice_date": _date(b["invoice_date"]),
            "received_date": _date(b["received_date"]), "due_date": _date(b["due_date"]), "currency": b["currency"],
            "subtotal": _money(b["subtotal_cents"]), "gst_hst_amount": _money(fed), "pst_qst_amount": _money(prov),
            "total": _money(b["total_cents"]), "fx_rate_to_cad": b["fx_rate_to_cad"],
            "total_cad": _money(b["total_cad_cents"]), "department_id": _text(b["department_id"]),
            "requester_user_id": _text(b["requester_user_id"]), "po_id": _text(b["po_id"]),
            "contract_id": _text(b["contract_id"]), "ship_to_province": _text(b["ship_to_province"]),
            "status": b["status"],
        }))
    lines = []
    for ln in _rows(session, models.BillLine.__table__):
        if ln["bill_id"] not in included:
            continue
        coded = ln["coding_status"] in CODED_STATUSES
        lines.append(_shape("invoice_lines", {
            "invoice_id": ln["bill_id"], "line_no": str(ln["line_no"]), "description": ln["description"],
            "quantity": ln["quantity"], "unit_price": ln["unit_price"], "amount": _money(ln["amount_cents"]),
            "gl_account": _text(ln["gl_account"]) if coded else "",
            "department_id": _text(ln["department_id"]) if coded else "",
            "gst_hst_code": _text(ln["gst_hst_code"]), "pst_qst_code": _text(ln["pst_qst_code"]),
            "line_type": ln["line_type"],
        }))
    return invoices, lines


def _card_transactions(session: Session) -> list[CsvRow]:
    """card_transactions.csv."""
    return [_shape("card_transactions", {
        "txn_id": t["txn_id"], "card_id": t["card_id"], "cardholder_user_id": t["cardholder_user_id"],
        "posted_date": _date(t["posted_date"]), "merchant_descriptor": t["merchant_descriptor"], "mcc": t["mcc"],
        "amount": _money(t["amount_cents"]), "currency": t["currency"], "amount_cad": _money(t["amount_cad_cents"]),
        "source": t["source"], "receipt_attached": _yes_no(t["receipt_attached"]), "memo": _text(t["memo"]),
    }) for t in _rows(session, models.CardTransaction.__table__)]


def _approval_policies(session: Session) -> list[CsvRow]:
    """approval_policies.csv from the policies table (admin edits included)."""
    return [_shape("approval_policies", {
        "rule_id": p["rule_id"], "rule_type": p["rule_type"], "condition": p["condition"],
        "required": p["required"], "notes": _text(p["notes"]),
    }) for p in _rows(session, models.Policy.__table__)]


# ---------------------------------------------------------------- public API


def rows_as_csv(session: Session, *, exclude_bill_id: str | None = None) -> dict[str, list[CsvRow]]:
    """The database as the CSV rows build_refdata reads: one list of string dicts per stem in REFDATA_FILES.

    `exclude_bill_id` leaves one bill (and its lines) out of invoices / invoice_lines. Read-only: autoflush is off,
    so pending changes in the caller's session are neither flushed nor seen.
    """
    with session.no_autoflush:
        invoices, invoice_lines = _invoices_and_lines(session, exclude_bill_id)
        rows = {
            "vendors": _vendors(session),
            "users": _users(session),
            "departments": _departments(session),
            "contracts": _contracts(session),
            "purchase_orders": _purchase_orders(session),
            "tax_codes": _tax_codes(session),
            "fx_rates": _fx_rates(session),
            "bank_change_history": _bank_change_history(session),
            "invoices": invoices,
            "invoice_lines": invoice_lines,
            "card_transactions": _card_transactions(session),
            "approval_policies": _approval_policies(session),
        }
    if set(rows) != set(REFDATA_FILES):
        raise AssertionError(f"rendered stems {sorted(rows)} differ from REFDATA_FILES {sorted(REFDATA_FILES)}")
    return {stem: rows[stem] for stem in REFDATA_FILES}


def refdata_from_db(session: Session, *, exclude_bill_id: str | None = None, as_of: date | None = None) -> RefData:
    """RefData for app.controls, built by controls' own build_refdata from the database.

    When running controls on a bill that is already stored, pass that bill's own id as `exclude_bill_id`. Otherwise
    the stored copy is in RefData's invoices and controls reports the bill as an exact duplicate of itself: a DraftBill
    rebuilt from the database carries its file hash as its id (controls.refdata.bill_id), not the bill_id, so controls
    can't tell the two apart. `as_of` defaults to the settings' as-of date (build_refdata's default). Read-only.
    """
    return build_refdata(rows_as_csv(session, exclude_bill_id=exclude_bill_id), as_of)
