"""Small checks shared by the write services.

Concurrency model: every write runs in a write session (BEGIN IMMEDIATE), which takes SQLite's write lock at the
first statement and holds it until commit. A service's read-check-write sequence therefore can't interleave with
another writer, so state checks like "status is still scheduled" are race-free. Bills additionally carry
row_version: the client sends the version it last saw, and a mismatch is a 409, so a user never overwrites a change
they didn't see.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.controls.wording import status_label


def check_row_version(current: int, expected: int, what: str = "record") -> None:
    if current != expected:
        raise ApiError(409, "conflict.stale",
                       f"This {what} changed since you loaded it (version {expected}, now {current}). Reload it.",
                       {"expected_row_version": expected, "current_row_version": current})


def invalid_state(what: str, status: str, allowed: tuple[str, ...] | str) -> ApiError:
    # The message words the statuses ("This bill needs review; it must be approved."); the details keep the codes.
    wanted = [allowed] if isinstance(allowed, str) else list(allowed)
    allowed_text = " or ".join(status_label(a) for a in wanted)
    current = "needs review" if status == "needs_review" else f"is {status_label(status)}"
    message = f"This {what.replace('_', ' ')} {current}; it must be {allowed_text}."
    return ApiError(409, f"{what}.invalid_state", message,
                    {"status": status, "allowed": allowed if isinstance(allowed, str) else list(allowed)})


def next_id(db: Session, column, prefix: str, width: int) -> str:
    """Next id in a dataset-style sequence, e.g. next_id(db, Vendor.vendor_id, "V", 3) -> "V057".
    Safe without a retry because the caller holds the write lock."""
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    numbers = (int(m.group(1)) for v in db.scalars(select(column).where(column.like(f"{prefix}%")))
               if (m := pattern.match(v)))
    return f"{prefix}{max(numbers, default=0) + 1:0{width}d}"
