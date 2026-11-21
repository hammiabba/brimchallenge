# db/

**Owner:** DB team. **Status:** schema and baseline migration done; seeding, adapters and the audit helper come next.

The app database: SQLAlchemy 2.0 models, engine and session setup, value helpers, and Alembic migrations.
Importing anything here never connects to or creates a database.

## What's in the package

| File | Contents |
|---|---|
| `models.py` | The schema: 25 tables (reference data from the dataset CSVs, bills and their lines/taxes, controls runs and flags, approval routes and decisions, vendor bank accounts and change requests, payments, absences, emails, intake items, the audit log). Also the allowed-value tuples behind every CHECK constraint. Import it as a module (`from app.db import models`): `TaxCode` and `AuditEvent` also exist in `app.shared.schemas`. |
| `database.py` | `make_engine(url=None)`, `get_engine()`, `get_session_factory()`, `get_session()` (a FastAPI dependency for later), `resolve_database_url()`. |
| `types.py` | `to_cents` / `from_cents`, `dec_to_text` / `text_to_dec`, `utcnow` / `to_utc`. |
| `migrations/` | Alembic `env.py`, the template for new revisions, and `versions/` (`0001_baseline.py`). |

Tests: `backend/tests/db/` (each test migrates a fresh SQLite file in pytest's `tmp_path`).

## Conventions

- **Money** is INTEGER minor units in `*_cents` columns, next to a `currency` column (`CAD` / `USD`). Columns named
  `*_cad_cents` are CAD by name. `bill_lines` and `bill_taxes` amounts are in their bill's currency. Convert only
  with `types.to_cents(Decimal)` / `types.from_cents(int)`: they round half-up to 2 places and refuse floats, NaN and
  infinity. (SQLite stores `Numeric` as a float, which is why money isn't `Numeric`.)
- **Rates, quantities and unit prices** are TEXT holding an exact decimal string (`"0.09975"`, `"1.3709"`).
  Use `types.dec_to_text` / `types.text_to_dec`; they never go through float or exponent notation.
- **Timestamps** are DATETIME holding **naive UTC**, because SQLite drops time zone offsets (15:00-05:00 would be
  stored as 15:00). Use `types.utcnow()`. The ORM converts aware datetimes to UTC on every insert and update; Core
  `insert()` / `update()` statements bypass that and must call `types.to_utc`. Business dates ("today") still come
  from `get_settings().as_of_date`, never the clock.
- **Dates** are DATE. **IDs** are TEXT and reuse the dataset formats (`V001`, `U007`, `AP-00001`, `PAY-00001`,
  `BC-001`, ...); app-created rows continue the same numbering.
- **Enumerated columns** have named CHECK constraints (`ck_<table>_<column>`); errors name the rule that failed.
- **`origin`** (`history` / `app`) marks rows loaded from the dataset vs created in the app.
- **`bills.draft_json`** is the frozen extraction snapshot from intake and is never edited. Corrections go to the
  bill columns, `bill_lines` and `bill_taxes`; the current DraftBill is rebuilt from those tables.
- **`audit_events`** is append-only: triggers abort any UPDATE or DELETE.
- **Foreign keys** are enforced (`PRAGMA foreign_keys=ON` on every connection). Always create engines with
  `make_engine()`, which also turns on WAL journaling.

## Running migrations

From `backend/`, with the venv active:

```bash
alembic upgrade head                                   # apply all migrations to DATABASE_URL
alembic downgrade base                                 # revert everything
alembic current                                        # which revision the database is at
alembic check                                          # fails if models.py and the migrations disagree
DATABASE_URL=sqlite:////tmp/scratch.db alembic upgrade head   # any other database
```

The URL comes from `DATABASE_URL` (or `.env`), through `app.db.database`. A relative SQLite path is resolved against
the repo root, so `sqlite:///./backend/ap.db` is the same file whether you start from the repo root or `backend/`.
`alembic.ini` deliberately contains no URL.

Adding a migration: change `models.py`, then
`alembic revision --autogenerate -m "what changed" --rev-id 0002`, review the generated file by hand (autogenerate
misses triggers and CHECK changes), write a full `downgrade()`, run `alembic upgrade head` + `downgrade -1` +
`upgrade head` + `alembic check` on a scratch database, and run `pytest tests/db`.

## Rules

- **A migration is never edited after it is pushed.** Once a revision is on a shared branch, someone may have
  applied it; fix forward with a new revision. Each migration is a frozen snapshot: it writes out its own allowed
  values instead of importing them from `models.py`.
- **The baseline (`0001`) is SQLite-only.** The audit triggers use SQLite's `RAISE(ABORT, ...)`, and the
  `users` <-> `departments` foreign keys reference each other inline, which only SQLite accepts at CREATE TABLE time.
  The migration refuses to run on another database. A Postgres port needs a trigger function and an
  `op.create_foreign_key` step for `departments.manager_user_id`.
- Alembic runs SQLite migrations without transactional DDL, so a migration that fails halfway can leave tables
  behind. On a dev or test database, delete the file and rerun.
- Never write to `dataset/`. Never commit a database file.

## Not built yet

- Seeding every CSV in `dataset/brim_ap_dataset/data/` (keep IDs, read as strings, idempotent).
- A `DbReferenceRepository` implementing `app.reference.repository.ReferenceRepository` (see
  `app/reference/README.md`), and a `RefData` built from the database for `app.controls`.
- Storage for `DraftBill` + `EmailTriage` to replace the TEMP dict in `api/routes_intake.py` (Person A's file).
- Storage for `ControlsResult` per bill, and the approval history `can_release` needs.
- One `log_event(...)` helper that writes `audit_events` (with the hash chain), and the bill and payment
  state machines.
