"""
Back-fill tests: every history bill gets one point-in-time controls run, nothing else about the history changes,
a second run adds nothing, one audit event is written per run that replayed something, and the CLI refuses --all
once runs exist.

Each test seeds a fresh SQLite file (tmp_path) from the real dataset. No network, no repo files.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.controls.engine import run_controls
from app.controls.history import replay_bill
from app.controls.refdata import bill_from_history
from app.db import models
from app.db.audit import SYSTEM_ACTOR, verify_chain
from app.db.backfill import BACKFILL_ACTION, BackfillReport, backfill_history_controls, main
from app.db.bills import create_bill_from_draft
from app.db.database import as_write_engine
from app.db.refdata_db import refdata_from_db
from app.db.seed import seed_all
from app.shared.schemas import SourceInfo
from tests.conftest import DATASET

HISTORY_BILLS = 426
SELF_APPROVED_BY_U010 = ("AP-00092", "AP-00178", "AP-00235")

# ---------------------------------------------------------------- fixtures and helpers


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    """The migrated test database, loaded with the real dataset (seed_all commits)."""
    with Session(as_write_engine(migrated_engine)) as s:
        seed_all(s, DATASET)
    return migrated_engine


@pytest.fixture
def ws(seeded: Engine) -> Iterator[Session]:
    """Write session (BEGIN IMMEDIATE) on the seeded database."""
    with Session(as_write_engine(seeded)) as s:
        yield s


def runs_by_bill(session: Session) -> dict[str, list[models.ControlsRun]]:
    """Every controls run, grouped by bill id, in version order."""
    out: dict[str, list[models.ControlsRun]] = {}
    for run in session.scalars(select(models.ControlsRun).order_by(models.ControlsRun.bill_id,
                                                                   models.ControlsRun.version)):
        out.setdefault(run.bill_id, []).append(run)
    return out


def latest_result(session: Session, bill_id: str) -> dict:
    """result_json of a bill's latest controls run."""
    return session.scalars(select(models.ControlsRun.result_json).where(models.ControlsRun.bill_id == bill_id)
                           .order_by(models.ControlsRun.version.desc())).first()


def flag_codes(session: Session, bill_id: str) -> set[str]:
    """Flag codes of a bill's latest controls run."""
    return {f["code"] for f in latest_result(session, bill_id)["flags"]}


def history_checksums(session: Session) -> dict[str, str]:
    """sha256 over every column of every history bill, approval decision and payment, in primary-key order."""
    queries = {
        "bills": "SELECT * FROM bills WHERE origin = 'history' ORDER BY bill_id",
        "approval_decisions": "SELECT * FROM approval_decisions ORDER BY 1",
        "payments": "SELECT * FROM payments ORDER BY 1",
    }
    return {name: hashlib.sha256(repr(session.execute(text(sql)).all()).encode()).hexdigest()
            for name, sql in queries.items()}


def backfill_events(session: Session) -> list[models.AuditEvent]:
    """The controls.backfilled audit events, oldest first."""
    return list(session.scalars(select(models.AuditEvent).where(models.AuditEvent.action == BACKFILL_ACTION)
                                .order_by(models.AuditEvent.seq)))


def add_app_copy(session: Session, invoice_id: str) -> str:
    """Create an app bill that repeats history invoice `invoice_id` one day earlier; returns its bill id."""
    ref = refdata_from_db(session)
    draft = bill_from_history(ref, invoice_id)
    draft = draft.model_copy(update={"invoice_date": draft.invoice_date - timedelta(days=1),
                                     "source": SourceInfo(file_name="copy.pdf", file_hash="sha256:copy")})
    return create_bill_from_draft(session, draft, created_by="U005", received_date=date(2026, 10, 30)).bill_id


# ---------------------------------------------------------------- 1. one run per history bill


def test_every_history_bill_gets_exactly_one_version_1_run_and_app_bills_are_untouched(ws: Session) -> None:
    app_bill = add_app_copy(ws, "AP-00100")

    report = backfill_history_controls(ws)

    runs = runs_by_bill(ws)
    history = set(ws.scalars(select(models.Bill.bill_id).where(models.Bill.origin == "history")))
    assert len(history) == HISTORY_BILLS
    assert (report.replayed, report.skipped) == (HISTORY_BILLS, 0)
    assert set(runs) == history  # the app bill has no run
    assert app_bill not in runs
    assert all([r.version for r in bill_runs] == [1] for bill_runs in runs.values())


