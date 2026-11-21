"""
Seed tests: the real dataset loads completely, exactly once, with money and facts intact; bad data is refused before
anything is written; --reset only ever deletes a safe SQLite file.

Databases live in pytest's tmp dirs. Nothing here touches the network or the repo.
"""
from __future__ import annotations

import csv
import hashlib
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.db import models
from app.db.database import make_engine
from app.db.seed import (
    NATURAL_KEYS,
    ResetRefused,
    SeedValidationError,
    check_rules,
    main,
    reset_target,
    seed_all,
)
from app.db.seed_mapping import (
    DataQualityError,
    RowReader,
    Violation,
    blank_to_none,
    exact_decimal_text,
    money_to_cents,
    parse_bool,
    parse_money,
)
from app.db.types import to_cents
from tests.conftest import DATASET
from tests.db.conftest import alembic_config

DATA = DATASET / "data"

# Row counts from the step 2 spec. The tests below also derive each count from the CSVs and assert both agree.
SPEC_COUNTS = {
    "departments": 8, "users": 40, "gl_accounts": 30, "tax_codes": 6, "vendors": 56, "contracts": 27,
    "purchase_orders": 52, "policies": 13, "fx_rates": 306, "card_transactions": 590, "bank_statement_lines": 354,
    "bills": 426, "bill_lines": 809, "approval_decisions": 474, "payments": 415, "bank_change_requests": 9,
    "emails": 59, "vendor_bank_accounts": 49,
}


def _csv(name: str) -> list[dict[str, str]]:
    with open(DATA / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()


def _scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _rows(engine: Engine, sql: str, **params: object) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def _migrated(path: Path) -> Engine:
    """A fresh database at `path`, migrated to head, with the app's engine settings."""
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), "head")
    return make_engine(url)


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory):
    """One database seeded from the real dataset, shared by the read-only tests in this module."""
    engine = _migrated(tmp_path_factory.mktemp("seeded") / "seed.db")
    with Session(engine) as session:
        report = seed_all(session, DATASET)
    yield engine, report
    engine.dispose()


# ---------------------------------------------------------------- 1. row counts

def _csv_counts() -> dict[str, int]:
    """Expected rows per table, derived from the dataset files themselves."""
    vendors, users, invoices = _csv("vendors"), _csv("users"), _csv("invoices")
    return {
        "departments": len(_csv("departments")), "users": len(users), "gl_accounts": len(_csv("gl_accounts")),
        "tax_codes": len(_csv("tax_codes")), "vendors": len(vendors), "contracts": len(_csv("contracts")),
        "purchase_orders": len(_csv("purchase_orders")), "policies": len(_csv("approval_policies")),
        "fx_rates": len(_csv("fx_rates")), "card_transactions": len(_csv("card_transactions")),
        "bank_statement_lines": len(_csv("bank_statement")), "bills": len(invoices),
        "bill_lines": len(_csv("invoice_lines")), "approval_decisions": len(_csv("approvals")),
        "payments": len(_csv("payments")), "bank_change_requests": len(_csv("bank_change_history")),
        "emails": 59, "vendor_bank_accounts": sum(1 for v in vendors if v["bank_account"]),
    }


def test_row_counts_match_the_csvs(seeded) -> None:
    engine, report = seeded
    expected = _csv_counts()
    assert expected == SPEC_COUNTS  # the spec's numbers and the files agree
    for table, count in expected.items():
        assert _count(engine, table) == count, table
    assert _count(engine, "user_absences") == sum(1 for u in _csv("users") if u["status"] == "on_leave") == 1
    # One tax row per non-zero GST/HST or PST/QST amount.
    nonzero = sum((Decimal(i["gst_hst_amount"]) != 0) + (Decimal(i["pst_qst_amount"]) != 0) for i in _csv("invoices"))
    assert _count(engine, "bill_taxes") == nonzero == 443
    # The report agrees with the database, and nothing was skipped on a first run.
    assert all(c.skipped == 0 for c in report.tables.values())
    assert report.tables["bills"].inserted == 426
    # Tables the seed must not touch.
    for untouched in ("audit_events", "intake_items", "controls_runs", "bill_flags", "approval_route_steps"):
        assert _count(engine, untouched) == 0, untouched


