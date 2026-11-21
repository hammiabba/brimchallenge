"""
SQLAlchemy 2.0 models: the app database schema.

Owner: DB team. The baseline migration (migrations/versions/0001_baseline.py) creates exactly these tables; change
the schema by editing this file AND adding a new migration, never by editing the baseline.

Import this module as a module (`from app.db import models`) rather than importing names: several class names here
(TaxCode, AuditEvent) also exist in app.shared.schemas, where they mean the API contract, not a table row.

Conventions (apply to every table):
- Money is INTEGER minor units in `*_cents` columns, next to a `currency` column, except `*_cad_cents`, which are
  CAD by name. Convert with app.db.types.to_cents / from_cents.
  Child rows (bill_lines, bill_taxes) are in their parent bill's currency.
- Rates, quantities and unit prices are TEXT holding an exact decimal string (types.dec_to_text / text_to_dec).
- IDs are TEXT and reuse the dataset formats (V001, U007, D01, PO-2026-0001, C018, AP-00001, PAY-00001, BC-001,
  CT-00001, BK-00001, EM-001). App-created rows continue the same numbering.
- Dates are DATE. Timestamps are DATETIME holding naive UTC (SQLite cannot store offsets; see the
  before_insert/before_update hook at the bottom, which converts aware datetimes to UTC).
- Enumerated text columns get a named CHECK constraint (`ck_<table>_<column>`) listing the allowed values.
  The allowed values are the module-level tuples below; each notes the dataset file or contract enum it came from.
- Tables that receive both dataset history and app-created rows carry `origin` ('history' | 'app').
- No UNIQUE on (vendor_id, vendor invoice number) or on payments.bill_id: the history has legitimate repeats
  (5 repeated invoice numbers, 3 invoices paid twice) that the controls engine must be able to see.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    REAL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import to_utc

# ---------------------------------------------------------------- allowed values for CHECK constraints
# Keep these in sync with the migration: a migration is a frozen snapshot, so changing a tuple here needs a new
# migration that rewrites the CHECK. tests/db/test_schema.py checks the contract-backed ones against schemas.py.

ORIGINS = ("history", "app")
CURRENCIES = ("CAD", "USD")  # every currency column in the dataset holds only these two
# Canadian provinces and territories; same set as extraction.normalize.PROVINCES. Dataset uses ON, QC, BC, AB.
PROVINCES = ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")

USER_ROLES = ("employee", "ap_clerk", "approver", "finance_manager", "controller_admin", "auditor")  # users.role
USER_STATUSES = ("active", "on_leave", "terminated")  # users.status
VENDOR_STATUSES = ("active", "on_hold", "pending_review")  # vendors.status
PAYMENT_METHODS = ("EFT", "CHEQUE", "CARD")  # payments.method, vendors.preferred_payment_method
# gl_accounts.account_type has asset / liability / expense; equity and revenue complete the standard set.
GL_ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")
TAX_APPLIES_TO = ("all", "goods")  # tax_codes.applies_to
CONTRACT_BILLING_TYPES = ("fixed_monthly", "rate_card", "retainer", "blanket")  # contracts.billing_type
CONTRACT_STATUSES = ("active", "expired")  # contracts.status
PO_STATUSES = ("open", "partially_invoiced", "closed")  # purchase_orders.status
POLICY_RULE_TYPES = ("approval", "payment_release", "match")  # approval_policies.rule_type
CARD_SOURCES = ("employee_card", "ap_virtual_card")  # card_transactions.source

# Bill lifecycle. invoices.csv uses paid / rejected / scheduled / approved, all included.
BILL_STATUSES = (
    "needs_review", "on_hold", "pending_approval", "approved", "rejected", "scheduled", "paid", "credit_open", "void",
)
LINE_TYPES = ("goods", "services")  # schemas.LineType, invoice_lines.line_type
CODING_STATUSES = ("none", "suggested", "accepted", "overridden")
SEVERITIES = ("block", "warn", "info")  # schemas.Severity
FLAG_RESOLUTIONS = ("open", "overridden", "resolved")
# Approval step roles from schemas.ApprovalStep.role / controls.approvals.STEP_ROLES. These are policy step names,
# not user roles: a dept_manager step is signed by a user whose role is "approver". approvals.csv stores this
# vocabulary in its approver_role column (dept_manager / finance_manager), which maps to approval_decisions.step_role.
STEP_ROLES = ("dept_manager", "finance_manager", "controller_admin", "cfo")
DECISIONS = ("approved", "rejected")  # approvals.action
BANK_CHANGE_CHANNELS = ("phone_callback_verified", "vendor_portal", "email_request")  # bank_change_history
BANK_CHANGE_STATUSES = ("pending_verification", "verified", "rejected")
# payments.csv has settled / outstanding / scheduled; released / failed / cancelled are for app payments.
PAYMENT_STATUSES = ("scheduled", "released", "settled", "outstanding", "failed", "cancelled")
EMAIL_CLASSES = (  # schemas.EmailClass
    "invoice", "credit_note", "statement", "payment_inquiry", "missing_attachment", "not_ap",
)
INTAKE_STATUSES = ("ok", "llm_skipped", "failed", "queued", "processing")  # ExtractionOutcome.status + queue states

# ---------------------------------------------------------------- naming and base class

# Deterministic constraint names. SQLite batch migrations (used by every later ALTER) can only drop or rewrite a
# constraint that has a name, and named CHECKs make IntegrityError messages say which rule failed.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base: shared metadata with the naming convention; plain `str` columns are TEXT."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {str: Text(), datetime: DateTime()}


def one_of(column: str, values: tuple[str, ...], *, name: str | None = None) -> CheckConstraint:
    """Named CHECK that `column` holds one of `values`. NULL passes, so nullable columns stay nullable."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name or column)


