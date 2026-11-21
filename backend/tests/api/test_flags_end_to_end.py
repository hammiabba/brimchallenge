"""The whole inbox through main's real path, offline: POST /intake/inbox/jobs → classify → the real extraction
pipeline (model output replayed from tests/fixtures/raw) → bills in the DB → Person B's controls with the whole batch
→ GET /bills/{id}. Asserts the flag each known trap in the dataset must raise, and that clean invoices are not
blocked. One run per module (about 3 s); each test reads from it.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import partial

import pytest

from app.config import get_settings
from app.services import jobs as jobs_service
from tests.api.conftest import TEST_AUDIT_HMAC_KEY, _client_on, _copy, _engine_on
from tests.conftest import replay_extract


@pytest.fixture(scope="module")
def flags(seeded_template, tmp_path_factory) -> Iterator[dict[str, list[dict]]]:
    """file name → the flags on its bill's latest controls run."""
    from app.db.settings import get_db_settings

    s = get_settings()
    mp = pytest.MonkeyPatch()
    mp.setenv("AUDIT_HMAC_KEY", TEST_AUDIT_HMAC_KEY)
    get_db_settings.cache_clear()
    mp.setattr(s, "cache_dir", tmp_path_factory.mktemp("cache"))
    mp.setattr(s, "anthropic_api_key", None)
    mp.setattr(jobs_service, "extract_outcome", partial(replay_extract))
    jobs_service.reset_for_tests()
    engine = _engine_on(_copy(seeded_template, tmp_path_factory.mktemp("e2e")))
    try:
        with _client_on(engine) as c:
            assert c.post("/auth/login", json={"user_id": "U004"}).status_code == 200
            job_id = c.post("/intake/inbox/jobs").json()["job_id"]
            job = c.get(f"/intake/inbox/jobs/{job_id}").json()
            assert job["status"] == "done", job
            out = {}
            for item in job["items"]:
                assert item["status"] == "ok" and item["bill_id"], item
                bill = c.get(f"/bills/{item['bill_id']}").json()
                out[item["file_name"]] = bill["latest_run"]["flags"]
            yield out
    finally:
        engine.dispose()
        jobs_service.reset_for_tests()
        mp.undo()
        get_db_settings.cache_clear()


def codes(flags_for_file: list[dict]) -> set[str]:
    return {f["code"] for f in flags_for_file}


# HACKATHON_PLAN §4: the trap each file carries and the flag controls must raise for it.
EXPECTED = [
    ("Invoice HA26-2766.pdf", "VENDOR_LOOKALIKE"),
    ("Invoice 4443.pdf", "VENDOR_NOT_FOUND"),                 # Blue Heron
    ("zephyrdataservic_7590.pdf", "VENDOR_NOT_FOUND"),
    ("cascadiacartagel_1625.pdf", "BANK_CHANGE_UNVERIFIED"),
    ("scan_8049.png", "BANK_CHANGE_UNVERIFIED"),             # Cascadia 1624, read from the image
    ("Invoice 000964.pdf", "OVER_FUEL_SURCHARGE_CAP"),       # Polar
    ("northboundcourie_000639.pdf", "TAX_WRONG_FOR_PROVINCE"),
    ("beaumontrivieres_FA000557.pdf", "TAX_MISSING"),
    ("signalsparrowcre_000970.pdf", "PST_ON_SERVICES"),
    ("ironwoodpalletco-inv-048.pdf", "TAX_MISSING"),
    ("evergreenenergyu_000850.pdf", "TOTAL_MISMATCH"),
    ("northstarmediabu_NO261773.pdf", "LINE_MATH_ERROR"),
    ("Invoice 000809.pdf", "PO_REQUIRED_MISSING"),           # Summit
    ("Invoice 853.pdf", "PO_REQUIRED_MISSING"),              # Hardhat
    ("alpengloweventsc-inv-010.pdf", "PO_REQUIRED_MISSING"),
    ("brightlinesafety-inv-032.pdf", "PO_REQUIRED_MISSING"),
    ("fixwellfacilitys-inv-052.pdf", "PO_REQUIRED_MISSING"),  # FA-000415
    ("fixwellfacilitys_CNFA000413.pdf", "PO_REQUIRED_MISSING"),
    ("keystonerackings-inv-002.pdf", "PO_REQUIRED_MISSING"),
    ("torqueindustrial_1771.pdf", "PO_REQUIRED_MISSING"),
    ("Invoice 000961.pdf", "DUPLICATE_EXACT"),               # Polar
    ("cloudbarnsoftwar_INV01561.pdf", "DUPLICATE_EXACT"),    # the history row was paid by card
    ("harlowsternllp_001468.pdf", "DUPLICATE_EXACT"),
    ("brightlinesafety-inv-032.pdf", "DUPLICATE_*"),          # "583" = history FA-000583
    ("riverbendcaterin_1739.pdf", "VENDOR_PENDING_REVIEW"),
]

# Checked on the PDFs and the master: active vendor, no PO needed, bank as on file, the right tax for the
# province, arithmetic adds up, no earlier invoice with that number.
CLEAN = [
    "Invoice FA-000318.pdf", "Invoice FA-001619.pdf", "Invoice FA-002853.pdf", "Invoice INV-00734.pdf",
    "Invoice TR26-1042.pdf", "benefitwisegroup_262.pdf", "granvillecommerc_GR262864.pdf",
    "greatlakescarrie-inv-016.pdf", "harlowsternllp_001470.pdf", "lakeshorehydrose-inv-012.pdf",
    "latticeledgersys_557.pdf", "laurentianlogist_FA002399.pdf", "ledgerlinecharte_FA002176.pdf",
    "mapletireautofle-inv-009.pdf", "papertrailoffice_2217.pdf", "placemontroyalim-inv-053.pdf",
    "polarfreightline_000963.pdf", "scan_8749.png",
]


def test_every_incoming_file_became_a_bill(flags):
    from tests.conftest import INCOMING

    assert sorted(flags) == sorted(p.name for p in INCOMING.iterdir() if p.is_file())


@pytest.mark.parametrize("name,code", EXPECTED, ids=[f"{n}-{c}" for n, c in EXPECTED])
def test_known_trap_is_flagged(flags, name, code):
    got = codes(flags[name])
    if code.endswith("*"):
        assert any(c.startswith(code[:-1]) for c in got), got
    else:
        assert code in got, got


def test_monthly_rent_is_not_a_duplicate(flags):
    # Queen Street 002935: same landlord, same amount every month, a new invoice number each time.
    assert not any(c.startswith("DUPLICATE") for c in codes(flags["Invoice 002935.pdf"]))


@pytest.mark.xfail(strict=True, reason="controls calls 000903-A an exact duplicate of 000903; the plan expects "
                                       "DUPLICATE_LIKELY (ISSUES_FOR_B.md item 2). Extraction reads 000903-A.")
def test_suffixed_number_is_a_near_duplicate(flags):
    got = codes(flags["voyageurcorporat-inv-017.pdf"])
    assert "DUPLICATE_LIKELY" in got and "DUPLICATE_EXACT" not in got


def test_suffixed_number_is_still_held_as_a_duplicate(flags):
    # Whatever the code, the near duplicate must block payment.
    assert any(f["code"].startswith("DUPLICATE") and f["severity"] == "block"
               for f in flags["voyageurcorporat-inv-017.pdf"])


@pytest.mark.parametrize("name", CLEAN)
def test_clean_invoice_is_not_blocked(flags, name):
    assert not [f["code"] for f in flags[name] if f["severity"] == "block"]
