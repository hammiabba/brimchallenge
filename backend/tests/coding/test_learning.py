"""Clerk decisions feed the next suggestion for the same vendor (in-memory, offline)."""
from app.coding.history_index import Correction, corrections_for, forget_corrections, learn
from app.coding.suggest import suggest
from tests.coding.test_suggest import bill

POLAR_LINE = "LTL shipment Toronto-Montreal"


def polar_override(gl="6630", dept="D04", desc=POLAR_LINE, bill_id="AP-00500", overridden=True):
    learn(Correction(vendor_id="V001", description=desc, gl_account=gl, department_id=dept, bill_id=bill_id,
                     overridden=overridden))


def test_override_changes_the_next_suggestion_and_says_why(repo):
    assert suggest(bill("V001", [POLAR_LINE]), repo).lines[0].coding.gl_account == "5010"
    polar_override()
    c = suggest(bill("V001", [POLAR_LINE]), repo).lines[0].coding
    assert (c.gl_account, c.department_id) == ("6630", "D04")
    assert "a clerk changed the coding of 'LTL shipment Toronto-Montreal'" in c.reason
    assert "bill AP-00500" in c.reason and "history alone would suggest 5010" in c.reason


def test_correction_only_applies_to_similar_lines(repo):
    polar_override(desc="Fuel surcharge October")
    c = suggest(bill("V001", ["LTL shipment Toronto-Montreal"]), repo).lines[0].coding
    assert c.gl_account == "5010" and "clerk" not in c.reason


def test_correction_is_per_vendor(repo):
    polar_override()
    c = suggest(bill("V051", [POLAR_LINE]), repo).lines[0].coding  # the lookalike Polar record
    assert "clerk" not in c.reason


def test_acceptance_is_recorded_as_confirmation(repo):
    polar_override(gl="5010", dept="D01", overridden=False)
    c = suggest(bill("V001", [POLAR_LINE]), repo).lines[0].coding
    assert c.gl_account == "5010" and "a clerk confirmed the coding" in c.reason
    assert "history alone" not in c.reason


def test_newer_decision_on_the_same_line_replaces_the_older(repo):
    polar_override(gl="6630")
    polar_override(gl="5020")
    assert [c.gl_account for c in corrections_for("V001")] == ["5020"]


def test_requester_department_still_overrides(repo):
    polar_override(dept="D04")
    c = suggest(bill("V001", [POLAR_LINE], requester="U013"), repo).lines[0].coding  # U013 is in D01
    assert c.department_id == "D01" and "from requester U013" in c.reason


def test_forget(repo):
    polar_override()
    forget_corrections()
    assert corrections_for("V001") == []


def test_lines_that_teach_nothing_are_skipped():
    from types import SimpleNamespace as NS

    from app.coding.feedback import learn_from_line
    from app.coding.history_index import corrections_for

    line = NS(coding_status="overridden", gl_account="6630", department_id="D04", description="x")
    assert not learn_from_line(NS(vendor_id=None, bill_id="AP-1"), line)                       # unknown vendor
    assert not learn_from_line(NS(vendor_id="V001", bill_id="AP-1"), NS(**{**vars(line), "coding_status": "suggested"}))
    assert not learn_from_line(NS(vendor_id="V001", bill_id="AP-1"), NS(**{**vars(line), "gl_account": None}))
    assert corrections_for("V001") == []


def test_start_up_replay_survives_a_database_without_tables(caplog):
    from types import SimpleNamespace as NS

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.coding.feedback import replay_on_startup
    from app.db.database import get_session

    def empty_db():
        with Session(create_engine("sqlite://")) as s:
            yield s

    replay_on_startup(NS(dependency_overrides={get_session: empty_db}))
    assert "learned codings not replayed" in caplog.text
