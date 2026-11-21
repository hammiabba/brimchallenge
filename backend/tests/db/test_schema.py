"""
Schema tests: the baseline migration builds the schema in app/db/models.py, it reverses cleanly, and the
constraints that protect money, approvals and the audit log really fire.

Every test gets a fresh SQLite file in tmp_path (see tests/db/conftest.py). No network, no LLM, no repo files.
"""
from __future__ import annotations

import csv
import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.db import models
from app.db.database import make_engine, resolve_database_url
from app.db.types import dec_to_text, from_cents, text_to_dec, to_cents, to_utc
from app.shared.schemas import EmailClass, LineType, Severity
from tests.conftest import DATASET
from tests.db.conftest import NOW, make_audit_event, make_bill, make_reference_rows

# Every table the baseline must create (from the step 1 spec), plus Alembic's own bookkeeping table.
EXPECTED_TABLES = {
    "departments", "users", "gl_accounts", "tax_codes", "vendors", "contracts", "purchase_orders", "policies",
    "fx_rates", "card_transactions", "bank_statement_lines",
    "bills", "bill_lines", "bill_taxes", "controls_runs", "bill_flags", "approval_route_steps",
    "approval_decisions", "vendor_bank_accounts", "bank_change_requests", "payments", "user_absences",
    "emails", "intake_items", "audit_events",
}
AUDIT_TRIGGERS = {"audit_events_no_update", "audit_events_no_delete"}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _triggers(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


# ---------------------------------------------------------------- 1. upgrade creates every table

def test_upgrade_creates_every_table(migrated_engine: Engine) -> None:
    tables = _tables(migrated_engine)
    assert tables == EXPECTED_TABLES | {"alembic_version"}
    # The models declare the same set, so nothing exists in one place only.
    assert set(models.Base.metadata.tables) == EXPECTED_TABLES
    assert _triggers(migrated_engine) == AUDIT_TRIGGERS


# ---------------------------------------------------------------- 2. the migration is reversible

def test_downgrade_base_then_upgrade_head(alembic_cfg: Config, db_url: str) -> None:
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")

    engine = make_engine(db_url)
    try:
        # Only Alembic's bookkeeping table survives a full downgrade: no tables, indexes or triggers are left over.
        assert _tables(engine) == {"alembic_version"}
        with engine.connect() as conn:
            leftovers = conn.exec_driver_sql(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name <> 'alembic_version'"
            ).all()
        assert leftovers == []
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = make_engine(db_url)
    try:
        assert _tables(engine) == EXPECTED_TABLES | {"alembic_version"}
        assert _triggers(engine) == AUDIT_TRIGGERS
    finally:
        engine.dispose()


# ---------------------------------------------------------------- 3. audit_events is append-only

def test_audit_events_insert_works_but_update_and_delete_fail(write_session: Session) -> None:
    write_session.add(make_audit_event())
    write_session.commit()
    assert write_session.scalar(select(models.AuditEvent.event_id)) == "EV-000001"

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        write_session.execute(update(models.AuditEvent).values(action="invoice.tampered"))
    write_session.rollback()

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        write_session.execute(delete(models.AuditEvent))
    write_session.rollback()

    # The row is still there, unchanged.
    row = write_session.scalars(select(models.AuditEvent)).one()
    assert (row.action, row.seq) == ("invoice.created", 1)


# ---------------------------------------------------------------- 4. foreign keys are enforced

def test_bill_line_for_missing_bill_is_rejected(session: Session) -> None:
    session.add(models.BillLine(bill_id="AP-99999", line_no=1, description="Freight", quantity="1",
                                unit_price="100.00", amount_cents=10_000, line_type="services", coding_status="none"))
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        session.flush()


def test_sqlite_pragmas_are_on_for_every_connection(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


# ---------------------------------------------------------------- 5. CHECK constraints

def _assert_check_fails(session: Session, constraint: str) -> None:
    """Flush and expect SQLite to name the CHECK constraint that failed."""
    with pytest.raises(IntegrityError, match=f"CHECK constraint failed: {constraint}"):
        session.flush()
    session.rollback()


def test_bad_bill_status_is_rejected(session: Session) -> None:
    make_reference_rows(session)
    session.add(make_bill(status="paid_twice"))
    _assert_check_fails(session, "ck_bills_status")


def test_bad_currency_is_rejected(session: Session) -> None:
    make_reference_rows(session)
    session.add(make_bill(currency="EUR"))
    _assert_check_fails(session, "ck_bills_currency")


def _controls_run(session: Session) -> int:
    make_reference_rows(session)
    session.add(make_bill())
    run = models.ControlsRun(bill_id="AP-00001", version=1, evaluated_at=NOW, can_auto_proceed=False,
                             result_json={"flags": []})
    session.add(run)
    session.commit()
    return run.run_id


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_overridden_flag_needs_a_comment(session: Session, comment: str | None) -> None:
    run_id = _controls_run(session)
    session.add(models.BillFlag(run_id=run_id, code="TAX_WRONG_FOR_PROVINCE", severity="warn", message="m",
                                evidence_json={}, resolution="overridden", resolution_comment=comment))
    _assert_check_fails(session, "ck_bill_flags_override_needs_comment")


def test_overridden_flag_with_comment_and_default_resolution_are_accepted(session: Session) -> None:
    run_id = _controls_run(session)
    session.add(models.BillFlag(run_id=run_id, code="TAX_WRONG_FOR_PROVINCE", severity="warn", message="m",
                                evidence_json={}, resolution="overridden", resolution_comment="Vendor confirmed"))
    session.add(models.BillFlag(run_id=run_id, code="CREDIT_NOTE", severity="info", message="m", evidence_json={}))
    session.commit()
    resolutions = sorted(session.scalars(select(models.BillFlag.resolution)))
    assert resolutions == ["open", "overridden"]  # the second flag got the server default


def test_bank_change_verified_by_its_requester_is_rejected(session: Session) -> None:
    make_reference_rows(session)
    session.add(models.BankChangeRequest(
        change_id="BC-010", vendor_id="V001", requested_at=NOW, requested_by="U004", request_channel="email_request",
        old_account_last4="2201", new_account_last4="9679", verified_by_callback=True, status="verified",
        verified_by="U004", verified_at=NOW, origin="app",
    ))
    _assert_check_fails(session, "ck_bank_change_requests_verifier_not_requester")


def test_bank_change_verified_by_someone_else_is_accepted(session: Session) -> None:
    make_reference_rows(session)
    session.add(models.BankChangeRequest(
        change_id="BC-010", vendor_id="V001", requested_at=NOW, requested_by="U004", request_channel="email_request",
        old_account_last4="2201", new_account_last4="9679", new_institution="004", new_transit="05541",
        new_account="000129679", verified_by_callback=True, status="verified", verified_by="U003", verified_at=NOW,
        origin="app",
    ))
    session.commit()  # leading zeros survive: the columns are TEXT
    assert session.scalar(select(models.BankChangeRequest.new_transit)) == "05541"


def _decision(**overrides: object) -> models.ApprovalDecision:
    """A valid history-style approval by U007 (role approver) on a dept_manager step."""
    values: dict[str, object] = {
        "decision_id": "AP-A-00001", "bill_id": "AP-00001", "step_no": 1, "actor_user_id": "U007",
        "actor_role": "approver", "step_role": "dept_manager", "decision": "approved", "acted_at": NOW,
        "origin": "history",
    }
    values.update(overrides)
    return models.ApprovalDecision(**values)


def test_approval_decision_keeps_user_role_and_step_role_apart(session: Session) -> None:
    make_reference_rows(session)
    session.add(make_bill())
    session.commit()
    # A routed step and a decision not tied to any step (step_role NULL) are both fine.
    session.add(_decision())
    session.add(_decision(decision_id="AP-A-00002", step_no=2, step_role=None))
    session.commit()
    rows = session.execute(select(models.ApprovalDecision.actor_role, models.ApprovalDecision.step_role)
                           .order_by(models.ApprovalDecision.decision_id)).all()
    assert rows == [("approver", "dept_manager"), ("approver", None)]


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"actor_role": "dept_manager"}, "ck_approval_decisions_actor_role"),  # a step name is not a user role
        ({"step_role": "approver"}, "ck_approval_decisions_step_role"),  # a user role is not a step name
    ],
)
def test_approval_decision_roles_reject_the_other_vocabulary(
    session: Session, overrides: dict[str, str], constraint: str
) -> None:
    make_reference_rows(session)
    session.add(make_bill())
    session.commit()
    session.add(_decision(**overrides))
    _assert_check_fails(session, constraint)


