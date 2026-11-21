from datetime import date
from decimal import Decimal

import pytest

from app.extraction.normalize import (
    detect_language,
    fix_digit_field,
    fix_tax_number,
    looks_foreign,
    map_tax_label,
    parse_date,
    parse_money,
    parse_rate,
    province_from_address,
)
from app.shared.schemas import TaxCode


@pytest.mark.parametrize("raw,expected", [
    ("$1,234.56", "1234.56"),
    ("-$1,042.76", "-1042.76"),
    ("($1,042.76)", "-1042.76"),
    ("1,042.76-", "-1042.76"),
    ("4 362,67 $", "4362.67"),
    ("4 362,67 $", "4362.67"),
    ("4 362,67 $", "4362.67"),
    ("1.234,56", "1234.56"),
    ("USD 1,950.00", "1950.00"),
    ("$5,400", "5400"),
    ("218,13 $", "218.13"),
    ("0.00", "0.00"),
    ("−385.74", "-385.74"),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "N/A", "abc"])
def test_parse_money_rejects_non_numbers(raw):
    assert parse_money(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("13%", "0.13"), ("9,975 %", "0.09975"), ("(5 %)", "0.05"), ("0.07", "0.07"), ("9.975", "0.09975"),
])
def test_parse_rate(raw, expected):
    assert parse_rate(raw) == Decimal(expected)


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-27", date(2026, 10, 27)),
    ("Oct 27, 2026", date(2026, 10, 27)),
    ("27 octobre 2026", date(2026, 10, 27)),
    ("1er novembre 2026", date(2026, 11, 1)),
    ("27/10/2026", date(2026, 10, 27)),
    ("2026/10/27", date(2026, 10, 27)),
    ("10/27/2026", date(2026, 10, 27)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("addr,expected", [
    ("88 Queens Quay W, Suite 1400, Toronto ON M5J 0B8", "ON"),
    ("1250 Rene-Levesque O, Bureau 2200, Montreal QC H3B 4W8", "QC"),
    ("250 6 Ave SW, Suite 700, Calgary AB T2P 3H7", "AB"),
    ("1055 W Hastings St, Vancouver, British Columbia", "BC"),
    ("123 Main St, Winnipeg R3C 1A1", "MB"),
    ("7348 Rue Sainte-Catherine, Austin TX 35030", None),
])
def test_province_from_address(addr, expected):
    assert province_from_address(addr) == expected


def test_looks_foreign():
    assert looks_foreign("7348 Rue Sainte-Catherine, Austin TX 35030")
    assert not looks_foreign("Toronto ON M5J 0B8")


@pytest.mark.parametrize("label,rate,expected", [
    ("HST (13%)", "0.13", TaxCode.HST13),
    ("TVH (13 %)", "0.13", TaxCode.HST13),
    ("GST (5%)", "0.05", TaxCode.GST5),
    ("TPS (5 %)", "0.05", TaxCode.GST5),
    ("QST (9.975%)", "0.09975", TaxCode.QST9975),
    ("TVQ (9,975 %)", "0.09975", TaxCode.QST9975),
    ("PST (7%)", "0.07", TaxCode.PST7_BC),
    ("GST/HST", "0.13", TaxCode.HST13),
    ("TPS/TVH", "0.05", TaxCode.GST5),
    ("Sales tax", "0.05", TaxCode.GST5),
    ("Tax exempt", None, TaxCode.EXEMPT),
])
def test_map_tax_label(label, rate, expected):
    assert map_tax_label(label, Decimal(rate) if rate else None) == expected


def test_map_tax_label_unknown():
    assert map_tax_label("Sales tax", Decimal("0.08")) is None


def test_fix_gst_number_ocr_noise():
    value, warning = fix_tax_number("669086667RT000!")
    assert value == "669086667RT0001"
    assert "OCR fix" in warning


def test_fix_gst_number_clean_has_no_warning():
    assert fix_tax_number("503486760 RT0001") == ("503486760RT0001", None)


def test_fix_qst_number():
    assert fix_tax_number("1745206219TQ0001", kind="qst") == ("1745206219TQ0001", None)
    value, warning = fix_tax_number("174520621OTQ0001", kind="qst")
    assert value == "1745206210TQ0001" and warning


def test_fix_transit_dollar_sign():
    value, warning = fix_digit_field("$5541", "transit", 5)
    assert value == "55541"
    assert "OCR fix" in warning


def test_fix_digit_field_wrong_length_left_alone():
    assert fix_digit_field("5541", "transit", 5) == ("5541", None)


def test_detect_language():
    assert detect_language("FACTURE\nFacture n°: FA-1\nSous-total 1 000,00 $\nTPS (5 %)\nTVQ") == "fr"
    assert detect_language("INVOICE\nSubtotal\nHST (13%)\nEFT / virement bancaire") == "en"
