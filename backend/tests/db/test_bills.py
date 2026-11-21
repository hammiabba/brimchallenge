"""
Bill persistence tests: a DraftBill goes in as an app bill and comes back out as the current DraftBill; controls runs
are stored per version with flag resolutions carried over; the helpers never commit and never write audit events.

Each test seeds a fresh SQLite file (tmp_path) from the real dataset. No network, no repo files.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from app.db import models
from app.db.bills import (
    approver_ids_for_bill,
    create_bill_from_draft,
    latest_controls_run,
    load_draft_bill,
    next_bill_id,
    route_for_bill,
    save_controls_run,
)
from app.db.database import as_write_engine
from app.db.seed import seed_all
from app.db.types import utcnow
from app.shared.schemas import (
    ApprovalStep,
    BankDetails,
    CodingSuggestion,
    ControlsResult,
    DraftBill,
    Flag,
    InvoiceLine,
    MatchMethod,
    Severity,
    SourceInfo,
    TaxCode,
    TaxLine,
    VendorOnInvoice,
)
from tests.conftest import DATASET

# ---------------------------------------------------------------- fixtures


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    """The migrated test database, loaded with the real dataset."""
    with Session(as_write_engine(migrated_engine)) as s:
        seed_all(s, DATASET)
    return migrated_engine


@pytest.fixture
def ws(seeded: Engine) -> Iterator[Session]:
    """Write session (BEGIN IMMEDIATE) on the seeded database."""
    with Session(as_write_engine(seeded)) as s:
        yield s


@pytest.fixture
def rs(seeded: Engine) -> Iterator[Session]:
    """Read session (plain BEGIN) on the seeded database."""
    with Session(seeded) as s:
        yield s


def harlow_draft(**changes: object) -> DraftBill:
    """The example DraftBill from schemas.py (Harlow and Stern, V052 / U013 / D01), with coding on both lines."""
    draft = DraftBill(
        source=SourceInfo(email_id="EM-026", sender_address="ar@harlowandstern-llp.example",
                          file_name="Invoice HA26-2766.pdf", file_hash="sha256:harlow-test"),
        vendor=VendorOnInvoice(name_on_invoice="Harlow and Stern LLP", gst_number="503486760RT0001",
                               bank=BankDetails(institution="010", transit="40238", account="593014216"),
                               vendor_id="V052", match_method=MatchMethod.GST_NUMBER, match_score=1.0),
        invoice_number="HA26-2766", invoice_date=date(2026, 10, 27), due_date=date(2026, 11, 26),
        ship_to_province="ON", department_id="D01", requester_user_id="U013",
        lines=[
            InvoiceLine(line_no=1, description="Legal services - Commercial lease review", quantity=Decimal("12"),
                        unit_price=Decimal("450.00"), amount=Decimal("5400.00"),
                        coding=CodingSuggestion(gl_account="6310", department_id="D01", confidence=0.9,
                                                reason="6310 Legal: 3 of 3 past lines from this vendor")),
            InvoiceLine(line_no=2, description="Disbursements and filing fees", quantity=Decimal("1"),
                        unit_price=Decimal("310.00"), amount=Decimal("310.00"),
                        coding=CodingSuggestion(gl_account="6310", department_id="D01", confidence=0.62,
                                                reason="6310 Legal: vendor default GL")),
        ],
        subtotal=Decimal("5710.00"),
        taxes=[TaxLine(code=TaxCode.HST13, rate=Decimal("0.13"), amount=Decimal("742.30"))],
        total=Decimal("6452.30"), total_cad=Decimal("6452.30"),
        field_confidence={"invoice_number": 0.95, "total": 0.95}, extraction_warnings=["sample warning"],
    )
    return draft.model_copy(update=changes) if changes else draft


def _create(session: Session, draft: DraftBill | None = None):
    """create_bill_from_draft with fixed creator and received date."""
    return create_bill_from_draft(session, draft or harlow_draft(), created_by="U004", received_date=date(2026, 10, 28))


def controls_result(*, evidence: dict | None = None, step1_user: str = "U007",
                    severity: Severity = Severity.BLOCK) -> ControlsResult:
    """A small ControlsResult: a VENDOR_LOOKALIKE flag (block unless `severity` says otherwise, with Decimal
    evidence), an info flag, and a two-step route."""
    if evidence is None:
        evidence = {"similar_vendor": "V026", "total": Decimal("6452.30")}
    return ControlsResult(
        flags=[
            Flag(code="VENDOR_LOOKALIKE", severity=severity, message="looks like V026", field="vendor",
                 evidence=evidence),
            Flag(code="CREDIT_NOTE", severity=Severity.INFO, message="info", field="total", evidence={}),
        ],
        duplicates=[],
        route=[
            ApprovalStep(step_no=1, role="dept_manager", user_id=step1_user, policy_ids=["P01"], reason="<= $10,000"),
            ApprovalStep(step_no=2, role="finance_manager", user_id="U003", policy_ids=["P06"], reason="Legal"),
        ],
        can_auto_proceed=False, recommendation="Hold: looks like V026",
    )


def _count(session: Session, model: type, **where: object) -> int:
    query = select(func.count()).select_from(model)
    for column, value in where.items():
        query = query.where(getattr(model, column) == value)
    return session.scalar(query)


def test_fixture_ids_exist_in_the_seeded_database(rs: Session) -> None:
    assert rs.get(models.Vendor, "V052").legal_name == "Harlow and Stern LLP"
    assert rs.get(models.User, "U013") is not None and rs.get(models.Department, "D01") is not None
    assert rs.get(models.GlAccount, "6310") is not None


# ---------------------------------------------------------------- 1. ids and defaults


def test_first_app_bills_continue_the_history_numbering(ws: Session) -> None:
    assert next_bill_id(ws) == "AP-00427"
    first, second = _create(ws), _create(ws)
    assert (first.bill_id, second.bill_id) == ("AP-00427", "AP-00428")
    for bill_id in (first.bill_id, second.bill_id):
        bill = ws.get(models.Bill, bill_id)
        assert (bill.origin, bill.status, bill.row_version) == ("app", "needs_review", 1)
        assert bill.norm_invoice_number == "262766" and bill.created_by == "U004"


# ---------------------------------------------------------------- 2. round trip


def test_round_trip_returns_the_original_draft(ws: Session) -> None:
    draft = harlow_draft()
    created = _create(ws, draft)
    assert created.warnings == []
    assert load_draft_bill(ws, created.bill_id).model_dump(mode="json") == draft.model_dump(mode="json")
    stored = ws.get(models.Bill, created.bill_id)
    assert stored.draft_json == draft.model_dump(mode="json")
    lines = ws.scalars(select(models.BillLine).where(models.BillLine.bill_id == created.bill_id)
                       .order_by(models.BillLine.line_no))
    assert [(ln.coding_status, ln.gl_account, ln.suggested_gl_account) for ln in lines] == [
        ("suggested", None, "6310"), ("suggested", None, "6310")]


# ---------------------------------------------------------------- 3. bad references


def test_bad_references_are_stored_as_null_with_warnings(ws: Session) -> None:
    created = _create(ws, harlow_draft(po_number="PO-2026-9999", requester_user_id="U999", department_id="D99"))
    bill = ws.get(models.Bill, created.bill_id)
    assert (bill.po_id, bill.requester_user_id, bill.department_id) == (None, None, None)
    assert created.warnings == [
        "department_id 'D99' not found; stored as NULL",
        "requester_user_id 'U999' not found; stored as NULL",
        "po_number 'PO-2026-9999' not found; stored as NULL",
    ]
    assert (bill.draft_json["po_number"], bill.draft_json["requester_user_id"], bill.draft_json["department_id"]) == (
        "PO-2026-9999", "U999", "D99")


def test_unknown_vendor_and_non_canadian_province_are_also_kept_out(ws: Session) -> None:
    vendor = harlow_draft().vendor.model_copy(update={"vendor_id": "V999"})
    created = _create(ws, harlow_draft(vendor=vendor, ship_to_province="Ontario", contract_id="C999"))
    bill = ws.get(models.Bill, created.bill_id)
    assert (bill.vendor_id, bill.ship_to_province, bill.contract_id) == (None, None, None)
    assert len(created.warnings) == 3


def test_a_currency_the_schema_cannot_store_is_refused_clearly(ws: Session) -> None:
    with pytest.raises(ValueError, match="EUR"):
        _create(ws, harlow_draft(currency="EUR"))


# ---------------------------------------------------------------- 4. money precision


def test_money_with_three_decimals_is_rounded_half_up_with_a_warning(ws: Session) -> None:
    lines = harlow_draft().lines
    lines = [lines[0].model_copy(update={"amount": Decimal("5400.125")}), lines[1]]
    created = _create(ws, harlow_draft(subtotal=Decimal("5710.005"), lines=lines))
    bill = ws.get(models.Bill, created.bill_id)
    assert bill.subtotal_cents == 571_001
    line1 = ws.get(models.BillLine, (created.bill_id, 1))
    assert line1.amount_cents == 540_013
    assert created.warnings == [
        "subtotal 5710.005 has more than 2 decimal places; stored as 5710.01",
        "lines[1].amount 5400.125 has more than 2 decimal places; stored as 5400.13",
    ]
    assert bill.draft_json["subtotal"] == "5710.005"  # the snapshot keeps what the document said


def test_usd_fx_rate_date_is_set_only_when_the_table_rate_matches(ws: Session) -> None:
    rate = Decimal(ws.scalar(select(models.FxRate.usd_to_cad).where(models.FxRate.rate_date == date(2026, 10, 27))))
    matching = _create(ws, harlow_draft(currency="USD", fx_rate_to_cad=rate))
    other = _create(ws, harlow_draft(currency="USD", fx_rate_to_cad=rate + Decimal("0.01")))
    assert ws.get(models.Bill, matching.bill_id).fx_rate_date == date(2026, 10, 27)
    assert ws.get(models.Bill, other.bill_id).fx_rate_date is None


def test_duplicate_line_numbers_are_renumbered_with_a_warning(ws: Session) -> None:
    lines = [ln.model_copy(update={"line_no": 1}) for ln in harlow_draft().lines]
    created = _create(ws, harlow_draft(lines=lines))
    assert [ln.line_no for ln in load_draft_bill(ws, created.bill_id).lines] == [1, 2]
    assert "not unique" in created.warnings[0]


# ---------------------------------------------------------------- 5. clerk edits show up in the rebuilt draft


def test_clerk_edits_to_the_columns_are_reflected(ws: Session) -> None:
    created = _create(ws)
    bill = ws.get(models.Bill, created.bill_id)
    bill.requester_user_id, bill.department_id = "U007", "D02"
    line1 = ws.get(models.BillLine, (created.bill_id, 1))
    line1.coding_status, line1.gl_account, line1.department_id = "overridden", "6610", "D02"
    line1.coded_by, line1.coded_at = "U004", utcnow()
    ws.flush()
    assert bill.row_version == 2  # the ORM bumped the optimistic-concurrency counter

    draft = load_draft_bill(ws, created.bill_id)
    assert (draft.requester_user_id, draft.department_id) == ("U007", "D02")
    one, two = draft.lines
    assert (one.coding.gl_account, one.coding.department_id, one.coding.accepted) == ("6610", "D02", True)
    assert (one.coding.confidence, one.coding.reason) == (0.9, "6310 Legal: 3 of 3 past lines from this vendor")
    assert (two.coding.gl_account, two.coding.accepted) == ("6310", False)


def test_a_line_coded_by_a_clerk_without_a_suggestion_says_so(ws: Session) -> None:
    lines = [ln.model_copy(update={"coding": None}) for ln in harlow_draft().lines]
    created = _create(ws, harlow_draft(lines=lines))
    assert load_draft_bill(ws, created.bill_id).lines[0].coding is None
    ws.execute(update(models.BillLine).where(models.BillLine.bill_id == created.bill_id, models.BillLine.line_no == 1)
               .values(coding_status="accepted", gl_account="6310", department_id="D01"))
    coding = load_draft_bill(ws, created.bill_id).lines[0].coding
    assert (coding.confidence, coding.reason, coding.accepted) == (1.0, "set by clerk", True)


# ---------------------------------------------------------------- 6. errors on load


def test_load_refuses_history_bills_and_unknown_ids(rs: Session) -> None:
    with pytest.raises(ValueError, match="history bills are built by RefData"):
        load_draft_bill(rs, "AP-00001")
    with pytest.raises(LookupError):
        load_draft_bill(rs, "AP-99999")


# ---------------------------------------------------------------- 7. writers need a write session


def test_writers_refuse_a_read_session(rs: Session) -> None:
    with pytest.raises(RuntimeError, match=r"^create_bill_from_draft requires a write session \(get_write_session\)$"):
        _create(rs)
    with pytest.raises(RuntimeError, match=r"^save_controls_run requires a write session \(get_write_session\)$"):
        save_controls_run(rs, "AP-00001", controls_result())
    assert _count(rs, models.Bill, origin="app") == 0


# ---------------------------------------------------------------- 8. runs are versioned


def test_controls_runs_are_versioned_with_their_own_flags_and_steps(ws: Session) -> None:
    bill_id = _create(ws).bill_id
    first = save_controls_run(ws, bill_id, controls_result())
    second = save_controls_run(ws, bill_id, controls_result(step1_user="U008"))
    runs = ws.execute(select(models.ControlsRun.run_id, models.ControlsRun.version)
                      .where(models.ControlsRun.bill_id == bill_id).order_by(models.ControlsRun.version)).all()
    assert [tuple(r) for r in runs] == [(first, 1), (second, 2)]
    for run_id in (first, second):
        assert _count(ws, models.BillFlag, run_id=run_id) == 2
        assert _count(ws, models.ApprovalRouteStep, run_id=run_id) == 2
    latest = latest_controls_run(ws, bill_id)
    assert (latest.run_id, latest.version, latest.result.route[0].user_id) == (second, 2, "U008")
    assert latest.flags[0].evidence == {"similar_vendor": "V026", "total": "6452.30"}  # JSON-safe evidence
    assert latest_controls_run(ws, _create(ws).bill_id) is None


# ---------------------------------------------------------------- 9. resolutions carry over


def test_overridden_flag_carries_over_until_its_evidence_changes(ws: Session) -> None:
    bill_id = _create(ws).bill_id
    run1 = save_controls_run(ws, bill_id, controls_result())
    resolved_at = utcnow()
    ws.execute(update(models.BillFlag).where(models.BillFlag.run_id == run1, models.BillFlag.code == "VENDOR_LOOKALIKE")
               .values(resolution="overridden", resolution_comment="Called Harlow & Stern; this is their new entity",
                       resolved_by="U003", resolved_at=resolved_at))

    save_controls_run(ws, bill_id, controls_result())  # identical flags
    lookalike, info = latest_controls_run(ws, bill_id).flags
    assert (lookalike.resolution, lookalike.resolved_by) == ("overridden", "U003")
    assert lookalike.resolution_comment == "Called Harlow & Stern; this is their new entity"
    assert lookalike.resolved_at == resolved_at
    assert info.resolution == "open"

    save_controls_run(ws, bill_id, controls_result(evidence={"similar_vendor": "V026", "total": "9999.00"}))
    assert latest_controls_run(ws, bill_id).flags[0].resolution == "open"


def _resolve_lookalike(session: Session, run_id: int, resolution: str, user_id: str) -> datetime:
    """Mark the run's VENDOR_LOOKALIKE flag as `resolution` by `user_id`, with a comment; returns resolved_at."""
    resolved_at = utcnow()
    session.execute(update(models.BillFlag)
                    .where(models.BillFlag.run_id == run_id, models.BillFlag.code == "VENDOR_LOOKALIKE")
                    .values(resolution=resolution, resolution_comment=f"{resolution} by {user_id}",
                            resolved_by=user_id, resolved_at=resolved_at))
    return resolved_at


