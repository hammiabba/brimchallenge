"""
DB-backed RefData parity: refdata_from_db over a seeded database is the same RefData load_refdata builds from the
CSVs, gives the same controls results for every history bill, and reflects app changes (app bills, verified bank
changes, policy edits) while never writing.

The seeded database is built once per module in a tmp dir; tests that change data do it in a session they roll back.
"""
from __future__ import annotations

import csv
import dataclasses
import statistics
import time
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from app.controls import REFDATA_FILES, RefData, bill_from_history, find_duplicates, load_refdata, route, run_controls
from app.db import models
from app.db.bills import create_bill_from_draft, load_draft_bill
from app.db.database import as_write_engine, make_engine
from app.db.refdata_db import CSV_COLUMNS, refdata_from_db, rows_as_csv
from app.db.seed import seed_all
from tests.conftest import DATASET
from tests.db.conftest import alembic_config
from tests.db.test_bills import harlow_draft

DATA = DATASET / "data"
# Columns where the CSV writes a whole amount ("500000") and the database renders cents ("500000.00").
MONEY_BY_VALUE = {("users", "approval_limit_cad"), ("departments", "annual_budget_cad")}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    """A database migrated to head and seeded from the real dataset, shared by this module (nothing commits to it)."""
    url = f"sqlite:///{tmp_path_factory.mktemp('refdata') / 'seed.db'}"
    command.upgrade(alembic_config(url), "head")
    engine = make_engine(url)
    with Session(as_write_engine(engine)) as s:
        seed_all(s, DATASET)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def csv_ref() -> RefData:
    """RefData the original way, from the CSV files."""
    return load_refdata(DATA)


@pytest.fixture
def rs(seeded: Engine) -> Iterator[Session]:
    """Read session; rolled back when the test ends."""
    with Session(seeded) as s:
        yield s


@pytest.fixture
def ws(seeded: Engine) -> Iterator[Session]:
    """Write session; never committed, so every change it makes is rolled back when the test ends."""
    with Session(as_write_engine(seeded)) as s:
        yield s
        s.rollback()


def _normalised(ref: RefData, field: str) -> object:
    """One RefData field ready to compare: whole-amount money columns become Decimals (compared by value)."""
    value = getattr(ref, field)
    if field in ("users", "departments"):
        return {key: {col: (Decimal(v) if (field, col) in MONEY_BY_VALUE else v) for col, v in row.items()}
                for key, row in value.items()}
    return value


def _bill_of(ref: RefData, vendor_id: str) -> str:
    """The first history invoice of a vendor."""
    return next(i for i, row in ref.invoices.items() if row["vendor_id"] == vendor_id)


def _codes(result) -> set[str]:
    return {f.code for f in result.flags}


# ---------------------------------------------------------------- 1. structural parity


def test_rendered_columns_are_the_csv_headers() -> None:
    for stem in REFDATA_FILES:
        with open(DATA / f"{stem}.csv", newline="", encoding="utf-8") as f:
            assert tuple(next(csv.reader(f))) == CSV_COLUMNS[stem], stem


def test_rows_as_csv_has_every_stem_with_csv_shaped_rows(rs: Session) -> None:
    rows = rows_as_csv(rs)
    assert tuple(rows) == REFDATA_FILES
    for stem, stem_rows in rows.items():
        assert stem_rows, stem
        assert all(tuple(r) == CSV_COLUMNS[stem] and all(isinstance(v, str) for v in r.values()) for r in stem_rows)


def test_db_refdata_equals_csv_refdata_field_by_field(rs: Session, csv_ref: RefData) -> None:
    db_ref = refdata_from_db(rs)
    for f in dataclasses.fields(RefData):
        assert _normalised(db_ref, f.name) == _normalised(csv_ref, f.name), f.name
    # Iteration order matters to controls (e.g. contract_for takes a vendor's first contract): same order as the CSVs.
    # tax_codes is the exception: the CSV isn't in key order, and controls only looks tax codes up by key.
    for name in ("vendors", "users", "departments", "contracts", "purchase_orders", "invoices", "invoice_lines",
                 "policies"):
        assert list(getattr(db_ref, name)) == list(getattr(csv_ref, name)), name
    assert db_ref.bank_changes == csv_ref.bank_changes and db_ref.card_txns == csv_ref.card_txns


def test_only_the_whole_amount_money_columns_needed_normalising(rs: Session, csv_ref: RefData) -> None:
    db_ref = refdata_from_db(rs)
    differing = {(name, col)
                 for name in ("vendors", "users", "departments", "contracts", "purchase_orders", "tax_codes",
                              "invoices")
                 for key, row in getattr(csv_ref, name).items()
                 for col, v in row.items() if getattr(db_ref, name)[key][col] != v}
    assert differing == MONEY_BY_VALUE