# Foreign keys that take part in a cycle (users <-> departments, users -> users) are DEFERRABLE INITIALLY DEFERRED,
# so a seed can insert both sides in one transaction and SQLite checks them at commit.
DEFERRED = {"deferrable": True, "initially": "DEFERRED"}


# ================================================================ reference data (loaded from dataset CSVs)


class Department(Base):
    """departments.csv."""

    __tablename__ = "departments"

    department_id: Mapped[str] = mapped_column(primary_key=True)  # "D01"
    name: Mapped[str]
    cost_centre: Mapped[str]  # "1100"; TEXT, it's a code, not a number
    annual_budget_cad_cents: Mapped[int]  # annual_budget_cad
    # use_alter breaks the users <-> departments cycle for SQLAlchemy's table ordering. SQLite still renders the FK
    # inline in CREATE TABLE (it has no ALTER ADD CONSTRAINT).
    manager_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", use_alter=True, **DEFERRED))


class User(Base):
    """users.csv. role is the user's own role; approval_limit_cad_cents is their approval limit, not a release cap."""

    __tablename__ = "users"
    __table_args__ = (
        one_of("role", USER_ROLES),
        one_of("status", USER_STATUSES),
        one_of("work_province", PROVINCES),
    )

    user_id: Mapped[str] = mapped_column(primary_key=True)  # "U007"
    full_name: Mapped[str]
    email: Mapped[str]
    title: Mapped[str]  # the CFO is identified by title ("Chief Financial Officer"), not by role
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.department_id", **DEFERRED))
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id", **DEFERRED))  # U001 has none
    role: Mapped[str]
    approval_limit_cad_cents: Mapped[int]  # approval_limit_cad
    work_province: Mapped[str]
    status: Mapped[str]
    status_since: Mapped[date | None]
    delegate_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id", **DEFERRED))
    hire_date: Mapped[date]


class GlAccount(Base):
    """gl_accounts.csv."""

    __tablename__ = "gl_accounts"
    __table_args__ = (one_of("account_type", GL_ACCOUNT_TYPES),)

    account_number: Mapped[str] = mapped_column(primary_key=True)  # "5010"; TEXT to keep it a code
    name: Mapped[str]
    account_type: Mapped[str]
    notes: Mapped[str | None]


