"""scripts/demo_scenario.py on a fresh seeded, back-filled database, run twice: the demo state, and no duplicates."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.auth.deps import load_current_user
from app.db import models
from app.db.audit import verify_chain
from app.db.backfill import backfill_history_controls
from app.db.database import as_write_engine
from app.services import approvals, bills, controls_runner, payments

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_scenario.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("demo_scenario", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo = _load_script()


def _counts(engine) -> dict[str, int]:
    with Session(engine) as db:
        return {t.__tablename__: db.scalar(select(func.count()).select_from(t)) for t in
                (models.Bill, models.IntakeItem, models.ApprovalDecision, models.Payment, models.AuditEvent,
                 models.ControlsRun)}


@pytest.fixture(scope="module")
def demo_db(seeded_template, tmp_path_factory):
    """One fresh seeded copy, back-filled, with the script run twice. Yields (engine, first, second, counts)."""
    import shutil

    from app.db.database import make_engine
    path = tmp_path_factory.mktemp("demo") / "ap.db"
    shutil.copyfile(seeded_template, path)
    engine = make_engine(f"sqlite:///{path}")
    with Session(as_write_engine(engine)) as s:
        backfill_history_controls(s)
        s.commit()
    first = demo.run(engine)
    after_first = _counts(engine)
    second = demo.run(engine)
    yield engine, first, second, after_first
    engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _module_audit_key():
    """The module fixture writes audit events before the per-test key fixture runs, so set the key for the module."""
    mp = pytest.MonkeyPatch()
    from app.db.settings import get_db_settings
    from tests.api.conftest import TEST_AUDIT_HMAC_KEY
    mp.setenv("AUDIT_HMAC_KEY", TEST_AUDIT_HMAC_KEY)
    get_db_settings.cache_clear()
    yield
    mp.undo()
    get_db_settings.cache_clear()


def bill_of(first, key: str) -> str:
    return first.bills[key]


def test_second_run_changes_nothing(demo_db):
    engine, first, second, after_first = demo_db
    assert len(first.did) == 30 and second.did == []
    assert second.bills == first.bills and len(set(first.bills.values())) == len(demo.BILLS) == 12
    assert _counts(engine) == after_first  # no new bills, intake items, decisions, payments, runs or audit events


def test_audit_log_is_genuine_and_intact(demo_db):
    engine, first, _, _ = demo_db
    with Session(engine) as db:
        assert verify_chain(db).ok
        actions = db.scalars(select(models.AuditEvent.action).where(
            models.AuditEvent.entity_id.in_(list(first.bills.values())))).all()
    assert actions.count("bill.created") == 12
    assert actions.count("bill.submitted") == 11   # the Cascadia bill is held, never submitted
    assert actions.count("bill.approved") == 4   # U007 (step 1 of the finance-queue bill), U003, U008, U011
    with Session(engine) as db:
        scheduled = db.scalar(select(func.count()).select_from(models.AuditEvent).where(
            models.AuditEvent.action == "payment.scheduled"))
    assert scheduled == 3  # the seed writes no audit events, so these are the demo's three payments


def test_every_approver_has_a_bill_waiting(demo_db):
    engine, first, _, _ = demo_db
    expected = {"U007": {"d01-queue"}, "U008": {"d02-queue"}, "U009": {"d03-queue"}, "U010": {"d05-queue"},
                "U011": {"d06-queue"}, "U002": {"d04-queue"}, "U003": {"d07-delegate-queue", "d01-finance-queue"}}
    with Session(engine) as db:
        for user_id, keys in expected.items():
            mine = {b.bill_id for b in approvals.queue(db, load_current_user(db, user_id))}
            assert {first.bills[k] for k in keys} <= mine, user_id


def test_delegate_step_and_delegated_approval(demo_db):
    engine, first, _, _ = demo_db
    with Session(engine) as db:
        step = approvals.current_step(db, first.bills["d07-delegate-queue"])
        assert step.user_id == "U003"
        decision = db.scalars(select(models.ApprovalDecision).where(
            models.ApprovalDecision.bill_id == first.bills["d07-delegated-paid"])).one()
        assert (decision.actor_user_id, decision.on_behalf_of, decision.decision) == ("U003", "U012", "approved")
        event = db.scalars(select(models.AuditEvent).where(
            models.AuditEvent.entity_id == first.bills["d07-delegated-paid"],
            models.AuditEvent.action == "bill.approved")).one()
        assert event.on_behalf_of == "U012"


def test_finance_manager_is_step_two_after_the_department_manager(demo_db):
    engine, first, _, _ = demo_db
    with Session(engine) as db:
        bill_id = first.bills["d01-finance-queue"]
        assert db.get(models.Bill, bill_id).status == "pending_approval"
        step = approvals.current_step(db, bill_id)
        assert (step.step_no, step.role, step.user_id) == (2, "finance_manager", "U003")


def test_payments_are_ready_to_release_by_the_right_people(demo_db):
    engine, first, _, _ = demo_db
    with Session(engine) as db:
        def payment_for(key):
            return db.scalars(select(models.Payment).where(models.Payment.bill_id == first.bills[key])).one()

        ready = [payment_for(k) for k in ("d07-delegated-paid", "d02-ready", "d06-ready")]
        assert all((p.status, p.prepared_by) == ("scheduled", "U004") for p in ready)
        assert all(db.get(models.Bill, p.bill_id).status == "scheduled" for p in ready)
        delegated, sales, _ = ready
        # U003 approved the delegated bill, so separation of duties (P11) keeps them from releasing it.
        with pytest.raises(ApiError) as refused:
            payments.release_check(db, load_current_user(db, "U003"), delegated)
        assert "P11" in refused.value.message
        payments.release_check(db, load_current_user(db, "U002"), delegated)  # the controller can
        payments.release_check(db, load_current_user(db, "U003"), sales)      # U003 didn't approve this one


def test_cascadia_is_held(demo_db):
    engine, first, _, _ = demo_db
    bill_id = first.bills["v004-hold"]
    with Session(engine) as db:
        assert db.get(models.Bill, bill_id).status == "needs_review"
        assert "BANK_CHANGE_UNVERIFIED" in controls_runner.open_blocking_codes(db, bill_id)
        assert db.get(models.Bill, "AP-00426").status == "approved"
    hold = demo.check_cascadia_hold(engine)
    assert any("BC-009 is pending verification" in line for line in hold)
    assert any("AP-00426 can't be scheduled" in line for line in hold)
    with Session(as_write_engine(engine)) as db:  # submitting is refused, and nothing is written
        bill = db.get(models.Bill, bill_id)
        with pytest.raises(ApiError) as refused:
            bills.submit(db, load_current_user(db, "U004"), bill_id, bill.row_version)
        db.rollback()
    assert refused.value.code == "bill.blocked"


def test_refuses_an_unseeded_database(tmp_path):
    from app.db.database import make_engine
    from app.db.seed import migrate_to_head
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    migrate_to_head(url)
    engine = make_engine(url)
    with pytest.raises(SystemExit, match="isn't seeded"):
        demo.run(engine)
    engine.dispose()