@pytest.mark.parametrize("resolution", ["overridden", "resolved"])
@pytest.mark.parametrize(("before", "after", "carries"), [
    (Severity.WARN, Severity.WARN, True),    # same severity: carries over, as before
    (Severity.WARN, Severity.BLOCK, False),  # severity rises: the new flag starts open
    (Severity.BLOCK, Severity.WARN, True),   # severity drops: carries over
    (Severity.INFO, Severity.WARN, False),
    (Severity.BLOCK, Severity.BLOCK, True),
])
def test_resolution_carries_over_only_to_the_same_or_lower_severity(
        ws: Session, resolution: str, before: Severity, after: Severity, carries: bool) -> None:
    # An AP clerk (U004) may resolve or override a warn; finance or the controller must decide on a block.
    bill_id = _create(ws).bill_id
    run1 = save_controls_run(ws, bill_id, controls_result(severity=before))
    resolved_at = _resolve_lookalike(ws, run1, resolution, "U004")

    save_controls_run(ws, bill_id, controls_result(severity=after))  # identical code, field and evidence
    lookalike = latest_controls_run(ws, bill_id).flags[0]
    assert (lookalike.code, lookalike.severity) == ("VENDOR_LOOKALIKE", after)
    if carries:
        assert (lookalike.resolution, lookalike.resolved_by, lookalike.resolved_at) == (resolution, "U004", resolved_at)
        assert lookalike.resolution_comment == f"{resolution} by U004"
    else:
        assert lookalike.resolution == "open"
        assert (lookalike.resolved_by, lookalike.resolved_at, lookalike.resolution_comment) == (None, None, None)


