# coding/

**Owner:** Person A. Feature 3: suggest a GL account and department for every invoice line, with a reason a clerk can trust.

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

The requester's department overrides the suggested department when the bill has a requester.

Example reason: `5010 Freight & Carrier Costs · D01 Operations: 58 of 58 past lines from Polar Freight Lines Ltd.; closest match 'LTL shipment Toronto-Montreal'`.

## How to change it safely
Add a case to `tests/coding/test_suggest.py`. Keep it deterministic (no LLM): suggestions must be
explainable from history alone. When the clerk accepts or edits a suggestion, the API sets `accepted=True`.
Feeding accepted codings back into history is a good next step.
