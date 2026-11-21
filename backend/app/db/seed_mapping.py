"""
Pure mapping from dataset rows (all strings) to column values for one table row. No database access.

Owner: DB team. Used by app.db.seed; kept separate so every rule can be unit-tested without a database.

How values are read (all CSVs are read as strings, so "004" and blanks survive):
- Blank string -> None (NULL). Whether NULL is allowed is decided later by the pre-flight, from the schema.
- Money -> Decimal -> integer cents. A value with more than 2 decimal places is NOT rounded: it is an error.
- Rates, quantities, unit prices -> exact decimal TEXT (types.dec_to_text), never through float.
- Booleans: yes/true -> True, no/false -> False, n/a -> None. Anything else is an error.
- Dates are ISO (YYYY-MM-DD). Timestamps are ISO; one without a zone is taken to be UTC and stored naive UTC.

A problem with a value never raises out of a mapping function. It is recorded as a Violation, so one run of the
seed reports every bad row at once.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.controls.duplicates import norm_invoice_no  # the exact normalization controls uses (public)
from app.controls.refdata import RefData, _history_taxes  # private: ask Hamid to make _history_taxes public
from app.db.types import dec_to_text, to_cents, to_utc

# Columns go into the database as plain dicts keyed by column name.
Row = dict[str, Any]


class DataQualityError(ValueError):
    """A dataset value that can't be stored without changing its meaning (e.g. money with 3 decimals)."""


@dataclass(frozen=True)
class Violation:
    """One reason the seed must not run: which rule, which table and row, and what was wrong."""

    rule: str  # "money_precision", "not_null", "enum", "foreign_key", "releaser_not_preparer", ...
    table: str
    row_id: str
    detail: str


# ---------------------------------------------------------------- value parsers (raise on bad input)

_TRUE = {"yes", "true"}
_FALSE = {"no", "false"}
_NOT_APPLICABLE = {"n/a"}


def blank_to_none(value: str | None) -> str | None:
    """Return None for a missing or blank cell, else the value unchanged (no stripping of leading zeros)."""
    if value is None or value.strip() == "":
        return None
    return value


def parse_money(text: str) -> Decimal:
    """Parse a money cell exactly. More than 2 decimal places is a DataQualityError, never rounded."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise DataQualityError(f"not a number: {text!r}") from exc
    if not value.is_finite():
        raise DataQualityError(f"not a finite number: {text!r}")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise DataQualityError(f"money with more than 2 decimal places: {text!r}")
    return value


def money_to_cents(text: str) -> int:
    """Money cell -> integer cents, e.g. "742.30" -> 74230, "500000" -> 50000000."""
    return to_cents(parse_money(text))


def exact_decimal_text(text: str) -> str:
    """Rate / quantity / unit price cell -> exact decimal TEXT, e.g. "0.09975" -> "0.09975"."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise DataQualityError(f"not a number: {text!r}") from exc
    if not value.is_finite():
        raise DataQualityError(f"not a finite number: {text!r}")
    return dec_to_text(value)


def parse_bool(text: str) -> bool | None:
    """yes/true -> True, no/false -> False, n/a -> None (case-insensitive). Anything else is a DataQualityError."""
    word = text.strip().lower()
    if word in _TRUE:
        return True
    if word in _FALSE:
        return False
    if word in _NOT_APPLICABLE:
        return None
    raise DataQualityError(f"not a yes/no value: {text!r}")