class TaxCode(Base):
    """tax_codes.csv. recoverable: yes -> True, no -> False, n/a (EXEMPT, FOREIGN: no tax charged) -> NULL."""

    __tablename__ = "tax_codes"
    __table_args__ = (one_of("applies_to", TAX_APPLIES_TO),)

    code: Mapped[str] = mapped_column(primary_key=True)  # "HST13"; same values as schemas.TaxCode
    description: Mapped[str]
    rate: Mapped[str]  # exact decimal TEXT: "0.09975"
    applies_to: Mapped[str]
    recoverable: Mapped[bool | None]
    gl_account: Mapped[str | None] = mapped_column(ForeignKey("gl_accounts.account_number"))  # input-tax-credit GL


class Vendor(Base):
    """vendors.csv minus the bank columns, which live in vendor_bank_accounts (versioned).

    origin: the dataset vendors are 'history'; vendors onboarded in the app are 'app'.
    """

    __tablename__ = "vendors"
    __table_args__ = (
        one_of("preferred_payment_method", PAYMENT_METHODS),
        one_of("status", VENDOR_STATUSES),
        one_of("origin", ORIGINS),
    )

    vendor_id: Mapped[str] = mapped_column(primary_key=True)  # "V001"
    legal_name: Mapped[str]
    category: Mapped[str]  # free text: 24 categories in the dataset, and onboarding may add more
    default_gl_account: Mapped[str | None] = mapped_column(ForeignKey("gl_accounts.account_number"))
    address: Mapped[str]
    province_or_state: Mapped[str]  # includes US states (WA, TX, IL, CO), so no province CHECK
    country: Mapped[str]  # "CA" | "US" in the dataset; ISO 3166 alpha-2
    gst_hst_number: Mapped[str | None]
    qst_number: Mapped[str | None]
    payment_terms_days: Mapped[int]
    early_pay_discount: Mapped[str | None]  # terms text such as "2/10 net 30", not an amount
    preferred_payment_method: Mapped[str]
    accepts_card_payment: Mapped[bool]
    ap_contact_email: Mapped[str]
    requires_po: Mapped[bool]
    status: Mapped[str]
    onboarded_at: Mapped[date]
    origin: Mapped[str]


class Contract(Base):
    """contracts.csv. Money columns are in `currency`; blanks in the CSV (no cap / no fee) are NULL."""

    __tablename__ = "contracts"
    __table_args__ = (
        one_of("billing_type", CONTRACT_BILLING_TYPES),
        one_of("currency", CURRENCIES),
        one_of("status", CONTRACT_STATUSES),
    )

    contract_id: Mapped[str] = mapped_column(primary_key=True)  # "C018"
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"))
    description: Mapped[str]
    billing_type: Mapped[str]
    monthly_fee_cents: Mapped[int | None]  # monthly_fee
    currency: Mapped[str]
    hourly_rate_cap_cents: Mapped[int | None]  # hourly_rate_cap
    fuel_surcharge_cap_pct: Mapped[str | None]  # exact decimal TEXT, percent: "12"
    not_to_exceed_monthly_cents: Mapped[int | None]  # not_to_exceed_monthly
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    auto_renew: Mapped[bool]
    status: Mapped[str]


class PurchaseOrder(Base):
    """purchase_orders.csv. A PO carries requester and department, which a bill can inherit."""

    __tablename__ = "purchase_orders"
    __table_args__ = (one_of("currency", CURRENCIES), one_of("status", PO_STATUSES))

    po_id: Mapped[str] = mapped_column(primary_key=True)  # "PO-2026-0001"
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"))
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.department_id"))
    requester_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    issue_date: Mapped[date]
    description: Mapped[str]
    total_amount_cents: Mapped[int]  # total_amount
    currency: Mapped[str]
    status: Mapped[str]
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"))


class Policy(Base):
    """approval_policies.csv, admin-editable.

    condition / required are kept as the dataset's text because controls.refdata parses thresholds out of them
    ("Invoice total over $10,000 CAD"). updated_at / updated_by record the last admin edit.
    """

    __tablename__ = "policies"
    __table_args__ = (one_of("rule_type", POLICY_RULE_TYPES),)

    rule_id: Mapped[str] = mapped_column(primary_key=True)  # "P01"
    rule_type: Mapped[str]
    condition: Mapped[str]
    required: Mapped[str]
    notes: Mapped[str | None]
    updated_at: Mapped[datetime]
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))


