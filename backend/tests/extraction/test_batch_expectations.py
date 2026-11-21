"""Expected values for all 56 incoming files, replayed offline from the recorded model output.

The expectations were derived from the documents themselves, not from our output: the PDF text layer
(read independently with a regex cross-check), the two scans read by eye, and the vendor master
(vendor_id by the printed GST number; the three vendors with no GST printed by their master record).
Each file goes through the real pipeline with the sender of the email it came in, like the inbox does.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D
from typing import NamedTuple

import pytest

from app.config import get_settings
from app.extraction.pipeline import extract_outcome
from tests.conftest import DATASET, INCOMING, FixtureClient, recorded_files


class E(NamedTuple):
    file: str
    vendor_id: str | None
    invoice_number: str
    invoice_date: str
    due_date: str | None
    currency: str
    province: str | None
    credit_note: bool
    subtotal: str
    total: str
    taxes: list[tuple[str, str]]
    lines: int
    po_label_blank: bool


EXPECTED = [
    E('Invoice 000809.pdf', 'V011', '000809', '2026-11-27', '2026-12-27', 'CAD', 'QC',
      False, '5000.00', '5748.75', [('GST5', '250.00'), ('QST9975', '498.75')], 1, True),
    E('Invoice 000961.pdf', 'V001', '000961', '2026-10-01', '2026-10-31', 'CAD', 'QC',
      False, '6206.47', '7135.89', [('GST5', '310.32'), ('QST9975', '619.10')], 6, False),
    E('Invoice 000964.pdf', 'V001', '000964', '2026-10-21', '2026-11-20', 'CAD', 'ON',
      False, '2807.78', '3172.79', [('HST13', '365.01')], 5, False),
    E('Invoice 002935.pdf', 'V036', '002935', '2026-11-01', '2026-11-01', 'CAD', 'ON',
      False, '16600.00', '18758.00', [('HST13', '2158.00')], 2, False),
    E('Invoice 287.pdf', 'V029', '287', '2026-10-28', '2026-11-27', 'CAD', 'ON',
      False, '4250.00', '4802.50', [('HST13', '552.50')], 1, False),
    E('Invoice 4443.pdf', None, '4443', '2026-10-20', '2026-11-19', 'CAD', 'AB',
      False, '1340.70', '1407.74', [('GST5', '67.04')], 2, False),
    E('Invoice 853.pdf', 'V014', '853', '2026-10-22', '2026-11-21', 'CAD', 'ON',
      False, '1128.00', '1274.64', [('HST13', '146.64')], 2, False),
    E('Invoice AU26-2207.pdf', 'V022', 'AU26-2207', '2026-11-02', '2026-11-23', 'CAD', 'BC',
      False, '2343.50', '2460.68', [('GST5', '117.18')], 1, False),
    E('Invoice FA-000318.pdf', 'V020', 'FA-000318', '2026-10-29', '2026-11-28', 'CAD', 'BC',
      False, '460.00', '483.00', [('GST5', '23.00')], 1, False),
    E('Invoice FA-001619.pdf', 'V003', 'FA-001619', '2026-10-27', '2026-11-26', 'CAD', 'QC',
      False, '6022.86', '6924.78', [('GST5', '301.14'), ('QST9975', '600.78')], 5, False),
    E('Invoice FA-002853.pdf', 'V023', 'FA-002853', '2026-10-29', '2026-11-19', 'CAD', 'ON',
      False, '890.00', '1005.70', [('HST13', '115.70')], 1, False),
    E('Invoice HA26-2766.pdf', 'V052', 'HA26-2766', '2026-10-27', '2026-11-26', 'CAD', 'ON',
      False, '5710.00', '6452.30', [('HST13', '742.30')], 2, False),
    E('Invoice INV-00734.pdf', 'V045', 'INV-00734', '2026-10-28', '2026-11-27', 'CAD', 'ON',
      False, '2250.00', '2542.50', [('HST13', '292.50')], 1, False),
    E('Invoice TR26-1042.pdf', 'V007', 'TR26-1042', '2026-10-20', '2026-11-04', 'CAD', 'ON',
      False, '4382.35', '4952.06', [('HST13', '569.71')], 1, False),
    E('alpengloweventsc-inv-010.pdf', 'V047', 'AL26-0689', '2026-10-23', '2026-11-22', 'CAD', 'QC',
      False, '5550.17', '6381.31', [('GST5', '277.51'), ('QST9975', '553.63')], 2, True),
    E('beaumontrivieres_FA000557.pdf', 'V027', 'FA-000557', '2026-10-23', '2026-11-22', 'CAD', 'QC',
      False, '7715.88', '8101.67', [('GST5', '385.79')], 1, False),
    E('benefitwisegroup_262.pdf', 'V049', '262', '2026-10-30', '2026-11-14', 'CAD', 'ON',
      False, '2190.00', '2474.70', [('HST13', '284.70')], 1, False),
    E('brightlinesafety-inv-032.pdf', 'V013', '583', '2026-08-12', '2026-09-11', 'CAD', 'ON',
      False, '3368.41', '3806.30', [('HST13', '437.89')], 2, True),
    E('cascadiacartagel_1625.pdf', 'V004', '1625', '2026-10-27', '2026-11-26', 'CAD', 'QC',
      False, '5263.09', '6051.23', [('GST5', '263.15'), ('QST9975', '524.99')], 5, False),
    E('cloudbarnsoftwar-inv-047.pdf', 'V015', 'INV-01568', '2026-10-31', '2026-11-30', 'CAD', 'BC',
      False, '2400.00', '2520.00', [('GST5', '120.00')], 1, False),
    E('cloudbarnsoftwar_INV01561.pdf', 'V015', 'INV-01561', '2026-10-09', '2026-11-08', 'CAD', 'AB',
      False, '2400.00', '2520.00', [('GST5', '120.00')], 1, False),
    E('evergreenenergyu_000850.pdf', 'V041', '000850', '2026-10-20', '2026-11-10', 'CAD', 'BC',
      False, '3180.00', '3439.00', [('GST5', '159.00')], 1, False),
    E('fixwellfacilitys-inv-052.pdf', 'V043', 'FA-000415', '2026-11-01', '2026-12-01', 'CAD', 'AB',
      False, '2730.00', '2866.50', [('GST5', '136.50')], 2, True),
    E('fixwellfacilitys_CNFA000413.pdf', 'V043', 'CN-FA-000413', '2026-10-29', '2026-11-28', 'CAD', 'ON',
      True, '-1428.50', '-1614.21', [('HST13', '-185.71')], 2, False),
    E('granvillecommerc_GR262864.pdf', 'V037', 'GR26-2864', '2026-11-01', '2026-11-01', 'CAD', 'BC',
      False, '7750.00', '8137.50', [('GST5', '387.50')], 2, False),
    E('greatlakescarrie-inv-016.pdf', 'V002', 'GR26-2271', '2026-10-26', '2026-11-25', 'CAD', 'ON',
      False, '4198.05', '4743.80', [('HST13', '545.75')], 6, False),
    E('greatlakescarrie-inv-025.pdf', 'V002', 'CN-GR26-2274', '2026-10-27', '2026-11-26', 'CAD', 'BC',
      True, '-640.00', '-672.00', [('GST5', '-32.00')], 1, False),
    E('harlowsternllp_001468.pdf', 'V026', '001468', '2026-10-06', '2026-11-05', 'CAD', 'BC',
      False, '15363.75', '16131.94', [('GST5', '768.19')], 2, False),
    E('harlowsternllp_001470.pdf', 'V026', '001470', '2026-10-21', '2026-11-20', 'CAD', 'BC',
      False, '323.35', '339.52', [('GST5', '16.17')], 1, False),
    E('ironwoodpalletco-inv-048.pdf', 'V010', 'INV-02210', '2026-10-30', '2026-11-29', 'CAD', 'ON',
      False, '915.64', '915.64', [], 1, True),
    E('keystonerackings-inv-002.pdf', 'V012', 'KE26-1198', '2026-10-19', '2026-11-18', 'CAD', 'ON',
      False, '6185.35', '6989.45', [('HST13', '804.10')], 2, True),
    E('lakeshorehydrose-inv-012.pdf', 'V040', 'INV-03018', '2026-10-24', '2026-11-14', 'CAD', 'ON',
      False, '4380.01', '4949.41', [('HST13', '569.40')], 1, False),
    E('latticeledgersys_557.pdf', 'V019', '557', '2026-10-31', '2026-11-30', 'CAD', 'ON',
      False, '8200.00', '9266.00', [('HST13', '1066.00')], 1, False),
    E('laurentianlogist_FA002399.pdf', 'V005', 'FA-002399', '2026-10-25', '2026-11-24', 'CAD', 'QC',
      False, '4362.67', '5015.98', [('GST5', '218.13'), ('QST9975', '435.18')], 6, False),
    E('ledgerlinecharte_FA002176.pdf', 'V028', 'FA-002176', '2026-10-23', '2026-11-22', 'CAD', 'AB',
      False, '1556.10', '1633.91', [('GST5', '77.81')], 1, False),
    E('lumenprintsignag_FA001761.pdf', 'V033', 'FA-001761', '2026-04-06', '2026-05-06', 'CAD', 'ON',
      False, '1860.00', '2101.80', [('HST13', '241.80')], 1, False),
    E('mapletireautofle-inv-009.pdf', 'V009', '1531', '2026-10-23', '2026-11-07', 'CAD', 'BC',
      False, '1860.00', '1953.00', [('GST5', '93.00')], 1, False),
    E('northboundcourie_000639.pdf', 'V006', '000639', '2026-10-29', '2026-11-28', 'CAD', 'AB',
      False, '2217.27', '2505.52', [('HST13', '288.25')], 5, False),
    E('northstarmediabu_NO261773.pdf', 'V032', 'NO26-1773', '2026-10-27', '2026-11-26', 'CAD', 'ON',
      False, '3800.00', '4294.00', [('HST13', '494.00')], 1, False),
    E('orionstrategypar-inv-029.pdf', 'V029', '279', '2026-10-28', '2026-11-27', 'CAD', 'ON',
      False, '4300.00', '4859.00', [('HST13', '559.00')], 1, False),
    E('orionstrategypar_281.pdf', 'V029', '281', '2026-10-28', '2026-11-27', 'CAD', 'ON',
      False, '4320.00', '4881.60', [('HST13', '561.60')], 1, False),
    E('papertrailoffice_2217.pdf', 'V024', '2217', '2026-10-26', '2026-11-25', 'CAD', 'ON',
      False, '542.16', '612.64', [('HST13', '70.48')], 1, False),
    E('pineconecollabor_PI262809.pdf', 'V017', 'PI26-2809', '2026-11-02', '2026-12-02', 'CAD', 'AB',
      False, '826.80', '868.14', [('GST5', '41.34')], 1, False),
    E('placemontroyalim-inv-053.pdf', 'V039', 'FA-000566', '2026-11-01', '2026-11-01', 'CAD', 'QC',
      False, '6080.00', '6990.48', [('GST5', '304.00'), ('QST9975', '606.48')], 2, False),
    E('polarfreightline_000963.pdf', 'V001', '000963', '2026-10-31', '2026-11-30', 'CAD', 'ON',
      False, '2311.14', '2611.59', [('HST13', '300.45')], 3, False),
    E('redlinefleetcard-inv-044.pdf', 'V008', 'FA-001687', '2026-10-31', '2026-11-15', 'CAD', 'ON',
      False, '5440.49', '6147.75', [('HST13', '707.26')], 1, False),
    E('riverbendcaterin_1739.pdf', 'V054', '1739', '2026-10-26', '2026-11-25', 'CAD', 'BC',
      False, '2860.00', '2860.00', [], 1, True),
    E('scan_8049.png', 'V004', '1624', '2026-10-24', '2026-11-23', 'CAD', 'QC',
      False, '5821.87', '6693.69', [('GST5', '291.09'), ('QST9975', '580.73')], 5, False),
    E('scan_8749.png', 'V042', 'PR26-1012', '2026-10-22', '2026-11-12', 'CAD', 'AB',
      False, '4494.55', '4719.28', [('GST5', '224.73')], 1, False),
    E('signalsparrowcre_000970.pdf', 'V031', '000970', '2026-10-28', '2026-11-27', 'CAD', 'BC',
      False, '8400.00', '9408.00', [('GST5', '420.00'), ('PST7_BC', '588.00')], 2, False),
    E('sparkgridcrminc_FA002342.pdf', 'V018', 'FA-002342', '2026-10-26', '2026-11-25', 'USD', 'BC',
      False, '1950.00', '1950.00', [('FOREIGN', '0')], 1, False),
    E('tesseraanalytics-inv-050.pdf', 'V016', '002715', '2026-10-31', '2026-11-30', 'USD', 'BC',
      False, '3100.00', '3100.00', [('FOREIGN', '0')], 1, False),
    E('torqueindustrial_1771.pdf', 'V044', '1771', '2026-10-27', '2026-11-26', 'CAD', 'AB',
      False, '2150.00', '2257.50', [('GST5', '107.50')], 1, True),
    E('voyageurcorporat-inv-017.pdf', 'V046', '000903-A', '2026-07-06', '2026-07-21', 'CAD', 'AB',
      False, '5308.92', '5574.37', [('GST5', '265.45')], 1, False),
    E('voyageurcorporat_000921.pdf', 'V046', '000921', '2026-10-29', '2026-11-13', 'CAD', 'ON',
      False, '1877.31', '2121.36', [('HST13', '244.05')], 1, False),
    E('zephyrdataservic_7590.pdf', None, '7590', '2026-10-22', '2026-11-21', 'CAD', 'AB',
      False, '6200.00', '6510.00', [('GST5', '310.00')], 1, False),
]
BY_FILE = {e.file: e for e in EXPECTED}
ARITHMETIC_ERRORS = {  # the only documents whose printed maths is wrong (checked on the PDFs)
    "evergreenenergyu_000850.pdf": "but the invoice total says 3439.00",
    "northstarmediabu_NO261773.pdf": "but the line amount says 3800.00",
}


def _senders() -> dict[str, tuple[str, str]]:
    emails = json.loads((DATASET / "inbox" / "emails.json").read_text(encoding="utf-8"))
    return {a: (e["email_id"], e["from_address"]) for e in emails for a in e.get("attachments") or []}


@pytest.fixture(scope="module")
def drafts(repo, tmp_path_factory):
    s = get_settings()
    saved = s.cache_dir, s.anthropic_api_key
    s.cache_dir, s.anthropic_api_key = tmp_path_factory.mktemp("cache"), None
    try:
        senders, client = _senders(), FixtureClient()
        out = {}
        for name in BY_FILE:
            email_id, sender = senders.get(name, (None, None))
            out[name] = extract_outcome((INCOMING / name).read_bytes(), name, email_id=email_id, sender=sender,
                                        repo=repo, client=client)
        return out
    finally:
        s.cache_dir, s.anthropic_api_key = saved


def test_expectations_cover_every_incoming_file_and_every_fixture():
    files = sorted(p.name for p in INCOMING.iterdir() if p.is_file())
    assert sorted(BY_FILE) == files
    assert recorded_files() == files


@pytest.mark.parametrize("name", sorted(BY_FILE))
def test_header_and_totals(drafts, name):
    e, out = BY_FILE[name], drafts[name]
    assert out.status == "ok", out.error
    d = out.draft
    got = (d.vendor.vendor_id, d.invoice_number, d.invoice_date.isoformat(),
           d.due_date.isoformat() if d.due_date else None, d.currency, d.ship_to_province, d.is_credit_note,
           d.subtotal, d.total, len(d.lines))
    want = (e.vendor_id, e.invoice_number, e.invoice_date, e.due_date, e.currency, e.province, e.credit_note,
            D(e.subtotal), D(e.total), e.lines)
    assert got == want
    assert sorted((t.code.value, t.amount) for t in d.taxes) == sorted((c, D(a)) for c, a in e.taxes)


@pytest.mark.parametrize("name", sorted(BY_FILE))
def test_arithmetic_warnings_only_where_the_document_is_wrong(drafts, name):
    warnings = [w for w in drafts[name].draft.extraction_warnings if " but the " in w]
    if name in ARITHMETIC_ERRORS:
        assert len(warnings) == 1 and ARITHMETIC_ERRORS[name] in warnings[0], warnings
    else:
        assert warnings == []


@pytest.mark.parametrize("name", sorted(BY_FILE))
def test_blank_po_field_is_noted(drafts, name):
    noted = any("PO field" in w for w in drafts[name].draft.extraction_warnings)
    assert noted == BY_FILE[name].po_label_blank
    assert drafts[name].draft.po_number is None  # no sample prints a PO value


@pytest.mark.parametrize("name", [e.file for e in EXPECTED if e.currency == "USD"])
def test_usd_converted_at_the_invoice_date_rate(drafts, repo, name):
    d = drafts[name].draft
    rate = repo.fx_rate(d.invoice_date)
    assert rate is not None and d.fx_rate_to_cad == rate
    assert d.total_cad == (d.total * rate).quantize(D("0.01"))


@pytest.mark.parametrize("name", [e.file for e in EXPECTED if e.credit_note])
def test_credit_notes_are_negative(drafts, name):
    d = drafts[name].draft
    assert d.total < 0 and d.subtotal < 0 and all(t.amount <= 0 for t in d.taxes)


@pytest.mark.parametrize("name,gst,transit,vendor", [
    ("scan_8749.png", "862863208RT0001", "55541", "V042"),
    ("scan_8049.png", "669086667RT0001", "92968", "V004"),
])
def test_scans_read_ids_exactly(drafts, name, gst, transit, vendor):
    d = drafts[name].draft
    assert d.source.was_ocr
    assert (d.vendor.gst_number, d.vendor.bank.transit, d.vendor.vendor_id) == (gst, transit, vendor)
    # Read from the image, so confidence is capped below a clean text layer's.
    assert max(d.field_confidence.values()) <= 0.75


def test_future_dated_invoice_is_read_as_printed(drafts):
    # Summit 000809 is dated after the as-of date; extraction keeps it, controls judge it.
    assert drafts["Invoice 000809.pdf"].draft.invoice_date == date(2026, 11, 27)
