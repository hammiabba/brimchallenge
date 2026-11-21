"""
Duplicate detection.  STUB (owner: Person B).

Pure function: DraftBill + history in, list[DuplicateMatch] out, each with a score and reasons.

Kinds and known cases (docs/HACKATHON_PLAN.md §4):
- exact: same vendor + invoice number (Invoice 000961.pdf, cloudbarnsoftwar_INV01561.pdf, harlowsternllp_001468.pdf)
- normalized: strip prefixes/leading zeros/punctuation ("583" == "FA-000583", brightlinesafety-inv-032.pdf)
- near: same vendor, amount within ~1%, date within ~14 days ("000903-A" vs "000903", voyageurcorporat-inv-017.pdf)
- cross_vendor: same amount + bank account under a lookalike vendor record
- card_paid: card_transactions merchant (fuzzy) + amount_cad + date window (Cloudbarn INV-01561)
Avoid false positives: fixed monthly contracts (Invoice 002935.pdf, Queen St rent $18,758) bill the same amount
every month. Require invoice-number similarity or the same service period too.
"""
from __future__ import annotations

from app.reference.repository import ReferenceRepository
from app.shared.schemas import DraftBill, DuplicateMatch


def find_duplicates(draft: DraftBill, repo: ReferenceRepository) -> list[DuplicateMatch]:
    """Return candidate duplicates of `draft` in history and card transactions, highest score first."""
    raise NotImplementedError("controls.duplicates is owned by Person B")
