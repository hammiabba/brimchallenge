# db/

**Owner:** DB team. **Status:** schema, baseline migration, seed and audit log done; DB adapters come next.

The app database: SQLAlchemy 2.0 models, engine and session setup, value helpers, and Alembic migrations.
Importing anything here never connects to or creates a database.

## What's in the package

| File | Contents |
|---|---|
| `database.py` | `make_engine(url=None)` (path resolution, SQLite pragmas, 15 s busy timeout, SQLAlchemy's pysqlite transaction recipe), `get_engine()`, `as_write_engine(engine)`, `resolve_database_url()`. Two session factories on one engine and pool: `get_session_factory()` / `get_session()` for **read sessions** (plain `BEGIN`) and `get_write_session_factory()` / `get_write_session()` for **write sessions** (`BEGIN IMMEDIATE`); the generators are FastAPI dependencies. `require_write_session(session, caller)` raises RuntimeError on SQLite unless the session is a write session. |
| `settings.py` | `DbSettings` / `get_db_settings()`: DB-only settings from the environment and `.env`; currently `AUDIT_HMAC_KEY` (a `SecretStr`). |
| `types.py` | `to_cents` / `from_cents`, `dec_to_text` / `text_to_dec`, `utcnow` / `to_utc`. |
| `models.py` | The schema: 25 tables (reference data from the dataset CSVs, bills and their lines/taxes, controls runs and flags, approval routes and decisions, vendor bank accounts and change requests, payments, absences, emails, intake items, the audit log). Also the allowed-value tuples behind every CHECK constraint. Import it as a module (`from app.db import models`): `TaxCode` and `AuditEvent` also exist in `app.shared.schemas`. |
| `seed.py` | `seed_all(session, dataset_dir) -> SeedReport` (insert-only, one `BEGIN IMMEDIATE` transaction, pre-flight first) and the `python -m app.db.seed` CLI. See "Seeding". |
| `seed_mapping.py` | Pure functions mapping one dataset row (all strings) to table columns, with strict money / boolean / date parsers; unit-tested without a database. |
| `bills.py` | Bill persistence (no commits, no audit events; the API services log): `next_bill_id`, `create_bill_from_draft` (DraftBill -> app bill, lines, taxes; bad extracted references stored as NULL with warnings), `load_draft_bill` (current DraftBill: document facts from `draft_json`, editable state from the columns and tables), `save_controls_run` (versioned runs, flags, route steps; overridden / resolved flags carry over when unchanged), `latest_controls_run`, `route_for_bill` (the `route` for `can_approve`) and `approver_ids_for_bill` (the `approver_ids` for `can_release`). Writers need a write session. |
| `refdata_db.py` | DB-backed RefData for `app.controls`: `rows_as_csv(session, exclude_bill_id=None)` renders the database as the CSV rows controls' `build_refdata` reads (one list per stem in `REFDATA_FILES`), and `refdata_from_db(session, exclude_bill_id=None, as_of=None)` hands them to `build_refdata`. Nothing is re-interpreted here. Includes app bills (not `void`) and verified app bank changes; policies come from the table, so admin edits apply. Read-only. **When running controls on a stored bill, pass its own `exclude_bill_id`**, or it is reported as a duplicate of itself. |
| `backfill.py` | `backfill_history_controls(session, only_missing=True) -> BackfillReport` and the `python -m app.db.backfill` CLI: one point-in-time controls run per history bill, via `controls.history.replay_bill` and `bills.save_controls_run`. See "Back-fill". |
| `audit.py` | The audit log: `log_event` (write sessions only), `verify_chain`, `chain_head`, `list_events`, `iter_events_csv`, plus `to_audit_json`, `redact`, `mask_digit_runs` and the `AuditAction` names. See "Audit log". |
| `migrations/` | Alembic `env.py`, the template for new revisions, and `versions/` (`0001_baseline.py`, `0002_audit_chain_unique.py`). |

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

## Seeding

Loads the synthetic dataset (`DATASET_DIR`, by default `dataset/brim_ap_dataset`) into the database. From `backend/`,
with the venv active:

```bash
python -m app.db.seed                                                   # DATABASE_URL / settings
python -m app.db.seed --database-url sqlite:////tmp/brim/seed.db        # any other database
python -m app.db.seed --database-url sqlite:////tmp/brim/seed.db --reset  # start from an empty file
```

A run first migrates the database to head (`alembic upgrade head`), then seeds it: it reads every CSV as strings
plus `inbox/emails.json`, maps each row (`seed_mapping.py`), runs the pre-flight, inserts everything in **one
transaction** (all or nothing), and prints the report. In code: `seed.seed_all(session, dataset_dir) -> SeedReport`
(use an engine from `make_engine()`). Not seeded: `incoming_invoices/` (those go through intake) and `audit_events`.

- `--database-url URL`: the database to seed. Default: `DATABASE_URL` / settings, with relative SQLite paths
  resolved against the repo root.
- `--reset`: deletes the SQLite file and its `-wal` / `-shm` before migrating. The guard refuses, exits with code 2
  and deletes nothing for: a non-SQLite URL, an in-memory or URI-style SQLite name, a directory, and any path
  inside the repo's `dataset/` or the configured `DATASET_DIR` (symlinks are resolved before the check).

**Insert-only.** Tables with a natural primary key use `INSERT ... ON CONFLICT (pk) DO NOTHING`; the autoincrement
tables are matched on a natural key instead: `vendor_bank_accounts` (vendor_id, institution, transit, account),
`bill_taxes` (bill_id, tax_code), `user_absences` (user_id, starts_on). Existing rows are never updated, so a
re-seed never overwrites app edits to vendors, users, policies or bills, and a second run inserts 0 rows. (A history
row the app *deleted* would come back on a re-seed; history rows are meant to be voided, not deleted.)

**Pre-flight validation.** Before anything is written, every mapped row is checked against the schema's own rules
(NOT NULL, CHECK value lists, the free-form CHECKs such as releaser ≠ preparer or verifier ≠ requester, foreign
keys) and the seed's rules (no duplicate keys; money with more than 2 decimals is an error, never rounded;
booleans must be yes / no / true / false / n/a; each bill's tax rows must add up to its GST/HST + PST/QST). All
violations are collected, not just the first. If there are any, nothing is written: the CLI prints them grouped by
rule with row ids on stderr and exits with code 1; `seed_all` raises `SeedValidationError` (`.violations`,
`.format()`).

**Data-quality notes.** Facts about the data that are worth knowing but don't block the seed (for example: actor
roles come from users.csv as of the seed date, FX rate-date matches, vendors without bank details, bills paid twice).
They print on stdout after the per-table counts (rows / inserted / skipped) and are in `SeedReport.notes`.