# ---------------------------------------------------------------- 6. one open bank account per vendor

def _account(account: str, valid_from: date, valid_to: date | None) -> models.VendorBankAccount:
    return models.VendorBankAccount(vendor_id="V001", institution="004", transit="95688", account=account,
                                    account_last4=account[-4:], valid_from=valid_from, valid_to=valid_to,
                                    origin="history")


def test_partial_unique_index_allows_closed_accounts_but_only_one_open(session: Session) -> None:
    make_reference_rows(session)
    session.add_all([
        _account("410650001", date(2024, 1, 1), date(2025, 1, 1)),  # closed
        _account("410650002", date(2025, 1, 1), date(2026, 1, 1)),  # closed
        _account("410652201", date(2026, 1, 1), None),  # the open one
    ])
    session.commit()

    session.add(_account("410659999", date(2026, 6, 1), None))  # a second open account
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: vendor_bank_accounts.vendor_id"):
        session.flush()


# ---------------------------------------------------------------- 7. repeated invoice numbers are allowed

def test_two_bills_with_same_vendor_and_normalized_number_are_allowed(session: Session) -> None:
    make_reference_rows(session)
    # FA-000583 and 583 normalize to the same number: a duplicate for controls to flag, not for the DB to refuse.
    session.add(make_bill(bill_id="AP-00001", vendor_invoice_number="FA-000583", norm_invoice_number="583"))
    session.add(make_bill(bill_id="AP-00002", vendor_invoice_number="583", norm_invoice_number="583"))
    session.commit()
    count = session.scalar(text("SELECT count(*) FROM bills WHERE vendor_id = 'V001' AND norm_invoice_number = '583'"))
    assert count == 2


