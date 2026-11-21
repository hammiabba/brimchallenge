"""Baseline schema: reference data, bills, controls results, approvals, bank accounts, payments, intake, audit log.

Generated with `alembic revision --autogenerate` against an empty database, then reviewed and reorganized by hand:
tables are grouped and commented, index creation uses op.create_index, and the audit-log triggers (which
autogenerate cannot see) are added with op.execute.

This migration is a frozen snapshot. Every allowed value and constraint is written out here, not imported from
app.db.models, so later edits to the models can never change what this revision does. tests/db/test_schema.py
checks that the database it builds is identical to app.db.models.

SQLite only. Two things here are SQLite-specific: the audit triggers use RAISE(ABORT, ...), and departments and
users reference each other, which SQLite accepts inline because it doesn't check FK targets at CREATE TABLE time.
A Postgres port needs its own trigger function and must add departments.manager_user_id with op.create_foreign_key
after users exists.

Revision ID: 0001
Revises:
Create Date: 2026-11-21 01:58:16.361577
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic to order migrations.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------- frozen value lists
# Copied from app/db/models.py at the time of this revision. Changing them needs a new migration.

ORIGINS = ("history", "app")
CURRENCIES = ("CAD", "USD")
PROVINCES = ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")
USER_ROLES = ("employee", "ap_clerk", "approver", "finance_manager", "controller_admin", "auditor")
USER_STATUSES = ("active", "on_leave", "terminated")
VENDOR_STATUSES = ("active", "on_hold", "pending_review")
PAYMENT_METHODS = ("EFT", "CHEQUE", "CARD")
GL_ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")
TAX_APPLIES_TO = ("all", "goods")
CONTRACT_BILLING_TYPES = ("fixed_monthly", "rate_card", "retainer", "blanket")
CONTRACT_STATUSES = ("active", "expired")
PO_STATUSES = ("open", "partially_invoiced", "closed")
POLICY_RULE_TYPES = ("approval", "payment_release", "match")
CARD_SOURCES = ("employee_card", "ap_virtual_card")
BILL_STATUSES = (
    "needs_review", "on_hold", "pending_approval", "approved", "rejected", "scheduled", "paid", "credit_open", "void",
)
LINE_TYPES = ("goods", "services")
CODING_STATUSES = ("none", "suggested", "accepted", "overridden")
SEVERITIES = ("block", "warn", "info")
FLAG_RESOLUTIONS = ("open", "overridden", "resolved")
STEP_ROLES = ("dept_manager", "finance_manager", "controller_admin", "cfo")
DECISIONS = ("approved", "rejected")
BANK_CHANGE_CHANNELS = ("phone_callback_verified", "vendor_portal", "email_request")
BANK_CHANGE_STATUSES = ("pending_verification", "verified", "rejected")
PAYMENT_STATUSES = ("scheduled", "released", "settled", "outstanding", "failed", "cancelled")
EMAIL_CLASSES = ("invoice", "credit_note", "statement", "payment_inquiry", "missing_attachment", "not_ap")
INTAKE_STATUSES = ("ok", "llm_skipped", "failed", "queued", "processing")

# Append-only audit log: any UPDATE or DELETE on audit_events aborts the statement.
AUDIT_TRIGGERS = {
    "audit_events_no_update": """
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END
""",
    "audit_events_no_delete": """
CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END
""",
}


# ---------------------------------------------------------------- small builders (keep the tables readable)
# op.f() marks a name as final, so Alembic doesn't run it through the naming convention a second time.

def _in(table: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """Named CHECK `column IN (...)`, named ck_<table>_<column> like the models' naming convention."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(f"ck_{table}_{column}"))


def _check(table: str, name: str, sql: str) -> sa.CheckConstraint:
    """Named free-form CHECK, ck_<table>_<name>."""
    return sa.CheckConstraint(sql, name=op.f(f"ck_{table}_{name}"))