**Intentional findings, not seed bugs.** These are in the dataset on purpose and are loaded exactly as recorded:
- 7 (vendor_id, norm_invoice_number) pairs repeat in history (5 exact repeats of the invoice number, 2 more after
  normalization). No UNIQUE constraint stops them, so the duplicate checks can see them.
- 3 self-approvals by U010 (AP-A-00101, AP-A-00193, AP-A-00259): kept as evidence for the audit view.
- BC-009 (Cascadia, V004, requested by email, never called back) is `pending_verification`, yet V004's open bank
  account is already the new one: the change was applied without verification, which controls must flag.

Exit codes: 0 seeded, 1 pre-flight failed (nothing written), 2 `--reset` refused.

## Back-fill

```bash
cd backend && python -m app.db.seed --reset && python -m app.db.backfill   # [--database-url URL] [--all]
```

The seed loads the 426 history bills without controls runs. `backfill.py` adds one run per history bill (version 1,
with its flags and route steps) so the UI shows them like app bills. It never changes a bill's status, approval
decisions or payments.

- **Point in time.** Each bill is replayed with Hamid's `controls.history.replay_bill`, not re-implemented: it sees only
  invoices before it (by invoice date, then id), bank changes made before its invoice date, user absences already
  started, and its received date as "today". So a duplicate is flagged on the later invoice only, and no history bill
  carries `BANK_CHANGE_UNVERIFIED` (BC-009 was requested after the last V004 invoice). App bills are left out of the
  replay's RefData: a history bill couldn't have known about them.
- **Idempotent.** By default bills that already have a run are skipped, so a second run replays 0. `--all`
  (`only_missing=False`) replays every history bill and is refused once any has a run, since it would add version-2
  runs next to the first.
