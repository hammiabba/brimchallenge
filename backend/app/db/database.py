"""
Engine and session factory for the app database.

Owner: DB team.

What this module does:
- Reads the URL from `get_settings().database_url` (env var DATABASE_URL, default SQLite under backend/).
- Resolves a relative SQLite path against the repository root, so `sqlite:///./backend/ap.db` means the same file
  whether the server is started from the repo root or from backend/.
- Turns on SQLite foreign keys (off by default in SQLite) and WAL journaling for every new connection.
- Hands out sessions that never autocommit: every write needs an explicit `session.commit()`.

Nothing connects at import time. The engine is created on first use, so importing this module never creates a
database file. Always build engines with `make_engine()` so the SQLite pragmas are applied; Alembic's env.py does.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT, get_settings

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


# ---------------------------------------------------------------- engine


def _sqlite_on_connect(dbapi_connection: Any, _connection_record: Any) -> None:
    """Runs once per new DBAPI connection. Pragmas are per connection in SQLite, so this must run on every one."""
    cursor = dbapi_connection.cursor()
    try:
        # SQLite ignores FOREIGN KEY clauses unless this is on; without it every FK in models.py is decoration.
        cursor.execute("PRAGMA foreign_keys=ON")
        # Write-ahead logging: readers don't block the writer. Stored in the file, so later connections inherit it.
        # In-memory databases answer "memory" and carry on, which is fine.
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def make_engine(url: str | URL | None = None, **engine_kwargs: Any) -> Engine:
    """Create an engine for `url` (default: the configured URL) with path resolution and SQLite pragmas applied."""
    resolved = make_url(resolve_database_url(url if url is not None else get_settings().database_url))
    if resolved.get_backend_name() == "sqlite" and resolved.get_driver_name() == "pysqlite":
        # FastAPI runs sync routes in a thread pool, so a pooled connection may be used by a different thread than
        # the one that opened it. The pool already guarantees one thread at a time, so the sqlite3 check can go.
        connect_args = {"check_same_thread": False, **engine_kwargs.pop("connect_args", {})}
        engine_kwargs["connect_args"] = connect_args
    engine = create_engine(resolved, **engine_kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_on_connect)
    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The process-wide engine for the configured database, created on first call."""
    return make_engine()


# ---------------------------------------------------------------- sessions


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Session factory bound to the process-wide engine.

    SQLAlchemy 2 sessions always run inside a transaction and never autocommit: nothing is written until the
    caller commits. expire_on_commit=False keeps loaded objects readable after commit (e.g. to build a response).
    """
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Yield one session and always close it. Intended for `Depends(get_session)` in FastAPI routes (later step).

    The caller commits. On an exception the open transaction is rolled back before the error propagates;
    close() also discards anything left uncommitted.
    """
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