def parse_date(text: str) -> date:
    """ISO date cell -> date."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise DataQualityError(f"not an ISO date: {text!r}") from exc


def parse_timestamp(text: str) -> datetime:
    """ISO timestamp cell -> naive UTC datetime. A value without a zone is taken to be UTC already."""
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise DataQualityError(f"not an ISO timestamp: {text!r}") from exc
    return to_utc(value)


def parse_int(text: str) -> int:
    """Integer cell -> int (no decimals allowed)."""
    try:
        return int(text.strip())
    except ValueError as exc:
        raise DataQualityError(f"not an integer: {text!r}") from exc


def midnight_utc(day: date) -> datetime:
    """A date as a naive UTC timestamp at 00:00, for history rows that only have a date."""
    return datetime.combine(day, time(0, 0))


# ---------------------------------------------------------------- reading one row, recording problems


class RowReader:
    """Reads typed values out of one dataset row. A bad value is recorded as a Violation and read as None."""

    def __init__(self, table: str, row_id: str, row: Mapping[str, Any], violations: list[Violation]) -> None:
        self.table = table
        self.row_id = row_id
        self.row = row
        self.violations = violations

    def _cell(self, column: str) -> str | None:
        """The raw cell, or None if blank. A missing column is a violation (the file doesn't match the schema)."""
        if column not in self.row:
            self.violations.append(Violation("missing_column", self.table, self.row_id, f"no column {column!r}"))
            return None
        return blank_to_none(self.row[column])

    def _parse(self, column: str, kind: str, parser: Callable[[str], Any]) -> Any:
        """Parse a non-blank cell with `parser`; record a violation named after `kind` if it fails."""
        raw = self._cell(column)
        if raw is None:
            return None
        try:
            return parser(raw)
        except DataQualityError as exc:
            rule = "money_precision" if "decimal places" in str(exc) else f"bad_{kind}"
            self.violations.append(Violation(rule, self.table, self.row_id, f"{column}: {exc}"))
            return None

    def text(self, column: str) -> str | None:
        """Text exactly as written (leading zeros kept); blank -> None."""
        return self._cell(column)

    def money(self, column: str) -> int | None:
        """Money in cents; blank -> None."""
        return self._parse(column, "money", money_to_cents)

    def decimal(self, column: str) -> str | None:
        """Exact decimal TEXT; blank -> None."""
        return self._parse(column, "decimal", exact_decimal_text)

    def boolean(self, column: str) -> bool | None:
        """yes/no/true/false -> bool, n/a or blank -> None."""
        return self._parse(column, "boolean", parse_bool)

    def date(self, column: str) -> date | None:
        """ISO date; blank -> None."""
        return self._parse(column, "date", parse_date)

    def timestamp(self, column: str) -> datetime | None:
        """ISO timestamp as naive UTC; blank -> None."""
        return self._parse(column, "timestamp", parse_timestamp)

    def integer(self, column: str) -> int | None:
        """Integer; blank -> None."""
        return self._parse(column, "integer", parse_int)


# ---------------------------------------------------------------- reference tables (1:1 from their CSVs)


def map_department(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """departments.csv -> departments. annual_budget_cad becomes annual_budget_cad_cents."""
    r = RowReader("departments", row.get("department_id", "?"), row, violations)
    return {
        "department_id": r.text("department_id"),
        "name": r.text("name"),
        "cost_centre": r.text("cost_centre"),
        "annual_budget_cad_cents": r.money("annual_budget_cad"),
        "manager_user_id": r.text("manager_user_id"),
    }


def map_user(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """users.csv -> users. approval_limit_cad becomes approval_limit_cad_cents."""
    r = RowReader("users", row.get("user_id", "?"), row, violations)
    return {
        "user_id": r.text("user_id"),
        "full_name": r.text("full_name"),
        "email": r.text("email"),
        "title": r.text("title"),
        "department_id": r.text("department_id"),
        "manager_id": r.text("manager_id"),
        "role": r.text("role"),
        "approval_limit_cad_cents": r.money("approval_limit_cad"),
        "work_province": r.text("work_province"),
        "status": r.text("status"),
        "status_since": r.date("status_since"),
        "delegate_user_id": r.text("delegate_user_id"),
        "hire_date": r.date("hire_date"),
    }


def map_gl_account(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """gl_accounts.csv -> gl_accounts."""
    r = RowReader("gl_accounts", row.get("account_number", "?"), row, violations)
    return {
        "account_number": r.text("account_number"),
        "name": r.text("name"),
        "account_type": r.text("account_type"),
        "notes": r.text("notes"),
    }


def map_tax_code(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """tax_codes.csv -> tax_codes. recoverable: yes/no -> bool, n/a -> NULL."""
    r = RowReader("tax_codes", row.get("code", "?"), row, violations)
    return {
        "code": r.text("code"),
        "description": r.text("description"),
        "rate": r.decimal("rate"),
        "applies_to": r.text("applies_to"),
        "recoverable": r.boolean("recoverable"),
        "gl_account": r.text("gl_account"),
    }


def map_vendor(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """vendors.csv -> vendors, without the bank columns (those go to vendor_bank_accounts)."""
    r = RowReader("vendors", row.get("vendor_id", "?"), row, violations)
    return {
        "vendor_id": r.text("vendor_id"),
        "legal_name": r.text("legal_name"),
        "category": r.text("category"),
        "default_gl_account": r.text("default_gl_account"),
        "address": r.text("address"),
        "province_or_state": r.text("province_or_state"),
        "country": r.text("country"),
        "gst_hst_number": r.text("gst_hst_number"),
        "qst_number": r.text("qst_number"),
        "payment_terms_days": r.integer("payment_terms_days"),
        "early_pay_discount": r.text("early_pay_discount"),
        "preferred_payment_method": r.text("preferred_payment_method"),
        "accepts_card_payment": r.boolean("accepts_card_payment"),
        "ap_contact_email": r.text("ap_contact_email"),
        "requires_po": r.boolean("requires_po"),
        "status": r.text("status"),
        "onboarded_at": r.date("onboarded_at"),
        "origin": "history",
    }


def map_contract(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """contracts.csv -> contracts. Money in cents (in `currency`); the fuel cap stays exact decimal text."""
    r = RowReader("contracts", row.get("contract_id", "?"), row, violations)
    return {
        "contract_id": r.text("contract_id"),
        "vendor_id": r.text("vendor_id"),
        "description": r.text("description"),
        "billing_type": r.text("billing_type"),
        "monthly_fee_cents": r.money("monthly_fee"),
        "currency": r.text("currency"),
        "hourly_rate_cap_cents": r.money("hourly_rate_cap"),
        "fuel_surcharge_cap_pct": r.decimal("fuel_surcharge_cap_pct"),
        "not_to_exceed_monthly_cents": r.money("not_to_exceed_monthly"),
        "start_date": r.date("start_date"),
        "end_date": r.date("end_date"),
        "auto_renew": r.boolean("auto_renew"),
        "status": r.text("status"),
    }


def map_purchase_order(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """purchase_orders.csv -> purchase_orders."""
    r = RowReader("purchase_orders", row.get("po_id", "?"), row, violations)
    return {
        "po_id": r.text("po_id"),
        "vendor_id": r.text("vendor_id"),
        "department_id": r.text("department_id"),
        "requester_user_id": r.text("requester_user_id"),
        "issue_date": r.date("issue_date"),
        "description": r.text("description"),
        "total_amount_cents": r.money("total_amount"),
        "currency": r.text("currency"),
        "status": r.text("status"),
        "approved_by": r.text("approved_by"),
    }


def map_policy(row: Mapping[str, str], loaded_at: datetime, violations: list[Violation]) -> Row:
    """approval_policies.csv -> policies. The dataset has no edit time, so updated_at is the load time given."""
    r = RowReader("policies", row.get("rule_id", "?"), row, violations)
    return {
        "rule_id": r.text("rule_id"),
        "rule_type": r.text("rule_type"),
        "condition": r.text("condition"),
        "required": r.text("required"),
        "notes": r.text("notes"),
        "updated_at": loaded_at,
        "updated_by": None,
    }


def map_fx_rate(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """fx_rates.csv -> fx_rates (the column is still called `date`)."""
    r = RowReader("fx_rates", row.get("date", "?"), row, violations)
    return {"date": r.date("date"), "usd_to_cad": r.decimal("usd_to_cad")}


def map_card_transaction(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """card_transactions.csv -> card_transactions."""
    r = RowReader("card_transactions", row.get("txn_id", "?"), row, violations)
    return {
        "txn_id": r.text("txn_id"),
        "card_id": r.text("card_id"),
        "cardholder_user_id": r.text("cardholder_user_id"),
        "posted_date": r.date("posted_date"),
        "merchant_descriptor": r.text("merchant_descriptor"),
        "mcc": r.text("mcc"),
        "amount_cents": r.money("amount"),
        "currency": r.text("currency"),
        "amount_cad_cents": r.money("amount_cad"),
        "source": r.text("source"),
        "receipt_attached": r.boolean("receipt_attached"),
        "memo": r.text("memo"),
    }


def map_bank_statement_line(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """bank_statement.csv -> bank_statement_lines (a CAD account, so debit/credit are *_cad_cents)."""
    r = RowReader("bank_statement_lines", row.get("bank_txn_id", "?"), row, violations)
    return {
        "bank_txn_id": r.text("bank_txn_id"),
        "posted_date": r.date("posted_date"),
        "description": r.text("description"),
        "debit_cad_cents": r.money("debit"),
        "credit_cad_cents": r.money("credit"),
    }


# ---------------------------------------------------------------- derived reference rows


def map_vendor_bank_account(vendor: Mapping[str, str], changes: list[Mapping[str, str]],
                            violations: list[Violation]) -> Row | None:
    """One open vendor_bank_accounts row from vendors.csv bank columns, or None if the vendor has none.

    valid_from = bank_details_updated_at, falling back to onboarded_at. source_change_id = the latest
    bank_change_history row for this vendor whose new_account_last4 matches the current account, else None.
    `changes` are that vendor's bank_change_history rows.
    """
    vendor_id = vendor.get("vendor_id", "?")
    r = RowReader("vendor_bank_accounts", vendor_id, vendor, violations)
    institution, transit, account = r.text("bank_institution"), r.text("bank_transit"), r.text("bank_account")
    if institution is None and transit is None and account is None:
        return None  # no bank details on file (card or cheque vendors)
    last4 = account[-4:] if account else None
    matching = [c for c in changes if c.get("new_account_last4") == last4]
    latest = max(matching, key=lambda c: (c.get("changed_at", ""), c.get("change_id", "")), default=None)
    return {
        "vendor_id": vendor_id,
        "institution": institution,
        "transit": transit,
        "account": account,
        "account_last4": last4,
        "valid_from": r.date("bank_details_updated_at") or r.date("onboarded_at"),
        "valid_to": None,
        "source_change_id": latest["change_id"] if latest else None,
        "origin": "history",
    }


def map_bank_change(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """bank_change_history.csv -> bank_change_requests.

    status: verified if verified_by_callback is yes, else pending_verification. requested_at = changed_at at 00:00
    UTC. History has only the last 4 digits, so the full new_* numbers are NULL; it also doesn't record who
    verified or when, so verified_by / verified_at are NULL.
    """
    r = RowReader("bank_change_requests", row.get("change_id", "?"), row, violations)
    changed_at = r.date("changed_at")
    verified = r.boolean("verified_by_callback")
    return {
        "change_id": r.text("change_id"),
        "vendor_id": r.text("vendor_id"),
        "requested_at": midnight_utc(changed_at) if changed_at else None,
        "requested_by": r.text("changed_by_user_id"),
        "request_channel": r.text("request_channel"),
        "old_account_last4": r.text("old_account_last4"),
        "new_account_last4": r.text("new_account_last4"),
        "new_institution": None,
        "new_transit": None,
        "new_account": None,
        "verified_by_callback": verified,
        "status": "verified" if verified else "pending_verification",
        "verified_by": None,
        "verified_at": None,
        "origin": "history",
    }


def map_user_absence(user: Mapping[str, str], violations: list[Violation]) -> Row | None:
    """An open-ended user_absences row for a user whose status is on_leave, else None."""
    if user.get("status") != "on_leave":
        return None
    r = RowReader("user_absences", user.get("user_id", "?"), user, violations)
    return {
        "user_id": r.text("user_id"),
        "delegate_user_id": r.text("delegate_user_id"),
        "starts_on": r.date("status_since"),
        "ends_on": None,
    }


# ---------------------------------------------------------------- bills and their children


def map_bill(row: Mapping[str, str], fx_by_date: Mapping[date, Decimal],
             violations: list[Violation]) -> tuple[Row, bool]:
    """invoices.csv -> bills. Returns (row, fx_mismatch).

    received_date comes from the CSV's received_date column. norm_invoice_number uses controls' own normalization.
    fx_rate_date: for USD, the invoice date when fx_rates.csv on that date equals the bill's fx_rate_to_cad
    (fx_mismatch=True otherwise, and the date stays NULL); for CAD, NULL. is_credit_note = total < 0.
    """
    bill_id = row.get("invoice_id", "?")
    r = RowReader("bills", bill_id, row, violations)
    invoice_date = r.date("invoice_date")
    received = r.date("received_date")
    currency = r.text("currency")
    fx_text = r.decimal("fx_rate_to_cad")
    total = r.money("total")

    fx_rate_date, mismatch = None, False
    if currency == "USD" and invoice_date is not None and fx_text is not None:
        table_rate = fx_by_date.get(invoice_date)
        if table_rate is not None and table_rate == Decimal(fx_text):
            fx_rate_date = invoice_date
        else:
            mismatch = True
    stamp = midnight_utc(received) if received else None
    number = r.text("vendor_invoice_number")
    return {
        "bill_id": bill_id,
        "origin": "history",
        "status": r.text("status"),
        "vendor_id": r.text("vendor_id"),
        "vendor_invoice_number": number,
        "norm_invoice_number": norm_invoice_no(number or ""),
        "invoice_date": invoice_date,
        "due_date": r.date("due_date"),
        "currency": currency,
        "subtotal_cents": r.money("subtotal"),
        "total_cents": total,
        "total_cad_cents": r.money("total_cad"),
        "fx_rate_to_cad": fx_text,
        "fx_rate_date": fx_rate_date,
        "is_credit_note": total is not None and total < 0,
        "ship_to_province": r.text("ship_to_province"),
        "department_id": r.text("department_id"),
        "requester_user_id": r.text("requester_user_id"),
        "po_id": r.text("po_id"),
        "contract_id": r.text("contract_id"),
        "file_hash": None,
        "source_email_id": None,
        "draft_json": None,
        "received_date": received,
        "created_at": stamp,
        "created_by": None,
        "updated_at": stamp,
    }, mismatch


def map_bill_line(row: Mapping[str, str], violations: list[Violation]) -> Row:
    """invoice_lines.csv -> bill_lines. History lines were coded, so coding_status is 'accepted'."""
    r = RowReader("bill_lines", f"{row.get('invoice_id', '?')}#{row.get('line_no', '?')}", row, violations)
    return {
        "bill_id": r.text("invoice_id"),
        "line_no": r.integer("line_no"),
        "description": r.text("description"),
        "quantity": r.decimal("quantity"),
        "unit_price": r.decimal("unit_price"),
        "amount_cents": r.money("amount"),
        "line_type": r.text("line_type"),
        "gst_hst_code": r.text("gst_hst_code"),
        "pst_qst_code": r.text("pst_qst_code"),
        "gl_account": r.text("gl_account"),
        "department_id": r.text("department_id"),
        "suggested_gl_account": None,
        "suggested_department_id": None,
        "suggestion_confidence": None,
        "suggestion_reason": None,
        "coding_status": "accepted",
        "coded_by": None,
        "coded_at": None,
    }


def map_bill_taxes(invoice: Mapping[str, str], lines: list[Mapping[str, str]], ref: RefData,
                   violations: list[Violation]) -> list[Row]:
    """Split an invoice's gst_hst_amount / pst_qst_amount into bill_taxes rows.

    The tax code of each amount is chosen by controls' own history builder (refdata._history_taxes), so the
    database and the controls engine always agree. Zero amounts produce no row. The rows must add up to
    gst_hst_amount + pst_qst_amount exactly, otherwise a violation is recorded.
    """
    bill_id = invoice.get("invoice_id", "?")
    r = RowReader("bill_taxes", bill_id, invoice, violations)
    before = len(violations)
    gst, pst = r.money("gst_hst_amount"), r.money("pst_qst_amount")
    if len(violations) > before:
        return []  # an amount was unreadable (e.g. 3 decimals); already reported, nothing safe to split
    try:
        tax_lines = _history_taxes(ref, dict(invoice), [dict(line) for line in lines])
    except (KeyError, ValueError) as exc:
        violations.append(Violation("tax_split", "bill_taxes", bill_id, f"could not build tax lines: {exc!r}"))
        return []
    rows = [
        {"bill_id": bill_id, "tax_code": t.code.value, "rate": dec_to_text(t.rate), "amount_cents": to_cents(t.amount)}
        for t in tax_lines
    ]
    expected = (gst or 0) + (pst or 0)
    if sum(row["amount_cents"] for row in rows) != expected:
        violations.append(Violation("tax_split", "bill_taxes", bill_id,
                                    f"tax rows add up to {sum(x['amount_cents'] for x in rows)} cents, "
                                    f"gst_hst_amount + pst_qst_amount is {expected}"))
    return rows


# ---------------------------------------------------------------- approvals, payments, emails


def map_approval(row: Mapping[str, str], user_roles: Mapping[str, str], violations: list[Violation]) -> Row:
    """approvals.csv -> approval_decisions.

    step_role = the CSV's approver_role (a route step name). actor_role = the approver's role in users.csv
    (the dataset doesn't record their role at the time). No history row shows delegation, so on_behalf_of is NULL.
    """
    r = RowReader("approval_decisions", row.get("approval_id", "?"), row, violations)
    actor = r.text("approver_user_id")
    return {
        "decision_id": r.text("approval_id"),
        "bill_id": r.text("invoice_id"),
        "step_no": r.integer("step_no"),
        "run_id": None,
        "actor_user_id": actor,
        "actor_role": user_roles.get(actor or ""),
        "step_role": r.text("approver_role"),
        "on_behalf_of": None,
        "decision": r.text("action"),
        "comment": r.text("comment"),
        "acted_at": r.timestamp("acted_at"),
        "origin": "history",
    }


def map_payment(row: Mapping[str, str], bill_dates: Mapping[str, date], fx_by_date: Mapping[date, Decimal],
                violations: list[Violation]) -> tuple[Row, bool]:
    """payments.csv -> payments. Returns (row, fx_mismatch).

    fx_rate_date follows the bills rule, on the paid bill's invoice date (the dataset converts at the invoice-date
    rate). History doesn't say which bank account version was paid or when the payment was released, so
    bank_account_id and released_at are NULL.
    """
    r = RowReader("payments", row.get("payment_id", "?"), row, violations)
    currency = r.text("currency")
    fx_text = r.decimal("fx_rate_to_cad")
    bill_id = r.text("invoice_id")
    fx_rate_date, mismatch = None, False
    if currency == "USD" and fx_text is not None:
        invoice_date = bill_dates.get(bill_id or "")
        table_rate = fx_by_date.get(invoice_date) if invoice_date else None
        if table_rate is not None and table_rate == Decimal(fx_text):
            fx_rate_date = invoice_date
        else:
            mismatch = True
    return {
        "payment_id": r.text("payment_id"),
        "bill_id": bill_id,
        "vendor_id": r.text("vendor_id"),
        "method": r.text("method"),
        "currency": currency,
        "amount_cents": r.money("amount"),
        "fx_rate_to_cad": fx_text,
        "fx_rate_date": fx_rate_date,
        "amount_cad_cents": r.money("amount_cad"),
        "discount_taken_cents": r.money("discount_taken"),
        "reference": r.text("reference"),
        "scheduled_date": r.date("scheduled_date"),
        "paid_date": r.date("paid_date"),
        "status": r.text("status"),
        "prepared_by": r.text("prepared_by"),
        "released_by": r.text("released_by"),
        "released_at": None,
        "bank_account_id": None,
        "idempotency_key": None,
        "origin": "history",
    }, mismatch


def map_email(record: Mapping[str, Any], violations: list[Violation]) -> Row:
    """inbox/emails.json -> emails. Not triaged yet, so email_class / triage_* are NULL."""
    email_id = str(record.get("email_id", "?"))
    attachments = record.get("attachments")
    if attachments is None:
        attachments = []
    if not isinstance(attachments, list) or not all(isinstance(a, str) for a in attachments):
        violations.append(Violation("bad_attachments", "emails", email_id, f"attachments is not a list of names: "
                                                                            f"{attachments!r}"))
        attachments = []
    # JSON values may be non-strings; read the text fields as strings so blanks become NULL consistently.
    as_text = {k: v if isinstance(v, str) else ("" if v is None else str(v)) for k, v in record.items()}
    r = RowReader("emails", email_id, as_text, violations)
    return {
        "email_id": r.text("email_id"),
        "from_name": r.text("from_name"),
        "from_address": r.text("from_address"),
        "to_address": r.text("to_address"),
        "subject": as_text.get("subject", ""),  # NOT NULL, but an empty subject is legitimate
        "received_at": r.timestamp("received_at"),
        "body": as_text.get("body", ""),  # same for an empty body
        "attachments": attachments,
        "email_class": None,
        "triage_reason": None,
        "triaged_at": None,
    }
