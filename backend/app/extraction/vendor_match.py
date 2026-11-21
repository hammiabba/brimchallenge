"""
Resolve the vendor on an invoice to a vendor_id in the master.

Owner: Person A.
Input: VendorOnInvoice (name, GST no., bank as extracted), sender email, repository.
Output: (VendorOnInvoice with vendor_id / match_method / match_score set, warnings).

Order, strongest evidence first:
  1. GST/HST number exact            score 1.0
  2. bank transit + account exact    score 1.0
  3. sender email domain             score 0.9
  4. fuzzy legal name (≥ 90)         score = ratio / 100
Why names come last: the master has lookalikes (V026 "Harlow & Stern LLP" vs V052
"Harlow and Stern LLP"; V002 vs V053 "Great Lakes Carriers Incorporated"), so a name
match alone can "succeed" against the wrong record. A name or domain candidate whose
GST number contradicts the invoice is rejected or downgraded, and every ambiguity
becomes a warning Person B can turn into a flag.

Matching is evidence only. Whether the vendor is active, on hold, or a lookalike is
for controls to decide.
"""
from __future__ import annotations

import re

import pandas as pd
from rapidfuzz import fuzz

from app.reference.repository import ReferenceRepository
from app.shared.schemas import MatchMethod, VendorOnInvoice

BUYER_GST = "100000001RT0001"  # Harborline's own number; printed in every bill-to block
FUZZY_THRESHOLD = 90


def _norm_gst(s: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def _norm_name(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _domain(email: str | None) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if email and "@" in email else ""


def _rank(cands: pd.DataFrame, inv: VendorOnInvoice) -> pd.DataFrame:
    """Order several candidates: matching GST, then exact name, then active status."""
    gst = _norm_gst(inv.gst_number)
    name = _norm_name(inv.name_on_invoice)
    printed = inv.name_on_invoice.casefold().split()
    key = pd.DataFrame({
        "gst": cands["gst_hst_number"].map(_norm_gst).eq(gst) & bool(gst),
        "name": cands["legal_name"].map(lambda n: n.casefold().split() == printed),
        "norm": cands["legal_name"].map(_norm_name).eq(name),
        "active": cands["status"].eq("active"),
    }, index=cands.index)
    order = key.sort_values(["gst", "name", "norm", "active"], ascending=False).index
    return cands.loc[order]


def _gst_conflict(row: pd.Series, inv: VendorOnInvoice) -> bool:
    inv_gst, master_gst = _norm_gst(inv.gst_number), _norm_gst(row["gst_hst_number"])
    return bool(inv_gst and master_gst and inv_gst != master_gst)


def resolve(inv: VendorOnInvoice, sender_address: str | None,
            repo: ReferenceRepository) -> tuple[VendorOnInvoice, list[str]]:
    vendors = repo.vendors()
    warnings: list[str] = []

    def pick(cands: pd.DataFrame, method: MatchMethod, score: float, what: str):
        ranked = _rank(cands, inv)
        best = ranked.iloc[0]
        if len(ranked) > 1:
            others = ", ".join(f"{r.vendor_id} '{r.legal_name}' ({r.status})"
                               for r in ranked.iloc[1:].itertuples())
            warnings.append(f"{what} also matches {others}: possible duplicate vendor record")
        return inv.model_copy(update={"vendor_id": best["vendor_id"], "match_method": method,
                                      "match_score": score}), best

    # 1. GST number
    gst = _norm_gst(inv.gst_number)
    if gst and gst != BUYER_GST:
        hits = vendors[vendors["gst_hst_number"].map(_norm_gst) == gst]
        if not hits.empty:
            return pick(hits, MatchMethod.GST_NUMBER, 1.0, f"GST {gst}")[0], warnings

    # 2. bank account
    b = inv.bank
    if b.transit and b.account:
        mask = (vendors["bank_transit"] == b.transit) & (vendors["bank_account"] == b.account)
        if b.institution:
            mask &= vendors["bank_institution"] == b.institution
        hits = vendors[mask]
        if not hits.empty:
            matched, row = pick(hits, MatchMethod.BANK_ACCOUNT, 1.0, "bank account")
            if _gst_conflict(row, inv):
                warnings.append(f"bank details match {row['vendor_id']} but the GST number on the invoice "
                                f"({inv.gst_number}) differs from the master ({row['gst_hst_number']})")
            return matched, warnings

    # 3. sender email domain
    dom = _domain(sender_address)
    if dom:
        hits = vendors[vendors["ap_contact_email"].map(_domain) == dom]
        if not hits.empty:
            matched, row = pick(hits, MatchMethod.EMAIL_DOMAIN, 0.9, f"sender domain {dom}")
            if _gst_conflict(row, inv):
                # Domain is decent evidence but a contradicting GST number is a red flag: keep the
                # candidate for the reviewer, with a low score and an explicit warning.
                matched.match_score = 0.5
                warnings.append(f"sender domain matches {row['vendor_id']} but the GST number on the invoice "
                                f"({inv.gst_number}) differs from the master ({row['gst_hst_number']})")
            return matched, warnings

    # 4. fuzzy name: weakest evidence
    name = _norm_name(inv.name_on_invoice)
    if name:
        scores = vendors["legal_name"].map(lambda n: fuzz.token_sort_ratio(name, _norm_name(n)))
        hits = vendors[scores >= FUZZY_THRESHOLD]
        if not hits.empty:
            hits = hits.assign(_score=scores[hits.index])
            consistent = hits[~hits.apply(lambda r: _gst_conflict(r, inv), axis=1)]
            if consistent.empty:
                ids = ", ".join(hits["vendor_id"])
                warnings.append(f"name '{inv.name_on_invoice}' resembles {ids} but the GST number differs; "
                                "not matched (possible lookalike)")
                return inv.model_copy(update={"vendor_id": None, "match_method": MatchMethod.NONE,
                                              "match_score": 0.0}), warnings
            top = consistent["_score"].max()
            best_cands = consistent[consistent["_score"] == top]
            matched, _ = pick(best_cands, MatchMethod.FUZZY_NAME, round(top / 100, 2),
                              f"name '{inv.name_on_invoice}'")
            return matched, warnings

    return inv.model_copy(update={"vendor_id": None, "match_method": MatchMethod.NONE,
                                  "match_score": 0.0}), warnings
