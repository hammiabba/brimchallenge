"""
Copy the cached LLM output for each incoming file into tests/fixtures/raw/<file_stem>.json.

Owner: Person A.   Run from backend/ after a real run:  python scripts/record_fixtures.py [--dir PATH]

The fixtures are what the model actually returned for each file, so the offline test suite replays real
model output through the real pipeline (record/replay). Refresh them after a prompt or model change:
  rm -rf .cache/llm && python scripts/run_inbox.py && python scripts/record_fixtures.py
Never calls the API: files without a cache entry for the current prompt version and model are listed
and skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # works even before `pip install -e`

from app.config import get_settings  # noqa: E402
from app.extraction import cache  # noqa: E402
from app.extraction.llm_parser import prompt_version  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "raw"


def record(folder: Path, out_dir: Path = FIXTURES) -> tuple[list[str], list[str]]:
    s = get_settings()
    pv = prompt_version()
    out_dir.mkdir(parents=True, exist_ok=True)
    written, missing = [], []
    for f in sorted(p for p in folder.iterdir() if p.is_file()):
        h = cache.file_sha256(f.read_bytes())
        entry = cache.get(h, pv, s.llm_model)
        if entry is None:
            missing.append(f.name)
            continue
        fixture = {"file_name": f.name, "file_hash": h, "input": entry.get("input"), "model": s.llm_model,
                   "prompt_version": pv, "raw": entry["raw"]}
        (out_dir / f"{f.stem}.json").write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
        written.append(f.name)
    return written, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dir", type=Path, default=None, help="folder of invoice files (default: dataset incoming)")
    ap.add_argument("--out", type=Path, default=FIXTURES)
    args = ap.parse_args()
    folder = args.dir or get_settings().dataset_dir / "incoming_invoices"
    written, missing = record(folder, args.out)
    print(f"{len(written)} fixtures written to {args.out}")
    if missing:
        print(f"{len(missing)} files have no cached result for prompt v{prompt_version()}: {', '.join(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