class FxRate(Base):
    """fx_rates.csv: one USD->CAD rate per calendar day. The column keeps the CSV name `date`."""

    __tablename__ = "fx_rates"

    rate_date: Mapped[date] = mapped_column("date", primary_key=True)
    usd_to_cad: Mapped[str]  # exact decimal TEXT: "1.3709"


class CardTransaction(Base):
    """card_transactions.csv: Brim employee cards and AP single-use virtual cards."""

    __tablename__ = "card_transactions"
    __table_args__ = (one_of("currency", CURRENCIES), one_of("source", CARD_SOURCES))

    txn_id: Mapped[str] = mapped_column(primary_key=True)  # "CT-00001"
    card_id: Mapped[str]  # "CARD-U017"
    cardholder_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    posted_date: Mapped[date]
    merchant_descriptor: Mapped[str]
    mcc: Mapped[str]  # merchant category code; TEXT, it's a code
    amount_cents: Mapped[int]
    currency: Mapped[str]
    amount_cad_cents: Mapped[int]
    source: Mapped[str]
    receipt_attached: Mapped[bool]
    memo: Mapped[str | None]  # "AP payment AP-00123" links a virtual-card charge to an invoice


class BankStatementLine(Base):
    """bank_statement.csv: the CAD operating account (every EFT/cheque payment in the dataset is CAD).

    The CSV has no currency column, so the money columns are `*_cad_cents`. Exactly one side is set per line.
    """

    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        CheckConstraint("(debit_cad_cents IS NULL) <> (credit_cad_cents IS NULL)", name="one_side"),
    )

    bank_txn_id: Mapped[str] = mapped_column(primary_key=True)  # "BK-00001"
    posted_date: Mapped[date]
    description: Mapped[str]
    debit_cad_cents: Mapped[int | None]  # debit
    credit_cad_cents: Mapped[int | None]  # credit (always blank in the dataset)


# ================================================================ transactional data


class Bill(Base):
    """One supplier invoice or credit note: the 426 historical invoices (origin 'history') plus every bill the app
    creates (origin 'app'). Amounts are in `currency`; total_cad_cents is the CAD equivalent.

    norm_invoice_number is the vendor invoice number with prefixes, punctuation and leading zeros removed (the same
    normalization as controls.duplicates.norm_invoice_no), indexed with vendor_id for duplicate lookups.
    row_version is SQLAlchemy's version counter: an UPDATE that lost a race raises StaleDataError.

    draft_json is the immutable snapshot of the extraction output (the DraftBill) taken at intake time. It is never
    edited, not even when a clerk corrects the bill. Corrections are written to this row's columns and to
    bill_lines / bill_taxes, and the current DraftBill (the input to controls) is rebuilt from those tables.
    Comparing draft_json with the rebuilt bill shows exactly what was extracted vs what a human corrected.
    Nothing in the database enforces this (no trigger); the code that writes bills must respect it.
    """

    __tablename__ = "bills"
    __table_args__ = (
        one_of("origin", ORIGINS),
        one_of("status", BILL_STATUSES),
        one_of("currency", CURRENCIES),
        one_of("ship_to_province", PROVINCES),
        Index(None, "file_hash"),
        Index(None, "vendor_id", "norm_invoice_number"),
        Index(None, "status"),
        Index(None, "department_id", "status"),
    )

    bill_id: Mapped[str] = mapped_column(primary_key=True)  # "AP-00001"; app bills continue the sequence
    origin: Mapped[str]
    status: Mapped[str]
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.vendor_id"))  # NULL: vendor not in master
    vendor_invoice_number: Mapped[str]
    norm_invoice_number: Mapped[str]
    invoice_date: Mapped[date]
    due_date: Mapped[date | None]  # DraftBill.due_date is optional
    currency: Mapped[str]
    subtotal_cents: Mapped[int]
    total_cents: Mapped[int]  # negative on credit notes
    total_cad_cents: Mapped[int]
    fx_rate_to_cad: Mapped[str]  # exact decimal TEXT; "1" for CAD
    fx_rate_date: Mapped[date | None]  # the fx_rates day actually used (weekend fallback can make it earlier)
    is_credit_note: Mapped[bool]
    ship_to_province: Mapped[str | None]  # place of supply; DraftBill.ship_to_province is optional
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.department_id"))
    requester_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    po_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_orders.po_id"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.contract_id"))
    file_hash: Mapped[str | None]  # sha256 of the source file; not unique (the same PDF can arrive twice)
    source_email_id: Mapped[str | None]  # "EM-029"; NULL for uploads and history
    # Frozen extraction snapshot (DraftBill, JSON mode); never edited after intake. NULL for history rows.
    draft_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    received_date: Mapped[date]
    created_at: Mapped[datetime]
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime]
    row_version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": row_version}


