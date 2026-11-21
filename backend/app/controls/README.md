# controls/

**Owner:** Person B. **Status: stubs only.** Signatures and docstrings are in place; every function raises `NotImplementedError`.

Deterministic checks on a `DraftBill`: validation, duplicates, approval routing and payment-release permissions.
**No LLM here.** Every result must be reproducible and explainable in the Q&A.

## Public API (to implement)
| Function | File | Returns |
|---|---|---|
| `validate(draft, repo)` | `validate.py` | `list[Flag]` |
| `find_duplicates(draft, repo)` | `duplicates.py` | `list[DuplicateMatch]` |
| `route(draft, repo)` | `routing.py` | `list[ApprovalStep]` |
| `can_approve(user_id, draft, route, step_no, repo)` | `permissions.py` | `PermissionDecision` |
| `can_release(user_id, payment, approval_chain, open_flags, repo)` | `permissions.py` | `PermissionDecision` |
| `run_controls(draft, repo)` | `engine.py` | `ControlsResult` |

## What Person A gives you on every `DraftBill`
- `vendor.vendor_id` + `match_method` + `match_score` (`NONE` = not in master), and the GST/bank details **as printed**
- `source.sender_address` for lookalike-domain checks; `source.was_ocr`
- `ship_to_province` from the bill-to address; `line_type` per line; `taxes` mapped to `TaxCode`
  (`FOREIGN` with 0 amount for foreign vendors with no tax)
- printed amounts, **never corrected**; arithmetic problems are listed in `extraction_warnings`
- `field_confidence` per field (low = LOW_EXTRACTION_CONFIDENCE candidate)
- `po_number` (None when blank; a warning says when the PO field was printed but empty)
- `is_credit_note`, `currency`, `fx_rate_to_cad`, `total_cad`

## How to work here
Write a failing test per row of `docs/HACKATHON_PLAN.md` §4 in `tests/controls/`, building `DraftBill`s by hand.
You don't need to wait for extraction. Use `get_settings().as_of_date`, never `date.today()`.
