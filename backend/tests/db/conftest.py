"""
Fixtures for the DB tests: a fresh SQLite file per test, migrated with the real Alembic migrations.

Every database lives in pytest's tmp_path, never inside the repo. The repo-wide autouse fixtures in
tests/conftest.py still apply (network blocked, settings isolated); SQLite needs neither.

Two kinds of session, like the app: `session` is a read session (plain BEGIN), `write_session` a write session
(BEGIN IMMEDIATE). Use `write_session` wherever a test writes audit events; app.db.audit.log_event refuses
anything else.

Every test in tests/db runs with AUDIT_HMAC_KEY set to a fixed, public test value (autouse fixture below), so audit
fingerprints are deterministic. A test that needs a different or missing key sets it itself and clears the cache.

Row factories (make_*) build the smallest valid rows for the parent tables a test needs. They are plain functions,
so a test can override any column to break exactly one rule.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
from app.db import models
from app.db.database import as_write_engine, make_engine
from app.db.settings import get_db_settings

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
NOW = datetime(2026, 11, 2, 15, 0, 0)  # naive UTC, like every stored timestamp
# Not a secret: a fixed key so fingerprints are reproducible in tests. 40 characters (the minimum is 32).
TEST_AUDIT_HMAC_KEY = "test-only-audit-hmac-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def _audit_hmac_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set AUDIT_HMAC_KEY for every db test, and drop the cached settings before and after so nothing leaks."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", TEST_AUDIT_HMAC_KEY)
    get_db_settings.cache_clear()
    yield
    get_db_settings.cache_clear()


# ---------------------------------------------------------------- alembic + engine fixtures

def alembic_config(url: str) -> Config:
    """An Alembic Config for backend/alembic.ini, pointed at `url` instead of the app's DATABASE_URL."""
    cfg = Config(str(ALEMBIC_INI))
    # ConfigParser treats % as interpolation, so escape it before storing the URL.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    # Don't let env.py's fileConfig() replace pytest's logging setup.
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """URL of a not-yet-created SQLite file in this test's temp dir."""
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def alembic_cfg(db_url: str) -> Config:
    return alembic_config(db_url)


@pytest.fixture
def migrated_engine(alembic_cfg: Config, db_url: str) -> Iterator[Engine]:
    """Engine on a database built by `alembic upgrade head` (the same path production takes)."""
    command.upgrade(alembic_cfg, "head")
    engine = make_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    """A read session (plain BEGIN) on the migrated database. Nothing is committed unless the test commits."""
    with Session(migrated_engine) as s:
        yield s


@pytest.fixture
def write_session(migrated_engine: Engine) -> Iterator[Session]:
    """A write session (BEGIN IMMEDIATE) on the migrated database, as app.db.database.get_write_session gives."""
    with Session(as_write_engine(migrated_engine)) as s:
        yield s


# ---------------------------------------------------------------- row factories

def make_reference_rows(session: Session) -> None:
    """Minimal reference data: one GL account, one department, three users, one vendor. Commits.

    departments.manager_user_id and users.department_id reference each other; both FKs are deferred, so the
    order of the inserts doesn't matter as long as both exist at commit.
    """
    session.add(models.GlAccount(account_number="5010", name="Freight & Carrier Costs", account_type="expense"))
    session.add(models.Department(department_id="D01", name="Operations", cost_centre="1100",
                                  annual_budget_cad_cents=180_000_000, manager_user_id="U007"))
    for user_id, role in (("U007", "approver"), ("U004", "ap_clerk"), ("U003", "finance_manager")):
        session.add(models.User(user_id=user_id, full_name=f"User {user_id}", email=f"{user_id}@example.test",
                                title=role, department_id="D01", role=role, approval_limit_cad_cents=0,
                                work_province="ON", status="active", hire_date=date(2024, 1, 1)))
    session.add(models.Vendor(vendor_id="V001", legal_name="Polar Freight Lines Ltd.", category="Freight & Carriers",
                              default_gl_account="5010", address="1 Test St, Hamilton ON", province_or_state="ON",
                              country="CA", payment_terms_days=30, preferred_payment_method="EFT",
                              accepts_card_payment=False, ap_contact_email="ar@polarfreight.example",
                              requires_po=False, status="active", onboarded_at=date(2022, 11, 8), origin="history"))
    session.commit()


def make_bill(**overrides: object) -> models.Bill:
    """A valid CAD bill for V001. Pass keyword overrides to change any column."""
    values: dict[str, object] = {
        "bill_id": "AP-00001", "origin": "app", "status": "needs_review", "vendor_id": "V001",
        "vendor_invoice_number": "INV-000583", "norm_invoice_number": "583", "invoice_date": date(2026, 10, 20),
        "due_date": date(2026, 11, 19), "currency": "CAD", "subtotal_cents": 100_000, "total_cents": 113_000,
        "total_cad_cents": 113_000, "fx_rate_to_cad": "1", "is_credit_note": False, "ship_to_province": "ON",
        "received_date": date(2026, 10, 21), "created_at": NOW, "updated_at": NOW,
    }
    values.update(overrides)
    return models.Bill(**values)


def make_audit_event(**overrides: object) -> models.AuditEvent:
    """A raw audit row for schema tests. It bypasses app.db.audit.log_event on purpose, so hash is a placeholder."""
    values: dict[str, object] = {
        "event_id": "EV-000001", "at": NOW, "actor_user_id": "U004", "actor_role": "ap_clerk",
        "action": "invoice.created", "entity_type": "invoice", "entity_id": "AP-00001",
        "after_json": {"status": "needs_review"}, "hash": "placeholder",
    }
    values.update(overrides)
    return models.AuditEvent(**values)
