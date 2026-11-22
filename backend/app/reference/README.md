# reference/

This module holds the interface and the CSV implementation; a database-backed one is planned for the db module.

Read-only access to master data: vendors, invoice history, lines, tax codes, FX rates, contracts, POs, users,
departments, GL accounts, card transactions, bank-change history and policies.

## Public API
- `ReferenceRepository` (Protocol, `repository.py`): one method per table, returning a `pandas.DataFrame`
  with the **CSV column names** and **string values** (`""` for blanks). Also `vendor(id) -> dict | None`
  and `fx_rate(date) -> Decimal | None` (closest earlier date).
- `CsvReferenceRepository(dataset_dir=None)`: reads `DATASET_DIR/data/*.csv`, caches each file.
- `default_repository()`: a shared process-wide instance.

## Swapping in the database (db module)
1. Write `DbReferenceRepository` in `app/db/` with the same methods. `pd.read_sql(..., dtype=str)` keeps
   the same "everything is a string" contract.
2. Change `default_repository()` to return it (or inject it through a FastAPI dependency).
3. Run `pytest`. The extraction/coding tests use the CSV repo as a fixture, so they won't change.

## Rules
- Never write to the dataset folder.
- Keep values as strings here; parse to `Decimal`/`date` where they're used.
