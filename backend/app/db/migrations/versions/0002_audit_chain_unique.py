"""Audit chain: a UNIQUE index on audit_events.prev_hash, so the hash chain can never fork.

Each audit event stores the hash of the event before it (prev_hash). Two events claiming the same predecessor would
fork the chain; this index makes the second insert fail, and app.db.audit.log_event re-reads the latest hash and
retries. The first event uses prev_hash "GENESIS" rather than NULL, so the start of the chain is unique too (NULLs
never collide in a UNIQUE index). The column stays nullable: the 0001 rows written by tests and scripts before this
revision may have NULL, and making it NOT NULL would need a table rebuild.

Generated with `alembic revision --autogenerate`, then edited by hand: autogenerate wrapped the index in
`batch_alter_table`. A batch block on SQLite can rebuild (copy and rename) the table, and a rebuild would silently drop
the append-only triggers created in 0001. A plain CREATE INDEX never touches the table or its triggers.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21 14:17:36.948119
"""
from collections.abc import Sequence

from alembic import op

# Revision identifiers, used by Alembic to order migrations.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_audit_events_prev_hash"


def upgrade() -> None:
    """Add the unique index on prev_hash (fails if existing rows already share a prev_hash)."""
    op.create_index(op.f(INDEX_NAME), "audit_events", ["prev_hash"], unique=True)


def downgrade() -> None:
    """Drop the index; the table, its rows and its triggers are untouched."""
    op.drop_index(op.f(INDEX_NAME), table_name="audit_events")
