# coding/

Feature 3: suggest a GL account and department for every invoice line, with a reason a clerk can trust.

## Public API
| Function | Returns |
|---|---|
| `suggest.suggest(draft, repo)` | copy of the `DraftBill` with `line.coding = CodingSuggestion` on each line |
| `suggest.suggest_line(line, draft, repo)` | `CodingSuggestion` or `None` |
| `history_index.index_for(repo)` | cached `HistoryIndex` (per-vendor + global past lines, GL/dept names) |

`extraction.pipeline` calls `suggest()` as its last step, so every `DraftBill` it returns is already coded.

## Tiers
1. **Vendor history**: each past line of the same vendor votes for its (GL, dept), weighted `0.5 + description similarity`.
   Confidence = `0.65 × weighted share + 0.35 × best similarity` (≤ 0.97).
2. **Vendor default GL** from the master (dept = most common for that GL). Confidence 0.55.
3. **Global similarity**: the top 10 most similar past lines across all vendors vote. Confidence ≤ 0.6.

0. **A clerk's correction** (`history_index.learn`): an accepted or overridden coding on an app bill wins for the
   same vendor when the description is ≥ 0.85 similar; the reason names the corrected bill. Fed by
   `feedback.learn_from_line` (from `services/bills.code_line`) and rebuilt at start-up from `bill_lines` by
   `feedback.replay_learned_codings`, so a restart keeps it.

The requester's department overrides the suggested department when the bill has a requester
(`requester.recode_for_requester`, on PATCH; the reason ends "department D01 from requester U013 (replaces D08)").
`requester.requester_problem` refuses a terminated or inactive requester (422).

Example reason: `5010 Freight & Carrier Costs · D01 Operations: 58 of 58 past lines from Polar Freight Lines Ltd.; closest match 'LTL shipment Toronto-Montreal'`.

## How to change it safely
Add a case to `tests/coding/test_suggest.py`. Keep it deterministic (no LLM): suggestions must be
explainable from history and the clerk's own corrections.