def test_app_bills_are_invisible_to_the_replay(ws: Session) -> None:
    """A history bill can't have known about an app bill, even one with an earlier invoice date."""
    app_bill = add_app_copy(ws, "AP-00100")

    # Unfiltered, the replay of AP-00100 sees the app copy (dated a day earlier) and matches it.
    unfiltered = replay_bill(refdata_from_db(ws), "AP-00100")
    assert app_bill in {m.matched_invoice_id for m in unfiltered.duplicates}

    backfill_history_controls(ws)
    for bill_runs in runs_by_bill(ws).values():
        assert app_bill not in {m["matched_invoice_id"] for m in bill_runs[-1].result_json["duplicates"]}


def test_backfill_never_commits(ws: Session) -> None:
    backfill_history_controls(ws)
    ws.rollback()

    assert ws.scalar(select(func.count()).select_from(models.ControlsRun)) == 0
    assert backfill_events(ws) == []


def test_backfill_requires_a_write_session(seeded: Engine) -> None:
    with Session(seeded) as read_session, pytest.raises(RuntimeError, match="requires a write session"):
        backfill_history_controls(read_session)


# ---------------------------------------------------------------- 2. idempotent


def test_second_call_replays_nothing(ws: Session) -> None:
    backfill_history_controls(ws)
    second = backfill_history_controls(ws)

    assert (second.replayed, second.skipped) == (0, HISTORY_BILLS)
    assert ws.scalar(select(func.count()).select_from(models.ControlsRun)) == HISTORY_BILLS
    assert second.route_mismatches == [] and second.flags_by_severity == {"block": 0, "warn": 0, "info": 0}


# ---------------------------------------------------------------- 3. point in time


def test_duplicate_is_flagged_on_the_later_invoice_only(ws: Session) -> None:
    """AP-00394 and AP-00407 are the same invoice (both dated 2026-10-03; ties go by invoice id)."""
    report = backfill_history_controls(ws)

    later = latest_result(ws, "AP-00407")
    assert "DUPLICATE_EXACT" in {f["code"] for f in later["flags"]}
    assert {m["matched_invoice_id"] for m in later["duplicates"]} == {"AP-00394"}
    earlier = latest_result(ws, "AP-00394")
    assert earlier["duplicates"] == []
    assert not {"DUPLICATE_EXACT", "DUPLICATE_LIKELY"} & flag_codes(ws, "AP-00394")
    assert "AP-00407" in report.flagged_bills["DUPLICATE_EXACT"]
    assert "AP-00394" not in report.flagged_bills["DUPLICATE_EXACT"]


def test_every_duplicate_match_points_to_an_earlier_invoice(ws: Session) -> None:
    backfill_history_controls(ws)
    order = {b: (d, b) for b, d in ws.execute(select(models.Bill.bill_id, models.Bill.invoice_date))}

    matches = 0
    for bill_id, bill_runs in runs_by_bill(ws).items():
        for match in bill_runs[-1].result_json["duplicates"]:
            if match["matched_invoice_id"]:
                matches += 1
                assert order[match["matched_invoice_id"]] < order[bill_id], (bill_id, match)
    assert matches > 0


# ---------------------------------------------------------------- 4. known findings


def test_no_v004_bill_postdates_the_unverified_bank_change(ws: Session) -> None:
    """BC-009 (V004, email request, not called back) was requested on 2026-10-27. The last V004 history invoice,
    AP-00426, is dated 2026-10-24, so as of its own date the change hadn't happened and no history bill carries
    BANK_CHANGE_UNVERIFIED. Evaluated against today's data, AP-00426 does carry it."""
    change = ws.get(models.BankChangeRequest, "BC-009")
    assert (change.vendor_id, change.status, change.requested_at.date()) == ("V004", "pending_verification",
                                                                             date(2026, 10, 27))
    v004 = ws.execute(select(models.Bill.bill_id, models.Bill.invoice_date)
                      .where(models.Bill.vendor_id == "V004", models.Bill.origin == "history")
                      .order_by(models.Bill.invoice_date.desc())).first()
    assert tuple(v004) == ("AP-00426", date(2026, 10, 24))

    report = backfill_history_controls(ws)

    assert report.flagged_bills["BANK_CHANGE_UNVERIFIED"] == []
    assert "BANK_CHANGE_UNVERIFIED" not in flag_codes(ws, "AP-00426")
    ref = refdata_from_db(ws)
    today = run_controls(bill_from_history(ref, "AP-00426"), ref=ref)
    assert "BANK_CHANGE_UNVERIFIED" in {f.code for f in today.flags}


