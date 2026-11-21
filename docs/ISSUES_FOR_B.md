# Issues for Person B (controls)

Found while integrating Person A's pipeline with `app/controls/`. Nothing in `controls/` was edited; each item is
yours to fix or close. Items with a test reference an `xfail` test that flips to passing once fixed.

| # | Found | Issue | Where | Test |
|---|---|---|---|---|
| 1 | 2026-11-21 | `ruff check .` reports 24 errors, all in `controls/`: 13 × E501 (line > 120), 10 × E741 (variable named `l`), 1 × E731 (lambda assigned to a name). The rest of `backend/` is clean, so the repo-wide lint gate fails only on these. | `approvals.py:252`, `duplicates.py:213-214`, `refdata.py:195,197,252`, `validate.py` (126-508) | `cd backend && ruff check app/controls` |
