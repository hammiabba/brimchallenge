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
| `DATABASE_URL` | For the DB team; SQLite by default (`backend/ap.db`). |
| `AUDIT_HMAC_KEY` | **Required.** Signs the audit log chain; nothing can be written without it. Keep it once the database has events. |
| `SESSION_SECRET` | Signs session cookies. Empty → a random one, so everyone is signed out when the backend restarts. |

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

## 4. Run the whole app

Everything from the repo root, with the venv active. You need Python 3.11+ and Node 20+ (`frontend/.nvmrc`: 24).

**Once:**

```bash
pip install -e "backend[dev]"
cd frontend && npm ci && cd ..
cp .env.example .env
# In .env, set the two secrets (each: python -c "import secrets; print(secrets.token_hex(32))"):
#   AUDIT_HMAC_KEY=...   required
#   SESSION_SECRET=...   keeps people signed in across backend restarts
# and ANTHROPIC_API_KEY=... to read new invoices (uploads and the inbox run). Each new file is one paid call
# (about $0.025); results are cached by file, so a file is only paid for once.
```

**The database, with the demo data** (run again any time to start over):

```bash
cd backend
python -m app.db.seed --reset          # the dataset into backend/ap.db (--reset starts from an empty file)
python -m app.db.backfill              # one controls run per history bill
python scripts/demo_scenario.py --database-url sqlite:///$PWD/ap.db   # bills in every queue, see docs/DEMO_SCENARIO.md
cd ..
```

**Start it** (two terminals):

```bash
cd backend && uvicorn app.main:app --port 8000     # API: http://127.0.0.1:8000/docs
cd frontend && npm run dev                          # UI:  http://localhost:5173
```

Open **http://localhost:5173** (not 127.0.0.1: the session cookie and the origin check are set for localhost) and
sign in by picking a person; there are no passwords. Useful people for the demo:

| User | Role | Start here |
|---|---|---|
| U013 Aiden Grant | Employee (Operations) | Submit invoice, My submissions |
| U004 Jordan Okafor | AP clerk | Inbox, Review queue (AP-00435: the Cascadia bank-change hold), Payments |
| U007 Dev Malhotra | Approver (Operations) | My approvals (AP-00427) |
| U003 Elise Tremblay | Finance manager | My approvals as U012's delegate (AP-00433) and step 2 of AP-00434; Payments |
| U002 Marcus Webb | Controller | Payments (releases PAY-00416), Bank reconciliation, Audit log, admin |
| U006 Hannah Lindqvist | Auditor | Audit log with CSV export, read-only everywhere |

The full walk-through, with every bill and payment the demo sets up, is in
[`docs/DEMO_SCENARIO.md`](docs/DEMO_SCENARIO.md). The frontend's own setup and scripts are in
[`frontend/README.md`](frontend/README.md).
