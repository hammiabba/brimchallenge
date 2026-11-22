"""
Re-run the self-check after a clerk edits a bill, so confidence and warnings describe the bill as it now stands.

Called once from app/services/bills.update_header, after the edit is saved and before controls re-run, so they see it.

- A field the clerk set is human-confirmed: its confidence becomes 1.0 and the extraction warnings about
  it (an ambiguous date, a blank PO field, ...) are dropped.
- The arithmetic checks run again on the current values, replacing the old arithmetic warnings.
- Everything else keeps what extraction said.

The bill's draft_json holds the confidence and warnings that load_draft_bill (and so controls) reads. The
first recheck copies the values as extracted to draft_json["as_extracted"], so the original stays on record.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.db.audit import SYSTEM_ACTOR
from app.db.bills import load_draft_bill
from app.extraction import selfcheck
from app.shared.schemas import DraftBill

# Bill header columns (as PATCHed) → the DraftBill confidence key they confirm.
HEADER_TO_FIELD = {
    "vendor_id": "vendor", "vendor_invoice_number": "invoice_number", "invoice_date": "invoice_date",
    "due_date": "due_date", "po_id": "po_number", "ship_to_province": "ship_to_province",
}
# How extraction warnings about a field begin (see normalize.resolve_dates and pipeline.build_draft).
_WARNING_PREFIXES = {
    "invoice_date": ("invoice date ",), "due_date": ("due date ",),
    "po_number": ("PO field ",), "currency": ("currency ",),
}


def recheck(draft: DraftBill, confirmed: set[str]) -> tuple[dict[str, float], list[str]]:
    """New (field_confidence, extraction_warnings) for `draft` after the clerk confirmed `confirmed` fields."""
    _, arithmetic = selfcheck.check(draft)
    conf = {**draft.field_confidence, **{f: 1.0 for f in confirmed}}
    stale = tuple(p for f in confirmed for p in _WARNING_PREFIXES.get(f, ()))
    kept = [w for w in draft.extraction_warnings if not selfcheck.is_check_warning(w) and not w.startswith(stale)]
    return conf, kept + arithmetic


RECHECKED = "bill.rechecked"  # audit action: confidence and warnings recomputed after a clerk's edit


def recheck_bill(db: Session, bill: models.Bill, changes: dict) -> None:
    confirmed = {HEADER_TO_FIELD[k] for k in changes if k in HEADER_TO_FIELD}
    db.flush()  # load_draft_bill reads the edited columns
    conf, warnings = recheck(load_draft_bill(db, bill.bill_id), confirmed)
    snapshot = dict(bill.draft_json or {})
    before = {"field_confidence": snapshot.get("field_confidence", {}),
              "extraction_warnings": snapshot.get("extraction_warnings", [])}
    if "as_extracted" not in snapshot:  # written once, at the first re-check, and never overwritten
        snapshot["as_extracted"] = before
    snapshot["field_confidence"], snapshot["extraction_warnings"] = conf, warnings
    bill.draft_json = snapshot  # a new dict, so the JSON column is marked changed
    from app.services.events import record  # the API lane's audit helper; imported here to keep extraction light

    record(db, actor_user_id=SYSTEM_ACTOR, actor_role=SYSTEM_ACTOR, action=RECHECKED, entity_type="bill",
           entity_id=bill.bill_id, before=before,
           after={"field_confidence": conf, "extraction_warnings": warnings},
           comment=f"self-check re-run after an edit of: {', '.join(sorted(changes)) or 'nothing'}")