- **Report** (`BackfillReport`, printed by the CLI): replayed / skipped, flags by severity, the 10 most common codes,
  the bills carrying `DUPLICATE_EXACT`, `ALREADY_PAID_BY_CARD`, `BANK_CHANGE_UNVERIFIED` and `POSSIBLE_SPLIT`, and
  `route_mismatches`: bills whose recorded approvers don't include every user on the replayed route (rejected bills
  aren't compared). Report only; nothing is changed.
- **Audit.** One `controls.backfilled` event (actor and role `system`, entity `system` / `history`, counts in `after`)
  per call that replayed something. The function never commits; the CLI commits once at the end.

## Audit log

`audit.py`. Every state change writes one event with `log_event()`, in the same transaction as the change, on a
**write session**:

```python
from app.db.audit import AuditAction, log_event
from app.db.database import get_write_session

# in a route: session: Session = Depends(get_write_session)
bill.status = "approved"
log_event(session, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.BILL_APPROVED,
          entity_type="bill", entity_id=bill.bill_id, before={"status": "pending_approval"},
          after={"status": "approved"}, on_behalf_of=step.delegated_from, request_id=request_id)
session.commit()  # the caller commits: the change and its event land together, or neither does
```

- **Write sessions vs read sessions** (`database.py`). SQLite transactions follow SQLAlchemy's pysqlite recipe: the
  driver's own BEGIN handling is off and SQLAlchemy emits BEGIN itself, so SAVEPOINTs nest properly and a rollback
  undoes everything. `get_session()` / `get_session_factory()` give **read sessions** (plain, deferred `BEGIN`: no
  lock until a write). `get_write_session()` / `get_write_session_factory()` give **write sessions**
  (`BEGIN IMMEDIATE`: the write lock is taken at the first statement and held until commit or rollback). Both use
  the same engine and pool; the difference is the execution option `sqlite_begin="IMMEDIATE"` (`as_write_engine`).
  The busy timeout is 15 s. Use a write session for anything that writes, and keep write transactions short (SQLite
  has one writer at a time). `log_event` on SQLite **refuses a read session** with
  `RuntimeError("log_event requires a write session (get_write_session)")`.
- **Never commits or closes the session.** The insert runs in a SAVEPOINT inside the caller's transaction; if the
  caller rolls back, the event is gone too. Because the write session holds the lock from its first statement,
  nobody can append between `log_event` reading the latest hash and inserting the new event.
- **Never rejects an event for its content.** Any `action` string is accepted; `AuditAction` lists the standard
  dotted names (`bill.approved`, `payment.released`, ...). Only an empty actor, role, action, entity type or entity
  id is refused (ValueError). Use `SYSTEM_ACTOR` (`"system"`, role `"system"`) for the seed and background jobs.
- **Payloads.** `before` / `after` go through `to_audit_json` (Decimal as an exact string, datetimes as ISO 8601 UTC
  with `Z`, enums as values, pydantic models dumped, sets sorted; anything unknown is a TypeError) and then `redact`:
  values under `account`, `new_account`, `bank_account` or `account_number` become `{"last4", "fingerprint"}`.
- **The HMAC key.** The fingerprint is the first 12 hex characters of HMAC-SHA256 keyed by `AUDIT_HMAC_KEY`, so two
  events about one account can be matched but a number can't be recovered by hashing every possible account. Set
  `AUDIT_HMAC_KEY` in `.env` (read by `app/db/settings.py`) to 32+ random characters:
  `python -c "import secrets; print(secrets.token_hex(32))"`. If it's missing or shorter, `log_event` raises
  `AuditKeyError` the first time it needs a fingerprint (events without account numbers still work). The key is a
  `SecretStr`: it never appears in logs, errors or stored rows. Changing it changes every future fingerprint, so
  old and new events about the same account no longer match; keep it stable.
- **Masking free text.** Runs of 7 or more digits are masked to stars plus their last 4
  (`"new acct 593014216 per call"` -> `"new acct *****4216 per call"`) in `comment`, and in `before` / `after` strings
  under any key containing `comment`, `note` or `memo` (case-insensitive). Shorter numbers, like a 6-digit invoice
  number, are left alone; so are other keys (an `invoice_number` of 10 digits stays). Digits split by spaces or
  dashes aren't caught, so still don't paste account numbers into comments.
