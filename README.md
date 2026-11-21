# Brim AP

AP automation: email/upload intake → extraction → coding → validation & duplicates → approval routing →
simulated payment → audit trail. See [`CLAUDE.md`](CLAUDE.md) for the team rules and repo map, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the pipeline.

## 1. System dependencies

You need Python 3.11+. OCR for scanned invoices needs **tesseract** (with French data). **poppler**
(`pdftotext`) is an optional fallback text extractor. Without either, the app still runs: PDFs with a
text layer work, and scans are sent to the LLM as images.

| OS | Command |
|---|---|
| macOS | `brew install tesseract tesseract-lang poppler` |
| Ubuntu/Debian | `sudo apt install tesseract-ocr tesseract-ocr-fra poppler-utils` |
| Windows | `choco install tesseract poppler`, plus `fra.traineddata` from github.com/tesseract-ocr/tessdata into tesseract's `tessdata` folder; make sure both are on `PATH` |

## 2. Python setup

Dependencies are declared in `backend/pyproject.toml` (one file; `[dev]` adds pytest, ruff, httpx).

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e "backend[dev]"
cp .env.example .env               # add ANTHROPIC_API_KEY to enable LLM extraction
```

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Enables LLM extraction. Empty → classification + text layer only. |
| `LLM_MODEL` / `LLM_EFFORT` | Extraction model and effort level. |
| `AS_OF_DATE` | Business "today" (2026-11-02). |
| `DATASET_DIR` | Empty → `dataset/brim_ap_dataset`. |
| `DATABASE_URL` | For the DB team; SQLite by default. |

## 3. Run

```bash
cd backend
uvicorn app.main:app --reload          # http://127.0.0.1:8000/health and /docs
pytest                                 # unit tests, no network
ruff check .                           # lint
python scripts/run_inbox.py            # process all 59 emails → backend/output/drafts/
python scripts/eval_extraction.py      # per-field accuracy vs tests/golden/
```

LLM results are cached in `backend/.cache/` by file hash + prompt version + model, so reruns are free and
deterministic. Delete the folder (or bump `PROMPT_VERSION` in the prompt) to force re-extraction.