# ---------------------------------------------------------------- 2. behavioural parity


def test_run_controls_is_identical_for_every_history_bill(rs: Session, csv_ref: RefData) -> None:
    db_ref = refdata_from_db(rs)
    started = time.perf_counter()
    for invoice_id in csv_ref.invoices:
        bill = bill_from_history(csv_ref, invoice_id)
        assert bill_from_history(db_ref, invoice_id).model_dump(mode="json") == bill.model_dump(mode="json")
        expected = run_controls(bill, ref=csv_ref).model_dump(mode="json")
        assert run_controls(bill, ref=db_ref).model_dump(mode="json") == expected, invoice_id
    assert len(csv_ref.invoices) == 426
    assert time.perf_counter() - started < 60


# ---------------------------------------------------------------- 3. self-duplicate trap


def test_a_stored_bill_must_be_excluded_or_it_duplicates_itself(ws: Session) -> None:
    bill_id = create_bill_from_draft(ws, harlow_draft(), created_by="U004", received_date=date(2026, 10, 28)).bill_id
    bill = load_draft_bill(ws, bill_id)

    excluded = run_controls(bill, ref=refdata_from_db(ws, exclude_bill_id=bill_id))
    assert all(m.matched_invoice_id != bill_id for m in excluded.duplicates)
    assert "DUPLICATE_EXACT" not in _codes(excluded)

    # The trap: without exclude_bill_id the stored copy is in RefData, and controls can't tell it is the same bill
    # (the rebuilt DraftBill's id is its file hash, not the bill_id), so it reports an exact duplicate of itself.
    trapped = run_controls(bill, ref=refdata_from_db(ws))
    assert any(m.kind == "exact" and m.matched_invoice_id == bill_id for m in trapped.duplicates)


# ---------------------------------------------------------------- 4. app bills are visible to later bills


def test_a_second_app_bill_matches_the_first_by_its_bill_id(ws: Session) -> None:
    first = create_bill_from_draft(ws, harlow_draft(), created_by="U004", received_date=date(2026, 10, 28)).bill_id
    second = create_bill_from_draft(ws, harlow_draft(), created_by="U004", received_date=date(2026, 10, 29)).bill_id
    ref = refdata_from_db(ws, exclude_bill_id=second)
    matches = find_duplicates(load_draft_bill(ws, second), ref)
    assert [(m.kind, m.matched_invoice_id) for m in matches if m.matched_invoice_id == first] == [("exact", first)]
    assert first == "AP-00427"  # the match carries the database bill_id


# ---------------------------------------------------------------- 5. bank changes


def _app_change(change_id: str, vendor_id: str, status: str, *, new_last4: str = "9999") -> models.BankChangeRequest:
    return models.BankChangeRequest(
        change_id=change_id, vendor_id=vendor_id, requested_at=datetime(2026, 11, 1, 9, 0), requested_by="U005",
        request_channel="phone_callback_verified", old_account_last4="0000", new_account_last4=new_last4,
        verified_by_callback=status == "verified", status=status,
        verified_by="U003" if status == "verified" else None, origin="app")


def test_bank_changes_follow_verification(ws: Session, csv_ref: RefData) -> None:
    # V001: a verified app change; the open account is switched to the new one.
    ws.add(_app_change("BC-010", "V001", "verified"))
    ws.execute(update(models.VendorBankAccount).where(models.VendorBankAccount.vendor_id == "V001",
                                                      models.VendorBankAccount.valid_to.is_(None))
               .values(valid_to=date(2026, 11, 1)))
    ws.add(models.VendorBankAccount(vendor_id="V001", institution="004", transit="95688", account="410659999",
                                    account_last4="9999", valid_from=date(2026, 11, 1), source_change_id="BC-010",
                                    origin="app"))
    # V002 pending and V003 rejected: requested, never applied.
    ws.add_all([_app_change("BC-011", "V002", "pending_verification"), _app_change("BC-012", "V003", "rejected")])
    ws.flush()

    ref = refdata_from_db(ws)
    vendor = ref.vendors["V001"]
    assert (vendor["bank_account"], vendor["bank_details_updated_at"]) == ("410659999", "2026-11-01")
    rendered = {c["change_id"]: c for c in ref.bank_changes}
    assert rendered["BC-010"]["verified_by_callback"] == "yes" and rendered["BC-010"]["changed_at"] == "2026-11-01"
    assert "BC-011" not in rendered and "BC-012" not in rendered
    assert rendered["BC-009"] == next(c for c in csv_ref.bank_changes if c["change_id"] == "BC-009")

    for vendor_id in ("V001", "V002", "V003"):
        result = run_controls(bill_from_history(ref, _bill_of(ref, vendor_id)), ref=ref)
        assert "BANK_CHANGE_UNVERIFIED" not in _codes(result), vendor_id
    assert "BANK_DETAILS_MISMATCH" not in _codes(run_controls(bill_from_history(ref, _bill_of(ref, "V001")), ref=ref))
    v004 = run_controls(bill_from_history(ref, _bill_of(ref, "V004")), ref=ref)
    assert "BANK_CHANGE_UNVERIFIED" in _codes(v004)  # history BC-009: by email, never called back


