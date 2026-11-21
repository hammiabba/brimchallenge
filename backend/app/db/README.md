# db/

**Owner:** DB team. **Status: stub.**

## What you own
- SQLAlchemy 2 models + migrations for all dataset tables, plus app tables: drafts/invoices, controls results,
  approvals, payments, vendor bank-change requests, policies (admin-editable), `audit_event` (append-only).
- Seeding: load every CSV in `dataset/brim_ap_dataset/data/` as-is (keep IDs; read with `dtype=str`).
- Invoice and payment state machines (pending_approval → approved → scheduled → paid / rejected).
- One `log_event(actor, action, entity_type, entity_id, before, after, comment)` helper that writes `AuditEvent`.
- `DATABASE_URL` from settings (SQLite locally, Postgres later).

## What Person A and Person B need from you
- **A `DbReferenceRepository`** implementing `app.reference.repository.ReferenceRepository` (same method names,
  DataFrames with CSV column names and string values). Then switch `default_repository()` to it.
  See `app/reference/README.md`.
- Storage for `DraftBill` + `EmailTriage` (replace the TEMP dict in `api/routes_intake.py`), keyed by `source.file_hash`.
- Storage for `ControlsResult` per invoice, and the approvals history that `can_release` needs.