# ---------------------------------------------------------------- 2. idempotency

def _checksum(engine: Engine) -> dict[str, str]:
    """sha256 of every table's rows, all columns, in a fixed order."""
    sums = {}
    with engine.connect() as conn:
        for table in sorted(models.Base.metadata.tables):
            n = len(models.Base.metadata.tables[table].columns)
            order = ", ".join(str(i) for i in range(1, n + 1))
            rows = conn.exec_driver_sql(f"SELECT * FROM {table} ORDER BY {order}").all()
            sums[table] = hashlib.sha256(repr(rows).encode()).hexdigest()
    return sums


def test_second_seed_inserts_nothing_and_changes_nothing(tmp_path: Path) -> None:
    engine = _migrated(tmp_path / "seed.db")
    try:
        with Session(engine) as session:
            seed_all(session, DATASET)
        before = _checksum(engine)
        with Session(engine) as session:
            again = seed_all(session, DATASET)
        assert again.inserted_total == 0
        assert all(c.skipped == c.attempted for c in again.tables.values())
        assert _checksum(engine) == before
    finally:
        engine.dispose()


def test_reseed_never_overwrites_app_edits(tmp_path: Path) -> None:
    engine = _migrated(tmp_path / "seed.db")
    try:
        with Session(engine) as session:
            seed_all(session, DATASET)
        edited_condition = "Invoice total up to $12,000 CAD"
        with engine.begin() as conn:  # edits the app might make later
            conn.exec_driver_sql("UPDATE vendors SET status = 'on_hold' WHERE vendor_id = 'V001'")
            conn.execute(text("UPDATE policies SET condition = :c WHERE rule_id = 'P01'"), {"c": edited_condition})
            conn.exec_driver_sql("UPDATE user_absences SET delegate_user_id = 'U002' WHERE user_id = 'U012'")
        with Session(engine) as session:
            assert seed_all(session, DATASET).inserted_total == 0
        assert _scalar(engine, "SELECT status FROM vendors WHERE vendor_id = 'V001'") == "on_hold"
        assert _scalar(engine, "SELECT condition FROM policies WHERE rule_id = 'P01'") == edited_condition
        # The absence is recognized by its natural key (user_id, starts_on), so the edited delegate isn't duplicated.
        assert _rows(engine, "SELECT delegate_user_id FROM user_absences WHERE user_id = 'U012'") == [("U002",)]
    finally:
        engine.dispose()


def test_natural_keys_cover_every_autoincrement_table_the_seed_writes() -> None:
    from app.db.seed import TABLE_ORDER

    generated = {name for name in TABLE_ORDER
                 if [c.name for c in models.Base.metadata.tables[name].primary_key.columns] == ["id"]}
    assert generated == set(NATURAL_KEYS)


# ---------------------------------------------------------------- 3. money totals

def test_money_totals_match_the_csvs(seeded) -> None:
    engine, _ = seeded
    invoices, payments = _csv("invoices"), _csv("payments")
    assert _scalar(engine, "SELECT sum(total_cents) FROM bills") == sum(to_cents(Decimal(i["total"])) for i in invoices)
    assert _scalar(engine, "SELECT sum(total_cad_cents) FROM bills") == sum(
        to_cents(Decimal(i["total_cad"])) for i in invoices)
    assert _scalar(engine, "SELECT sum(amount_cad_cents) FROM payments") == sum(
        to_cents(Decimal(p["amount_cad"])) for p in payments)

    taxes = dict(_rows(engine, "SELECT bill_id, sum(amount_cents) FROM bill_taxes GROUP BY bill_id"))
    for inv in invoices:
        expected = to_cents(Decimal(inv["gst_hst_amount"]) + Decimal(inv["pst_qst_amount"]))
        assert taxes.get(inv["invoice_id"], 0) == expected, inv["invoice_id"]


# ---------------------------------------------------------------- 4. known facts