# ---------------------------------------------------------------- 6. status


def test_void_bills_are_hidden_and_rejected_ones_pass_through(ws: Session) -> None:
    void = create_bill_from_draft(ws, harlow_draft(), created_by="U004", received_date=date(2026, 10, 28)).bill_id
    rejected = create_bill_from_draft(ws, harlow_draft(), created_by="U004", received_date=date(2026, 10, 28)).bill_id
    ws.execute(update(models.Bill).where(models.Bill.bill_id == void).values(status="void"))
    ws.execute(update(models.Bill).where(models.Bill.bill_id == rejected).values(status="rejected"))
    ref = refdata_from_db(ws)
    assert void not in ref.invoices and void not in ref.invoice_lines
    assert ref.invoices[rejected]["status"] == "rejected" and len(ref.invoice_lines[rejected]) == 2


# ---------------------------------------------------------------- 7. admin policy edits


def test_policy_threshold_edits_change_routing(ws: Session, csv_ref: RefData) -> None:
    def single_step_candidate() -> str:
        """A history bill between $5k and $10k that routes to the department manager alone."""
        for invoice_id, row in csv_ref.invoices.items():
            vendor = csv_ref.vendors[row["vendor_id"]]
            if (Decimal("5000") < Decimal(row["total_cad"]) <= Decimal("10000") and not row["po_id"]
                    and vendor["status"] == "active" and vendor["category"] != "Legal"):
                bill = bill_from_history(csv_ref, invoice_id)
                if [s.role for s in route(bill, csv_ref)] == ["dept_manager"]:
                    return invoice_id
        raise AssertionError("no candidate bill")

    invoice_id = single_step_candidate()
    bill = bill_from_history(csv_ref, invoice_id)
    assert [s.role for s in route(bill, refdata_from_db(ws))] == ["dept_manager"]

    ws.execute(update(models.Policy).where(models.Policy.rule_id == "P01")
               .values(condition="Invoice total up to $5,000 CAD"))
    ws.execute(update(models.Policy).where(models.Policy.rule_id == "P02")
               .values(condition="Invoice total over $5,000 CAD"))
    edited = refdata_from_db(ws)
    assert edited.policies["P01"].threshold == Decimal("5000")
    steps = route(bill, edited)
    assert [s.role for s in steps] == ["dept_manager", "finance_manager"]
    assert steps[1].policy_ids == ["P02"]


# ---------------------------------------------------------------- 8. read-only


def test_building_writes_nothing_and_flushes_nothing(seeded: Engine) -> None:
    tables = sorted(models.Base.metadata.tables)

    def counts() -> dict[str, int]:
        with seeded.connect() as conn:
            return {t: conn.execute(select(func.count()).select_from(text(t))).scalar_one() for t in tables}

    before = counts()
    with Session(seeded) as s:
        pending = models.GlAccount(account_number="9999", name="pending, never flushed", account_type="expense")
        s.add(pending)
        refdata_from_db(s)
        refdata_from_db(s, exclude_bill_id="AP-00001")
        assert pending in s.new  # still pending: the adapter didn't autoflush it
        assert s.scalar(select(func.count()).select_from(models.GlAccount).where(
            models.GlAccount.account_number == "9999").execution_options(autoflush=False)) == 0
        s.rollback()
    assert counts() == before
    assert before["audit_events"] == 0


# ---------------------------------------------------------------- 9. timing


def test_build_timing(rs: Session, capsys: pytest.CaptureFixture[str]) -> None:
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        refdata_from_db(rs)
        timings.append(time.perf_counter() - started)
    median = statistics.median(timings)
    with capsys.disabled():
        print(f"\nrefdata_from_db median of 5: {median * 1000:.1f} ms")
    assert median < 2.0
