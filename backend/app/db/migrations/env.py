"""
Alembic environment: how `alembic upgrade / downgrade / revision` connect, and which metadata they compare against.

Owner: DB team. Run Alembic from backend/ (alembic.ini lives there).

Where the database URL comes from, first match wins:
1. config.attributes["connection"]: an open SQLAlchemy connection handed in by code (not used yet; supported so a
   caller can run migrations inside its own transaction).
2. sqlalchemy.url set on the Config, e.g. `cfg.set_main_option("sqlalchemy.url", ...)` in tests.
3. app.db.database.default_database_url(): DATABASE_URL / settings, the same URL the app uses.
Cases 2 and 3 go through app.db.database, so relative SQLite paths are resolved against the repo root and the
engine gets the SQLite pragmas (foreign_keys=ON, WAL).

render_as_batch=True: SQLite can't ALTER most constraints, so autogenerate emits `with op.batch_alter_table(...)`
blocks (copy-and-move table rebuilds) for later schema changes.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from app.db.database import default_database_url, make_engine, resolve_database_url
from app.db.models import Base

# The Config object for this run: values from alembic.ini plus anything set programmatically.
config = context.config

# Logging comes from alembic.ini. Code that runs migrations in-process (tests) can opt out so Alembic doesn't
# reconfigure the caller's loggers: cfg.attributes["configure_logger"] = False.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The metadata autogenerate compares the live database against. Importing app.db.models registers every table.
target_metadata = Base.metadata


def _database_url() -> str:
    """The URL to migrate: an explicit sqlalchemy.url override, else the app's configured URL. Always resolved."""
    override = config.get_main_option("sqlalchemy.url")
    return resolve_database_url(override) if override else default_database_url()


def _configure(**kwargs: object) -> None:
    """Options shared by offline and online runs."""
    context.configure(
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite-friendly ALTERs, see module docstring
        compare_type=True,  # autogenerate also reports column type changes
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it. No connection is opened."""
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_with(connection: Connection) -> None:
    """Run the migrations on an open connection.

    Alembic treats SQLite as non-transactional DDL ("Will assume non-transactional DDL" in the log), so a migration
    that fails halfway can leave some tables behind. For a dev or test database, delete the file and rerun.
    """
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Normal mode: connect and apply migrations."""
    handed_in = config.attributes.get("connection")
    if handed_in is not None:
        _run_with(handed_in)
        return
    engine = make_engine(_database_url())
    try:
        with engine.connect() as connection:
            _run_with(connection)
    finally:
        engine.dispose()  # release the file handle, so tests can delete their temp DB right away


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
