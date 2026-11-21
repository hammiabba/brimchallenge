# Detection coverage

The brief says the data includes "real-world mess" and that finding it is part of the job. This page lists each
item from that list, the flags that catch it and one example bill. It also lists what nothing catches, and why.
Owner: Person B (controls).

**How this was produced.** All 56 incoming files went through the real pipeline: email triage, extraction
(replaying the model output recorded in `backend/tests/fixtures/raw/`, so there are no API calls) and
`run_controls` on all 56 bills as one batch, like `backend/scripts/run_incoming.py`. Items the batch has no example
of come from the history replay (`backend/scripts/replay_history.py`), where each historical invoice is judged as of
its own date. Result: 24 hold, 10 review, 22 can proceed, $110,405.03 CAD on hold.

**Kept honest by a test.** [`backend/tests/controls/test_detection_coverage.py`](../backend/tests/controls/test_detection_coverage.py)
runs the batch the same way and fails if any example below stops getting its flag. It also fails if this page stops
listing an example. When you change a row here, change the same row in the test.

Severity: **block** holds the bill until someone fixes or overrides the flag, **warn** needs a look and
**info** is a note.

## Covered

| Brief item | Flag(s) | Example | What the engine says |
|---|---|---|---|
| duplicates | `DUPLICATE_EXACT` (block) | `Invoice 000961.pdf` (Polar), `harlowsternllp_001468.pdf`, `cloudbarnsoftwar_INV01561.pdf` | Same vendor and invoice number as paid history bills AP-00393, AP-00389, AP-00370. |
| | `ALREADY_PAID_BY_CARD` (block) | history AP-00015 (Paper Trail) | Already charged to an employee card (CT-00017). The history replay finds 5 such double payments. |
| near-duplicates | `DUPLICATE_EXACT` (block), after the invoice number is normalized | `voyageurcorporat-inv-017.pdf` "000903-A", `brightlinesafety-inv-032.pdf` "583" | Same as history 000903 (AP-00277) and FA-000583 (AP-00330) once prefixes, suffixes and leading zeros are removed. |
| | `DUPLICATE_LIKELY` (warn) | none (see below) | Same vendor, close amount and date, with a similar invoice number or the same service month. Also a different vendor with the same bank account. |
| over-contract price | `OVER_CONTRACT_RATE` (warn) | `Invoice AU26-2207.pdf` (Aurora), `pineconecollabor_PI262809.pdf` | Fee billed $2,343.50 vs $2,150.00 in C008, and $826.80 vs $780.00 in C003. |
| | `OVER_FUEL_SURCHARGE_CAP` (warn) | `Invoice 000964.pdf` (Polar) | Fuel surcharge 22% of freight, while C018 caps it at 12%. |
| | `OVER_CONTRACT_NTE` (warn) | `redlinefleetcard-inv-044.pdf` | This month's billing would reach $9,946.54, over the $9,000 monthly limit in C027. |
| | `CONTRACT_EXPIRED` (warn) | `torqueindustrial_1771.pdf` | Contract C025 ended 2026-06-30. |
| wrong tax | `TAX_WRONG_FOR_PROVINCE` (block) | `northboundcourie_000639.pdf` | Ships to AB but charged HST 13%, expected GST 5%. |
| | `TAX_MISSING` (block) | `beaumontrivieres_FA000557.pdf`, `ironwoodpalletco-inv-048.pdf` | QC delivery with no QST, and ON delivery with no tax at all. |
| | `PST_ON_SERVICES` (warn) | `signalsparrowcre_000970.pdf` | BC PST charged on services (PST is for goods only). |
| | `GST_NUMBER_MISSING` (warn) | `riverbendcaterin_1739.pdf` | No GST/HST number on file or on the invoice: confirm it's a small supplier. No tax flag, since a small supplier charges none. |
| changed bank details | `BANK_CHANGE_UNVERIFIED` (block) | `cascadiacartagel_1625.pdf`, `scan_8049.png` (Cascadia) | Bank account changed on 2026-10-27 by email, never verified by callback. |
| | `BANK_DETAILS_MISMATCH` (block) | `scan_8049.png`, `lumenprintsignag_FA001761.pdf` | The invoice shows an account that was only set up after the invoice's date, so it was likely edited. |
| split invoices | `POSSIBLE_SPLIT` (warn) | `orionstrategypar-inv-029.pdf`, `orionstrategypar_281.pdf`, `Invoice 287.pdf` (Orion 279, 281, 287) | 3 invoices within 3 days, each under $10,000 but $14,543.10 together, routed as one bill. Cascadia's 3 bills are flagged the same way. |
| unknown or unapproved vendors | `VENDOR_NOT_FOUND` (block) | `Invoice 4443.pdf` (Blue Heron), `zephyrdataservic_7590.pdf` | Not in the vendor master. |
| | `VENDOR_PENDING_REVIEW` (warn) | `riverbendcaterin_1739.pdf` | Vendor still pending review, so a finance manager step is added (P05). |
| | `VENDOR_LOOKALIKE` (block) | `Invoice HA26-2766.pdf` "Harlow and Stern LLP" (V052) | Looks like existing vendor V026 "Harlow & Stern LLP". |
| | `VENDOR_NOT_ACTIVE` (block) | history AP-00109 (V053) | Vendor is `on_hold` in the master. |
| USD invoices | `FOREIGN_CURRENCY` (info) | `sparkgridcrminc_FA002342.pdf`, `tesseraanalytics-inv-050.pdf` | USD converted to CAD at the rate for the invoice date. Limits and routing use the CAD amount. |
| | `CURRENCY_UNSUPPORTED` (block) | none (see below) | No rate for the currency or date, so the CAD amount is unknown. |
| credit notes | `CREDIT_NOTE` (info) | `fixwellfacilitys_CNFA000413.pdf`, `greatlakescarrie-inv-025.pdf` | Negative amount: apply it against an open invoice, don't pay it. The approval route treats it differently too. |
| odd dates | `DATE_ANOMALY` (warn) | `Invoice 000809.pdf` (Summit), `lumenprintsignag_FA001761.pdf` | Dated 2026-11-27, after today (2026-11-02), and 210 days old. A due date before the invoice date is also flagged. |
| PO problems | `PO_REQUIRED_MISSING` (block) | `keystonerackings-inv-002.pdf` (10 bills in the batch) | Vendor requires a PO and the invoice has none. |
| | `PO_CLOSED_OR_WRONG_VENDOR` (block) | history AP-00224 (Alpenglow) | PO-2026-0027 is closed and fully used. |
| | `PO_OVER_BALANCE` (warn) | history AP-00159 | Over the PO's remaining balance, so a finance manager step is added (P12). |
| | `PO_NOT_FOUND` (block) | none (see below) | PO number doesn't exist. |
| self-approval | no flag: the approval route and `can_approve` | history AP-00092 (requested and approved by U010) | The route skips the requester and escalates to their manager (P07), and `can_approve` refuses them. The history replay finds 3 past self-approvals (AP-00092, AP-00178, AP-00235). |
| arithmetic errors | `TOTAL_MISMATCH` (block) | `evergreenenergyu_000850.pdf` | 3,180.00 + 159.00 = 3,339.00, but the total says 3,439.00. |
| | `LINE_MATH_ERROR` (block) | `northstarmediabu_NO261773.pdf` | 24 × 150.00 = 3,600.00, but the line says 3,800.00. |
| | `SUBTOTAL_MISMATCH` (block) | none (see below) | Lines don't add up to the subtotal. |
| low-quality scans | `LOW_EXTRACTION_CONFIDENCE` (warn) | `scan_8749.png` (Prairie Natural Gas), `scan_8049.png` (Cascadia) | Read from a scanned image, with extraction notes: check the vendor, invoice number, date, amounts and bank details against the image. It also fires on any key field read below 0.7 confidence, and names those fields. Both scans otherwise get the same checks as any bill: Cascadia's bank flags above come from its scan. |

