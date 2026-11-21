"""The detection coverage map (docs/DETECTION_COVERAGE.md) as a test.

Every "real-world mess" item from the brief that the controls catch has an example bill here, and the test fails if
that bill stops getting its flag. The incoming batch runs offline: extraction replays the recorded model output
(tests/fixtures/raw, as in tests/extraction/test_batch_expectations.py) and the controls check all 56 bills as one
batch, the same way scripts/run_incoming.py does. History examples are judged as of their own date
(history.replay_bill), as in scripts/replay_history.py.

If you change a row here, change the same row in docs/DETECTION_COVERAGE.md (the last test checks they agree).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest

from app.config import get_settings
from app.controls import route
from app.controls.approvals import can_approve
from app.controls.history import replay_bill
from app.controls.incoming import IncomingItem, run_batch
from app.controls.refdata import bill_from_history
from app.extraction.pipeline import extract_outcome
from tests.conftest import DATASET, INCOMING, FixtureClient

DOC = Path(__file__).resolve().parents[3] / "docs" / "DETECTION_COVERAGE.md"

# The brief's list, in its order: "Expect real-world mess..."
BRIEF_ITEMS = [
    "duplicates", "near-duplicates", "over-contract price", "wrong tax", "changed bank details", "split invoices",
    "unknown or unapproved vendors", "USD invoices", "credit notes", "odd dates", "PO problems", "self-approval",
    "arithmetic errors", "low-quality scans",
]


class Case(NamedTuple):
    item: str                  # one of BRIEF_ITEMS
    source: str                # "batch" (incoming file name) or "history" (invoice id)
    example: str
    code: str
    evidence: dict | None = None   # flag evidence that must match (a list in the flag must contain the value)


CASES = [
    Case("duplicates", "batch", "Invoice 000961.pdf", "DUPLICATE_EXACT", {"matches": "AP-00393"}),
    Case("duplicates", "batch", "harlowsternllp_001468.pdf", "DUPLICATE_EXACT", {"matches": "AP-00389"}),
    Case("duplicates", "batch", "cloudbarnsoftwar_INV01561.pdf", "DUPLICATE_EXACT", {"matches": "AP-00370"}),
    Case("duplicates", "history", "AP-00015", "ALREADY_PAID_BY_CARD"),
    Case("near-duplicates", "batch", "voyageurcorporat-inv-017.pdf", "DUPLICATE_EXACT", {"matches": "AP-00277"}),
    Case("near-duplicates", "batch", "brightlinesafety-inv-032.pdf", "DUPLICATE_EXACT", {"matches": "AP-00330"}),
    Case("over-contract price", "batch", "Invoice AU26-2207.pdf", "OVER_CONTRACT_RATE"),
    Case("over-contract price", "batch", "pineconecollabor_PI262809.pdf", "OVER_CONTRACT_RATE"),
    Case("over-contract price", "batch", "Invoice 000964.pdf", "OVER_FUEL_SURCHARGE_CAP"),
    Case("over-contract price", "batch", "redlinefleetcard-inv-044.pdf", "OVER_CONTRACT_NTE"),
    Case("over-contract price", "batch", "torqueindustrial_1771.pdf", "CONTRACT_EXPIRED"),
    Case("wrong tax", "batch", "northboundcourie_000639.pdf", "TAX_WRONG_FOR_PROVINCE"),
    Case("wrong tax", "batch", "beaumontrivieres_FA000557.pdf", "TAX_MISSING"),
    Case("wrong tax", "batch", "ironwoodpalletco-inv-048.pdf", "TAX_MISSING"),
    Case("wrong tax", "batch", "signalsparrowcre_000970.pdf", "PST_ON_SERVICES"),
    Case("wrong tax", "batch", "riverbendcaterin_1739.pdf", "GST_NUMBER_MISSING", {"kind": "no_tax"}),
    Case("changed bank details", "batch", "cascadiacartagel_1625.pdf", "BANK_CHANGE_UNVERIFIED"),
    Case("changed bank details", "batch", "scan_8049.png", "BANK_CHANGE_UNVERIFIED"),
    Case("changed bank details", "batch", "scan_8049.png", "BANK_DETAILS_MISMATCH", {"kind": "account_before_change"}),
    Case("changed bank details", "batch", "lumenprintsignag_FA001761.pdf", "BANK_DETAILS_MISMATCH",
         {"kind": "account_before_change"}),
    Case("split invoices", "batch", "orionstrategypar-inv-029.pdf", "POSSIBLE_SPLIT", {"combined_cad": "14543.10"}),
    Case("split invoices", "batch", "orionstrategypar_281.pdf", "POSSIBLE_SPLIT", {"combined_cad": "14543.10"}),
    Case("split invoices", "batch", "Invoice 287.pdf", "POSSIBLE_SPLIT", {"combined_cad": "14543.10"}),
    Case("unknown or unapproved vendors", "batch", "Invoice 4443.pdf", "VENDOR_NOT_FOUND"),
    Case("unknown or unapproved vendors", "batch", "zephyrdataservic_7590.pdf", "VENDOR_NOT_FOUND"),
    Case("unknown or unapproved vendors", "batch", "riverbendcaterin_1739.pdf", "VENDOR_PENDING_REVIEW"),
    Case("unknown or unapproved vendors", "batch", "Invoice HA26-2766.pdf", "VENDOR_LOOKALIKE"),
    Case("unknown or unapproved vendors", "history", "AP-00109", "VENDOR_NOT_ACTIVE"),
    Case("USD invoices", "batch", "sparkgridcrminc_FA002342.pdf", "FOREIGN_CURRENCY"),
    Case("USD invoices", "batch", "tesseraanalytics-inv-050.pdf", "FOREIGN_CURRENCY"),
    Case("credit notes", "batch", "fixwellfacilitys_CNFA000413.pdf", "CREDIT_NOTE"),
    Case("credit notes", "batch", "greatlakescarrie-inv-025.pdf", "CREDIT_NOTE"),
    Case("odd dates", "batch", "Invoice 000809.pdf", "DATE_ANOMALY", {"kind": "future"}),
    Case("odd dates", "batch", "lumenprintsignag_FA001761.pdf", "DATE_ANOMALY", {"kind": "stale"}),
    Case("PO problems", "batch", "keystonerackings-inv-002.pdf", "PO_REQUIRED_MISSING"),
    Case("PO problems", "history", "AP-00224", "PO_CLOSED_OR_WRONG_VENDOR"),
    Case("PO problems", "history", "AP-00159", "PO_OVER_BALANCE"),
    Case("arithmetic errors", "batch", "evergreenenergyu_000850.pdf", "TOTAL_MISMATCH"),
    Case("arithmetic errors", "batch", "northstarmediabu_NO261773.pdf", "LINE_MATH_ERROR"),
]

# Items with no flag of their own. Each is explained in the doc's "Not caught" section.
NO_FLAG = {
    "self-approval": "enforced by route() and can_approve(), not a flag (test below)",
    "low-quality scans": "LOW_EXTRACTION_CONFIDENCE is in FLAG_CODES but nothing raises it",
}


@pytest.fixture(scope="module")
def batch(repo, tmp_path_factory) -> dict[str, IncomingItem]:
    """The incoming batch through the real pipeline (recorded model output) and run_batch, by file name."""
    s = get_settings()
    saved = s.cache_dir, s.anthropic_api_key
    s.cache_dir, s.anthropic_api_key = tmp_path_factory.mktemp("cache"), None
    try:
        emails = json.loads((DATASET / "inbox" / "emails.json").read_text(encoding="utf-8"))
        sent = {a: (e["email_id"], e["from_address"]) for e in emails for a in e.get("attachments") or []}
        client, items = FixtureClient(), []
        for path in sorted(p for p in INCOMING.iterdir() if p.is_file()):
            email_id, sender = sent.get(path.name, (None, None))
            o = extract_outcome(path.read_bytes(), path.name, email_id=email_id, sender=sender, repo=repo,
                                client=client)
            items.append(IncomingItem(file_name=path.name, status=o.status, bill=o.draft, email_id=email_id,
                                      sender=sender, error=o.error))
        return {it.file_name: it for it in run_batch(items)}
    finally:
        s.cache_dir, s.anthropic_api_key = saved


def _flags(case: Case, batch, ref):
    if case.source == "batch":
        it = batch[case.example]
        assert it.result is not None, f"{case.example} was not read: {it.error}"
        return it.result.flags
    return replay_bill(ref, case.example).flags


def _matches(evidence: dict, want: dict) -> bool:
    for k, v in want.items():
        got = evidence.get(k)
        if not (v in got if isinstance(got, list) else got == v):
            return False
    return True


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.code}-{c.example}")
def test_example_still_gets_its_flag(case, batch, ref):
    flags = [f for f in _flags(case, batch, ref) if f.code == case.code]
    assert flags, f"{case.item}: {case.example} no longer gets {case.code}"
    if case.evidence:
        assert any(_matches(f.evidence or {}, case.evidence) for f in flags), [f.evidence for f in flags]


def test_every_brief_item_is_covered_or_explained():
    covered = {c.item for c in CASES}
    assert covered | set(NO_FLAG) == set(BRIEF_ITEMS)
    assert not covered & set(NO_FLAG)


def test_whole_batch_is_read_and_checked(batch):
    assert len(batch) == 56
    assert all(it.result is not None for it in batch.values())


def test_self_approval_escalates_and_is_refused(ref):
    # AP-00092: U010 (D05 manager) requested it and approved it themselves in the history (finding in test_history).
    bill = bill_from_history(ref, "AP-00092")
    assert bill.requester_user_id == "U010"
    steps = route(bill, ref)
    assert "U010" not in {s.user_id for s in steps}
    assert any("P07" in s.policy_ids for s in steps)
    decision = can_approve("U010", steps[0], bill, ref, route=steps)
    assert not decision.allowed and "P07" in decision.reason


def test_scans_are_read_and_checked(batch):
    # Both scans go through the same checks as any bill (scan_8049's bank flags come from its scan).
    # No flag says "read from a scan" yet: see the doc's "Not caught" section.
    for name in ("scan_8049.png", "scan_8749.png"):
        it = batch[name]
        assert it.bill.source.was_ocr and it.result is not None


def test_doc_lists_every_case():
    text = DOC.read_text(encoding="utf-8")
    missing = [f"{c.example} / {c.code}" for c in CASES if c.example not in text or c.code not in text]
    assert not missing, f"docs/DETECTION_COVERAGE.md is missing: {missing}"
    assert all(item in text for item in BRIEF_ITEMS)
