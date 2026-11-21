"""
Index of how past invoice lines were coded (GL account + department).

Owner: Person A.
Input: invoice_lines + invoices (for vendor_id) + gl_accounts + departments from the repository.
Output: HistoryIndex with per-vendor and global line lists, plus GL/department names
for readable reasons.

Built once per repository and cached. History is small (~800 lines), so plain lists
plus rapidfuzz are fast enough. No vector store needed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from app.reference.repository import ReferenceRepository


@dataclass(frozen=True)
class PastLine:
    vendor_id: str
    description: str
    gl_account: str
    department_id: str


@dataclass
class HistoryIndex:
    by_vendor: dict[str, list[PastLine]] = field(default_factory=dict)
    all_lines: list[PastLine] = field(default_factory=list)
    gl_names: dict[str, str] = field(default_factory=dict)
    dept_names: dict[str, str] = field(default_factory=dict)
    vendor_names: dict[str, str] = field(default_factory=dict)
    # most common department per GL account: used when only a GL is known
    dept_for_gl: dict[str, str] = field(default_factory=dict)

    def label(self, gl: str, dept: str) -> str:
        return f"{gl} {self.gl_names.get(gl, '')} · {dept} {self.dept_names.get(dept, '')}".replace("  ", " ")


def build_index(repo: ReferenceRepository) -> HistoryIndex:
    lines = repo.invoice_lines().merge(repo.invoices()[["invoice_id", "vendor_id"]], on="invoice_id", how="left")
    idx = HistoryIndex(
        gl_names=dict(zip(repo.gl_accounts()["account_number"], repo.gl_accounts()["name"], strict=True)),
        dept_names=dict(zip(repo.departments()["department_id"], repo.departments()["name"], strict=True)),
        vendor_names=dict(zip(repo.vendors()["vendor_id"], repo.vendors()["legal_name"], strict=True)),
    )
    per_gl: dict[str, Counter] = {}
    for r in lines.itertuples(index=False):
        if not r.gl_account:
            continue
        pl = PastLine(r.vendor_id or "", r.description, r.gl_account, r.department_id)
        idx.all_lines.append(pl)
        idx.by_vendor.setdefault(pl.vendor_id, []).append(pl)
        per_gl.setdefault(pl.gl_account, Counter())[pl.department_id] += 1
    idx.dept_for_gl = {gl: c.most_common(1)[0][0] for gl, c in per_gl.items()}
    return idx


@lru_cache(maxsize=4)
def index_for(repo: ReferenceRepository) -> HistoryIndex:
    return build_index(repo)
