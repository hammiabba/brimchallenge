"""
Object-level permission rules for approving and releasing payments.  STUB (owner: Person B).

Pure functions returning PermissionDecision(allowed, reason). The API layer turns
allowed=False into HTTP 403 and shows the reason.

Rules:
- can_approve: the user must be the step's assignee (or their recorded delegate), active, within
  approval_limit_cad, and not the requester (P07).
- can_release: finance_manager up to $100k, controller_admin above (P09–P10); anyone who approved the invoice
  can never release its payment (P11); blocked while any BLOCK flag is open (bank mismatch, unverified bank
  change, duplicate).
"""
from __future__ import annotations

from app.reference.repository import ReferenceRepository
from app.shared.schemas import ApprovalStep, DraftBill, Flag, PermissionDecision


def can_approve(user_id: str, draft: DraftBill, route: list[ApprovalStep], step_no: int,
                repo: ReferenceRepository) -> PermissionDecision:
    """May `user_id` act on approval step `step_no` of `draft`?"""
    raise NotImplementedError("controls.permissions is owned by Person B")


def can_release(user_id: str, payment: dict, approval_chain: list[ApprovalStep], open_flags: list[Flag],
                repo: ReferenceRepository) -> PermissionDecision:
    """May `user_id` release `payment` (a payments.csv-shaped dict) given who approved the invoice?"""
    raise NotImplementedError("controls.permissions is owned by Person B")
