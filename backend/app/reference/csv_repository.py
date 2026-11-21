"""
CsvReferenceRepository: ReferenceRepository backed by dataset/brim_ap_dataset/data/*.csv.

Owner: Person A. Used until the DB team ships a DB-backed implementation.
Each CSV is loaded once and cached per instance. Use `default_repository()` for a
process-wide shared instance.

The dataset folder is never written to.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import cache, lru_cache
from pathlib import Path

import pandas as pd

from app.config import get_settings


class CsvReferenceRepository:
    def __init__(self, dataset_dir: Path | None = None):
        self.data_dir = Path(dataset_dir or get_settings().dataset_dir) / "data"
        if not self.data_dir.is_dir():
            raise FileNotFoundError(f"Dataset CSV folder not found: {self.data_dir} (check DATASET_DIR)")

    @cache  # noqa: B019 - one repository per process; caching per instance is intended
    def _load(self, name: str) -> pd.DataFrame:
        # dtype=str + keep_default_na=False: IDs keep leading zeros and blanks stay "" not NaN.
        return pd.read_csv(self.data_dir / f"{name}.csv", dtype=str, keep_default_na=False)

    def vendors(self) -> pd.DataFrame:
        return self._load("vendors")

    def vendor(self, vendor_id: str) -> dict | None:
        rows = self.vendors()[self.vendors()["vendor_id"] == vendor_id]
        return None if rows.empty else rows.iloc[0].to_dict()

    def invoices(self) -> pd.DataFrame:
        return self._load("invoices")

    def invoice_lines(self) -> pd.DataFrame:
        return self._load("invoice_lines")

    def tax_codes(self) -> pd.DataFrame:
        return self._load("tax_codes")

    def fx_rates(self) -> pd.DataFrame:
        return self._load("fx_rates")

    def contracts(self) -> pd.DataFrame:
        return self._load("contracts")

    def purchase_orders(self) -> pd.DataFrame:
        return self._load("purchase_orders")

    def users(self) -> pd.DataFrame:
        return self._load("users")

    def departments(self) -> pd.DataFrame:
        return self._load("departments")

    def gl_accounts(self) -> pd.DataFrame:
        return self._load("gl_accounts")

    def card_transactions(self) -> pd.DataFrame:
        return self._load("card_transactions")

    def bank_change_history(self) -> pd.DataFrame:
        return self._load("bank_change_history")

    def approval_policies(self) -> pd.DataFrame:
        return self._load("approval_policies")

    def fx_rate(self, on: date) -> Decimal | None:
        rates = self.fx_rates()
        # ISO strings sort chronologically, so a string comparison is enough.
        earlier = rates[rates["date"] <= on.isoformat()]
        if earlier.empty:
            return None
        return Decimal(earlier.sort_values("date").iloc[-1]["usd_to_cad"])


@lru_cache
def default_repository() -> CsvReferenceRepository:
    return CsvReferenceRepository()
