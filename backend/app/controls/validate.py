"""
Validation & matching checks for one DraftBill.  STUB (owner: Person B).

Pure function: DraftBill + reference data in, list[Flag] out. No LLM, no I/O besides the repository.
Flag codes come from shared.schemas.FLAG_CODES.

Known cases to cover (docs/HACKATHON_PLAN.md §4):
- vendor: not in master (Invoice 4443.pdf, zephyrdataservic_7590.pdf); pending_review / inactive
  (riverbendcaterin_1739.pdf); GST ≠ master; bank ≠ master; unverified bank change
  (Cascadia V004, BC-009 by email on 2026-10-27); lookalike sender domain (EM-026 harlowandstern-llp.example)
- tax from ship_to_province + line_type: ON HST13; AB/MB/SK GST5; BC GST5 + PST7 goods only
  (signalsparrowcre_000970.pdf has PST on services); QC GST5 + QST9975 (beaumontrivieres_FA000557.pdf missing QST);
  northboundcourie_000639.pdf AB charged HST; ironwoodpalletco-inv-048.pdf ON no tax; insurance exempt; foreign no tax
- arithmetic: draft.extraction_warnings already lists line/subtotal/total mismatches
  (evergreen 000850, northstar NO26-1773)
- contract: fuel surcharge cap (Invoice 000964.pdf 22% vs C018 12%), hourly cap, monthly fee, NTE (Orion C023), expired
- PO: requires_po with blank PO → PO_REQUIRED_MISSING (P13); over remaining balance (P12); closed / other vendor
- dates relative to get_settings().as_of_date; low extraction confidence → LOW_EXTRACTION_CONFIDENCE
"""
from __future__ import annotations

from app.reference.repository import ReferenceRepository
from app.shared.schemas import DraftBill, Flag


def validate(draft: DraftBill, repo: ReferenceRepository) -> list[Flag]:
    """Return every validation flag for `draft`, most severe first."""
    raise NotImplementedError("controls.validate is owned by Person B")
