"""
Run every control on one DraftBill → ControlsResult.  STUB (owner: Person B).

This is the single entry point the API calls after extraction. Expected shape:
    flags = validate(draft, repo) + flags derived from find_duplicates(draft, repo)
    route = route(draft, repo)
    can_auto_proceed = no BLOCK flag
    recommendation = plain-English summary built from the flags (bonus feature)
"""
from __future__ import annotations

from app.reference.repository import ReferenceRepository
from app.shared.schemas import ControlsResult, DraftBill


def run_controls(draft: DraftBill, repo: ReferenceRepository) -> ControlsResult:
    raise NotImplementedError("controls.engine is owned by Person B")
