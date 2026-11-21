# intake/

**Owner:** Person A. Feature 1: emails and uploads in, triage + draft bills out.

## Public API
| Function | Returns |
|---|---|
| `classifier.classify(email, client=None)` | `EmailTriage` (class, attachments to process, human-readable reason) |
| `classifier.classify_rules(email)` | `EmailTriage` or `None` when the rules aren't sure |
| `inbox.load_emails(path=None)` | list of email dicts (`DATASET_DIR/inbox/emails.json` by default) |
| `inbox.process_inbox(emails, attachments_dir=None, repo=None, client=None)` | `[(EmailTriage, [ExtractionOutcome, ...])]` |
| `upload.process_upload(file_bytes, filename)` | `DraftBill` |

## Classification rules (in order)
1. Promotional wording, no invoice wording or file → `not_ap`
2. "Statement of account" / "relevé de compte" → `statement` (never creates bills)
3. Asks about a payment and has no file → `payment_inquiry`
4. Has PDF/image attachments → `credit_note` (credit wording or a `CN-` number) or `invoice`. **One bill per attachment.**
5. Mentions an attachment or invoice but has none → `missing_attachment` (the clerk asks the vendor to resend)
6. Otherwise: LLM tie-break if an API key is set, else `not_ap`

Subject and body are scanned together with **both** English and French keywords, because they can be in different languages.
`sender_address` is passed into every `DraftBill.source` so controls can detect lookalike domains.

## How to change it safely
Add the failing email to `tests/intake/test_classifier.py` first (prefer a made-up variant over a dataset
email, to avoid overfitting), then add a generic keyword or rule.
