# Brim AP: team guide

**Product.** An accounts-payable web app for Harborline Logistics (synthetic dataset). Invoices arrive by
email or upload. They're read and coded (GL + department), validated and checked for duplicates, routed to
approvers by role/policy, paid (simulated EFT) and logged in a full audit trail. There are six roles:
employee, ap_clerk, approver, finance_manager, controller_admin, auditor. Role rules are enforced
**server-side**. Judges run a **hidden batch** of unseen invoices, so build for generality, not the 56 samples.

Known dataset traps and the flag that catches each: [`docs/DETECTION_COVERAGE.md`](docs/DETECTION_COVERAGE.md). Design decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Repo map

| Folder | Owner | Purpose |
|---|---|---|
| `backend/app/shared/` | everyone | `schemas.py` = the data contract |
| `backend/app/reference/` | Intake and extraction | Read-only master data (CSV now, DB later) behind `ReferenceRepository` |
| `backend/app/intake/` | Intake and extraction | Email classification, inbox processing, uploads |
| `backend/app/extraction/` | Intake and extraction | PDF/OCR text → LLM → normalize → self-check → vendor match → `DraftBill` |
| `backend/app/coding/` | Intake and extraction | GL/department suggestions from history |
| `backend/app/controls/` | Controls | Validation, duplicates, approval routing, payment-release rules (deterministic) |
| `backend/app/db/`, `backend/app/auth/` | Database and API | Schema, seeding, auth, role middleware, audit log, state machines |
| `backend/app/api/` | Database and API (`routes_intake.py`: intake and extraction) | HTTP endpoints |
| `frontend/` | everyone, later | React + TS UI |
| `dataset/brim_ap_dataset/` | nobody | Provided data. **Never modified by code.** |

## Rules
1. **No AI attribution anywhere.** No `Co-Authored-By`, "Generated with …", session links, or mentions of AI
   tools in commits, PR descriptions, code comments, docstrings or docs. Use plain conventional commits:
   `feat(extraction): add PDF text layer`.
2. **Stay in your folder.** If you need something from another owner's folder, ask them or open an issue.
3. **`shared/schemas.py` changes need team agreement.** Prefer additive, optional fields.
4. **Use the fixed as-of date** `get_settings().as_of_date` (2026-11-02). Never `date.today()` in business logic.
5. **Money is `Decimal`**, never float. Parse strings straight to Decimal.
6. **No secrets in git.** Keys live in `.env` (gitignored); `.env.example` has placeholders only.
7. **Never commit generated output or caches** (`backend/.cache/`, `backend/output/`, `__pycache__`, `.venv`).
8. **LLM only in intake/extraction.** Everything in `controls/` is deterministic and unit-tested.
9. **Tests never call the network.** Mock the LLM client.
10. **Don't overfit.** Regex only as a cross-check, never as the main parser.

## Commands (run from repo root unless noted)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
cp .env.example .env                       # then add ANTHROPIC_API_KEY
cd backend && uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
cd backend && pytest                       # no network needed
cd backend && ruff check .
cd backend && python scripts/run_inbox.py        # all 59 emails → backend/output/
cd backend && python scripts/eval_extraction.py  # accuracy vs tests/golden/
```

## Adding a feature
1. Work in your own folder on your own branch.
2. Write the test first (`backend/tests/<area>/`). Use the cases in docs/DETECTION_COVERAGE.md.
3. Implement it, then run `pytest` and `ruff check .`.
4. Update that folder's `README.md` (public functions, how to change it).
5. Add one line to `docs/DECISIONS.md` if you made a design choice.

## Git workflow
- Branch per person: `a/extraction`, `b/controls`, `db/<topic>`.
- Small commits. Rebase on `main` often. Merge via PR.
- Never force-push `main`.