def _fk(table: str, column: str, target: str, **kw: object) -> sa.ForeignKeyConstraint:
    """Single-column FK named fk_<table>_<column>_<target table>. `target` is "table.column"."""
    target_table = target.split(".")[0]
    return sa.ForeignKeyConstraint([column], [target], name=op.f(f"fk_{table}_{column}_{target_table}"), **kw)


def _pk(table: str, *columns: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint(*columns, name=op.f(f"pk_{table}"))


def _index(table: str, *columns: str) -> None:
    """Non-unique index ix_<table>_<col1>_<col2>..."""
    op.create_index(op.f(f"ix_{table}_{'_'.join(columns)}"), table, list(columns), unique=False)


def _drop_index(table: str, *columns: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{'_'.join(columns)}"), table_name=table)


# FKs in the users <-> departments cycle are checked at COMMIT, so a seed can insert both sides in one transaction.
DEFERRED = {"deferrable": True, "initially": "DEFERRED"}


def upgrade() -> None:
    """Create every table, index and trigger."""
    if op.get_bind().dialect.name != "sqlite":
        raise NotImplementedError("0001_baseline targets SQLite; see the module docstring for what a port needs.")

    # ============================================================ reference data (loaded from dataset CSVs)

    op.create_table(
        "gl_accounts",
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        _in("gl_accounts", "account_type", GL_ACCOUNT_TYPES),
        _pk("gl_accounts", "account_number"),
    )

    # departments.manager_user_id -> users and users.department_id -> departments form a cycle (see docstring).
    op.create_table(
        "departments",
        sa.Column("department_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cost_centre", sa.Text(), nullable=False),
        sa.Column("annual_budget_cad_cents", sa.Integer(), nullable=False),
        sa.Column("manager_user_id", sa.Text(), nullable=False),
        _fk("departments", "manager_user_id", "users.user_id", **DEFERRED),
        _pk("departments", "department_id"),
    )

    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("department_id", sa.Text(), nullable=False),
        sa.Column("manager_id", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("approval_limit_cad_cents", sa.Integer(), nullable=False),
        sa.Column("work_province", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("status_since", sa.Date(), nullable=True),
        sa.Column("delegate_user_id", sa.Text(), nullable=True),
        sa.Column("hire_date", sa.Date(), nullable=False),
        _in("users", "role", USER_ROLES),
        _in("users", "status", USER_STATUSES),
        _in("users", "work_province", PROVINCES),
        _fk("users", "delegate_user_id", "users.user_id", **DEFERRED),
        _fk("users", "department_id", "departments.department_id", **DEFERRED),
        _fk("users", "manager_id", "users.user_id", **DEFERRED),
        _pk("users", "user_id"),
    )

    # recoverable: yes / no / NULL (= "n/a" in the CSV, for EXEMPT and FOREIGN).
    op.create_table(
        "tax_codes",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rate", sa.Text(), nullable=False),
        sa.Column("applies_to", sa.Text(), nullable=False),
        sa.Column("recoverable", sa.Boolean(), nullable=True),
        sa.Column("gl_account", sa.Text(), nullable=True),
        _in("tax_codes", "applies_to", TAX_APPLIES_TO),
        _fk("tax_codes", "gl_account", "gl_accounts.account_number"),
        _pk("tax_codes", "code"),
    )

    # Vendor master without bank columns; those are versioned in vendor_bank_accounts.
    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("default_gl_account", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("province_or_state", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("gst_hst_number", sa.Text(), nullable=True),
        sa.Column("qst_number", sa.Text(), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("early_pay_discount", sa.Text(), nullable=True),
        sa.Column("preferred_payment_method", sa.Text(), nullable=False),
        sa.Column("accepts_card_payment", sa.Boolean(), nullable=False),
        sa.Column("ap_contact_email", sa.Text(), nullable=False),
        sa.Column("requires_po", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("onboarded_at", sa.Date(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        _in("vendors", "origin", ORIGINS),
        _in("vendors", "preferred_payment_method", PAYMENT_METHODS),
        _in("vendors", "status", VENDOR_STATUSES),
        _fk("vendors", "default_gl_account", "gl_accounts.account_number"),
        _pk("vendors", "vendor_id"),
    )

    op.create_table(
        "contracts",
        sa.Column("contract_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("billing_type", sa.Text(), nullable=False),
        sa.Column("monthly_fee_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("hourly_rate_cap_cents", sa.Integer(), nullable=True),
        sa.Column("fuel_surcharge_cap_pct", sa.Text(), nullable=True),
        sa.Column("not_to_exceed_monthly_cents", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _in("contracts", "billing_type", CONTRACT_BILLING_TYPES),
        _in("contracts", "currency", CURRENCIES),
        _in("contracts", "status", CONTRACT_STATUSES),
        _fk("contracts", "vendor_id", "vendors.vendor_id"),
        _pk("contracts", "contract_id"),
    )

    op.create_table(
        "purchase_orders",
        sa.Column("po_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("department_id", sa.Text(), nullable=False),
        sa.Column("requester_user_id", sa.Text(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("total_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=False),
        _in("purchase_orders", "currency", CURRENCIES),
        _in("purchase_orders", "status", PO_STATUSES),
        _fk("purchase_orders", "approved_by", "users.user_id"),
        _fk("purchase_orders", "department_id", "departments.department_id"),
        _fk("purchase_orders", "requester_user_id", "users.user_id"),
        _fk("purchase_orders", "vendor_id", "vendors.vendor_id"),
        _pk("purchase_orders", "po_id"),
    )

    # approval_policies.csv; condition / required keep the dataset text (controls parses thresholds from it).
    op.create_table(
        "policies",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("required", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=True),
        _in("policies", "rule_type", POLICY_RULE_TYPES),
        _fk("policies", "updated_by", "users.user_id"),
        _pk("policies", "rule_id"),
    )

    op.create_table(
        "fx_rates",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("usd_to_cad", sa.Text(), nullable=False),
        _pk("fx_rates", "date"),
    )

    op.create_table(
        "card_transactions",
        sa.Column("txn_id", sa.Text(), nullable=False),
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("cardholder_user_id", sa.Text(), nullable=False),
        sa.Column("posted_date", sa.Date(), nullable=False),
        sa.Column("merchant_descriptor", sa.Text(), nullable=False),
        sa.Column("mcc", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("amount_cad_cents", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("receipt_attached", sa.Boolean(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        _in("card_transactions", "currency", CURRENCIES),
        _in("card_transactions", "source", CARD_SOURCES),
        _fk("card_transactions", "cardholder_user_id", "users.user_id"),
        _pk("card_transactions", "txn_id"),
    )

    # The CAD operating account; exactly one of debit / credit per line.
    op.create_table(
        "bank_statement_lines",
        sa.Column("bank_txn_id", sa.Text(), nullable=False),
        sa.Column("posted_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("debit_cad_cents", sa.Integer(), nullable=True),
        sa.Column("credit_cad_cents", sa.Integer(), nullable=True),
        _check("bank_statement_lines", "one_side", "(debit_cad_cents IS NULL) <> (credit_cad_cents IS NULL)"),
        _pk("bank_statement_lines", "bank_txn_id"),
    )

    # ============================================================ intake

    op.create_table(
        "emails",
        sa.Column("email_id", sa.Text(), nullable=False),
        sa.Column("from_name", sa.Text(), nullable=True),
        sa.Column("from_address", sa.Text(), nullable=False),
        sa.Column("to_address", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("email_class", sa.Text(), nullable=True),
        sa.Column("triage_reason", sa.Text(), nullable=True),
        sa.Column("triaged_at", sa.DateTime(), nullable=True),
        _in("emails", "email_class", EMAIL_CLASSES),
        _pk("emails", "email_id"),
    )

    # ============================================================ bills and their lines / taxes

    # History invoices and app bills in one table. No UNIQUE on (vendor_id, norm_invoice_number): the history
    # repeats some, and the duplicate check needs to see them. row_version backs optimistic concurrency.
    # draft_json is the immutable snapshot of the extraction output at intake time and is never edited.
    # Clerk corrections go to the bill columns, bill_lines and bill_taxes; the current DraftBill is rebuilt
    # from those tables. Enforced by the writing code, not by a trigger.
    op.create_table(
        "bills",
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=True),
        sa.Column("vendor_invoice_number", sa.Text(), nullable=False),
        sa.Column("norm_invoice_number", sa.Text(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("total_cad_cents", sa.Integer(), nullable=False),
        sa.Column("fx_rate_to_cad", sa.Text(), nullable=False),
        sa.Column("fx_rate_date", sa.Date(), nullable=True),
        sa.Column("is_credit_note", sa.Boolean(), nullable=False),
        sa.Column("ship_to_province", sa.Text(), nullable=True),
        sa.Column("department_id", sa.Text(), nullable=True),
        sa.Column("requester_user_id", sa.Text(), nullable=True),
        sa.Column("po_id", sa.Text(), nullable=True),
        sa.Column("contract_id", sa.Text(), nullable=True),
        sa.Column("file_hash", sa.Text(), nullable=True),
        sa.Column("source_email_id", sa.Text(), nullable=True),
        sa.Column("draft_json", sa.JSON(), nullable=True),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _in("bills", "currency", CURRENCIES),
        _in("bills", "origin", ORIGINS),
        _in("bills", "ship_to_province", PROVINCES),
        _in("bills", "status", BILL_STATUSES),
        _fk("bills", "contract_id", "contracts.contract_id"),
        _fk("bills", "created_by", "users.user_id"),
        _fk("bills", "department_id", "departments.department_id"),
        _fk("bills", "po_id", "purchase_orders.po_id"),
        _fk("bills", "requester_user_id", "users.user_id"),
        _fk("bills", "vendor_id", "vendors.vendor_id"),
        _pk("bills", "bill_id"),
    )
    _index("bills", "department_id", "status")
    _index("bills", "file_hash")
    _index("bills", "status")
    _index("bills", "vendor_id", "norm_invoice_number")

    op.create_table(
        "bill_lines",
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Text(), nullable=False),
        sa.Column("unit_price", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("line_type", sa.Text(), nullable=False),
        sa.Column("gst_hst_code", sa.Text(), nullable=True),
        sa.Column("pst_qst_code", sa.Text(), nullable=True),
        sa.Column("gl_account", sa.Text(), nullable=True),
        sa.Column("department_id", sa.Text(), nullable=True),
        sa.Column("suggested_gl_account", sa.Text(), nullable=True),
        sa.Column("suggested_department_id", sa.Text(), nullable=True),
        sa.Column("suggestion_confidence", sa.REAL(), nullable=True),
        sa.Column("suggestion_reason", sa.Text(), nullable=True),
        sa.Column("coding_status", sa.Text(), nullable=False),
        sa.Column("coded_by", sa.Text(), nullable=True),
        sa.Column("coded_at", sa.DateTime(), nullable=True),
        _in("bill_lines", "coding_status", CODING_STATUSES),
        _check(
            "bill_lines",
            "coded_line_has_codes",
            "coding_status NOT IN ('accepted', 'overridden') OR (gl_account IS NOT NULL AND department_id IS NOT NULL)",
        ),
        _in("bill_lines", "line_type", LINE_TYPES),
        _check(
            "bill_lines",
            "confidence_range",
            "suggestion_confidence IS NULL OR (suggestion_confidence >= 0 AND suggestion_confidence <= 1)",
        ),
        _fk("bill_lines", "bill_id", "bills.bill_id"),
        _fk("bill_lines", "coded_by", "users.user_id"),
        _fk("bill_lines", "department_id", "departments.department_id"),
        _fk("bill_lines", "gl_account", "gl_accounts.account_number"),
        _fk("bill_lines", "gst_hst_code", "tax_codes.code"),
        _fk("bill_lines", "pst_qst_code", "tax_codes.code"),
        _pk("bill_lines", "bill_id", "line_no"),
    )

    op.create_table(
        "bill_taxes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("tax_code", sa.Text(), nullable=False),
        sa.Column("rate", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        _fk("bill_taxes", "bill_id", "bills.bill_id"),
        _fk("bill_taxes", "tax_code", "tax_codes.code"),
        _pk("bill_taxes", "id"),
    )
    _index("bill_taxes", "bill_id")

    # ============================================================ controls results

    op.create_table(
        "controls_runs",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("can_auto_proceed", sa.Boolean(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        _fk("controls_runs", "bill_id", "bills.bill_id"),
        _pk("controls_runs", "run_id"),
        sa.UniqueConstraint("bill_id", "version", name=op.f("uq_controls_runs_bill_id_version")),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "bill_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_comment", sa.Text(), nullable=True),
        _check(
            "bill_flags",
            "override_needs_comment",
            "resolution <> 'overridden' OR (resolution_comment IS NOT NULL AND length(trim(resolution_comment)) > 0)",
        ),
        _in("bill_flags", "resolution", FLAG_RESOLUTIONS),
        _in("bill_flags", "severity", SEVERITIES),
        _fk("bill_flags", "resolved_by", "users.user_id"),
        _fk("bill_flags", "run_id", "controls_runs.run_id"),
        _pk("bill_flags", "id"),
    )
    _index("bill_flags", "run_id")

    # ============================================================ approvals

    # user_id NULL = routing returned "UNASSIGNED".
    op.create_table(
        "approval_route_steps",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("policy_ids", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("delegated_from", sa.Text(), nullable=True),
        sa.Column("escalated_from", sa.Text(), nullable=True),
        _in("approval_route_steps", "role", STEP_ROLES),
        _fk("approval_route_steps", "bill_id", "bills.bill_id"),
        _fk("approval_route_steps", "run_id", "controls_runs.run_id"),
        _fk("approval_route_steps", "user_id", "users.user_id"),
        _pk("approval_route_steps", "run_id", "step_no"),
    )
    _index("approval_route_steps", "bill_id")

    # actor_role is the actor's user role (users.role); step_role is the route step kind (ApprovalStep.role),
    # NULL when the decision isn't tied to a routed step. Two vocabularies, two columns, never mixed.
    op.create_table(
        "approval_decisions",
        sa.Column("decision_id", sa.Text(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Text(), nullable=False),
        sa.Column("actor_role", sa.Text(), nullable=False),
        sa.Column("step_role", sa.Text(), nullable=True),
        sa.Column("on_behalf_of", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        _in("approval_decisions", "actor_role", USER_ROLES),
        _in("approval_decisions", "step_role", STEP_ROLES),
        _in("approval_decisions", "decision", DECISIONS),
        _in("approval_decisions", "origin", ORIGINS),
        _check("approval_decisions", "not_on_behalf_of_self", "on_behalf_of IS NULL OR on_behalf_of <> actor_user_id"),
        _fk("approval_decisions", "actor_user_id", "users.user_id"),
        _fk("approval_decisions", "bill_id", "bills.bill_id"),
        _fk("approval_decisions", "on_behalf_of", "users.user_id"),
        _fk("approval_decisions", "run_id", "controls_runs.run_id"),
        _pk("approval_decisions", "decision_id"),
    )
    _index("approval_decisions", "bill_id")

    op.create_table(
        "user_absences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("delegate_user_id", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        _check("user_absences", "delegate_not_self", "delegate_user_id <> user_id"),
        _check("user_absences", "valid_range", "ends_on IS NULL OR ends_on >= starts_on"),
        _fk("user_absences", "delegate_user_id", "users.user_id"),
        _fk("user_absences", "user_id", "users.user_id"),
        _pk("user_absences", "id"),
    )
    _index("user_absences", "user_id")

    # ============================================================ vendor bank accounts and changes

    op.create_table(
        "vendor_bank_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("institution", sa.Text(), nullable=False),
        sa.Column("transit", sa.Text(), nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("account_last4", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source_change_id", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        _in("vendor_bank_accounts", "origin", ORIGINS),
        _check("vendor_bank_accounts", "last4_matches_account", "account_last4 = substr(account, length(account) - 3)"),
        _check("vendor_bank_accounts", "valid_range", "valid_to IS NULL OR valid_to >= valid_from"),
        _fk("vendor_bank_accounts", "vendor_id", "vendors.vendor_id"),
        _pk("vendor_bank_accounts", "id"),
        sqlite_autoincrement=True,
    )
    _index("vendor_bank_accounts", "vendor_id")
    # One open account per vendor: unique over the rows where valid_to IS NULL only.
    op.create_index(
        op.f("uq_vendor_bank_accounts_one_active"),
        "vendor_bank_accounts",
        ["vendor_id"],
        unique=True,
        sqlite_where=sa.text("valid_to IS NULL"),
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    op.create_table(
        "bank_change_requests",
        sa.Column("change_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("request_channel", sa.Text(), nullable=False),
        sa.Column("old_account_last4", sa.Text(), nullable=True),
        sa.Column("new_account_last4", sa.Text(), nullable=False),
        sa.Column("new_institution", sa.Text(), nullable=True),
        sa.Column("new_transit", sa.Text(), nullable=True),
        sa.Column("new_account", sa.Text(), nullable=True),
        sa.Column("verified_by_callback", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        _in("bank_change_requests", "origin", ORIGINS),
        _in("bank_change_requests", "request_channel", BANK_CHANGE_CHANNELS),
        _in("bank_change_requests", "status", BANK_CHANGE_STATUSES),
        _check(
            "bank_change_requests",
            "new_last4_matches_account",
            "new_account IS NULL OR new_account_last4 = substr(new_account, length(new_account) - 3)",
        ),
        _check(
            "bank_change_requests",
            "verifier_not_requester",
            "verified_by IS NULL OR requested_by IS NULL OR verified_by <> requested_by",
        ),
        _fk("bank_change_requests", "requested_by", "users.user_id"),
        _fk("bank_change_requests", "vendor_id", "vendors.vendor_id"),
        _fk("bank_change_requests", "verified_by", "users.user_id"),
        _pk("bank_change_requests", "change_id"),
    )
    _index("bank_change_requests", "vendor_id")

    # ============================================================ payments

    # Not unique per bill: the history has invoices paid twice. idempotency_key is UNIQUE (NULLs don't collide).
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.Text(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("fx_rate_to_cad", sa.Text(), nullable=False),
        sa.Column("fx_rate_date", sa.Date(), nullable=True),
        sa.Column("amount_cad_cents", sa.Integer(), nullable=False),
        sa.Column("discount_taken_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("prepared_by", sa.Text(), nullable=True),
        sa.Column("released_by", sa.Text(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        _in("payments", "currency", CURRENCIES),
        _in("payments", "method", PAYMENT_METHODS),
        _in("payments", "origin", ORIGINS),
        _in("payments", "status", PAYMENT_STATUSES),
        _check(
            "payments",
            "releaser_not_preparer",
            "released_by IS NULL OR prepared_by IS NULL OR released_by <> prepared_by",
        ),
        _fk("payments", "bank_account_id", "vendor_bank_accounts.id"),
        _fk("payments", "bill_id", "bills.bill_id"),
        _fk("payments", "prepared_by", "users.user_id"),
        _fk("payments", "released_by", "users.user_id"),
        _fk("payments", "vendor_id", "vendors.vendor_id"),
        _pk("payments", "payment_id"),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_payments_idempotency_key")),
    )
    _index("payments", "bill_id")
    _index("payments", "status")

    # ============================================================ intake items (needs emails and bills)

    op.create_table(
        "intake_items",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("email_id", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        _in("intake_items", "status", INTAKE_STATUSES),
        _fk("intake_items", "bill_id", "bills.bill_id"),
        _fk("intake_items", "created_by", "users.user_id"),
        _fk("intake_items", "email_id", "emails.email_id"),
        _pk("intake_items", "item_id"),
        sqlite_autoincrement=True,
    )
    _index("intake_items", "email_id")
    _index("intake_items", "file_hash")

    # ============================================================ audit log (append-only)

    # seq is AUTOINCREMENT so numbers are never reused. No FKs or CHECKs on purpose: the log must accept every event.
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.Text(), nullable=False),
        sa.Column("actor_role", sa.Text(), nullable=False),
        sa.Column("on_behalf_of", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("hash", sa.Text(), nullable=False),
        _pk("audit_events", "seq"),
        sa.UniqueConstraint("event_id", name=op.f("uq_audit_events_event_id")),
        sqlite_autoincrement=True,
    )
    _index("audit_events", "actor_user_id")
    _index("audit_events", "at")
    _index("audit_events", "entity_type", "entity_id")
    for trigger_sql in AUDIT_TRIGGERS.values():
        op.execute(trigger_sql)


def downgrade() -> None:
    """Drop everything upgrade() created, children before parents, triggers before their table."""
    # Audit log: triggers first, so nothing about the drop is blocked by them.
    for trigger_name in AUDIT_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    _drop_index("audit_events", "entity_type", "entity_id")
    _drop_index("audit_events", "at")
    _drop_index("audit_events", "actor_user_id")
    op.drop_table("audit_events")

    _drop_index("intake_items", "file_hash")
    _drop_index("intake_items", "email_id")
    op.drop_table("intake_items")

    _drop_index("payments", "status")
    _drop_index("payments", "bill_id")
    op.drop_table("payments")

    _drop_index("bank_change_requests", "vendor_id")
    op.drop_table("bank_change_requests")

    op.drop_index(op.f("uq_vendor_bank_accounts_one_active"), table_name="vendor_bank_accounts")
    _drop_index("vendor_bank_accounts", "vendor_id")
    op.drop_table("vendor_bank_accounts")

    _drop_index("user_absences", "user_id")
    op.drop_table("user_absences")

    _drop_index("approval_decisions", "bill_id")
    op.drop_table("approval_decisions")

    _drop_index("approval_route_steps", "bill_id")
    op.drop_table("approval_route_steps")

    _drop_index("bill_flags", "run_id")
    op.drop_table("bill_flags")

    op.drop_table("controls_runs")

    _drop_index("bill_taxes", "bill_id")
    op.drop_table("bill_taxes")

    op.drop_table("bill_lines")

    _drop_index("bills", "vendor_id", "norm_invoice_number")
    _drop_index("bills", "status")
    _drop_index("bills", "file_hash")
    _drop_index("bills", "department_id", "status")
    op.drop_table("bills")

    op.drop_table("emails")

    # Reference data, in reverse dependency order (departments and users reference each other; both go last).
    op.drop_table("bank_statement_lines")
    op.drop_table("card_transactions")
    op.drop_table("fx_rates")
    op.drop_table("policies")
    op.drop_table("purchase_orders")
    op.drop_table("contracts")
    op.drop_table("vendors")
    op.drop_table("tax_codes")
    op.drop_table("users")
    op.drop_table("departments")
    op.drop_table("gl_accounts")
