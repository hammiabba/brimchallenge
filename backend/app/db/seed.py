"""
Idempotent seed: load the synthetic dataset (dataset/brim_ap_dataset) into the app database.

Owner: DB team.

    cd backend && python -m app.db.seed [--database-url URL] [--reset]

What it does, in order:
1. (--reset only) deletes the SQLite file and its -wal / -shm, after checking the target is safe to delete.
2. Runs `alembic upgrade head` on the target database.
3. Reads every dataset file as strings and maps each row to table columns (app.db.seed_mapping).
4. Pre-flight: checks every mapped row against the same rules the schema enforces (NOT NULL, CHECK lists and
   free-form CHECKs, foreign keys, duplicate keys) plus the seed's own rules (money precision, tax split). It
   collects ALL violations; if there is even one, nothing is written and SeedValidationError lists them by rule.
5. Inserts everything in ONE transaction: all or nothing.

Idempotency: insert-only. Tables with a natural primary key use INSERT ... ON CONFLICT (pk) DO NOTHING; tables
with an autoincrement id use a natural-key existence check (NATURAL_KEYS). Existing rows are never updated, so
edits the app made to vendors, users, policies or bills survive a re-seed. A second run inserts 0 rows.

Not seeded here: incoming_invoices/ (they go through intake) and audit_events.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, Table, func, insert, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, REPO_ROOT, get_settings
from app.controls.refdata import load_refdata
from app.db import models
from app.db.database import (
    SQLITE_BEGIN_OPTION,
    WRITE_EXECUTION_OPTIONS,
    as_write_engine,
    make_engine,
    resolve_database_url,
)
from app.db.seed_mapping import (
    Row,
    Violation,
    map_approval,
    map_bank_change,
    map_bank_statement_line,
    map_bill,
    map_bill_line,
    map_bill_taxes,
    map_card_transaction,
    map_contract,
    map_department,
    map_email,
    map_fx_rate,
    map_gl_account,
    map_payment,
    map_policy,
    map_purchase_order,
    map_tax_code,
    map_user,
    map_user_absence,
    map_vendor,
    map_vendor_bank_account,
    midnight_utc,
    parse_date,
)

# ---------------------------------------------------------------- what gets seeded, and in which order

# Every immediate FK target is inserted before the rows that point at it. departments <-> users reference each
# other; those FKs are DEFERRABLE INITIALLY DEFERRED, so SQLite checks them at COMMIT of the single transaction.
TABLE_ORDER = (
    "gl_accounts", "departments", "users", "tax_codes", "vendors", "contracts", "purchase_orders", "policies",
    "fx_rates", "card_transactions", "bank_statement_lines", "bank_change_requests", "vendor_bank_accounts",
    "user_absences", "emails", "bills", "bill_lines", "bill_taxes", "approval_decisions", "payments",
)

# Tables whose primary key is an autoincrement id: a re-seed recognizes an existing row by these columns instead.
NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "vendor_bank_accounts": ("vendor_id", "institution", "transit", "account"),  # the same account of the vendor
    "bill_taxes": ("bill_id", "tax_code"),  # a history bill has at most one amount per tax code
    "user_absences": ("user_id", "starts_on"),  # one absence per user per start day (survives a delegate edit)
}

# Dataset CSVs read from <dataset_dir>/data/, by file stem.
CSV_FILES = (
    "approval_policies", "approvals", "bank_change_history", "bank_statement", "card_transactions", "contracts",
    "departments", "fx_rates", "gl_accounts", "invoice_lines", "invoices", "payments", "purchase_orders",
    "tax_codes", "users", "vendors",
)


# ---------------------------------------------------------------- results and errors


@dataclass
class TableCounts:
    """How many rows the dataset offered for a table, and how many were actually new."""

    attempted: int
    inserted: int

    @property
    def skipped(self) -> int:
        """Rows that already existed (by primary key or natural key) and were left untouched."""
        return self.attempted - self.inserted


@dataclass
class SeedReport:
    """Per-table insert counts plus data-quality notes (facts about the data worth knowing; not errors)."""

    tables: dict[str, TableCounts] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def inserted_total(self) -> int:
        """Rows inserted across all tables (0 on a re-run)."""
        return sum(c.inserted for c in self.tables.values())

    def format(self) -> str:
        """Plain-text report: one line per table, a total, then numbered notes."""
        width = max([len(n) for n in self.tables] + [5])
        out = [f"{'table':<{width}}  {'rows':>6}  {'inserted':>8}  {'skipped':>7}"]
        for name, c in self.tables.items():
            out.append(f"{name:<{width}}  {c.attempted:>6}  {c.inserted:>8}  {c.skipped:>7}")
        attempted = sum(c.attempted for c in self.tables.values())
        skipped = attempted - self.inserted_total
        out.append(f"{'total':<{width}}  {attempted:>6}  {self.inserted_total:>8}  {skipped:>7}")
        out.append("")
        out.append("Data-quality notes:")
        out.extend(f"{i:>2}. {note}" for i, note in enumerate(self.notes, 1))
        return "\n".join(out)


class SeedValidationError(Exception):
    """Pre-flight found rows that the schema (or the seed's rules) would reject. Nothing was written."""

    def __init__(self, violations: Sequence[Violation]) -> None:
        self.violations = list(violations)
        super().__init__(f"{len(self.violations)} dataset row(s) failed pre-flight validation; nothing was written")

    def format(self) -> str:
        """Every violation, grouped by rule, each with its table and row id."""
        by_rule: dict[str, list[Violation]] = defaultdict(list)
        for v in self.violations:
            by_rule[v.rule].append(v)
        out = [str(self)]
        for rule in sorted(by_rule):
            out.append(f"\n[{rule}] {len(by_rule[rule])} row(s)")
            out.extend(f"  {v.table} {v.row_id}: {v.detail}" for v in by_rule[rule])
        return "\n".join(out)


class ResetRefused(ValueError):
    """--reset was asked to delete something that isn't a plain SQLite file outside the dataset."""


# ---------------------------------------------------------------- reading the dataset


def load_dataset(dataset_dir: Path) -> dict[str, Any]:
    """Read every CSV as strings (blanks stay "", "004" stays "004") and inbox/emails.json as parsed JSON."""
    data_dir = dataset_dir / "data"
    raw: dict[str, Any] = {}
    for stem in CSV_FILES:
        path = data_dir / f"{stem}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"dataset file missing: {path}")
        with open(path, newline="", encoding="utf-8") as f:
            raw[stem] = list(csv.DictReader(f))
    emails_path = dataset_dir / "inbox" / "emails.json"
    if not emails_path.is_file():
        raise FileNotFoundError(f"dataset file missing: {emails_path}")
    raw["emails"] = json.loads(emails_path.read_text(encoding="utf-8"))
    return raw


def _fx_table(fx_rows: Sequence[Mapping[str, str]]) -> dict[date, Decimal]:
    """fx_rates.csv as {date: rate}, skipping rows the fx_rates mapping will report as unreadable."""
    table: dict[date, Decimal] = {}
    for row in fx_rows:
        try:
            table[parse_date(row["date"])] = Decimal(row["usd_to_cad"])
        except (KeyError, ValueError, InvalidOperation):
            continue
    return table


# ---------------------------------------------------------------- dataset rows -> table rows


@dataclass
class _Mapped:
    """Everything build_rows produces: rows per table, violations found while mapping, and FX mismatch ids."""

    rows: dict[str, list[Row]]
    violations: list[Violation]
    fx_mismatch_bills: list[str]
    fx_mismatch_payments: list[str]


def build_rows(raw: Mapping[str, Any], dataset_dir: Path, loaded_at: datetime) -> _Mapped:
    """Map every dataset row to the row dicts that will be inserted, collecting violations instead of raising."""
    v: list[Violation] = []
    rows: dict[str, list[Row]] = {name: [] for name in TABLE_ORDER}

    rows["gl_accounts"] = [map_gl_account(r, v) for r in raw["gl_accounts"]]
    rows["departments"] = [map_department(r, v) for r in raw["departments"]]
    rows["users"] = [map_user(r, v) for r in raw["users"]]
    rows["tax_codes"] = [map_tax_code(r, v) for r in raw["tax_codes"]]
    rows["vendors"] = [map_vendor(r, v) for r in raw["vendors"]]
    rows["contracts"] = [map_contract(r, v) for r in raw["contracts"]]
    rows["purchase_orders"] = [map_purchase_order(r, v) for r in raw["purchase_orders"]]
    rows["policies"] = [map_policy(r, loaded_at, v) for r in raw["approval_policies"]]
    rows["fx_rates"] = [map_fx_rate(r, v) for r in raw["fx_rates"]]
    rows["card_transactions"] = [map_card_transaction(r, v) for r in raw["card_transactions"]]
    rows["bank_statement_lines"] = [map_bank_statement_line(r, v) for r in raw["bank_statement"]]
    rows["bank_change_requests"] = [map_bank_change(r, v) for r in raw["bank_change_history"]]

    changes_by_vendor: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for change in raw["bank_change_history"]:
        changes_by_vendor[change.get("vendor_id", "")].append(change)
    accounts = (map_vendor_bank_account(r, changes_by_vendor[r.get("vendor_id", "")], v) for r in raw["vendors"])
    rows["vendor_bank_accounts"] = [a for a in accounts if a is not None]
    rows["user_absences"] = [a for a in (map_user_absence(r, v) for r in raw["users"]) if a is not None]
    rows["emails"] = [map_email(r, v) for r in raw["emails"]]

    fx_by_date = _fx_table(raw["fx_rates"])
    fx_mismatch_bills: list[str] = []
    for r in raw["invoices"]:
        bill, mismatch = map_bill(r, fx_by_date, v)
        rows["bills"].append(bill)
        if mismatch:
            fx_mismatch_bills.append(bill["bill_id"])
    rows["bill_lines"] = [map_bill_line(r, v) for r in raw["invoice_lines"]]

    # Tax split reuses controls' history builder, which only needs the tax codes from a RefData.
    try:
        ref = load_refdata(dataset_dir / "data")
    except Exception as exc:  # a malformed reference file: report it, don't crash before the full list is out
        v.append(Violation("reference_load", "bill_taxes", "*", f"controls.load_refdata failed: {exc!r}"))
        ref = None
    if ref is not None:
        lines_by_invoice: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        for line in raw["invoice_lines"]:
            lines_by_invoice[line.get("invoice_id", "")].append(line)
        for r in raw["invoices"]:
            rows["bill_taxes"].extend(map_bill_taxes(r, lines_by_invoice[r.get("invoice_id", "")], ref, v))

    user_roles = {u.get("user_id", ""): u.get("role", "") for u in raw["users"]}
    rows["approval_decisions"] = [map_approval(r, user_roles, v) for r in raw["approvals"]]

    bill_dates = {b["bill_id"]: b["invoice_date"] for b in rows["bills"] if b["invoice_date"] is not None}
    fx_mismatch_payments: list[str] = []
    for r in raw["payments"]:
        payment, mismatch = map_payment(r, bill_dates, fx_by_date, v)
        rows["payments"].append(payment)
        if mismatch:
            fx_mismatch_payments.append(payment["payment_id"])
    return _Mapped(rows, v, fx_mismatch_bills, fx_mismatch_payments)


# ---------------------------------------------------------------- pre-flight: the schema's rules, in Python

_IN_LIST = re.compile(r"^\s*(\w+) IN \(((?:\s*'[^']*'\s*,?)+)\)\s*$")


def _is_null(value: Any) -> bool:
    """SQL truth: a CHECK whose operands are NULL passes."""
    return value is None


def _last4(account: str) -> str:
    """Python equivalent of substr(account, length(account) - 3) for accounts of 4+ characters."""
    return account[-4:]


# Free-form CHECKs (anything that isn't `column IN (...)`), by constraint name. Each predicate returns True when the
# row passes, with SQL's rule that a NULL operand makes the CHECK pass. The schema test checks this stays complete.
FREE_FORM_CHECKS: dict[str, Callable[[Row], bool]] = {
    "ck_bank_statement_lines_one_side": lambda r: (r["debit_cad_cents"] is None) != (r["credit_cad_cents"] is None),
    "ck_bill_lines_coded_line_has_codes": lambda r: r["coding_status"] not in ("accepted", "overridden")
    or (r["gl_account"] is not None and r["department_id"] is not None),
    "ck_bill_lines_confidence_range": lambda r: _is_null(r["suggestion_confidence"])
    or 0 <= r["suggestion_confidence"] <= 1,
    "ck_bill_flags_override_needs_comment": lambda r: r["resolution"] != "overridden"
    or bool((r["resolution_comment"] or "").strip()),
    "ck_approval_decisions_not_on_behalf_of_self": lambda r: _is_null(r["on_behalf_of"])
    or r["on_behalf_of"] != r["actor_user_id"],
    "ck_vendor_bank_accounts_last4_matches_account": lambda r: _is_null(r["account"]) or _is_null(r["account_last4"])
    or r["account_last4"] == _last4(r["account"]),
    "ck_vendor_bank_accounts_valid_range": lambda r: _is_null(r["valid_to"]) or _is_null(r["valid_from"])
    or r["valid_to"] >= r["valid_from"],
    "ck_bank_change_requests_verifier_not_requester": lambda r: _is_null(r["verified_by"])
    or _is_null(r["requested_by"]) or r["verified_by"] != r["requested_by"],
    "ck_bank_change_requests_new_last4_matches_account": lambda r: _is_null(r["new_account"])
    or r["new_account_last4"] == _last4(r["new_account"]),
    "ck_payments_releaser_not_preparer": lambda r: _is_null(r["released_by"]) or _is_null(r["prepared_by"])
    or r["released_by"] != r["prepared_by"],
    "ck_user_absences_delegate_not_self": lambda r: r["delegate_user_id"] != r["user_id"]
    or _is_null(r["user_id"]),
    "ck_user_absences_valid_range": lambda r: _is_null(r["ends_on"]) or _is_null(r["starts_on"])
    or r["ends_on"] >= r["starts_on"],
}


def check_rules(table: Table) -> list[tuple[str, Callable[[Row], bool], str]]:
    """Every CHECK on `table` as (rule name, predicate, description). Raises if a CHECK has no Python version."""
    rules = []
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        name = str(constraint.name)
        sql = str(constraint.sqltext)
        match = _IN_LIST.match(sql)
        if match:
            column, allowed = match.group(1), frozenset(re.findall(r"'([^']*)'", match.group(2)))
            rules.append(("enum", lambda r, c=column, a=allowed: _is_null(r[c]) or r[c] in a,
                          f"{column} must be one of {sorted(allowed)}"))
        elif name in FREE_FORM_CHECKS:
            rule = name.removeprefix(f"ck_{table.name}_")
            rules.append((rule, FREE_FORM_CHECKS[name], sql))
        else:
            raise RuntimeError(f"pre-flight has no Python version of CHECK {name}: {sql}")
    return rules


def _row_id(table: Table, row: Row) -> str:
    """A readable id for a row: its primary key, or its natural key for autoincrement tables."""
    key = NATURAL_KEYS.get(table.name) or tuple(c.name for c in table.primary_key.columns)
    return "/".join(str(row.get(k)) for k in key)


def _is_generated_pk(table: Table, column_name: str) -> bool:
    """True for a single-column INTEGER primary key (SQLite assigns it), which the seed never supplies."""
    pk = list(table.primary_key.columns)
    return len(pk) == 1 and pk[0].name == column_name and isinstance(pk[0].type, Integer)


def preflight(rows: Mapping[str, Sequence[Row]]) -> list[Violation]:
    """Check all mapped rows against the schema's NOT NULL, CHECK, FK and key rules. Returns every violation."""
    tables = models.Base.metadata.tables
    violations: list[Violation] = []

    # Values present per (table, column), only for columns some foreign key points at (all scalar keys).
    fk_targets = {(e.column.table.name, e.column.name)
                  for t in tables.values() for fk in t.constraints if isinstance(fk, ForeignKeyConstraint)
                  for e in fk.elements}
    present: dict[tuple[str, str], set[Any]] = {
        (name, column): {r.get(column) for r in rows.get(name, ())} for name, column in fk_targets
    }

    for name, table_rows in rows.items():
        table = tables[name]
        column_names = {c.name for c in table.columns}
        rules = check_rules(table)
        key = NATURAL_KEYS.get(name) or tuple(c.name for c in table.primary_key.columns)
        seen: Counter[tuple[Any, ...]] = Counter(tuple(r.get(k) for k in key) for r in table_rows)

        for dup, count in seen.items():
            if count > 1:
                violations.append(Violation("duplicate_key", name, "/".join(map(str, dup)),
                                            f"{count} dataset rows share this key {key}"))

        for row in table_rows:
            row_id = _row_id(table, row)
            unknown = set(row) - column_names
            if unknown:  # a mapping bug, not a data problem: fail loudly
                raise RuntimeError(f"mapping for {name} produced unknown columns {sorted(unknown)}")
            for column in table.columns:
                if column.nullable or _is_generated_pk(table, column.name):
                    continue
                # An explicit None is inserted as NULL even when the column has a server default, so it fails too.
                # A column left out of the row is fine only if the database fills it (server default).
                supplied_null = column.name in row and row[column.name] is None
                missing = column.name not in row and column.server_default is None
                if supplied_null or missing:
                    violations.append(Violation("not_null", name, row_id, f"{column.name} is blank"))
            for rule, passes, description in rules:
                try:
                    ok = passes(row)
                except (KeyError, TypeError) as exc:
                    ok, description = False, f"{description} (could not evaluate: {exc!r})"
                if not ok:
                    violations.append(Violation(rule, name, row_id, description))
            for fk in table.constraints:
                if not isinstance(fk, ForeignKeyConstraint):
                    continue
                for element in fk.elements:
                    value = row.get(element.parent.name)
                    if value is None:
                        continue  # NULL never violates an FK
                    target = (element.column.table.name, element.column.name)
                    if value not in present.get(target, set()):
                        violations.append(Violation(
                            "foreign_key", name, row_id,
                            f"{element.parent.name}={value!r} not found in {target[0]}.{target[1]}"))
    return violations


# ---------------------------------------------------------------- data-quality notes


def build_notes(raw: Mapping[str, Any], mapped: _Mapped) -> list[str]:
    """Facts about the dataset worth knowing when reading the seeded tables. Informational, never blocking."""
    rows = mapped.rows
    users = {u["user_id"]: u for u in raw["users"]}
    approvers = sorted({a["approver_user_id"] for a in raw["approvals"]})
    terminated_approvers = [u for u in approvers if users.get(u, {}).get("status") == "terminated"]
    notes = [
        "history actor_role is taken from users.csv as of the seed date; the dataset does not record the approver's "
        "role at the time. Approvers terminated in users.csv: "
        + (", ".join(terminated_approvers) if terminated_approvers else "none") + ".",
    ]

    pairs = Counter((d["step_role"], d["actor_role"]) for d in rows["approval_decisions"])
    notes.append("approval step_role / actor_role pairs: "
                 + "; ".join(f"{s} signed by {a}: {n}" for (s, a), n in sorted(pairs.items())) + ".")

    bills = {b["bill_id"]: b for b in rows["bills"]}
    self_approvals = sorted(f"{d['decision_id']} ({d['actor_user_id']} on {d['bill_id']})"
                            for d in rows["approval_decisions"]
                            if bills.get(d["bill_id"], {}).get("requester_user_id") == d["actor_user_id"])
    notes.append(f"{len(self_approvals)} self-approval(s) kept as recorded (approver = requester): "
                 + (", ".join(self_approvals) or "none") + ".")
    notes.append("no approval in approvals.csv is recorded as delegated, so on_behalf_of is NULL for every history "
                 "decision.")

    notes.append("bills.received_date comes from the invoices.csv received_date column.")
    usd_bills = [b for b in rows["bills"] if b["currency"] == "USD"]
    notes.append(f"fx_rate_date: {len(usd_bills) - len(mapped.fx_mismatch_bills)} of {len(usd_bills)} USD bills match "
                 f"fx_rates.csv on their invoice date; mismatches: {len(mapped.fx_mismatch_bills)}"
                 + (f" ({', '.join(mapped.fx_mismatch_bills)})" if mapped.fx_mismatch_bills else "")
                 + f". USD payments with no matching rate: {len(mapped.fx_mismatch_payments)}"
                 + (f" ({', '.join(mapped.fx_mismatch_payments)})" if mapped.fx_mismatch_payments else "")
                 + ". CAD rows have fx_rate_to_cad '1' and fx_rate_date NULL.")

    rounding = []
    for b in rows["bills"]:
        if None in (b["total_cents"], b["fx_rate_to_cad"], b["total_cad_cents"]):
            continue
        computed = (Decimal(b["total_cents"]) * Decimal(b["fx_rate_to_cad"])).quantize(Decimal("1"),
                                                                                      rounding=ROUND_HALF_UP)
        if int(computed) != b["total_cad_cents"]:
            rounding.append(b["bill_id"])
    notes.append(f"{len(rounding)} bill(s) whose total_cad differs from total x fx_rate_to_cad rounded half-up to the "
                 "cent (the dataset rounds half-up, like types.to_cents; banker's rounding would disagree on a few); "
                 "stored as given: " + (", ".join(rounding) or "none") + ".")
    exact_repeats = Counter((b["vendor_id"], b["vendor_invoice_number"]) for b in rows["bills"])
    notes.append(f"{sum(1 for n in exact_repeats.values() if n > 1)} (vendor_id, vendor_invoice_number) pair(s) repeat "
                 "exactly in history; after normalization more pairs collide (see the norm_invoice_number note).")

    no_bank = sorted(v["vendor_id"] for v in raw["vendors"] if not v["bank_account"])
    fallback = sum(1 for v in raw["vendors"] if v["bank_account"] and not v["bank_details_updated_at"])
    linked = sorted(f"{a['vendor_id']}<-{a['source_change_id']}" for a in rows["vendor_bank_accounts"]
                    if a["source_change_id"])
    short = sorted(a["vendor_id"] for a in rows["vendor_bank_accounts"] if a["account"] and len(a["account"]) < 9)
    notes.append(f"vendor_bank_accounts: {len(rows['vendor_bank_accounts'])} open accounts; vendors without bank "
                 f"details (no row): {', '.join(no_bank) or 'none'}. valid_from fell back to onboarded_at for "
                 f"{fallback} vendor(s) with no bank_details_updated_at. Linked to a bank change: {', '.join(linked)}. "
                 f"Accounts shorter than 9 digits (kept as is): {', '.join(short) or 'none'}.")

    statuses = Counter(c["status"] for c in rows["bank_change_requests"])
    current_last4 = {a["vendor_id"]: a["account_last4"] for a in rows["vendor_bank_accounts"]}
    pending = [c for c in rows["bank_change_requests"] if c["status"] == "pending_verification"]
    applied = [f"{c['change_id']} ({c['vendor_id']})" for c in pending
               if current_last4.get(c["vendor_id"]) == c["new_account_last4"]]
    notes.append(f"bank_change_requests: {dict(sorted(statuses.items()))}. Unverified changes whose new account is "
                 f"already the vendor's current account in vendors.csv (applied without a callback): "
                 f"{', '.join(applied) or 'none'}. History records no verifier or verification time, so verified_by / "
                 "verified_at are NULL, and only the last 4 digits of accounts.")

    for absence in rows["user_absences"]:
        notes.append(f"user_absences: {absence['user_id']} on leave from {absence['starts_on']} with delegate "
                     f"{absence['delegate_user_id']}; open-ended (users.csv has no end date).")

    payments_per_bill = Counter(p["bill_id"] for p in rows["payments"])
    multi = sorted(b for b, n in payments_per_bill.items() if n > 1)
    unpaid = sorted(set(bills) - set(payments_per_bill))
    no_releaser = Counter(p["status"] for p in rows["payments"] if p["released_by"] is None)
    notes.append(f"payments: bills with more than one payment: {', '.join(multi) or 'none'}; bills with no payment: "
                 f"{len(unpaid)}; payments with no releaser, by status: {dict(sorted(no_releaser.items()))}. "
                 "bank_account_id and released_at are NULL (not recorded in history).")

    repeats = Counter((b["vendor_id"], b["norm_invoice_number"]) for b in rows["bills"])
    repeated = sorted(f"{vid}/{num}" for (vid, num), n in repeats.items() if n > 1)
    notes.append(f"{len(repeated)} (vendor_id, norm_invoice_number) pair(s) repeat in history (norm_invoice_number "
                 f"from controls.duplicates.norm_invoice_no), kept for the duplicate checks: {', '.join(repeated)}.")

    blank_tax = sorted(f"{line['bill_id']}#{line['line_no']}" for line in rows["bill_lines"]
                       if line["gst_hst_code"] is None)
    notes.append(f"invoice lines with a blank gst_hst_code (stored NULL): {', '.join(blank_tax) or 'none'}.")

    terminated = sorted(u for u, row in users.items() if row["status"] == "terminated")
    for uid in terminated:
        count = sum(1 for b in rows["bills"] if b["requester_user_id"] == uid)
        notes.append(f"{uid} is terminated (since {users[uid]['status_since']}) and is the requester on {count} "
                     "bill(s).")

    credits = sum(1 for b in rows["bills"] if b["is_credit_note"])
    statement_credits = sum(1 for s in rows["bank_statement_lines"] if s["credit_cad_cents"] is not None)
    notes.append(f"credit notes in history (negative totals): {credits}. Bank statement lines with a credit: "
                 f"{statement_credits} of {len(rows['bank_statement_lines'])}.")
    notes.append(f"policies.updated_at is set to the as-of date ({get_settings().as_of_date}); the dataset has no edit "
                 "times. updated_by is NULL.")
    return notes


# ---------------------------------------------------------------- writing


def _insert(session: Session, name: str, rows: Sequence[Row]) -> TableCounts:
    """Insert-only write of one table's rows; never updates. Counts new rows by comparing COUNT(*) before/after."""
    table = models.Base.metadata.tables[name]

    def count() -> int:
        return session.scalar(select(func.count()).select_from(table)) or 0

    before = count()
    if rows:
        if name in NATURAL_KEYS:
            key = NATURAL_KEYS[name]
            existing = {tuple(row) for row in session.execute(select(*(table.c[k] for k in key)))}
            new = [r for r in rows if tuple(r[k] for k in key) not in existing]
            if new:
                session.execute(insert(table), new)
        else:
            pk = [c.name for c in table.primary_key.columns]
            # ON CONFLICT on the primary key only: any other uniqueness violation still raises.
            session.execute(sqlite_insert(table).on_conflict_do_nothing(index_elements=pk), list(rows))
    return TableCounts(attempted=len(rows), inserted=count() - before)


def seed_all(session: Session, dataset_dir: Path) -> SeedReport:
    """Load the whole dataset in ONE transaction and commit it. All or nothing.

    Pass a fresh session from an engine made by app.db.database.make_engine (foreign keys must be on). The seed is a
    write, so it opens its transaction as a write session would (BEGIN IMMEDIATE), whatever kind of session is passed;
    on SQLite it raises RuntimeError if the session's transaction had already begun some other way. Raises
    SeedValidationError, with every violation, before writing anything if pre-flight fails.
    """
    dataset_dir = Path(dataset_dir)
    connection = session.connection(execution_options=WRITE_EXECUTION_OPTIONS)  # BEGIN IMMEDIATE on a fresh session
    begin_mode = connection.get_execution_options().get(SQLITE_BEGIN_OPTION)
    if connection.dialect.name == "sqlite" and begin_mode != "IMMEDIATE":
        raise RuntimeError("seed_all needs a fresh session: its transaction already began without BEGIN IMMEDIATE")
    if session.execute(text("PRAGMA foreign_keys")).scalar() != 1:
        raise RuntimeError("foreign keys are off on this connection; create the engine with make_engine()")
    raw = load_dataset(dataset_dir)
    mapped = build_rows(raw, dataset_dir, midnight_utc(get_settings().as_of_date))
    violations = mapped.violations + preflight(mapped.rows)
    if violations:
        session.rollback()
        raise SeedValidationError(violations)

    report = SeedReport(notes=build_notes(raw, mapped))
    try:
        for name in TABLE_ORDER:
            report.tables[name] = _insert(session, name, mapped.rows[name])
        session.commit()  # deferred FKs (users <-> departments) are checked here
    except Exception:
        session.rollback()
        raise
    return report


# ---------------------------------------------------------------- command line


def reset_target(url: str, protected_dirs: Sequence[Path]) -> Path:
    """The SQLite file --reset may delete for `url`. Raises ResetRefused for anything else.

    Refuses non-SQLite URLs, in-memory and URI-style SQLite names, and any path inside a protected directory
    (the repo's dataset/ and the configured DATASET_DIR). Symlinks are resolved before the check.
    """
    parsed = make_url(resolve_database_url(url))
    if parsed.get_backend_name() != "sqlite":
        raise ResetRefused(f"only a SQLite file can be reset, not {parsed.get_backend_name()}")
    database = parsed.database
    if not database or database == ":memory:" or database.startswith("file:") or parsed.query.get("uri"):
        raise ResetRefused("not a SQLite file path (in-memory or URI-style database)")
    path = Path(os.path.realpath(database))
    for protected in protected_dirs:
        root = Path(os.path.realpath(protected))
        if path == root or root in path.parents:
            raise ResetRefused(f"{path} is inside the protected directory {root}")
    if path.is_dir():
        raise ResetRefused(f"{path} is a directory")
    return path


def delete_sqlite_files(path: Path) -> list[Path]:
    """Delete a SQLite database file and its -wal / -shm companions. Returns the files that existed."""
    removed = []
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate)
    return removed


