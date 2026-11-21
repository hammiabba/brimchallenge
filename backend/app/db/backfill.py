"""
Back-fill controls runs for the history bills: what the controls engine would have said about each historical
invoice, judged as of its own date, stored like any other controls run.

Owner: DB team.

    cd backend && python -m app.db.backfill [--database-url URL] [--all]

Why: the seed loads 426 history bills without controls runs, so the UI would show them with no flags and no
approval route. This replays each one with Hamid's own controls.history.replay_bill (nothing is re-implemented) and
saves the result with bills.save_controls_run.

Point in time (controls.history.ref_as_of_invoice): each bill sees only invoices that came before it (by invoice
date, then invoice id), bank changes made before its invoice date, user leave/termination that had already started,
and its own received date as "today". Vendors, contracts, POs, policies and FX rates are today's. So a duplicate pair
or split group is flagged on its later bill only, and a bill dated before a bank change isn't flagged for it.

What it never touches: a history bill's status, its approval decisions and its payments. It only adds controls runs
(with their flags and route steps). App bills are neither replayed nor visible to the replay: the history bills
couldn't have known about them.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.controls.history import replay_bill
from app.controls.refdata import d
from app.db import models
from app.db.audit import SYSTEM_ACTOR, log_event
from app.db.bills import save_controls_run
from app.db.database import as_write_engine, make_engine, require_write_session, resolve_database_url
from app.db.refdata_db import refdata_from_db
from app.db.seed import migrate_to_head
from app.shared.schemas import ControlsResult

BACKFILL_ACTION = "controls.backfilled"
WATCHED_CODES = ("DUPLICATE_EXACT", "ALREADY_PAID_BY_CARD", "BANK_CHANGE_UNVERIFIED", "POSSIBLE_SPLIT")
TOP_CODES = 10


# ---------------------------------------------------------------- report


@dataclass(frozen=True)
class RouteMismatch:
    """A history bill whose recorded approvers don't cover the route its replay computes (as of its own date)."""

    bill_id: str
    expected_steps: list[str]  # "1 dept_manager U001 [P01, P07]"
    recorded_approvers: list[str]  # actor_user_id of each 'approved' decision, in step order
    missing: list[str]  # expected signers with no approval on record ("UNASSIGNED" for an unassigned step)


@dataclass
class BackfillReport:
    """What a back-fill did and what the replayed controls found. Informational only; nothing is changed by it."""

    replayed: int = 0
    skipped: int = 0
    flags_by_severity: dict[str, int] = field(default_factory=dict)  # flag count per severity
    top_flag_codes: list[tuple[str, int]] = field(default_factory=list)  # bills per code, most common first
    flagged_bills: dict[str, list[str]] = field(default_factory=dict)  # WATCHED_CODES -> bill ids
    route_mismatches: list[RouteMismatch] = field(default_factory=list)
    rejected_not_compared: int = 0  # rejected bills: a rejection ends the route, so approvals can't cover it

    def format(self) -> str:
        """Plain-text report for the CLI."""
        out = [f"replayed {self.replayed} history bill(s), skipped {self.skipped} that already had a run"]
        if not self.replayed:
            return "\n".join(out)
        out.append("flags by severity: " + ", ".join(f"{k} {v}" for k, v in self.flags_by_severity.items()))
        out.append(f"top {TOP_CODES} flag codes (bills carrying each):")
        out.extend(f"  {code:<26} {n}" for code, n in self.top_flag_codes)
        for code in WATCHED_CODES:
            ids = self.flagged_bills.get(code, [])
            out.append(f"{code} on {len(ids)} bill(s): {', '.join(ids) or 'none'}")
        out.append(f"route mismatches ({len(self.route_mismatches)}; recorded approvals vs the replayed route, "
                   f"{self.rejected_not_compared} rejected bill(s) not compared):")
        for m in self.route_mismatches:
            out.append(f"  {m.bill_id}: expected {'; '.join(m.expected_steps)} | approved by "
                       f"{', '.join(m.recorded_approvers) or 'nobody'} | missing {', '.join(m.missing)}")
        return "\n".join(out)


# ---------------------------------------------------------------- the back-fill


def _history_statuses(session: Session) -> dict[str, str]:
    """Status of every history bill except void ones, by bill id.

    A void bill isn't replayed: refdata_from_db leaves void bills out of the invoices, so there's nothing to replay.
    (The dataset has none; app actions might void one later.)
    """
    rows = session.execute(select(models.Bill.bill_id, models.Bill.status)
                           .where(models.Bill.origin == "history", models.Bill.status != "void"))
    return {bill_id: status for bill_id, status in rows}


def _bills_with_runs(session: Session) -> set[str]:
    """Bill ids that already have at least one controls run."""
    return set(session.scalars(select(models.ControlsRun.bill_id).distinct()))


def _approvals(session: Session, bill_ids: set[str]) -> dict[str, list[str]]:
    """Per bill, the users who approved it (decision 'approved'), in step order, from approval_decisions."""
    rows = session.execute(select(models.ApprovalDecision.bill_id, models.ApprovalDecision.actor_user_id)
                           .where(models.ApprovalDecision.decision == "approved")
                           .order_by(models.ApprovalDecision.bill_id, models.ApprovalDecision.step_no))
    out: dict[str, list[str]] = defaultdict(list)
    for bill_id, actor in rows:
        if bill_id in bill_ids:
            out[bill_id].append(actor)
    return out