class BillLine(Base):
    """One line of a bill (invoice_lines.csv for history), with its final coding and the coding suggestion."""

    __tablename__ = "bill_lines"
    __table_args__ = (
        one_of("line_type", LINE_TYPES),
        one_of("coding_status", CODING_STATUSES),
        # A line that is accepted or overridden must actually carry a GL account and department.
        CheckConstraint(
            "coding_status NOT IN ('accepted', 'overridden') OR (gl_account IS NOT NULL AND department_id IS NOT NULL)",
            name="coded_line_has_codes",
        ),
        CheckConstraint(
            "suggestion_confidence IS NULL OR (suggestion_confidence >= 0 AND suggestion_confidence <= 1)",
            name="confidence_range",
        ),
    )

    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.bill_id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str]
    quantity: Mapped[str]  # exact decimal TEXT
    unit_price: Mapped[str]  # exact decimal TEXT (can have more than 2 places)
    amount_cents: Mapped[int]  # in the bill's currency
    line_type: Mapped[str]
    gst_hst_code: Mapped[str | None] = mapped_column(ForeignKey("tax_codes.code"))
    pst_qst_code: Mapped[str | None] = mapped_column(ForeignKey("tax_codes.code"))
    gl_account: Mapped[str | None] = mapped_column(ForeignKey("gl_accounts.account_number"))  # final coding
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.department_id"))  # final coding
    suggested_gl_account: Mapped[str | None]  # from coding.suggest
    suggested_department_id: Mapped[str | None]
    suggestion_confidence: Mapped[float | None] = mapped_column(REAL)  # 0..1, not money, so REAL is fine
    suggestion_reason: Mapped[str | None]
    coding_status: Mapped[str]
    coded_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    coded_at: Mapped[datetime | None]


class BillTax(Base):
    """One tax amount on a bill (schemas.TaxLine), in the bill's currency."""

    __tablename__ = "bill_taxes"
    __table_args__ = (Index(None, "bill_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.bill_id"))
    tax_code: Mapped[str] = mapped_column(ForeignKey("tax_codes.code"))
    rate: Mapped[str]  # exact decimal TEXT
    amount_cents: Mapped[int]


class ControlsRun(Base):
    """One run of controls.run_controls on a bill. Re-running after an edit adds version + 1; old runs stay."""

    __tablename__ = "controls_runs"
    __table_args__ = (UniqueConstraint("bill_id", "version"), {"sqlite_autoincrement": True})

    run_id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.bill_id"))
    version: Mapped[int]
    evaluated_at: Mapped[datetime]
    can_auto_proceed: Mapped[bool]
    recommendation: Mapped[str | None]
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)  # the full ControlsResult (JSON mode)