def migrate_to_head(url: str) -> None:
    """Run `alembic upgrade head` on `url` using backend/alembic.ini, without reconfiguring logging."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # ConfigParser interpolation
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code: 0 ok, 1 pre-flight failed, 2 --reset refused."""
    parser = argparse.ArgumentParser(prog="python -m app.db.seed", description="Load the dataset into the app DB.")
    parser.add_argument("--database-url", help="database to seed (default: DATABASE_URL / settings)")
    parser.add_argument("--reset", action="store_true",
                        help="delete the SQLite file (and -wal/-shm) first; refused for non-SQLite or dataset paths")
    args = parser.parse_args(argv)

    settings = get_settings()
    url = resolve_database_url(args.database_url or settings.database_url)
    started = time.perf_counter()

    if args.reset:
        try:
            path = reset_target(url, [REPO_ROOT / "dataset", settings.dataset_dir])
        except ResetRefused as exc:
            print(f"refusing --reset: {exc}", file=sys.stderr)
            return 2
        removed = delete_sqlite_files(path)
        print(f"reset: removed {len(removed)} file(s) at {path}")

    migrate_to_head(url)
    engine = make_engine(url)
    try:
        # A write session on the chosen URL (the process-wide get_write_session_factory is bound to DATABASE_URL,
        # which --database-url may override).
        with Session(as_write_engine(engine)) as session:
            report = seed_all(session, settings.dataset_dir)
    except SeedValidationError as exc:
        print(exc.format(), file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(report.format())
    print(f"\nSeeded {url} from {settings.dataset_dir} in {time.perf_counter() - started:.2f}s "
          f"({report.inserted_total} rows inserted).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