def test_known_facts_survive_the_seed(seeded) -> None:
    engine, _ = seeded
    # U012 is on leave with U003 as delegate, open-ended.
    assert _rows(engine, "SELECT delegate_user_id, starts_on, ends_on FROM user_absences WHERE user_id = 'U012'") == [
        ("U003", "2026-10-20", None)]
    # BC-009 (Cascadia, by email, never called back) is pending, and V004's open account came from it.
    bc009 = _scalar(engine, "SELECT status FROM bank_change_requests WHERE change_id = 'BC-009'")
    assert bc009 == "pending_verification"
    assert _scalar(engine, "SELECT source_change_id FROM vendor_bank_accounts "
                           "WHERE vendor_id = 'V004' AND valid_to IS NULL") == "BC-009"
    # Vendor statuses.
    assert dict(_rows(engine, "SELECT vendor_id, status FROM vendors WHERE status <> 'active'")) == {
        "V053": "on_hold", "V054": "pending_review", "V055": "pending_review", "V056": "pending_review"}
    # Three bills were paid twice.
    assert _rows(engine, "SELECT bill_id FROM payments GROUP BY bill_id HAVING count(*) = 2 ORDER BY bill_id") == [
        ("AP-00117",), ("AP-00278",), ("AP-00338",)]
    # Repeated invoice numbers: 5 exact (vendor, number) pairs; 7 once numbers are normalized like controls does.
    exact = _rows(engine, "SELECT vendor_id, vendor_invoice_number FROM bills GROUP BY 1, 2 HAVING count(*) > 1")
    normalized = _rows(engine, "SELECT vendor_id, norm_invoice_number FROM bills GROUP BY 1, 2 HAVING count(*) > 1")
    assert (len(exact), len(normalized)) == (5, 7)
    # U015 is terminated and still the requester on 10 bills.
    assert _scalar(engine, "SELECT status FROM users WHERE user_id = 'U015'") == "terminated"
    assert _scalar(engine, "SELECT count(*) FROM bills WHERE requester_user_id = 'U015'") == 10
    # Leading zeros in bank details survive (TEXT columns, strings all the way).
    assert _scalar(engine, "SELECT institution FROM vendor_bank_accounts WHERE vendor_id = 'V001'") == "004"
    # The three self-approvals by U010 are kept as evidence.
    self_approvals = _rows(engine, "SELECT d.decision_id, d.actor_user_id FROM approval_decisions d "
                                   "JOIN bills b ON b.bill_id = d.bill_id WHERE b.requester_user_id = d.actor_user_id "
                                   "ORDER BY d.decision_id")
    assert self_approvals == [("AP-A-00101", "U010"), ("AP-A-00193", "U010"), ("AP-A-00259", "U010")]
    # Roles: user role and step role are stored separately.
    assert _rows(engine, "SELECT actor_role, step_role FROM approval_decisions WHERE decision_id = 'AP-A-00001'") == [
        ("approver", "dept_manager")]


def test_report_carries_the_data_quality_notes(seeded) -> None:
    _, report = seeded
    assert report.notes[0].startswith(
        "history actor_role is taken from users.csv as of the seed date; the dataset does not record the "
        "approver's role at the time.")
    assert "Approvers terminated in users.csv: none." in report.notes[0]
    joined = "\n".join(report.notes)
    assert "mismatches: 0" in joined  # fx_rate_date
    assert "BC-009 (V004)" in joined


# ---------------------------------------------------------------- 5. database integrity

def test_foreign_key_and_integrity_checks_are_clean(seeded) -> None:
    engine, _ = seeded
    assert _rows(engine, "PRAGMA foreign_key_check") == []
    assert _rows(engine, "PRAGMA integrity_check") == [("ok",)]


# ---------------------------------------------------------------- 6. pre-flight refuses bad data, writes nothing

def _copy_dataset(tmp_path: Path) -> Path:
    """A writable copy of the dataset's data/ and inbox/ (no incoming invoices) to break on purpose."""
    target = tmp_path / "dataset"
    shutil.copytree(DATASET / "data", target / "data")
    shutil.copytree(DATASET / "inbox", target / "inbox")
    return target


