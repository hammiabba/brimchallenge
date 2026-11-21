"""build_refdata (rows in, RefData out) gives exactly what load_refdata gives from the CSVs."""
from datetime import date

from app.config import get_settings
from app.controls import REFDATA_FILES, build_refdata, load_refdata
from app.controls.refdata import _read

P = get_settings().dataset_dir / "data"


def test_build_refdata_matches_load_refdata():
    assert build_refdata({s: _read(P / f"{s}.csv") for s in REFDATA_FILES}) == load_refdata(P)


def test_refdata_files_are_the_twelve_csvs():
    assert len(REFDATA_FILES) == 12 and all((P / f"{s}.csv").exists() for s in REFDATA_FILES)


def test_as_of_defaults_to_settings_and_can_be_set():
    rows = {s: _read(P / f"{s}.csv") for s in REFDATA_FILES}
    assert build_refdata(rows).as_of == get_settings().as_of_date
    assert build_refdata(rows, as_of=date(2026, 12, 1)).as_of == date(2026, 12, 1)
