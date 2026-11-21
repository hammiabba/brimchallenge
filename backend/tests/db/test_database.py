"""
Engine and session tests: SQLAlchemy's pysqlite recipe is in force (real BEGIN, working SAVEPOINTs), write sessions
take the write lock with BEGIN IMMEDIATE, and non-SQLite URLs are left untouched.

Every database lives in pytest's tmp_path. No network, no repo files.
"""
from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import database, models
from app.db.database import SQLITE_BUSY_TIMEOUT_SECONDS, as_write_engine, make_engine


def _gl_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql("SELECT count(*) FROM gl_accounts").scalar_one()


def _gl(number: str) -> models.GlAccount:
    return models.GlAccount(account_number=number, name=f"GL {number}", account_type="expense")


# ---------------------------------------------------------------- 1. SAVEPOINT as the first write is rolled back

def test_savepoint_as_the_first_write_rolls_back_with_the_outer_transaction(migrated_engine: Engine) -> None:
    # ORM, read session: begin_nested() before anything else in the transaction.
    with Session(migrated_engine) as s:
        with s.begin_nested():
            s.add(_gl("9001"))
        s.rollback()
    assert _gl_count(migrated_engine) == 0

    # Core connection: same thing without the ORM.
    with migrated_engine.connect() as conn:
        savepoint = conn.begin_nested()
        conn.execute(models.GlAccount.__table__.insert().values(account_number="9002", name="x", account_type="asset"))
        savepoint.commit()  # RELEASE SAVEPOINT: must not commit the outer transaction
        conn.rollback()
    assert _gl_count(migrated_engine) == 0

    # Write session, then commit: the row stays.
    with Session(as_write_engine(migrated_engine)) as s:
        with s.begin_nested():
            s.add(_gl("9003"))
        s.commit()
    assert _gl_count(migrated_engine) == 1


# ---------------------------------------------------------------- 2. write sessions take the lock up front

def test_write_sessions_hold_the_write_lock_and_read_sessions_still_read(migrated_engine: Engine, db_url: str) -> None:
    impatient = make_engine(db_url, connect_args={"timeout": 1})  # waits 1 s for the lock instead of 15
    holder = Session(as_write_engine(migrated_engine))
    try:
        holder.connection()  # BEGIN IMMEDIATE: holds the write lock before any statement of its own
        started = time.monotonic()
        with Session(as_write_engine(impatient)) as second, pytest.raises(OperationalError, match="locked"):
            second.connection()
        assert 0.9 <= time.monotonic() - started < 5  # it waited for its 1-second busy timeout, then gave up

        with Session(impatient) as reader:  # a read session (deferred BEGIN) is not blocked in WAL mode
            assert reader.scalar(text("SELECT count(*) FROM gl_accounts")) == 0
    finally:
        holder.close()

    with Session(as_write_engine(impatient)) as second:  # lock released: the next writer gets it
        second.add(_gl("9100"))
        second.commit()
    impatient.dispose()
    assert _gl_count(migrated_engine) == 1


def test_an_open_read_session_does_not_block_a_writer(migrated_engine: Engine, db_url: str) -> None:
    impatient = make_engine(db_url, connect_args={"timeout": 1})
    try:
        with Session(migrated_engine) as reader:
            reader.scalar(text("SELECT count(*) FROM gl_accounts"))  # deferred BEGIN + a read: no write lock
            with Session(as_write_engine(impatient)) as writer:
                writer.add(_gl("9200"))
                writer.commit()
    finally:
        impatient.dispose()
    assert _gl_count(migrated_engine) == 1


# ---------------------------------------------------------------- 3. the begin listener fires for option engines

@pytest.fixture
def statements(migrated_engine: Engine) -> Iterator[list[str]]:
    """Every SQL statement sent through `migrated_engine` (and engines derived from it) while the test runs."""
    seen: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _many) -> None:
        seen.append(statement)

    event.listen(migrated_engine, "before_cursor_execute", record)
    yield seen
    event.remove(migrated_engine, "before_cursor_execute", record)


def test_begin_listener_fires_for_option_engine_connections(migrated_engine: Engine, statements: list[str]) -> None:
    write_engine = as_write_engine(migrated_engine)
    assert write_engine is not migrated_engine  # an OptionEngine sharing the same pool and listeners

    with write_engine.connect() as conn:
        assert conn.get_execution_options()["sqlite_begin"] == "IMMEDIATE"
        conn.exec_driver_sql("SELECT 1")
        dbapi = conn.connection.dbapi_connection
        assert dbapi.isolation_level is None  # recipe part one: the driver no longer sends BEGIN itself
        assert dbapi.in_transaction is True  # ... so this is true only because our listener sent one
    assert statements[:2] == ["BEGIN IMMEDIATE", "SELECT 1"]

    statements.clear()
    with migrated_engine.connect() as conn:
        assert "sqlite_begin" not in conn.get_execution_options()
        conn.exec_driver_sql("SELECT 1")
        assert conn.connection.dbapi_connection.in_transaction is True
    assert statements[:2] == ["BEGIN", "SELECT 1"]


def test_session_factories_and_generators_pick_the_right_begin(migrated_engine: Engine, statements: list[str],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    # Point the process-wide factories at the test database (never the default backend/ap.db).
    monkeypatch.setattr(database, "get_engine", lambda: migrated_engine)
    database.get_session_factory.cache_clear()
    database.get_write_session_factory.cache_clear()
    try:
        for generator, expected in ((database.get_write_session(), "BEGIN IMMEDIATE"),
                                    (database.get_session(), "BEGIN")):
            statements.clear()
            session = next(generator)
            session.execute(text("SELECT 1"))
            generator.close()  # what FastAPI does after the response: rolls back and closes
            assert statements[0] == expected
    finally:
        database.get_session_factory.cache_clear()
        database.get_write_session_factory.cache_clear()


def test_busy_timeout_defaults_to_15_seconds(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == SQLITE_BUSY_TIMEOUT_SECONDS * 1000
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


# ---------------------------------------------------------------- non-SQLite URLs are untouched

def test_non_sqlite_urls_get_no_sqlite_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    def fake_create_engine(url, **kwargs):
        created.update(url=url.render_as_string(hide_password=False), kwargs=kwargs)
        return object()

    def no_listeners(*_args, **_kwargs):
        pytest.fail("make_engine added an event listener to a non-SQLite engine")

    monkeypatch.setattr(database, "create_engine", fake_create_engine)
    monkeypatch.setattr(database.event, "listen", no_listeners)
    database.make_engine("postgresql://user:secret@db.example/brim", pool_size=3)
    assert created == {"url": "postgresql://user:secret@db.example/brim", "kwargs": {"pool_size": 3}}