def _edit_csv(path: Path, key_column: str, key: str, changes: dict[str, str]) -> None:
    """Rewrite one row of a CSV in place."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        if row[key_column] == key:
            row.update(changes)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_bad_rows_are_all_reported_and_nothing_is_written(tmp_path: Path) -> None:
    dataset = _copy_dataset(tmp_path)
    _edit_csv(dataset / "data" / "payments.csv", "payment_id", "PAY-00001", {"released_by": "U004"})  # = preparer
    _edit_csv(dataset / "data" / "invoices.csv", "invoice_id", "AP-00002", {"total": "18758.005"})  # 3 decimals
    _edit_csv(dataset / "data" / "users.csv", "user_id", "U012", {"delegate_user_id": "U012"})  # own delegate
    engine = _migrated(tmp_path / "seed.db")
    try:
        with Session(engine) as session, pytest.raises(SeedValidationError) as caught:
            seed_all(session, dataset)
        found = {(v.rule, v.row_id) for v in caught.value.violations}
        assert ("releaser_not_preparer", "PAY-00001") in found
        assert ("money_precision", "AP-00002") in found
        assert ("delegate_not_self", "U012/2026-10-20") in found
        assert "[releaser_not_preparer]" in caught.value.format()
        for table in models.Base.metadata.tables:
            assert _count(engine, table) == 0, table
    finally:
        engine.dispose()


def test_every_check_constraint_has_a_python_version() -> None:
    for table in models.Base.metadata.tables.values():
        check_rules(table)  # raises RuntimeError for a CHECK the pre-flight can't evaluate


# ---------------------------------------------------------------- 7. mapping helpers

def test_money_with_three_decimals_is_rejected_not_rounded() -> None:
    with pytest.raises(DataQualityError):
        parse_money("1.005")
    with pytest.raises(DataQualityError):
        money_to_cents("18758.005")
    assert money_to_cents("742.30") == 74_230
    assert money_to_cents("500000") == 50_000_000
    violations: list[Violation] = []
    assert RowReader("bills", "AP-1", {"total": "1.005"}, violations).money("total") is None
    assert [v.rule for v in violations] == ["money_precision"]


def test_booleans() -> None:
    assert parse_bool("yes") is True and parse_bool("TRUE") is True
    assert parse_bool("no") is False and parse_bool("false") is False
    assert parse_bool("n/a") is None
    with pytest.raises(DataQualityError):
        parse_bool("maybe")


def test_text_and_blanks() -> None:
    assert blank_to_none("") is None and blank_to_none("   ") is None and blank_to_none(None) is None
    assert blank_to_none("004") == "004"
    violations: list[Violation] = []
    reader = RowReader("vendors", "V001", {"bank_institution": "004", "qst_number": ""}, violations)
    assert reader.text("bank_institution") == "004"
    assert reader.text("qst_number") is None
    assert exact_decimal_text("0.09975") == "0.09975" and exact_decimal_text("1") == "1"
    assert violations == []


# ---------------------------------------------------------------- 8. --reset safety

def test_reset_refuses_anything_but_a_safe_sqlite_file(tmp_path: Path) -> None:
    protected = [REPO_ROOT / "dataset"]
    with pytest.raises(ResetRefused, match="only a SQLite file"):
        reset_target("postgresql://user:secret@db.example/brim", protected)
    with pytest.raises(ResetRefused, match="in-memory"):
        reset_target("sqlite://", protected)
    with pytest.raises(ResetRefused, match="protected"):
        reset_target(f"sqlite:///{DATASET / 'data' / 'seed.db'}", protected)
    with pytest.raises(ResetRefused, match="protected"):  # relative URL, resolved against the repo root first
        reset_target("sqlite:///./dataset/brim_ap_dataset/x.db", protected)
    assert reset_target(f"sqlite:///{tmp_path / 'ok.db'}", protected) == Path(tmp_path / "ok.db").resolve()


def test_cli_reset_refusal_exits_2_and_touches_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--database-url", "postgresql://user:secret@db.example/brim", "--reset"]) == 2
    assert "refusing --reset" in capsys.readouterr().err


def test_cli_seeds_then_reseeds_with_zero_inserts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    assert main(["--database-url", url, "--reset"]) == 0
    first = capsys.readouterr().out
    assert "(4167 rows inserted)" in first
    assert main(["--database-url", url]) == 0  # no --reset: the same database, seeded again
    second = capsys.readouterr().out
    assert "(0 rows inserted)" in second
    bills_line = next(line for line in second.splitlines() if line.startswith("bills "))
    assert bills_line.split()[1:] == ["426", "0", "426"]  # rows, inserted, skipped