# ---------------------------------------------------------------- 8. money and decimal helpers

@pytest.mark.parametrize("value", ["742.30", "0.01", "-15.00"])
def test_cents_round_trip_exactly(value: str) -> None:
    cents = to_cents(Decimal(value))
    assert isinstance(cents, int)
    back = from_cents(cents)
    assert back == Decimal(value)
    assert str(back) == value  # same digits, not just the same number


@pytest.mark.parametrize("value", ["742.30", "0.01", "-15.00", "0.09975"])
def test_decimal_text_round_trip_exactly(value: str) -> None:
    stored = dec_to_text(Decimal(value))
    assert stored == value
    assert text_to_dec(stored) == Decimal(value)
    assert str(text_to_dec(stored)) == value


def test_cents_conversion_details() -> None:
    assert to_cents(Decimal("742.30")) == 74_230
    assert to_cents(Decimal("0.005")) == 1  # ROUND_HALF_UP
    assert to_cents(Decimal("-0.005")) == -1  # half rounds away from zero on negatives too
    # A rate is not money: through cents it is quantized to 2 places, which is why rates are stored as TEXT.
    assert to_cents(Decimal("0.09975")) == 10
    assert dec_to_text(Decimal("1E-7")) == "0.0000001"  # never exponent notation in the database


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_to_cents_rejects_non_finite(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        to_cents(bad)


def test_helpers_reject_floats_and_junk() -> None:
    with pytest.raises(TypeError):
        to_cents(742.30)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        from_cents(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        dec_to_text(0.1)  # type: ignore[arg-type]
    for junk in ("", "  ", "1,234.56", "abc", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            text_to_dec(junk)


# ---------------------------------------------------------------- 9. relative SQLite URL resolution

def test_relative_sqlite_url_resolves_under_repo_root() -> None:
    target = REPO_ROOT / "backend" / "ap.db"
    existed_before = target.exists()

    resolved = resolve_database_url("sqlite:///./backend/ap.db")

    assert make_url(resolved).database == str(target)
    assert resolved == f"sqlite:///{target}"
    assert target.exists() == existed_before  # resolving a URL never creates the file


def test_other_urls_pass_through_unchanged(tmp_path) -> None:
    absolute = f"sqlite:///{tmp_path / 'ap.db'}"
    assert resolve_database_url(absolute) == absolute
    for url in ("sqlite://", "sqlite:///:memory:", "postgresql://user:secret@db.example/brim"):
        assert resolve_database_url(url) == url


# ---------------------------------------------------------------- migration and models agree exactly

def _schema_snapshot(engine: Engine) -> dict[str, object]:
    """Everything SQLite stores about the schema, in an order-independent form.

    CREATE TABLE text is split into one entry per column / constraint and sorted, so the same table declared with
    its constraints in a different order still compares equal. CHECK text, DEFERRABLE clauses and partial-index
    WHERE clauses are all part of that text, so they are compared too (alembic check doesn't look at CHECKs).
    """
    snapshot: dict[str, object] = {}
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND name <> 'alembic_version' AND sql IS NOT NULL"
        ).all()
    for kind, name, sql in rows:
        if kind == "table":
            body = sql[sql.index("(") + 1: sql.rindex(")")]
            parts = sorted(part.strip().rstrip(",") for part in body.splitlines() if part.strip())
            snapshot[f"table:{name}"] = parts
        else:
            snapshot[f"{kind}:{name}"] = re.sub(r"\s+", " ", sql).strip()
    return snapshot


def test_migration_builds_exactly_the_models_schema(migrated_engine: Engine, tmp_path) -> None:
    from_models = make_engine(f"sqlite:///{tmp_path / 'from_models.db'}")
    try:
        models.Base.metadata.create_all(from_models)
        assert _schema_snapshot(migrated_engine) == _schema_snapshot(from_models)
    finally:
        from_models.dispose()


# ---------------------------------------------------------------- CHECK lists vs the contract and the dataset

def test_check_lists_match_the_shared_contract_enums() -> None:
    assert models.EMAIL_CLASSES == tuple(c.value for c in EmailClass)
    assert models.SEVERITIES == tuple(s.value for s in Severity)
    assert models.LINE_TYPES == tuple(t.value for t in LineType)


DATASET_COLUMNS = [
    ("users", "role", models.USER_ROLES),
    ("users", "status", models.USER_STATUSES),
    ("users", "work_province", models.PROVINCES),
    ("vendors", "status", models.VENDOR_STATUSES),
    ("vendors", "preferred_payment_method", models.PAYMENT_METHODS),
    ("gl_accounts", "account_type", models.GL_ACCOUNT_TYPES),
    ("tax_codes", "applies_to", models.TAX_APPLIES_TO),
    ("contracts", "billing_type", models.CONTRACT_BILLING_TYPES),
    ("contracts", "status", models.CONTRACT_STATUSES),
    ("contracts", "currency", models.CURRENCIES),
    ("purchase_orders", "status", models.PO_STATUSES),
    ("purchase_orders", "currency", models.CURRENCIES),
    ("approval_policies", "rule_type", models.POLICY_RULE_TYPES),
    ("card_transactions", "source", models.CARD_SOURCES),
    ("card_transactions", "currency", models.CURRENCIES),
    ("invoices", "status", models.BILL_STATUSES),
    ("invoices", "currency", models.CURRENCIES),
    ("invoices", "ship_to_province", models.PROVINCES),
    ("invoice_lines", "line_type", models.LINE_TYPES),
    ("approvals", "action", models.DECISIONS),
    ("approvals", "approver_role", models.STEP_ROLES),  # loads into approval_decisions.step_role
    ("bank_change_history", "request_channel", models.BANK_CHANGE_CHANNELS),
    ("payments", "method", models.PAYMENT_METHODS),
    ("payments", "status", models.PAYMENT_STATUSES),
    ("payments", "currency", models.CURRENCIES),
]


@pytest.mark.parametrize(("csv_name", "column", "allowed"), DATASET_COLUMNS)
def test_every_dataset_value_fits_its_check(csv_name: str, column: str, allowed: tuple[str, ...]) -> None:
    """Loading the dataset later must never trip a CHECK. Blank cells become NULL, which CHECKs allow."""
    with open(DATASET / "data" / f"{csv_name}.csv", newline="", encoding="utf-8") as f:
        values = {row[column] for row in csv.DictReader(f)} - {""}
    assert values, f"{csv_name}.{column} is empty; the test is reading the wrong column"
    assert values <= set(allowed), f"{csv_name}.{column} has values outside the CHECK: {values - set(allowed)}"


# ---------------------------------------------------------------- timestamps and optimistic concurrency

def test_aware_timestamps_are_stored_as_utc(write_session: Session) -> None:
    toronto = timezone(timedelta(hours=-5))
    write_session.add(make_audit_event(at=datetime(2026, 11, 2, 10, 0, tzinfo=toronto)))
    write_session.commit()
    raw = write_session.scalar(text("SELECT at FROM audit_events"))
    assert raw.startswith("2026-11-02 15:00:00")  # 10:00-05:00 is 15:00 UTC
    assert to_utc(datetime(2026, 11, 2, 15, 0, tzinfo=UTC)) == datetime(2026, 11, 2, 15, 0)


def test_bill_row_version_increments_on_update(session: Session) -> None:
    make_reference_rows(session)
    bill = make_bill()
    session.add(bill)
    session.commit()
    assert bill.row_version == 1
    bill.status = "pending_approval"
    session.commit()
    assert bill.row_version == 2
