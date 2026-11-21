"""
Approval routing.  STUB (owner: Person B).

Pure function: DraftBill + users + policies in, ordered list[ApprovalStep] out.
Policies are read from the repository (admin-editable), never hard-coded.

Rules (approval_policies.csv, docs/HACKATHON_PLAN.md §2):
- P01–P04 amount tiers on total_cad
- P05 extra finance step for new/pending vendors; P06 Legal category
- P07 requester == approver → escalate to their manager (set escalated_from)
- P08 approver on leave → delegate (set delegated_from). U012 is on leave with delegate U003, who is also the
  finance manager: one person must not fill two steps, so escalate to the controller.
- terminated users (U015) can't approve; approval_limit_cad must cover the amount at each step
"""
from __future__ import annotations

from app.reference.repository import ReferenceRepository
from app.shared.schemas import ApprovalStep, DraftBill


def route(draft: DraftBill, repo: ReferenceRepository) -> list[ApprovalStep]:
    """Return the approval chain for `draft`, step 1 first."""
    raise NotImplementedError("controls.routing is owned by Person B")