def test_self_approvals_by_u010_are_route_mismatches(ws: Session) -> None:
    """U010 approved bills they requested; P07 sends those to their manager U001 instead."""
    report = backfill_history_controls(ws)

    mismatches = {m.bill_id: m for m in report.route_mismatches}
    for bill_id in SELF_APPROVED_BY_U010:
        assert bill_id in mismatches, bill_id
        assert mismatches[bill_id].recorded_approvers == ["U010"]
        assert mismatches[bill_id].missing == ["U001"]
        assert "P07" in mismatches[bill_id].expected_steps[0]


# ---------------------------------------------------------------- 5. history unchanged


def test_history_statuses_decisions_and_payments_are_unchanged(ws: Session) -> None:
    before = history_checksums(ws)

    backfill_history_controls(ws)
    backfill_history_controls(ws, only_missing=False)

    assert history_checksums(ws) == before


# ---------------------------------------------------------------- 6. audit


def test_one_audit_event_per_call_that_replayed_something(ws: Session) -> None:
    report = backfill_history_controls(ws)
    backfill_history_controls(ws)  # replays nothing: no event

    events = backfill_events(ws)
    assert len(events) == 1
    event = events[0]
    assert (event.actor_user_id, event.actor_role, event.entity_type, event.entity_id) == (SYSTEM_ACTOR, "system",
                                                                                          "system", "history")
    assert event.after_json["replayed"] == report.replayed == HISTORY_BILLS
    assert event.after_json["route_mismatches"] == len(report.route_mismatches)
    assert verify_chain(ws).ok


# ---------------------------------------------------------------- report


def test_report_format_lists_counts_and_watched_codes(ws: Session) -> None:
    report = backfill_history_controls(ws)
    out = report.format()

    assert out.startswith(f"replayed {HISTORY_BILLS} history bill(s), skipped 0")
    for code in ("DUPLICATE_EXACT", "ALREADY_PAID_BY_CARD", "BANK_CHANGE_UNVERIFIED", "POSSIBLE_SPLIT"):
        assert code in out
    assert len(report.top_flag_codes) <= 10
    assert sum(report.flags_by_severity.values()) >= max(n for _, n in report.top_flag_codes)
    assert BackfillReport().format() == "replayed 0 history bill(s), skipped 0 that already had a run"


# ---------------------------------------------------------------- 7. CLI


def test_cli_backfills_then_refuses_all(seeded: Engine, db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--database-url", db_url]) == 0
    assert f"replayed {HISTORY_BILLS} history bill(s)" in capsys.readouterr().out

    assert main(["--database-url", db_url, "--all"]) == 2
    assert "refusing --all" in capsys.readouterr().err

    assert main(["--database-url", db_url]) == 0
    assert f"replayed 0 history bill(s), skipped {HISTORY_BILLS}" in capsys.readouterr().out
    with Session(seeded) as s:
        assert s.scalar(select(func.count()).select_from(models.ControlsRun)) == HISTORY_BILLS
        assert len(backfill_events(s)) == 1


def test_cli_all_runs_on_a_database_without_runs(seeded: Engine, db_url: str) -> None:
    assert main(["--database-url", db_url, "--all"]) == 0
    with Session(seeded) as s:
        assert s.scalar(select(func.count()).select_from(models.ControlsRun)) == HISTORY_BILLS


def test_cli_refuses_an_unseeded_database(migrated_engine: Engine, db_url: str,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--database-url", db_url]) == 2
    assert "no history bills" in capsys.readouterr().err
