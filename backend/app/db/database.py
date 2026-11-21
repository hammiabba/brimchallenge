"""
Engine and session factories for the app database.

Owner: DB team.

What this module does:
- Reads the URL from `get_settings().database_url` (env var DATABASE_URL, default SQLite under backend/).
- Resolves a relative SQLite path against the repository root, so `sqlite:///./backend/ap.db` means the same file
  whether the server is started from the repo root or from backend/.
- Turns on SQLite foreign keys (off by default in SQLite) and WAL journaling for every new connection, and sets a
  15-second busy timeout.
- Makes SQLite transactions real (SQLAlchemy's documented pysqlite recipe, "Using SQLAlchemy to emit BEGIN in lieu
  of SQLite's transaction control"): the sqlite3 driver's own transaction handling is switched off
  (`isolation_level = None`) and SQLAlchemy emits BEGIN itself when a transaction starts. Without this, the driver
  only sends BEGIN before INSERT / UPDATE / DELETE, so a SAVEPOINT opened first would commit on RELEASE, SELECTs
  would not be repeatable, and DDL would autocommit.
- Hands out two kinds of sessions, neither of which ever autocommits:
    read sessions  (get_session / get_session_factory)              BEGIN            (deferred: no lock until a write)
    write sessions (get_write_session / get_write_session_factory)  BEGIN IMMEDIATE  (takes the write lock up front)
  A write session holds SQLite's single write lock from its first statement, so it can read and then write without
  another writer slipping in between. In WAL mode a deferred transaction that read first and then tries to write
  after someone else committed fails at once with "database is locked"; BEGIN IMMEDIATE waits for the lock instead.
  Use write sessions for anything that writes, and always for app.db.audit.log_event (it refuses a read session).

The write/read choice travels as the execution option `sqlite_begin="IMMEDIATE"` (see as_write_engine). Non-SQLite
URLs get none of this: no listeners, no extra connect arguments; the option is simply ignored.

Nothing connects at import time. The engine is created on first use, so importing this module never creates a
database file. Always build engines with `make_engine()` so all of the above is applied; Alembic's env.py does.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT, get_settings

# How long a connection waits for SQLite's write lock before raising "database is locked".
SQLITE_BUSY_TIMEOUT_SECONDS = 15

# The execution option that makes the begin listener send BEGIN IMMEDIATE (write sessions).
SQLITE_BEGIN_OPTION = "sqlite_begin"
WRITE_EXECUTION_OPTIONS = {SQLITE_BEGIN_OPTION: "IMMEDIATE"}

# ---------------------------------------------------------------- URL resolution


def _render(url: URL) -> str:
    # hide_password=False: this string is used to connect, not to log.
    return url.render_as_string(hide_password=False)


def resolve_database_url(url: str | URL) -> str:
    """Return the URL with a relative SQLite file path made absolute under the repository root.

    Unchanged: non-SQLite URLs, absolute SQLite paths, in-memory databases ("sqlite://", ":memory:")
    and SQLite URI-style names ("file:..." or ?uri=true), whose meaning is up to SQLite.
    "Unchanged" is literal: those come back as the exact string passed in, because re-rendering a URL can
    re-encode characters (":memory:" would become "%3Amemory%3A").
    """
    parsed = make_url(url)
    unchanged = url if isinstance(url, str) else _render(parsed)
    if parsed.get_backend_name() != "sqlite":
        return unchanged
    database = parsed.database
    if not database or database == ":memory:" or database.startswith("file:") or parsed.query.get("uri"):
        return unchanged
    path = Path(database)
    if path.is_absolute():
        return unchanged
    # normpath folds "./" and "../" without touching the filesystem (the file may not exist yet).
    absolute = Path(os.path.normpath(REPO_ROOT / path))
    return _render(parsed.set(database=str(absolute)))


def default_database_url() -> str:
    """The configured URL (settings / DATABASE_URL), already resolved."""
    return resolve_database_url(get_settings().database_url)


# ---------------------------------------------------------------- SQLite connection and transaction hooks


def _sqlite_on_connect(dbapi_connection: Any, _connection_record: Any) -> None:
    """Runs once per new DBAPI connection (pragmas and driver settings are per connection in SQLite).

    1. isolation_level = None switches off the sqlite3 driver's own BEGIN handling (part one of the pysqlite recipe);
       _sqlite_on_begin then emits BEGIN itself. COMMIT and ROLLBACK still go through the driver as usual.
    2. foreign_keys=ON: SQLite ignores FOREIGN KEY clauses without it.
    3. journal_mode=WAL: readers don't block the writer. Stored in the file, so later connections inherit it.
       In-memory databases answer "memory" and carry on, which is fine.
    Both pragmas run here, in autocommit mode, because SQLite ignores them inside a transaction.
    """
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def _sqlite_on_begin(connection: Connection) -> None:
    """Part two of the pysqlite recipe: emit BEGIN when SQLAlchemy starts a transaction.

    BEGIN IMMEDIATE when the connection's execution options carry sqlite_begin="IMMEDIATE" (write sessions),
    plain BEGIN (deferred) otherwise (read sessions, migrations, scripts).
    """
    immediate = connection.get_execution_options().get(SQLITE_BEGIN_OPTION) == "IMMEDIATE"
    connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")


# ---------------------------------------------------------------- engines


def make_engine(url: str | URL | None = None, **engine_kwargs: Any) -> Engine:
    """Create an engine for `url` (default: the configured URL) with path resolution and the SQLite setup applied.

    For SQLite with the standard sqlite3 driver: check_same_thread=False, a 15 s busy timeout (both overridable via
    connect_args), the connect listener (driver BEGIN off, foreign keys, WAL) and the begin listener (BEGIN or
    BEGIN IMMEDIATE). Any other database is created exactly as create_engine would, with nothing added.
    """
    resolved = make_url(resolve_database_url(url if url is not None else get_settings().database_url))
    pysqlite = resolved.get_backend_name() == "sqlite" and resolved.get_driver_name() == "pysqlite"
    if pysqlite:
        # FastAPI runs sync routes in a thread pool, so a pooled connection may be used by a different thread than
        # the one that opened it; the pool already guarantees one thread at a time. `timeout` is sqlite3's busy
        # timeout in seconds. Values passed by the caller win (tests use a 1-second timeout).
        connect_args = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
                        **engine_kwargs.pop("connect_args", {})}
        engine_kwargs["connect_args"] = connect_args
    engine = create_engine(resolved, **engine_kwargs)
    if pysqlite:
        event.listen(engine, "connect", _sqlite_on_connect)
        event.listen(engine, "begin", _sqlite_on_begin)
    return engine


def as_write_engine(engine: Engine) -> Engine:
    """The same engine (same pool, same listeners) with sqlite_begin="IMMEDIATE", for write sessions.

    A no-op in effect on other databases: the option is stored on the engine and nothing reads it.
    """
    return engine.execution_options(**WRITE_EXECUTION_OPTIONS)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The process-wide engine for the configured database, created on first call."""
    return make_engine()


# ---------------------------------------------------------------- sessions


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Factory for read sessions (plain BEGIN) on the process-wide engine.

    SQLAlchemy 2 sessions always run inside a transaction and never autocommit: nothing is written until the
    caller commits. expire_on_commit=False keeps loaded objects readable after commit (e.g. to build a response).
    """
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@lru_cache(maxsize=1)
def get_write_session_factory() -> sessionmaker[Session]:
    """Factory for write sessions (BEGIN IMMEDIATE) on the process-wide engine. Same pool as the read factory."""
    return sessionmaker(bind=as_write_engine(get_engine()), expire_on_commit=False)


def _session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield one session from `factory`; roll back if the caller raised, and always close it. Never commits."""
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """A read session, for `Depends(get_session)` in FastAPI routes that only read. The caller commits if needed."""
    yield from _session_scope(get_session_factory())


def get_write_session() -> Iterator[Session]:
    """A write session (BEGIN IMMEDIATE), for `Depends(get_write_session)` in routes that change data or write
    audit events. The caller commits; until then the write lock is held, so keep write transactions short."""
    yield from _session_scope(get_write_session_factory())
