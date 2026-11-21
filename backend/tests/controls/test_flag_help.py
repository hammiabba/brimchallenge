"""Every flag code has UI help text, and history_taxes is public (with the old name still working)."""
from app.controls import FLAG_HELP, help_for, history_taxes
from app.controls.refdata import _history_taxes
from app.shared.schemas import FLAG_CODES


def test_every_flag_code_has_help():
    assert set(FLAG_CODES) - set(FLAG_HELP) == set()


def test_no_help_for_codes_that_dont_exist():
    assert set(FLAG_HELP) - set(FLAG_CODES) == set()


def test_help_is_short_title_and_one_sentence():
    for code, h in FLAG_HELP.items():
        assert 1 <= len(h.title.split()) <= 5, code
        assert h.help.endswith(".") and h.help.count(". ") == 0, code  # one sentence


def test_help_for_adds_code_and_severity():
    assert help_for("PO_NOT_FOUND") == {"code": "PO_NOT_FOUND", "severity": "block", "title": "PO not found",
                                        "help": FLAG_HELP["PO_NOT_FOUND"].help}
    assert help_for("SOMETHING_NEW")["title"] == "Something new"


def test_history_taxes_is_public_and_old_name_still_works():
    assert _history_taxes is history_taxes
