"""
Learn from the clerk: an accepted or overridden line coding on an app bill feeds the next suggestion.

Owner: Person A. Called from app/services/bills.code_line, and replayed from the database at start-up
(app/main.py), so a restart keeps what clerks taught (see docs/ISSUES_FOR_DB.md).
Input: the bill and the line just coded (database rows). Effect: one Correction in the in-memory store
(coding/history_index.py), so the next bill from that vendor with a similar line gets this coding,
and its reason names the bill the clerk corrected.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coding.history_index import Correction, forget_corrections, learn
from app.db import models

log = logging.getLogger(__name__)


def learn_from_line(bill: models.Bill, line: models.BillLine) -> bool:
    """True if the line taught something (a vendor, a final coding, accepted or overridden)."""
    if not bill.vendor_id or line.coding_status not in ("accepted", "overridden"):
        return False
    if not (line.gl_account and line.department_id):
        return False
    learn(Correction(vendor_id=bill.vendor_id, description=line.description, gl_account=line.gl_account,
                     department_id=line.department_id, bill_id=bill.bill_id,
                     overridden=line.coding_status == "overridden"))
    return True


def replay_learned_codings(db: Session) -> int:
    """Rebuild the learned corrections from the database: every accepted or overridden line on an app bill.

    The in-memory store is only a cache of these rows, so this makes it the same after a restart as before.
    Returns how many were learned.
    """
    forget_corrections()
    rows = db.execute(select(models.Bill, models.BillLine)
                      .join(models.BillLine, models.BillLine.bill_id == models.Bill.bill_id)
                      .where(models.Bill.origin == "app",
                             models.BillLine.coding_status.in_(("accepted", "overridden")))
                      .order_by(models.Bill.bill_id, models.BillLine.line_no))
    return sum(learn_from_line(bill, line) for bill, line in rows)


def replay_on_startup(app) -> None:
    """Start-up hook: replay learned codings on the app's database (honours test dependency overrides).
    A missing or unmigrated database is logged and skipped, never a reason not to start."""
    from app.db.database import get_session

    dep = app.dependency_overrides.get(get_session, get_session)
    gen = dep()
    try:
        db = next(gen)
        log.info("replayed %d learned codings", replay_learned_codings(db))
    except Exception as exc:  # e.g. a fresh checkout before `alembic upgrade head`
        log.warning("learned codings not replayed: %s", exc)
    finally:
        gen.close()
