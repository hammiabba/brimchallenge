"""
Learn from the clerk: an accepted or overridden line coding on an app bill feeds the next suggestion.

Owner: Person A. Called once from app/services/bills.code_line (see docs/ISSUES_FOR_DB.md).
Input: the bill and the line just coded (database rows). Effect: one Correction in the in-memory store
(coding/history_index.py), so the next bill from that vendor with a similar line gets this coding,
and its reason names the bill the clerk corrected.
"""
from __future__ import annotations

from app.coding.history_index import Correction, learn
from app.db import models


def learn_from_line(bill: models.Bill, line: models.BillLine) -> None:
    if not bill.vendor_id or line.coding_status not in ("accepted", "overridden"):
        return
    if not (line.gl_account and line.department_id):
        return
    learn(Correction(vendor_id=bill.vendor_id, description=line.description, gl_account=line.gl_account,
                     department_id=line.department_id, bill_id=bill.bill_id,
                     overridden=line.coding_status == "overridden"))