- **Hash chain.** Each event stores `prev_hash` (`"GENESIS"` for the first) and
  `hash = sha256(prev_hash + "\n" + canonical JSON of the event's fields except seq and hash)`. A UNIQUE index on
  `prev_hash` (migration 0002) stops the chain from forking; if another writer extended the same event first,
  `log_event` re-reads and retries, up to 5 attempts, then raises `AuditChainConflict`.
- **`verify_chain(session) -> ChainReport(ok, count, first_bad_seq, reason)`** recomputes every hash in `seq` order
  and finds the first edited, inserted or deleted event. It can't see the newest events being removed (truncation).
- **`chain_head(session) -> (seq, hash) | None`** returns the newest event, or None on an empty log. Record it with
  each export (somewhere the database can't change); later, that seq must still exist with that hash, which catches
  the truncation `verify_chain` can't.
- **Reading, for the audit API** (no authorization here; the route checks the role):
  `list_events(session, entity_type=, entity_id=, actor_user_id=, action=, since=, until=, after_seq=, limit=100)`
  returns `AuditRecord`s (a `schemas.AuditEvent` plus `seq`, `request_id`, `prev_hash`, `hash`), oldest first.
  Page with `after_seq=<last seq>`; `limit` is capped at 500; `since` is inclusive and `until` exclusive.
  `iter_events_csv(session, **same filters)` streams a header and one CSV record per event, 500 rows per query,
  with cells starting `= + - @`, tab or CR prefixed by `'` (spreadsheet formula injection). Keep the session open
  until the stream is consumed.
- **Append-only.** Triggers from 0001 abort any UPDATE or DELETE on `audit_events`. Tests that simulate tampering
  drop the triggers in their own temp database only.

## Rules

- **A migration is never edited after it is pushed.** Once a revision is on a shared branch, someone may have
  applied it; fix forward with a new revision. Each migration is a frozen snapshot: it writes out its own allowed
  values instead of importing them from `models.py`.
- **The baseline (`0001`) is SQLite-only.** The audit triggers use SQLite's `RAISE(ABORT, ...)`, and the
  `users` <-> `departments` foreign keys reference each other inline, which only SQLite accepts at CREATE TABLE time.
  The migration refuses to run on another database. A Postgres port needs a trigger function and an
  `op.create_foreign_key` step for `departments.manager_user_id`.
- **Each migration is atomic; a multi-revision upgrade is not.** Alembic still logs "Will assume non-transactional
  DDL" for SQLite and commits after every revision, but with the pysqlite recipe each revision runs inside a real
  transaction: if a revision fails, everything it did (DDL and DML) rolls back and `alembic_version` stays at the
  previous revision. Tested by running a revision that created a table, inserted a row and created an index, then
  raised: none of the three survived. An `upgrade head` across several revisions stops at the last one that
  succeeded; the ones before it stay committed. (Before the recipe, the failed revision's CREATE TABLE survived
  while `alembic_version` still pointed at the previous revision, so a rerun failed with "table already exists".)
- **Never use `batch_alter_table` on `audit_events`.** On SQLite a batch block can rebuild the table (create a copy,
  move the rows, drop the original), and the rebuild silently drops the append-only triggers. Use plain
  `op.create_index` / `op.drop_index`, and add columns with `op.add_column` only if SQLite supports it directly.
  Any future migration that touches `audit_events` must end by asserting the triggers still exist, e.g. in
  `upgrade()`: `SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ('audit_events_no_update',
  'audit_events_no_delete')` must return 2, else raise. (Autogenerate emits `batch_alter_table` by default: always
  rewrite it for this table.)
- Never write to `dataset/`. Never commit a database file.

## Not built yet

- A `DbReferenceRepository` implementing `app.reference.repository.ReferenceRepository` for extraction and coding
  (see `app/reference/README.md`). The controls side is done: `refdata_db.refdata_from_db`.
- Storage for `EmailTriage` (the `emails` triage columns) and `intake_items`, and wiring `api/routes_intake.py`
  (Person A's file) to `bills.create_bill_from_draft` in place of its TEMP dict.
- Recording approval decisions, and deriving what `can_approve` / `can_release` need beyond `bills.py`: the step
  being signed, `approval_complete`, the CAD amount the route was built for (a split's combined amount), and the
  flags still blocking (stored flags whose resolution is open).
- The bill and payment state machines.
- Re-running controls on history bills after a controls change: the back-fill only fills in missing runs. Replaying all
  of them again (new versions) needs a decision on whether history should be judged by today's rules.
