"""Sets up the demo state on a seeded, back-filled database, through the real services, so the audit log is genuine.

    cd backend
    python -m app.db.seed --reset && python -m app.db.backfill      # once
    python scripts/demo_scenario.py [--database-url URL]

What it leaves behind (all as of 2026-11-02):
- one bill waiting in every approver's queue (U007 D01, U008 D02, U009 D03, U010 D05, U011 D06, U002 as D04's
  manager), one in the finance manager's queue at step 2 of an over-$10,000 bill, and one in U003's queue as the
  delegate of U012 (on leave);
- the V004 Cascadia bank-change hold: BC-009 (by email, no callback) is still pending, so history bill AP-00426
  can't be scheduled, and a new Cascadia bill is held by BANK_CHANGE_UNVERIFIED (submit is refused);
- a delegated approval: U003 approved a Facilities bill acting for U012, recorded with on_behalf_of=U012;
- payments approved and ready to release: three bills approved by their department managers and scheduled by the
  AP clerk (U004). The delegated one can't be released by U003 (P11: they approved it); the controller (U002) can.

Every step goes through app.services (intake, bills, approvals, payments): the same code the API runs, with the same
checks and one audit event per action. Invoices are typed in as DraftBills (the extraction step is skipped, so no
LLM is called); everything after that is the normal intake path.

Idempotent: each demo bill has a fixed file hash, and intake links a file it has already seen to its bill. Each step
looks at the bill first and only does what's missing, so a second run changes nothing and writes no audit events.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.api import schemas_api as s  # noqa: E402
from app.api.errors import ApiError  # noqa: E402
from app.auth.deps import CurrentUser, load_current_user  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import models  # noqa: E402
from app.db.database import as_write_engine, make_engine, resolve_database_url  # noqa: E402
from app.db.refdata_db import refdata_from_db  # noqa: E402
from app.extraction.pipeline import ExtractionOutcome  # noqa: E402
from app.intake.received import existing_bill_for_file  # noqa: E402
from app.services import approvals, bills, intake, payments  # noqa: E402
from app.shared.schemas import (  # noqa: E402
    BankDetails,
    DraftBill,
    InvoiceLine,
    LineType,
    MatchMethod,
    SourceInfo,
    TaxCode,
    TaxLine,
    VendorOnInvoice,
)

CLERK = "U004"                      # uploads, submits and schedules (AP clerk)
INVOICE_DATE = date(2026, 10, 30)
TAX = {"ON": ("HST13", D("0.13")), "BC": ("GST5", D("0.05"))}


@dataclass(frozen=True)
class DemoBill:
    key: str                        # fixed: the file hash is derived from it, which makes reruns find the bill
    number: str                     # invoice number; distinct digits, since duplicate checks compare digits only
    vendor_id: str
    department_id: str
    requester: str | None
    amount: str                     # pre-tax
    description: str
    province: str = "ON"
    approvals: tuple[str, ...] = ()  # who signs, step by step, before the script stops
    schedule: bool = False          # schedule the payment once fully approved
    submit: bool = True             # False: left in review (a held bill)

    @property
    def file_hash(self) -> str:
        return f"sha256:demo-{self.key}"

    @property
    def file_name(self) -> str:
        return f"demo-{self.key}.pdf"


BILLS = [
    # Waiting at step 1 in each department manager's queue.
    DemoBill("d01-queue", "DM-1001", "V001", "D01", "U013", "2840.00", "LTL shipment Toronto-Ottawa, Oct 28"),
    DemoBill("d02-queue", "DM-1002", "V029", "D02", None, "3150.00", "Sales pipeline workshop, Oct 2026"),
    DemoBill("d03-queue", "DM-1003", "V032", "D03", None, "4200.00", "Digital media placement, November 2026"),
    DemoBill("d04-queue", "DM-1004", "V028", "D04", None, "2600.00", "Quarterly review procedures, Q3 2026"),
    DemoBill("d05-queue", "DM-1005", "V023", "D05", None, "1180.00", "Fibre circuit installation, Oct 2026"),
    DemoBill("d06-queue", "DM-1006", "V048", "D06", None, "6500.00", "Recruiting fee, warehouse supervisor"),
    # U012 is on leave: step 1 goes to U003 as the named delegate (P08).
    DemoBill("d07-delegate-queue", "DM-1007", "V040", "D07", None, "1860.00",
             "Electrical repairs, Mississauga warehouse"),
    # Over $10,000: the department manager signed, the finance manager is next (P02).
    DemoBill("d01-finance-queue", "DM-1008", "V002", "D01", "U013", "11800.00",
             "Dedicated truckload runs, October 2026", approvals=("U007",)),
    # Cascadia after the unverified bank change: held, never submitted.
    DemoBill("v004-hold", "DM-1009", "V004", "D01", "U013", "3480.00", "Cross-dock handling, Delta BC, Oct 29",
             province="BC", submit=False),
    # Approved and scheduled: ready to release.
    DemoBill("d07-delegated-paid", "DM-1010", "V040", "D07", None, "1420.00", "Lighting retrofit, loading bays 3-4",
             approvals=("U003",), schedule=True),
    DemoBill("d02-ready", "DM-1011", "V030", "D02", None, "3900.00", "Territory planning engagement, Oct 2026",
             approvals=("U008",), schedule=True),
    DemoBill("d06-ready", "DM-1012", "V024", "D06", None, "640.00", "Onboarding kits and office supplies",
             approvals=("U011",), schedule=True),
]


@dataclass
class DemoReport:
    bills: dict[str, str] = field(default_factory=dict)       # key -> bill id
    did: list[str] = field(default_factory=list)              # what this run changed
    skipped: list[str] = field(default_factory=list)          # already in place


def _write(engine: Engine) -> Session:
    return Session(as_write_engine(engine), expire_on_commit=False)


def _user(db: Session, user_id: str) -> CurrentUser:
    u = load_current_user(db, user_id)
    if u is None:
        raise SystemExit(f"User {user_id} is missing or terminated. Seed the database first.")
    return u


def _draft(engine: Engine, b: DemoBill) -> DraftBill:
    with Session(engine) as db:
        v = refdata_from_db(db).vendors[b.vendor_id]
    code, rate = TAX[b.province]
    amount = D(b.amount)
    tax = (amount * rate).quantize(D("0.01"))
    return DraftBill(
        source=SourceInfo(file_name=b.file_name, file_hash=b.file_hash),
        vendor=VendorOnInvoice(name_on_invoice=v["legal_name"], gst_number=v["gst_hst_number"] or None,
                               bank=BankDetails(institution=v["bank_institution"] or None,
                                                transit=v["bank_transit"] or None, account=v["bank_account"] or None),
                               vendor_id=b.vendor_id, match_method=MatchMethod.GST_NUMBER, match_score=1.0),
        invoice_number=b.number, invoice_date=INVOICE_DATE,
        due_date=INVOICE_DATE + timedelta(days=int(v["payment_terms_days"] or 0)), currency="CAD",
        ship_to_province=b.province, requester_user_id=b.requester, department_id=b.department_id,
        lines=[InvoiceLine(line_no=1, description=b.description, quantity=D("1"), unit_price=amount, amount=amount,
                           line_type=LineType.SERVICES)],
        subtotal=amount, taxes=[TaxLine(code=TaxCode(code), rate=rate, amount=tax)], total=amount + tax,
        total_cad=amount + tax)


def _bill(engine: Engine, b: DemoBill) -> models.Bill | None:
    with Session(engine) as db:
        return existing_bill_for_file(db, b.file_hash)


def _create(engine: Engine, b: DemoBill, report: DemoReport) -> str:
    """Upload as the AP clerk, then store the typed-in DraftBill through intake (controls run, bill.created)."""
    existing = _bill(engine, b)
    if existing is not None:
        report.skipped.append(f"{b.key}: bill {existing.bill_id} exists")
        return existing.bill_id
    with _write(engine) as db:
        # A run that stopped between the upload and storing the bill left its intake item queued: reuse it.
        item_id = db.scalar(select(models.IntakeItem.item_id).where(
            models.IntakeItem.file_name == b.file_name, models.IntakeItem.bill_id.is_(None),
            models.IntakeItem.status == "queued"))
        if item_id is None:
            item_id, _ = intake.queue_submission(db, _user(db, CLERK), b.file_name, b.department_id)
            db.commit()
        overrides = intake.Overrides(department_id=b.department_id)
    outcome = ExtractionOutcome(b.file_name, b.file_hash, "ok", draft=_draft(engine, b), text_method="typed_in")
    bill_id = intake.store_outcome(engine, intake.Extracted(item_id, outcome, overrides=overrides),
                                   started_by=CLERK, batch=[outcome.draft])
    report.did.append(f"{b.key}: created {bill_id}")
    return bill_id


def _advance(engine: Engine, b: DemoBill, bill_id: str, report: DemoReport) -> None:
    if not b.submit:
        return
    with _write(engine) as db:
        bill = db.get(models.Bill, bill_id)
        if bill.status in ("needs_review", "on_hold"):
            bills.submit(db, _user(db, CLERK), bill_id, bill.row_version)
            db.commit()
            report.did.append(f"{b.key}: submitted {bill_id}")
    for approver in b.approvals:
        with _write(engine) as db:
            bill = db.get(models.Bill, bill_id)
            signed = db.scalar(select(models.ApprovalDecision.decision_id).where(
                models.ApprovalDecision.bill_id == bill_id, models.ApprovalDecision.actor_user_id == approver,
                models.ApprovalDecision.decision == "approved"))
            if signed or bill.status != "pending_approval":
                continue
            approvals.approve(db, _user(db, approver), bill_id,
                              s.DecisionIn(row_version=bill.row_version, comment="Approved for the demo."))
            db.commit()
            report.did.append(f"{b.key}: {approver} approved {bill_id}")
    if b.schedule:
        with _write(engine) as db:
            bill = db.get(models.Bill, bill_id)
            if bill.status == "approved":
                pid = payments.schedule(db, _user(db, CLERK), bill_id,
                                        s.ScheduleIn(scheduled_date=get_settings().as_of_date, method="EFT"))
                db.commit()
                report.did.append(f"{b.key}: scheduled {pid} for {bill_id}")


def run(engine: Engine) -> DemoReport:
    """Brings the database to the demo state. Safe to run again: only missing steps are done."""
    with Session(engine) as db:
        if db.get(models.User, CLERK) is None or db.get(models.Bill, "AP-00426") is None:
            raise SystemExit("The database isn't seeded. Run `python -m app.db.seed` and "
                             "`python -m app.db.backfill` first.")
    report = DemoReport()
    for b in BILLS:
        try:
            bill_id = _create(engine, b, report)
            report.bills[b.key] = bill_id
            _advance(engine, b, bill_id, report)
        except ApiError as e:
            raise SystemExit(f"{b.key}: refused by the service ({e.code}): {e.message} {e.details or ''}") from e
    return report


def check_cascadia_hold(engine: Engine) -> list[str]:
    """What blocks Cascadia (V004), read-only: the pending bank change, AP-00426 not schedulable, the held bill."""
    out = []
    with Session(engine) as db:
        change = db.scalars(select(models.BankChangeRequest).where(
            models.BankChangeRequest.vendor_id == "V004",
            models.BankChangeRequest.status == "pending_verification")).first()
        if change:
            out.append(f"{change.change_id} is pending verification (requested by {change.request_channel})")
        try:
            payments.schedule_check(db, db.get(models.Bill, "AP-00426"))
        except ApiError as e:
            out.append(f"AP-00426 can't be scheduled: {e.message}")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/demo_scenario.py", description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", default=None, help="database to set up (default: DATABASE_URL / settings)")
    args = ap.parse_args(argv)
    # Same resolution as seed.py and backfill.py: the --database-url flag, else the configured DATABASE_URL,
    # with a relative SQLite path made absolute under the repo root.
    engine = make_engine(resolve_database_url(args.database_url or get_settings().database_url))
    try:
        report = run(engine)
        hold = check_cascadia_hold(engine)
    finally:
        engine.dispose()
    print("Demo bills:")
    for key, bill_id in report.bills.items():
        print(f"  {bill_id}  {key}")
    print(f"\n{len(report.did)} step(s) done" + (":" if report.did else " (already set up)."))
    for line in report.did:
        print(f"  {line}")
    print("\nCascadia (V004) hold:")
    for line in hold:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