def test_carry_over_uses_the_stored_severity_and_reopens_once_raised(ws: Session) -> None:
    # The previous flag's severity comes from bill_flags.severity, not from today's FLAG_CODES: a warn override
    # stays on the warn flag, is not inherited by the block that follows, and stays gone after that.
    bill_id = _create(ws).bill_id
    run1 = save_controls_run(ws, bill_id, controls_result(severity=Severity.WARN))
    _resolve_lookalike(ws, run1, "overridden", "U004")
    stored = ws.scalar(select(models.BillFlag.severity)
                       .where(models.BillFlag.run_id == run1, models.BillFlag.code == "VENDOR_LOOKALIKE"))
    assert stored == "warn"

    save_controls_run(ws, bill_id, controls_result(severity=Severity.BLOCK))
    assert latest_controls_run(ws, bill_id).flags[0].resolution == "open"
    save_controls_run(ws, bill_id, controls_result(severity=Severity.WARN))  # the open block doesn't carry anything
    assert latest_controls_run(ws, bill_id).flags[0].resolution == "open"


def test_a_resolution_skipped_by_a_higher_flag_still_covers_a_later_identical_one(ws: Session) -> None:
    # Two identical warn flags, one overridden. In the next run the first identical flag is a block (not covered)
    # and the second is a warn, which keeps the override.
    def two_flags(first: Severity, second: Severity) -> ControlsResult:
        """Two VENDOR_LOOKALIKE flags with the same field and evidence, at the given severities."""
        flag = controls_result().flags[0]
        return controls_result().model_copy(update={"flags": [flag.model_copy(update={"severity": first}),
                                                              flag.model_copy(update={"severity": second})]})

    bill_id = _create(ws).bill_id
    run1 = save_controls_run(ws, bill_id, two_flags(Severity.WARN, Severity.WARN))
    first_id = ws.scalar(select(func.min(models.BillFlag.id)).where(models.BillFlag.run_id == run1))
    ws.execute(update(models.BillFlag).where(models.BillFlag.id == first_id)
               .values(resolution="overridden", resolution_comment="checked", resolved_by="U004",
                       resolved_at=utcnow()))

    save_controls_run(ws, bill_id, two_flags(Severity.BLOCK, Severity.WARN))
    block, warn = latest_controls_run(ws, bill_id).flags
    assert (block.severity, block.resolution) == ("block", "open")
    assert (warn.severity, warn.resolution, warn.resolved_by) == ("warn", "overridden", "U004")


