"""run_controls(bill, batch) -> ControlsResult: the one call Person A / the backend needs."""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from app.shared.schemas import ControlsResult, DraftBill, Severity

from .approvals import route
from .duplicates import duplicate_flags, find_duplicates, find_split
from .refdata import RefData, default_refdata
from .validate import validate
from .wording import flag_titles


def run_controls(bill: DraftBill, batch: Iterable[DraftBill] = (), ref: RefData | None = None) -> ControlsResult:
    """Runs every check on one bill.

    batch: the other bills that arrived with this one (it may include `bill` itself). They are
    checked for duplicates and splits alongside history.
    """
    ref = ref or default_refdata()
    batch = list(batch)

    flags = validate(bill, ref)
    duplicates = find_duplicates(bill, ref, batch)
    flags += duplicate_flags(duplicates)

    split = find_split(bill, ref, batch)
    routed_amount = None
    if split:
        flags.append(split)
        routed_amount = Decimal(split.evidence["combined_cad"])  # route the group as one bill

    steps = route(bill, ref, flags, amount_cad=routed_amount)
    blocks = [f for f in flags if f.severity == Severity.BLOCK]
    return ControlsResult(
        flags=flags,
        duplicates=duplicates,
        route=steps,
        can_auto_proceed=not blocks,
        # The reason in a few words (the blocking flags' titles); each flag's own message is shown with the flag.
        recommendation=f"Hold until cleared: {flag_titles(f.code for f in blocks)}." if blocks else None,
    )
