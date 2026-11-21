# Issues for Person B (controls)

Found while integrating Person A's pipeline with `app/controls/`. Nothing in `controls/` was edited; each item is
yours to fix or close. Items with a test reference an `xfail` test that flips to passing once fixed.

| # | Found | Issue | Where | Test |
|---|---|---|---|---|
| 1 | 2026-11-21 | **Closed** (fixed on main by B). `ruff check .` reported 24 errors, all in `controls/`: 13 × E501 (line > 120), 10 × E741 (variable named `l`), 1 × E731 (lambda assigned to a name). The rest of `backend/` is clean, so the repo-wide lint gate fails only on these. | `approvals.py:252`, `duplicates.py:213-214`, `refdata.py:195,197,252`, `validate.py` (126-508) | `cd backend && ruff check app/controls` |
| 2 | 2026-11-21 | Voyageur `000903-A` (`voyageurcorporat-inv-017.pdf`) gets `DUPLICATE_EXACT` against history 000903 (AP-00277). HACKATHON_PLAN §4 lists it as a **near** duplicate (`DUPLICATE_LIKELY`): the number differs by a suffix, so a clerk should compare rather than treat it as the same document. Payment is held either way (severity `block`), so this is about the label and the message. Extraction reads the number exactly as printed (`000903-A`), total 5574.37 and date 2026-07-06, so the input to controls is right. | `duplicates.py` (number normalisation drops the `-A` suffix before the exact match) | `tests/api/test_flags_end_to_end.py::test_suffixed_number_is_a_near_duplicate` (strict xfail) |