## Not caught, or only partly

1. **Scans: a misread that looks plausible.** `LOW_EXTRACTION_CONFIDENCE` (warn) now marks a bill when a key
   field is below 0.7 confidence, or when a scan has extraction notes. It tells the approver to check the bill
   against the image, but it doesn't find the misread itself.

   A misread GST number or bank account is caught because it no longer matches the vendor master
   (`GST_NUMBER_MISMATCH`, `BANK_DETAILS_MISMATCH`). So is a misread amount that breaks the arithmetic. A misread
   amount that still adds up, or a misread date, is only covered by that warning and the clerk's review. Both scans
   in the batch were read correctly.

   A clean scan with no extraction notes isn't flagged. Its fields score 0.75, above the threshold. In this batch
   tesseract isn't installed, so both scans were read by the vision model, which leaves a note. With tesseract, a
   clean OCR read leaves none, and the only marker left is `was_ocr` on the bill.

2. **Self-approval can't be spotted at intake.** Invoices don't print who requested them, so no incoming bill has a
   requester, and the "terminated requester" check (`REQUESTER_TERMINATED`) can't fire on them either. Both are
   enforced once someone sets the requester and the bill is routed, as shown above. That's by design: it's a rule
   about people, checked when the approval happens.

3. **Near-duplicates with a different number or amount have no real example.** Both near-duplicates in the batch
   are caught as exact duplicates, because the invoice number is normalized first. `DUPLICATE_LIKELY` (close amount
   and date with a similar number or the same service month) never fires in the batch or the history, so its thresholds are only
   tested on made-up bills in `test_duplicates.py`. The hidden batch may need them tuned.

4. **Flags with no example in the data, tested only on made-up bills:** `SUBTOTAL_MISMATCH` and `GST_NUMBER_MISMATCH`
   (`test_validate.py`), `PO_NOT_FOUND`, `CURRENCY_UNSUPPORTED`, `SENDER_DOMAIN_MISMATCH` and `REQUESTER_TERMINATED`
   (`test_flag_codes.py`), and the "due date before invoice date" case of `DATE_ANOMALY` (`test_validate.py`).
   They work in tests, but the real data never triggers them.

5. **Lookalike vendor records in the master aren't checked on their own.** V051 "Polar Freight Lines Limited" and
   V053 "Great Lakes Carriers Incorporated" are only caught when a bill is booked to them. The history replay shows
   that happening (`VENDOR_LOOKALIKE` on 5 history bills). The controls check bills, not the vendor master, so a
   lookalike record with no bills yet isn't reported.

6. **Odd dates the engine doesn't look for:** weekend or holiday invoice dates, and a due date that doesn't match the
   vendor's payment terms. Every incoming bill's due date matches its vendor's terms, so nothing is missed in this
   batch.

## Checked and correctly not flagged

- **Queen Street rent** (`Invoice 002935.pdf`, $18,758 every month) is contract rent, not a duplicate. The
  recurring-vendor rule needs the same service month.
- **Orion's 3 invoices** come to $14,543.10, under C023's $25,000 monthly limit. They're flagged as a possible split,
  not as over the contract.
- **Cloudbarn INV-01561** was paid through an AP virtual card, which is the normal AP payment. `DUPLICATE_EXACT` is the
  right flag. `ALREADY_PAID_BY_CARD` is for employee card charges.
- **Harlow and Stern's email** (EM-026) comes from V052's own domain, so `SENDER_DOMAIN_MISMATCH` doesn't fire. The
  lookalike vendor is caught by `VENDOR_LOOKALIKE` instead.
