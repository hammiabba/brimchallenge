"""
Suggest a GL account + department for each line of a DraftBill.

Owner: Person A.
Input: DraftBill (vendor already resolved) + repository.
Output: a copy of the DraftBill with `line.coding = CodingSuggestion(...)` on each line.

Tiers, best evidence first:
  1. Same vendor's history: vote over past (gl, dept) pairs, each vote weighted by how
     similar the past description is to this line. Frequency still counts, so a vendor
     that always codes to 5010 stays at 5010 even for a new description.
  2. Vendor master `default_gl_account` (department = most common for that GL).
  3. Global description similarity across all history (top matches vote).
If the bill has a requester, their department overrides the suggested department.

Confidence is 0..1 and drops with each tier. The reason is written for a clerk:
"5010 Freight & Carrier Costs · D01 Operations: 58 of 58 past lines from Polar Freight
Lines Ltd.; closest match 'LTL shipment Toronto-Montreal'".
"""
from __future__ import annotations

from collections import defaultdict

from rapidfuzz import fuzz, process

from app.coding.history_index import HistoryIndex, PastLine, index_for
from app.reference.repository import ReferenceRepository
from app.shared.schemas import CodingSuggestion, DraftBill, InvoiceLine

GLOBAL_TOP_K = 10


def _sim(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a.lower(), b.lower()) / 100


def _from_vendor(desc: str, past: list[PastLine], idx: HistoryIndex, vendor_name: str) -> CodingSuggestion:
    scores: dict[tuple[str, str], float] = defaultdict(float)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    best_match: dict[tuple[str, str], tuple[float, str]] = {}
    for pl in past:
        key = (pl.gl_account, pl.department_id)
        s = _sim(desc, pl.description)
        # 0.5 floor: every past line votes, similar ones vote harder.
        scores[key] += 0.5 + s
        counts[key] += 1
        if s > best_match.get(key, (-1, ""))[0]:
            best_match[key] = (s, pl.description)
    key = max(scores, key=scores.get)
    share = scores[key] / sum(scores.values())
    sim, closest = best_match[key]
    confidence = round(min(0.97, 0.65 * share + 0.35 * sim), 2)
    reason = (f"{idx.label(*key)}: {counts[key]} of {len(past)} past lines from {vendor_name} coded this way; "
              f"closest match '{closest}'")
    return CodingSuggestion(gl_account=key[0], department_id=key[1], confidence=confidence, reason=reason)


def _from_global(desc: str, idx: HistoryIndex) -> CodingSuggestion | None:
    if not idx.all_lines or not desc.strip():
        return None
    matches = process.extract(desc.lower(), [pl.description.lower() for pl in idx.all_lines],
                              scorer=fuzz.token_set_ratio, limit=GLOBAL_TOP_K)
    votes: dict[tuple[str, str], float] = defaultdict(float)
    for _, score, i in matches:
        pl = idx.all_lines[i]
        votes[(pl.gl_account, pl.department_id)] += score
    key = max(votes, key=votes.get)
    top_score, top_i = max((score, i) for _, score, i in matches
                           if (idx.all_lines[i].gl_account, idx.all_lines[i].department_id) == key)
    closest = idx.all_lines[top_i]
    confidence = round(min(0.6, 0.6 * top_score / 100 * votes[key] / sum(votes.values())), 2)
    return CodingSuggestion(
        gl_account=key[0], department_id=key[1], confidence=confidence,
        reason=(f"{idx.label(*key)}: no history for this vendor; most similar past line "
                f"'{closest.description}' ({idx.vendor_names.get(closest.vendor_id, closest.vendor_id)})"),
    )


def suggest_line(line: InvoiceLine, draft: DraftBill, repo: ReferenceRepository,
                 idx: HistoryIndex | None = None) -> CodingSuggestion | None:
    idx = idx or index_for(repo)
    vid = draft.vendor.vendor_id
    vendor_name = idx.vendor_names.get(vid or "", draft.vendor.name_on_invoice)

    suggestion = None
    if vid and idx.by_vendor.get(vid):
        suggestion = _from_vendor(line.description, idx.by_vendor[vid], idx, vendor_name)
    elif vid and (master := repo.vendor(vid)) and master.get("default_gl_account"):
        gl = master["default_gl_account"]
        dept = idx.dept_for_gl.get(gl, "D01")
        suggestion = CodingSuggestion(
            gl_account=gl, department_id=dept, confidence=0.55,
            reason=f"{idx.label(gl, dept)}: {vendor_name}'s default GL account (no past invoices to learn from)",
        )
    else:
        suggestion = _from_global(line.description, idx)

    if suggestion and draft.requester_user_id:
        users = repo.users()
        row = users[users["user_id"] == draft.requester_user_id]
        if not row.empty and (dept := row.iloc[0]["department_id"]) and dept != suggestion.department_id:
            suggestion = suggestion.model_copy(update={
                "department_id": dept,
                "reason": suggestion.reason + f"; department {dept} from requester {draft.requester_user_id}",
            })
    return suggestion


def suggest(draft: DraftBill, repo: ReferenceRepository) -> DraftBill:
    idx = index_for(repo)
    lines = [ln.model_copy(update={"coding": suggest_line(ln, draft, repo, idx)}) for ln in draft.lines]
    return draft.model_copy(update={"lines": lines})