def _route_mismatch(bill_id: str, result: ControlsResult, approvers: list[str]) -> RouteMismatch | None:
    """A RouteMismatch when some step of the replayed route has no approval by its signer on record, else None.

    A step is covered when its assigned user approved the bill (any step: history records the signer, and steps
    can be numbered differently). An unassigned step can never be covered.
    """
    recorded = set(approvers)
    missing = [step.user_id for step in result.route if step.user_id not in recorded]
    if not missing:
        return None
    expected = [f"{s.step_no} {s.role} {s.user_id} [{', '.join(s.policy_ids)}]" for s in result.route]
    return RouteMismatch(bill_id=bill_id, expected_steps=expected, recorded_approvers=approvers, missing=missing)


def backfill_history_controls(session: Session, *, only_missing: bool = True) -> BackfillReport:
    """Replay every history bill as of its own date and store the result as a controls run. Never commits.

    Requires a write session. With only_missing (the default) bills that already have a run are skipped, so a second
    call adds nothing. When anything was replayed, writes one audit event (controls.backfilled, actor "system")
    with the counts. Statuses, approval decisions and payments are never changed.
    """
    require_write_session(session, "backfill_history_controls")
    statuses = _history_statuses(session)
    history_ids = set(statuses)
    already = _bills_with_runs(session) if only_missing else set()

    # One RefData for the whole replay, limited to history bills: a history bill can't have known about app bills.
    ref = refdata_from_db(session)
    ref = replace(ref, invoices={k: v for k, v in ref.invoices.items() if k in history_ids},
                  invoice_lines={k: v for k, v in ref.invoice_lines.items() if k in history_ids})

    # Same order as controls.history.replay (invoice date, then id); each replay is independent of the order.
    order = sorted(history_ids, key=lambda i: (d(ref.invoices[i]["invoice_date"]), i))
    report = BackfillReport()
    severity: Counter = Counter()
    bills_per_code: Counter = Counter()
    flagged: dict[str, list[str]] = {code: [] for code in WATCHED_CODES}
    approvals = _approvals(session, history_ids)

    for bill_id in order:
        if bill_id in already:
            report.skipped += 1
            continue
        result = replay_bill(ref, bill_id)
        save_controls_run(session, bill_id, result)
        report.replayed += 1
        codes = {f.code for f in result.flags}
        severity.update(f.severity.value for f in result.flags)
        bills_per_code.update(codes)
        for code in WATCHED_CODES:
            if code in codes:
                flagged[code].append(bill_id)
        if statuses.get(bill_id) == "rejected":
            report.rejected_not_compared += 1
        elif (mismatch := _route_mismatch(bill_id, result, approvals.get(bill_id, []))) is not None:
            report.route_mismatches.append(mismatch)

    report.flags_by_severity = {s: severity[s] for s in ("block", "warn", "info")}
    report.top_flag_codes = bills_per_code.most_common(TOP_CODES)
    report.flagged_bills = flagged
    if report.replayed:
        log_event(session, actor_user_id=SYSTEM_ACTOR, actor_role="system", action=BACKFILL_ACTION,
                  entity_type="system", entity_id="history",
                  after={"replayed": report.replayed, "skipped": report.skipped, "only_missing": only_missing,
                         "flags_by_severity": report.flags_by_severity,
                         "route_mismatches": len(report.route_mismatches)})
    return report


# ---------------------------------------------------------------- command line


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Exit codes: 0 done, 2 refused (no history bills, or --all on a database that has runs)."""
    parser = argparse.ArgumentParser(
        prog="python -m app.db.backfill",
        description="Store a controls run for every history bill, judged as of its own date (seed the database first).")
    parser.add_argument("--database-url", help="database to back-fill (default: DATABASE_URL / settings)")
    parser.add_argument("--all", action="store_true",
                        help="replay every history bill, not only those without a run. Refused if any history bill "
                             "already has a run: replaying it again would add a version-2 run next to the first.")
    args = parser.parse_args(argv)

    url = resolve_database_url(args.database_url or get_settings().database_url)
    started = time.perf_counter()
    migrate_to_head(url)  # as the seed does: a database at an older revision is brought up to date first
    engine = make_engine(url)
    try:
        # A write session on the chosen URL (the process-wide factory is bound to DATABASE_URL, which
        # --database-url may override).
        with Session(as_write_engine(engine)) as session:
            history = set(_history_statuses(session))
            if not history:
                print("refusing: no history bills found; run python -m app.db.seed first", file=sys.stderr)
                return 2
            if args.all and history & _bills_with_runs(session):
                print("refusing --all: some history bills already have a controls run, and replaying them would add "
                      "version-2 runs. Run without --all to fill in only the missing ones.", file=sys.stderr)
                return 2
            report = backfill_history_controls(session, only_missing=not args.all)
            session.commit()
    finally:
        engine.dispose()
    print(report.format())
    print(f"\nBack-filled {url} in {time.perf_counter() - started:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