class BillFlag(Base):
    """One schemas.Flag from a controls run, plus how a human resolved it.

    code is not CHECKed: FLAG_CODES lives in schemas.py and is expected to grow; controls.validate.flag() already
    refuses unknown codes.
    """

    __tablename__ = "bill_flags"
    __table_args__ = (
        one_of("severity", SEVERITIES),
        one_of("resolution", FLAG_RESOLUTIONS),
        # Overriding a flag is a judgement call, so it must say why.
        CheckConstraint(
            "resolution <> 'overridden' OR (resolution_comment IS NOT NULL AND length(trim(resolution_comment)) > 0)",
            name="override_needs_comment",
        ),
        Index(None, "run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("controls_runs.run_id"))
    code: Mapped[str]  # "TAX_WRONG_FOR_PROVINCE"
    severity: Mapped[str]
    field: Mapped[str | None]  # UI field to highlight
    message: Mapped[str]
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    resolution: Mapped[str] = mapped_column(server_default=text("'open'"))
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    resolved_at: Mapped[datetime | None]
    resolution_comment: Mapped[str | None]


class ApprovalRouteStep(Base):
    """One planned approval step (schemas.ApprovalStep) from a controls run.

    user_id is NULL when routing returned "UNASSIGNED" (nobody eligible; AP assigns one manually).
    """

    __tablename__ = "approval_route_steps"
    __table_args__ = (one_of("role", STEP_ROLES), Index(None, "bill_id"))

    run_id: Mapped[int] = mapped_column(ForeignKey("controls_runs.run_id"), primary_key=True)
    step_no: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.bill_id"))
    role: Mapped[str]
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    policy_ids: Mapped[list[str]] = mapped_column(JSON)  # ["P02", "P06"]
    reason: Mapped[str]
    delegated_from: Mapped[str | None]  # the on-leave approver this step was delegated from (P08)
    escalated_from: Mapped[str | None]  # the requester this step escalated past (P07)


class ApprovalDecision(Base):
    """One recorded approve/reject. History rows come from approvals.csv (no run_id); app rows point at the run
    whose route was being signed. on_behalf_of is set when a delegate acts (P08) and can never be the actor.

    Two role columns, two vocabularies, never mixed:
    - actor_role: the acting user's own role (users.role) at the time of the decision, e.g. "approver".
    - step_role:  which kind of approval step was signed (ApprovalStep.role), e.g. "dept_manager". NULL for a
      decision not tied to a routed step. approvals.csv's approver_role column holds this vocabulary.
    """

    __tablename__ = "approval_decisions"
    __table_args__ = (
        one_of("actor_role", USER_ROLES),
        one_of("step_role", STEP_ROLES),
        one_of("decision", DECISIONS),
        one_of("origin", ORIGINS),
        CheckConstraint("on_behalf_of IS NULL OR on_behalf_of <> actor_user_id", name="not_on_behalf_of_self"),
        Index(None, "bill_id"),
    )

    decision_id: Mapped[str] = mapped_column(primary_key=True)  # "AP-A-00001"
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.bill_id"))
    step_no: Mapped[int]
    run_id: Mapped[int | None] = mapped_column(ForeignKey("controls_runs.run_id"))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    actor_role: Mapped[str]  # user role of the actor when they acted
    step_role: Mapped[str | None]  # route step kind; NULL if not tied to a routed step
    on_behalf_of: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    decision: Mapped[str]
    comment: Mapped[str | None]
    acted_at: Mapped[datetime]
    origin: Mapped[str]


class VendorBankAccount(Base):
    """A vendor's bank account, versioned: at most one open row (valid_to IS NULL) per vendor.

    Account numbers are always TEXT (institution "004" and transit "05541" have leading zeros).
    origin: accounts from vendors.csv are 'history'; accounts created by a verified bank change are 'app'.
    """

    __tablename__ = "vendor_bank_accounts"
    __table_args__ = (
        one_of("origin", ORIGINS),
        # last4 must agree with the full number. substr(x, length(x) - 3) works in SQLite and Postgres alike.
        CheckConstraint("account_last4 = substr(account, length(account) - 3)", name="last4_matches_account"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        Index(None, "vendor_id"),
        # One active account per vendor: a partial unique index over open rows only.
        Index(
            "uq_vendor_bank_accounts_one_active",
            "vendor_id",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"))
    institution: Mapped[str]
    transit: Mapped[str]
    account: Mapped[str]
    account_last4: Mapped[str]
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    source_change_id: Mapped[str | None]  # the bank_change_requests.change_id that created this row, if any
    origin: Mapped[str]


class BankChangeRequest(Base):
    """A request to change a vendor's bank details (bank_change_history.csv for history).

    History rows only have the last 4 digits, so the full new_* numbers are nullable. The person who requested a
    change can never be the one who verifies it.
    """

    __tablename__ = "bank_change_requests"
    __table_args__ = (
        one_of("request_channel", BANK_CHANGE_CHANNELS),
        one_of("status", BANK_CHANGE_STATUSES),
        one_of("origin", ORIGINS),
        CheckConstraint(
            "verified_by IS NULL OR requested_by IS NULL OR verified_by <> requested_by",
            name="verifier_not_requester",
        ),
        CheckConstraint(
            "new_account IS NULL OR new_account_last4 = substr(new_account, length(new_account) - 3)",
            name="new_last4_matches_account",
        ),
        Index(None, "vendor_id"),
    )

    change_id: Mapped[str] = mapped_column(primary_key=True)  # "BC-001"
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"))
    requested_at: Mapped[datetime]  # changed_at
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))  # changed_by_user_id
    request_channel: Mapped[str]
    old_account_last4: Mapped[str | None]  # NULL when the vendor had no account before
    new_account_last4: Mapped[str]
    new_institution: Mapped[str | None]
    new_transit: Mapped[str | None]
    new_account: Mapped[str | None]
    verified_by_callback: Mapped[bool]
    status: Mapped[str]
    verified_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    verified_at: Mapped[datetime | None]
    origin: Mapped[str]


class Payment(Base):
    """A payment of a bill (payments.csv for history). Not unique per bill: history has invoices paid twice.

    amount_cents is in `currency`; amount_cad_cents is the CAD equivalent. bank_account_id records which bank
    account version an app payment was sent to. idempotency_key stops a retried release from paying twice.
    """

    __tablename__ = "payments"
    __table_args__ = (
        one_of("method", PAYMENT_METHODS),
        one_of("currency", CURRENCIES),
        one_of("status", PAYMENT_STATUSES),
        one_of("origin", ORIGINS),
        # Separation of duties at the row level: the clerk who prepared a payment never releases it (P09 note).
        CheckConstraint(
            "released_by IS NULL OR prepared_by IS NULL OR released_by <> prepared_by",
            name="releaser_not_preparer",
        ),
        Index(None, "bill_id"),
        Index(None, "status"),
    )

    payment_id: Mapped[str] = mapped_column(primary_key=True)  # "PAY-00001"
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.bill_id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"))
    method: Mapped[str]
    currency: Mapped[str]
    amount_cents: Mapped[int]
    fx_rate_to_cad: Mapped[str]  # exact decimal TEXT
    fx_rate_date: Mapped[date | None]
    amount_cad_cents: Mapped[int]
    discount_taken_cents: Mapped[int] = mapped_column(server_default=text("0"))  # discount_taken, in `currency`
    reference: Mapped[str | None]  # "BRIM-VC-17166635", "EFT-REF-..." from payments.csv
    scheduled_date: Mapped[date]
    paid_date: Mapped[date | None]
    status: Mapped[str]
    prepared_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    released_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    released_at: Mapped[datetime | None]
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("vendor_bank_accounts.id"))
    idempotency_key: Mapped[str | None] = mapped_column(unique=True)  # NULLs don't collide in a UNIQUE index
    origin: Mapped[str]


class UserAbsence(Base):
    """An approver's leave with a named delegate (P08). users.csv only has status=on_leave + delegate_user_id;
    this table adds the date range. ends_on NULL means open-ended."""

    __tablename__ = "user_absences"
    __table_args__ = (
        CheckConstraint("delegate_user_id <> user_id", name="delegate_not_self"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="valid_range"),
        Index(None, "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    delegate_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    starts_on: Mapped[date]
    ends_on: Mapped[date | None]


class Email(Base):
    """An inbound AP email (inbox/emails.json) and its triage result (schemas.EmailTriage)."""

    __tablename__ = "emails"
    __table_args__ = (one_of("email_class", EMAIL_CLASSES),)

    email_id: Mapped[str] = mapped_column(primary_key=True)  # "EM-001"
    from_name: Mapped[str | None]
    from_address: Mapped[str]
    to_address: Mapped[str | None]
    subject: Mapped[str]
    received_at: Mapped[datetime]
    body: Mapped[str]
    attachments: Mapped[list[str]] = mapped_column(JSON)  # file names as listed in the email; [] when none
    email_class: Mapped[str | None]  # NULL until triaged
    triage_reason: Mapped[str | None]
    triaged_at: Mapped[datetime | None]


class IntakeItem(Base):
    """One file through intake (an email attachment or an upload), including the ones that failed, so a clerk can
    see and retry them. bill_id is set once a bill was created from it."""

    __tablename__ = "intake_items"
    __table_args__ = (
        one_of("status", INTAKE_STATUSES),
        Index(None, "email_id"),
        Index(None, "file_hash"),
        {"sqlite_autoincrement": True},
    )

    item_id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[str | None] = mapped_column(ForeignKey("emails.email_id"))  # NULL for uploads
    file_name: Mapped[str]
    file_hash: Mapped[str | None]  # NULL when the attachment was missing, so there were no bytes to hash
    status: Mapped[str]
    error: Mapped[str | None]
    warnings: Mapped[list[str]] = mapped_column(JSON)
    bill_id: Mapped[str | None] = mapped_column(ForeignKey("bills.bill_id"))
    created_at: Mapped[datetime]
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))


class AuditEvent(Base):
    """Append-only audit log (schemas.AuditEvent plus ordering and hash-chain columns).

    seq is AUTOINCREMENT, so numbers are never reused and give a total order. UPDATE and DELETE are blocked by
    triggers (below and in the baseline migration). actor_user_id has no FK and actor_role / action / entity_type
    have no CHECK on purpose: the log must accept every event, including system actors, rather than lose one.
    prev_hash / hash will chain rows together (computed in a later step); for now hash is only required.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(None, "entity_type", "entity_id"),
        Index(None, "at"),
        Index(None, "actor_user_id"),
        # Migration 0002: no two events may extend the same predecessor, so the hash chain can never fork. The first
        # event uses prev_hash "GENESIS" (not NULL), so the start of the chain is covered too.
        Index("uq_audit_events_prev_hash", "prev_hash", unique=True),
        {"sqlite_autoincrement": True},
    )

    seq: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(unique=True)
    at: Mapped[datetime]
    actor_user_id: Mapped[str]
    actor_role: Mapped[str]
    on_behalf_of: Mapped[str | None]  # set when a delegate acted
    action: Mapped[str]  # "invoice.approved", "payment.released", "vendor.bank_changed"
    entity_type: Mapped[str]  # "invoice" | "payment" | "vendor" | "policy" | "user"
    entity_id: Mapped[str]
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    comment: Mapped[str | None]
    request_id: Mapped[str | None]  # correlates all events written by one HTTP request
    prev_hash: Mapped[str | None]
    hash: Mapped[str]


# ---------------------------------------------------------------- append-only triggers for audit_events
# The baseline migration creates the same triggers from its own copy of this SQL (migrations are frozen snapshots).
# Attaching them here too means metadata.create_all() (if anyone uses it, e.g. a quick script) is append-only as well.

AUDIT_NO_UPDATE_TRIGGER = """
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END
"""

AUDIT_NO_DELETE_TRIGGER = """
CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END
"""

for _trigger_sql in (AUDIT_NO_UPDATE_TRIGGER, AUDIT_NO_DELETE_TRIGGER):
    # RAISE(ABORT, ...) is SQLite trigger syntax; another backend needs its own version (e.g. a Postgres rule).
    event.listen(AuditEvent.__table__, "after_create", DDL(_trigger_sql).execute_if(dialect="sqlite"))


# ---------------------------------------------------------------- store timestamps as UTC


@event.listens_for(Base, "before_insert", propagate=True)
@event.listens_for(Base, "before_update", propagate=True)
def _timestamps_to_utc(mapper: Any, _connection: Any, target: Any) -> None:
    """Before the ORM writes a row, convert every aware datetime on it to naive UTC.

    SQLite would otherwise drop the offset silently (15:00-05:00 stored as 15:00). Naive values are taken to be
    UTC already. Core-level inserts (session.execute(insert(...))) bypass this hook and must call types.to_utc.
    """
    for attr in mapper.column_attrs:
        if isinstance(attr.columns[0].type, DateTime):
            value = getattr(target, attr.key, None)
            if isinstance(value, datetime) and value.tzinfo is not None:
                setattr(target, attr.key, to_utc(value))
