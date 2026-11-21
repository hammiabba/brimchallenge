"""
Audit log tests: log_event writes one hash-chained event inside the caller's transaction, the chain detects
tampering, bank numbers are redacted, and the read helpers page and export correctly.

Every test gets a fresh SQLite file migrated to head (0001 + 0002) in tmp_path. No network, no repo files.
"""
from __future__ import annotations

import csv
import hashlib
import io
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db import audit, models
from app.db.audit import (
    GENESIS,
    AuditAction,
    AuditChainConflict,
    AuditRecord,
    compute_hash,
    iter_events_csv,
    list_events,
    log_event,
    redact,
    to_audit_json,
    verify_chain,
)
from app.db.database import make_engine
from app.shared import schemas
from tests.db.conftest import make_bill, make_reference_rows

BASE_TIME = datetime(2026, 11, 2, 15, 0, 0)  # naive UTC


def _log(session: Session, n: int = 0, **overrides: object) -> AuditRecord:
    """log_event with valid defaults; `n` makes entity ids and timestamps distinct."""
    kwargs: dict[str, object] = {
        "actor_user_id": "U004", "actor_role": "ap_clerk", "action": AuditAction.BILL_UPDATED,
        "entity_type": "bill", "entity_id": f"AP-{n:05d}", "after": {"n": n}, "at": BASE_TIME + timedelta(minutes=n),
    }
    kwargs.update(overrides)
    return log_event(session, **kwargs)


