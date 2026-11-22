# intake/

Feature 1: emails and uploads in, triage + draft bills out.

## Public API
| Function | Returns |
|---|---|
| `classifier.classify(email, client=None)` | `EmailTriage` (class, attachments to process, human-readable reason) |
| `classifier.classify_rules(email)` | `EmailTriage` or `None` when the rules aren't sure |
| `inbox.load_emails(path=None)` | list of email dicts (`DATASET_DIR/inbox/emails.json` by default) |
| `inbox.process_inbox(emails, attachments_dir=None, repo=None, client=None)` | `[(EmailTriage, [ExtractionOutcome, ...])]` |
| `upload.ALLOWED_EXTS` | extensions accepted by `POST /submissions` (`.pdf` and images) |
| `review.action_for(email_row, repo=None)` | `SuggestedAction` for a stored `Email` (None before triage); shown on `GET /intake/emails` |
| `review.email_detail(db, email_id)` | `EmailDetail` (body, triage, suggested action, bill ids, items) for `GET /intake/emails/{email_id}` |
| `files.keep(data)` | sha256; stores the original under `settings.files_dir` (called by the pipeline for every file) |
| `files.load(db, file_hash)` | `(bytes, content type, name)` for `GET /intake/files/{file_hash}`, or `None` |
| `actions.suggest_action(email, triage, repo)` | `SuggestedAction`: what the clerk should do next, with a ready reply when useful |
| `actions.invoice_status(vendor, invoice_number, text, repo)` | `InvoiceStatus` from `invoices.csv` + `payments.csv` |

## Classification rules (in order)
1. Promotional wording, no invoice wording or file → `not_ap`
2. "Statement of account" / "relevé de compte" → `statement` (never creates bills)
3. Asks about a payment and has no file → `payment_inquiry`
4. Has PDF/image attachments → `credit_note` (credit wording or a `CN-` number) or `invoice`. **One bill per attachment.**
5. Mentions an attachment or invoice but has none → `missing_attachment` (the clerk asks the vendor to resend)
6. Otherwise: LLM tie-break if an API key is set, else `not_ap`

Subject and body are scanned together with **both** English and French keywords, because they can be in different languages.
`sender_address` is passed into every `DraftBill.source` so controls can detect lookalike domains.

## Suggested actions
| Class | Action | Reply text |
|---|---|---|
| `invoice`, `credit_note` | `create_drafts` (one per attachment) | none |
| `missing_attachment` | `request_resend` | asks for the file, in the email's language (EN/FR) |
| `payment_inquiry` | `answer_status` | the invoice's status, payment date, method and payment reference |
| `statement` | `reconcile_later` | none; no bill is created |
| `not_ap` | `ignore` | none |

Payment inquiries are answered only when the sender identifies the vendor (AP address, then domain, then a
strict name match). Two master records can share one AP address (Polar V001/V051, Great Lakes V002/V053): the
sender name splits them, and failing that the invoice number must exist under exactly one of them. Same-number
resubmissions in history (one rejected, one paid) answer for the live one. Bank details never go in a reply.
EM-057 (Torque, invoice 1743) answers: paid 2026-03-09 by EFT, reference BRIM-EFT-26388945.

## Endpoints (`app/api/routes_intake.py`)
| Endpoint | Roles | Notes |
|---|---|---|
| `GET /intake/emails/{email_id}` | ap_clerk, finance_manager, controller_admin, auditor | 404 `email.not_found` |
| `GET /intake/files/{file_hash}` | same | content type sniffed from the bytes; PDF/images `inline`, anything else a download; `nosniff`; only hashes an intake item references; falls back to the dataset inbox (hash checked) |

The list `GET /intake/emails` belongs to the API module; it shows `suggested_action` through `review.action_for`.

## Original files
`files.keep` stores every file the pipeline reads under `backend/files/<sha256>` (gitignored, written atomically,
content-addressed so a resend costs nothing). At 100× volume this becomes object storage (S3) keyed the same way.

## How to change it safely
Add the failing email to `tests/intake/test_classifier.py` first (prefer a made-up variant over a dataset
email, to avoid overfitting), then add a generic keyword or rule.
