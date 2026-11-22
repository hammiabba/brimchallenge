# shared/

**Owner:** whole team. **Changes need agreement from all four people.**

`schemas.py` is the data contract between the intake and extraction modules, the controls module and the database
and API modules.
Everyone imports these models; nobody defines a parallel version.

| Model | Produced by | Consumed by |
|---|---|---|
| `EmailTriage` | `intake.classifier.classify` | API, UI inbox view |
| `DraftBill` (+ `VendorOnInvoice`, `InvoiceLine`, `TaxLine`, `CodingSuggestion`, `SourceInfo`) | `extraction.pipeline.extract` + `coding.suggest` | controls, DB, UI |
| `Flag`, `DuplicateMatch`, `ApprovalStep`, `ControlsResult`, `PermissionDecision` | controls | DB, UI |
| `AuditEvent` | the db module's `log_event()` | auditor UI |
| `FLAG_CODES` | agreed catalogue | controls, UI icons/help text |

## Conventions
- Money is `Decimal` (never float), in invoice currency unless the field ends in `_cad`.
- Dates are `datetime.date`; "today" is `AS_OF_DATE` from config (2026-11-02).
- IDs reuse dataset IDs (`V001`, `U007`, `D01`, `PO-2026-0001`, `C018`).

## How to change it
1. Propose the change in the team chat with the reason.
2. Make it additive if possible (new optional field with a default) so nobody's code breaks.
3. Merge it in its own small PR, then everyone rebases.