def _stored(engine: Engine) -> list[dict]:
    """Every stored audit row, as dicts, read through a separate connection (only committed rows)."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(models.AuditEvent.__table__).order_by(text("seq"))).mappings()]


def _drop_triggers(engine: Engine) -> None:
    """Test databases only: remove the append-only triggers so a test can simulate tampering."""
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER audit_events_no_update")
        conn.exec_driver_sql("DROP TRIGGER audit_events_no_delete")


# ---------------------------------------------------------------- 1. one call, one row

def test_one_call_inserts_exactly_one_row_matching_the_return_value(session: Session, migrated_engine: Engine) -> None:
    event = _log(session, 1, comment="first", request_id="req-1", on_behalf_of="U012",
                 before={"status": "needs_review"})
    session.commit()

    rows = _stored(migrated_engine)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(event, AuditRecord) and isinstance(event, schemas.AuditEvent)
    assert event.event_id == row["event_id"] and event.event_id.startswith("EV-") and len(event.event_id) == 35
    assert event.seq == row["seq"]
    assert event.at == row["at"].replace(tzinfo=UTC)
    assert (event.actor_user_id, event.actor_role, event.on_behalf_of) == ("U004", "ap_clerk", "U012")
    assert (event.action, event.entity_type, event.entity_id) == (row["action"], row["entity_type"], row["entity_id"])
    assert event.before == row["before_json"] == {"status": "needs_review"}
    assert event.after == row["after_json"] == {"n": 1}
    assert (event.comment, event.request_id) == ("first", "req-1") == (row["comment"], row["request_id"])
    assert (event.prev_hash, event.hash) == (row["prev_hash"], row["hash"])


def test_given_timestamp_is_stored_in_utc(session: Session, migrated_engine: Engine) -> None:
    toronto = timezone(timedelta(hours=-5))
    event = _log(session, at=datetime(2026, 11, 2, 10, 0, tzinfo=toronto))
    session.commit()
    assert _stored(migrated_engine)[0]["at"] == datetime(2026, 11, 2, 15, 0)
    assert event.at == datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


# ---------------------------------------------------------------- 2. the chain links

def test_chain_starts_at_genesis_and_links_each_event_to_the_previous(session: Session) -> None:
    events = [_log(session, n) for n in range(5)]
    assert events[0].prev_hash == GENESIS
    for previous, current in zip(events, events[1:], strict=False):
        assert current.prev_hash == previous.hash
    # Each hash is reproducible from the event's own fields.
    fields = audit._hash_fields({**events[2].model_dump(), "before_json": events[2].before,
                                 "after_json": events[2].after})
    assert compute_hash(events[2].prev_hash, fields) == events[2].hash


# ---------------------------------------------------------------- 3. atomic with the caller's transaction

def test_event_rolls_back_with_the_caller_even_as_the_first_write(session: Session, migrated_engine: Engine) -> None:
    # Regression: with pysqlite, a SAVEPOINT opened before any other write would commit on RELEASE.
    _log(session, 1)
    session.rollback()
    assert _stored(migrated_engine) == []

    _log(session, 2)
    session.commit()
    assert [r["entity_id"] for r in _stored(migrated_engine)] == ["AP-00002"]


def test_event_and_state_change_commit_or_roll_back_together(session: Session, migrated_engine: Engine) -> None:
    make_reference_rows(session)
    session.add(make_bill(bill_id="AP-09001"))
    _log(session, action=AuditAction.BILL_CREATED, entity_id="AP-09001")
    session.rollback()
    with migrated_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM bills").scalar() == 0
    assert _stored(migrated_engine) == []

    session.add(make_bill(bill_id="AP-09001"))
    _log(session, action=AuditAction.BILL_CREATED, entity_id="AP-09001")
    session.commit()
    with migrated_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM bills").scalar() == 1
    assert len(_stored(migrated_engine)) == 1


# ---------------------------------------------------------------- 4. log_event never commits

def test_other_sessions_cannot_see_the_event_until_the_caller_commits(session: Session, db_url: str) -> None:
    other = make_engine(db_url)
    try:
        _log(session, 1)
        with Session(other) as reader:
            assert reader.scalar(text("SELECT count(*) FROM audit_events")) == 0
        session.commit()
        with Session(other) as reader:
            assert reader.scalar(text("SELECT count(*) FROM audit_events")) == 1
    finally:
        other.dispose()


# ---------------------------------------------------------------- 5. verify_chain and tampering

def test_verify_chain_is_ok_on_a_clean_chain(session: Session) -> None:
    assert verify_chain(session) == audit.ChainReport(ok=True, count=0)
    for n in range(20):
        _log(session, n)
    session.commit()
    assert verify_chain(session) == audit.ChainReport(ok=True, count=20)


def test_verify_chain_finds_an_edited_row(session: Session, migrated_engine: Engine) -> None:
    for n in range(20):
        _log(session, n)
    session.commit()
    _drop_triggers(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.exec_driver_sql("""UPDATE audit_events SET after_json = '{"n": 999}' WHERE seq = 7""")
    report = verify_chain(session)
    assert (report.ok, report.count, report.first_bad_seq) == (False, 20, 7)
    assert "changed" in report.reason


def test_verify_chain_finds_a_deleted_middle_row(session: Session, migrated_engine: Engine) -> None:
    for n in range(20):
        _log(session, n)
    session.commit()
    _drop_triggers(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM audit_events WHERE seq = 10")
    report = verify_chain(session)
    assert (report.ok, report.count, report.first_bad_seq) == (False, 19, 11)
    assert "deleted" in report.reason


def test_verify_chain_rejects_a_chain_that_does_not_start_at_genesis(session: Session) -> None:
    _log(session, 1)
    session.commit()
    assert verify_chain(session).ok
    # A row written outside log_event with no predecessor marker breaks the chain at that row.
    session.execute(models.AuditEvent.__table__.insert().values(
        event_id="EV-manual", at=BASE_TIME, actor_user_id="x", actor_role="x", action="x", entity_type="x",
        entity_id="x", prev_hash=None, hash="bogus"))
    report = verify_chain(session)
    assert (report.ok, report.first_bad_seq) == (False, 2)


# ---------------------------------------------------------------- 6. racing writers

def _insert_racer(session: Session, prev_hash: str) -> str:
    """Append a valid event directly (as another writer would) on top of `prev_hash`; returns its hash."""
    values = {"event_id": f"EV-{uuid.uuid4().hex}", "at": BASE_TIME, "actor_user_id": "U005", "actor_role": "ap_clerk",
              "on_behalf_of": None, "action": "racer", "entity_type": "bill", "entity_id": "AP-99999",
              "before_json": None, "after_json": None, "comment": None, "request_id": None, "prev_hash": prev_hash}
    values["hash"] = compute_hash(prev_hash, audit._hash_fields(values))
    session.execute(models.AuditEvent.__table__.insert().values(**values))
    return values["hash"]


def test_log_event_retries_after_losing_the_prev_hash_race(session: Session, monkeypatch) -> None:
    first = _log(session, 1)
    real_latest = audit._latest_hash
    reads: list[str] = []
    racer_hash: list[str] = []

    def racing_latest(s: Session) -> str:
        latest = real_latest(s)
        if not reads:  # another writer appends right after our first read, on the same predecessor
            racer_hash.append(_insert_racer(s, latest))
        reads.append(latest)
        return latest

    monkeypatch.setattr(audit, "_latest_hash", racing_latest)
    event = _log(session, 2)
    assert reads == [first.hash, racer_hash[0]]  # collided once, re-read, succeeded
    assert event.prev_hash == racer_hash[0]
    session.commit()
    assert verify_chain(session) == audit.ChainReport(ok=True, count=3)


def test_log_event_gives_up_after_five_collisions(session: Session, monkeypatch) -> None:
    _log(session, 1)  # takes GENESIS
    attempts: list[int] = []

    def always_stale(_s: Session) -> str:
        attempts.append(1)
        return GENESIS  # every attempt claims the predecessor that's already taken

    monkeypatch.setattr(audit, "_latest_hash", always_stale)
    with pytest.raises(AuditChainConflict):
        _log(session, 2)
    assert len(attempts) == audit.MAX_ATTEMPTS == 5
    # Every failed attempt was rolled back to its savepoint; the caller's transaction is still usable.
    assert session.scalar(text("SELECT count(*) FROM audit_events")) == 1


def test_other_integrity_errors_are_not_swallowed(session: Session, monkeypatch) -> None:
    fixed = uuid.UUID("12345678123456781234567812345678")
    monkeypatch.setattr(audit.uuid, "uuid4", lambda: fixed)
    _log(session, 1)
    with pytest.raises(IntegrityError, match="event_id"):  # duplicate event_id: not a chain race, not retried
        _log(session, 2)


# ---------------------------------------------------------------- 7. redaction

def test_bank_account_numbers_are_redacted_everywhere(session: Session, migrated_engine: Engine) -> None:
    _log(session, after={"bank": {"institution": "004", "transit": "40238", "account": "593014216"}},
         before={"bank_account": "410652201", "new_account_last4": "9679"})
    session.commit()
    row = _stored(migrated_engine)[0]
    expected_fp = hashlib.sha256(b"593014216").hexdigest()[:12]
    assert row["after_json"] == {"bank": {"institution": "004", "transit": "40238",
                                          "account": {"last4": "4216", "fingerprint": expected_fp}}}
    assert row["before_json"]["bank_account"]["last4"] == "2201"
    assert row["before_json"]["new_account_last4"] == "9679"  # *_last4 keys are left alone
    with migrated_engine.connect() as conn:
        raw = " ".join(str(v) for v in conn.exec_driver_sql("SELECT * FROM audit_events").one())
    assert "593014216" not in raw and "410652201" not in raw


def test_redact_handles_all_account_keys_nested_lists_and_is_idempotent() -> None:
    payload = {"lines": [{"account_number": "12345678"}, {"new_account": 987654321}], "account": "", "id": "AP-1"}
    once = redact(payload)
    assert once["lines"][0]["account_number"]["last4"] == "5678"
    assert once["lines"][1]["new_account"]["last4"] == "4321"
    assert once["account"] == "" and once["id"] == "AP-1"  # empty values and IDs untouched
    assert redact(once) == once


# ---------------------------------------------------------------- 8. to_audit_json

def test_to_audit_json_conversions() -> None:
    toronto = timezone(timedelta(hours=-5))
    assert to_audit_json(Decimal("742.30")) == "742.30"
    assert to_audit_json(Decimal("1E-7")) == "0.0000001"
    assert to_audit_json(datetime(2026, 11, 2, 10, 0, tzinfo=toronto)) == "2026-11-02T15:00:00Z"
    assert to_audit_json(datetime(2026, 11, 2, 15, 0, 0, 250000)) == "2026-11-02T15:00:00.250000Z"
    assert to_audit_json(date(2026, 11, 2)) == "2026-11-02"
    assert to_audit_json(schemas.Severity.BLOCK) == "block"
    assert to_audit_json({"codes": {"b", "a"}, "pair": (1, 2), 3: None}) == {"codes": ["a", "b"], "pair": [1, 2],
                                                                            "3": None}
    flag = schemas.Flag(code="TAX_MISSING", severity=schemas.Severity.WARN, message="m", evidence={"x": 1})
    assert to_audit_json(flag)["severity"] == "warn"


@pytest.mark.parametrize("bad", [object(), b"bytes", complex(1, 2)])
def test_to_audit_json_rejects_unsupported_types(bad: object) -> None:
    with pytest.raises(TypeError):
        to_audit_json({"x": bad})


def test_to_audit_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        to_audit_json(float("nan"))
    with pytest.raises(ValueError):
        to_audit_json(Decimal("NaN"))


# ---------------------------------------------------------------- 9. input validation

@pytest.mark.parametrize("field", ["actor_user_id", "actor_role", "action", "entity_type", "entity_id"])
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_required_fields_are_refused(session: Session, field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        _log(session, **{field: value})


def test_any_action_string_is_accepted(session: Session) -> None:
    assert _log(session, action="something.nobody_planned").action == "something.nobody_planned"
    assert "bill.flag_overridden" in AuditAction.all() and len(AuditAction.all()) == 28


# ---------------------------------------------------------------- 10. list_events

def test_list_events_filters(session: Session) -> None:
    _log(session, 1, entity_type="bill", entity_id="AP-1", actor_user_id="U004", action="bill.created")
    _log(session, 2, entity_type="bill", entity_id="AP-1", actor_user_id="U007", action="bill.approved")
    _log(session, 3, entity_type="payment", entity_id="PAY-1", actor_user_id="U003", action="payment.released")
    _log(session, 4, entity_type="bill", entity_id="AP-2", actor_user_id="U004", action="bill.created")
    session.commit()

    def ids(**filters: object) -> list[str]:
        return [f"{e.entity_id}:{e.action}" for e in list_events(session, **filters)]

    assert ids(entity_type="bill", entity_id="AP-1") == ["AP-1:bill.created", "AP-1:bill.approved"]
    assert ids(actor_user_id="U004") == ["AP-1:bill.created", "AP-2:bill.created"]
    assert ids(action="payment.released") == ["PAY-1:payment.released"]
    # since is inclusive, until exclusive; aware datetimes are converted to UTC first.
    assert ids(since=BASE_TIME + timedelta(minutes=2), until=BASE_TIME + timedelta(minutes=4)) == [
        "AP-1:bill.approved", "PAY-1:payment.released"]
    toronto = timezone(timedelta(hours=-5))
    assert len(list_events(session, since=datetime(2026, 11, 2, 10, 3, tzinfo=toronto))) == 2


def test_list_events_keyset_pagination_has_no_gaps_or_repeats(session: Session) -> None:
    for n in range(20):
        _log(session, n)
    session.commit()
    seen, cursor, pages = [], None, []
    while True:
        page = list_events(session, after_seq=cursor, limit=7)
        if not page:
            break
        pages.append(len(page))
        seen += [e.seq for e in page]
        cursor = page[-1].seq
    assert pages == [7, 7, 6]
    assert seen == sorted(seen) == list(range(1, 21))


def test_list_events_limit_is_capped_at_500(session: Session) -> None:
    for n in range(600):
        _log(session, n)
    session.commit()
    assert len(list_events(session, limit=10_000)) == 500
    with pytest.raises(ValueError):
        list_events(session, limit=0)


# ---------------------------------------------------------------- 11. CSV export

def test_csv_header_quoting_and_formula_injection(session: Session) -> None:
    _log(session, 1, comment="=HYPERLINK(\"http://evil\")")
    _log(session, 2, comment="paid, then\nrefunded \"in part\"")
    _log(session, 3, comment="-15.00", actor_role="@admin")
    session.commit()
    lines = list(iter_events_csv(session))
    assert lines[0] == ",".join(audit.CSV_COLUMNS) + "\r\n"
    records = list(csv.DictReader(io.StringIO("".join(lines))))
    assert [r["comment"] for r in records] == [
        "'=HYPERLINK(\"http://evil\")", "paid, then\nrefunded \"in part\"", "'-15.00"]
    assert records[2]["actor_role"] == "'@admin"
    assert records[0]["at"] == "2026-11-02T15:01:00Z"
    assert records[0]["after_json"] == '{"n":1}'
    assert records[0]["prev_hash"] == GENESIS


def test_csv_streams_in_batches_of_500(session: Session, monkeypatch) -> None:
    for n in range(1200):
        _log(session, n)
    session.commit()
    limits: list[int] = []
    real_fetch = audit._fetch

    def counting_fetch(s, query, limit):
        limits.append(limit)
        return real_fetch(s, query, limit)

    monkeypatch.setattr(audit, "_fetch", counting_fetch)
    lines = list(iter_events_csv(session))
    assert len(lines) == 1201  # header + one record per event
    assert limits == [500, 500, 500]  # three queries (500 + 500 + 200), never the whole table at once
    assert len(list(iter_events_csv(session, entity_id="AP-00042"))) == 2


# ---------------------------------------------------------------- 12. triggers still bite after 0002

def test_append_only_triggers_still_block_update_and_delete(session: Session) -> None:
    _log(session, 1)
    session.commit()
    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(text("UPDATE audit_events SET comment = 'edited'"))
    session.rollback()
    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(text("DELETE FROM audit_events"))
    session.rollback()
    assert verify_chain(session).ok


# ---------------------------------------------------------------- 13. migration 0002 is reversible

def _audit_indexes(db_url: str) -> set[str]:
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            return {r[1] for r in conn.exec_driver_sql("PRAGMA index_list('audit_events')")}
    finally:
        engine.dispose()


def _triggers(db_url: str) -> set[str]:
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            return {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    finally:
        engine.dispose()


def test_migration_0002_upgrades_and_downgrades_cleanly(alembic_cfg: Config, db_url: str) -> None:
    triggers = {"audit_events_no_update", "audit_events_no_delete"}
    command.upgrade(alembic_cfg, "head")
    assert "uq_audit_events_prev_hash" in _audit_indexes(db_url)
    command.downgrade(alembic_cfg, "0001")
    assert "uq_audit_events_prev_hash" not in _audit_indexes(db_url)
    assert _triggers(db_url) == triggers  # downgrading 0002 leaves 0001's triggers alone
    command.upgrade(alembic_cfg, "head")
    assert "uq_audit_events_prev_hash" in _audit_indexes(db_url)
    assert _triggers(db_url) == triggers