# ---------------------------------------------------------------- 10. UNASSIGNED


def test_unassigned_step_is_null_in_the_table_but_kept_in_the_route(ws: Session) -> None:
    bill_id = _create(ws).bill_id
    run_id = save_controls_run(ws, bill_id, controls_result(step1_user="UNASSIGNED"))
    stored = ws.scalar(select(models.ApprovalRouteStep.user_id).where(models.ApprovalRouteStep.run_id == run_id,
                                                                     models.ApprovalRouteStep.step_no == 1))
    assert stored is None
    route = route_for_bill(ws, bill_id)
    assert [s.user_id for s in route] == ["UNASSIGNED", "U003"]
    assert all(isinstance(s, ApprovalStep) for s in route)
    assert route_for_bill(ws, _create(ws).bill_id) == []


# ---------------------------------------------------------------- 11. approver ids


def test_approver_ids_include_delegators_and_skip_rejections(ws: Session) -> None:
    assert approver_ids_for_bill(ws, "AP-00002") == {"U012", "U003"}  # history: two approval steps

    bill_id = _create(ws).bill_id
    now = utcnow()
    ws.add_all([
        models.ApprovalDecision(decision_id="AP-A-90001", bill_id=bill_id, step_no=1, actor_user_id="U003",
                                actor_role="finance_manager", step_role="dept_manager", on_behalf_of="U012",
                                decision="approved", acted_at=now, origin="app"),
        models.ApprovalDecision(decision_id="AP-A-90002", bill_id=bill_id, step_no=2, actor_user_id="U007",
                                actor_role="approver", step_role="dept_manager", decision="rejected",
                                acted_at=now, origin="app"),
    ])
    ws.flush()
    assert approver_ids_for_bill(ws, bill_id) == {"U003", "U012"}
    with pytest.raises(LookupError):
        approver_ids_for_bill(ws, "AP-99999")


# ---------------------------------------------------------------- 12. atomic with the caller


def test_everything_rolls_back_with_the_caller(ws: Session, seeded: Engine) -> None:
    bill_id = _create(ws).bill_id
    save_controls_run(ws, bill_id, controls_result())
    ws.rollback()
    with seeded.connect() as conn:
        for table in ("bill_lines", "bill_taxes", "controls_runs", "approval_route_steps"):
            assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE bill_id = :b"), {"b": bill_id}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM bills WHERE origin = 'app'")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM bill_flags")).scalar() == 0


# ---------------------------------------------------------------- 13. no audit events


def test_no_helper_writes_audit_events(ws: Session) -> None:
    before = _count(ws, models.AuditEvent)
    bill_id = _create(ws).bill_id
    load_draft_bill(ws, bill_id)
    save_controls_run(ws, bill_id, controls_result())
    save_controls_run(ws, bill_id, controls_result())
    latest_controls_run(ws, bill_id)
    route_for_bill(ws, bill_id)
    approver_ids_for_bill(ws, bill_id)
    next_bill_id(ws)
    ws.commit()
    assert _count(ws, models.AuditEvent) == before == 0
