"""Running controls on a stored bill, the one way every service does it.

Order matters (DB layer rules):
1. flush the session, so RefData sees edits made earlier in this transaction;
2. build RefData from the database on every call (cheap, never cached), passing the bill's own id as
   exclude_bill_id, or controls would flag the bill as a duplicate of itself and count its amount twice against
   PO and contract limits;
3. rebuild the current DraftBill, run controls, store the run (versioned; resolutions carry over when a flag is
   unchanged).
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.controls import RefData, run_controls
from app.db.bills import StoredControlsRun, latest_controls_run, load_draft_bill, save_controls_run
from app.db.refdata_db import refdata_from_db
from app.shared.schemas import ControlsResult, DraftBill, Flag

SPLIT_FLAG = "POSSIBLE_SPLIT"


def refdata_for(db: Session, bill_id: str) -> RefData:
    db.flush()
    return refdata_from_db(db, exclude_bill_id=bill_id)


def rerun(db: Session, bill_id: str, batch: Iterable[DraftBill] = ()) -> tuple[ControlsResult, int]:
    """Run controls on the bill as it is now and store the run. Returns (result, run_id)."""
    ref = refdata_for(db, bill_id)
    draft = load_draft_bill(db, bill_id)
    result = run_controls(draft, batch, ref=ref)
    return result, save_controls_run(db, bill_id, result)


def open_flags(stored: StoredControlsRun | None) -> list[Flag]:
    """Flags of the latest stored run that nobody has resolved or overridden, as controls.Flag objects. This is
    what can_release must see; result.flags would keep blocking on a flag someone already overrode."""
    if stored is None:
        return []
    return [Flag(code=f.code, severity=f.severity, message=f.message, evidence=f.evidence or {}, field=f.field)
            for f in stored.flags if f.resolution == "open"]


def open_blocking_codes(db: Session, bill_id: str) -> list[str]:
    return [f.code for f in open_flags(latest_controls_run(db, bill_id)) if f.severity == "block"]


def routed_amount(stored: StoredControlsRun | None) -> Decimal | None:
    """The amount the route was built for: the combined amount when controls saw a split, else None (the bill's)."""
    if stored is None:
        return None
    for f in stored.result.flags:
        if f.code == SPLIT_FLAG and "combined_cad" in f.evidence:
            return Decimal(str(f.evidence["combined_cad"]))
    return None
