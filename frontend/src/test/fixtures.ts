/**
 * API response fixtures for the bill screens, shaped like the real responses (taken from the seeded and back-filled
 * database: AP-00407 duplicates AP-00394, AP-00004 is in USD). User ids match PICKER_USERS in fakeApi.ts.
 */
import type {
  BillDetail,
  BillFlag,
  BillSummary,
  BillsPage,
  ControlsRun,
  FlagHelp,
  GlAccount,
  VendorDetail,
  VendorSummary,
} from '../api/types'
import { DEPARTMENTS, PICKER_USERS, makeMe } from './fakeApi'

export const FLAG_HELP: Record<string, FlagHelp> = {
  DUPLICATE_EXACT: {
    title: 'Exact duplicate', severity: 'block',
    help: 'This invoice matches one already entered, so check whether it was paid before approving.',
  },
  PO_CLOSED_OR_WRONG_VENDOR: {
    title: 'PO closed or wrong vendor', severity: 'block',
    help: 'The PO is closed or belongs to another vendor, so confirm the right PO with the requester.',
  },
  FOREIGN_CURRENCY: {
    title: 'Foreign currency', severity: 'info', help: 'The bill is in USD and is converted at the rate shown.',
  },
  TAX_WRONG_FOR_PROVINCE: {
    title: 'Wrong tax for province', severity: 'warn',
    help: 'The taxes charged do not match the ship-to province, so ask the vendor for a corrected invoice.',
  },
  VENDOR_LOOKALIKE: {
    title: 'Lookalike vendor', severity: 'block',
    help: 'This vendor looks like another existing vendor, so call the real vendor before approving.',
  },
}

export const GL_ACCOUNTS: GlAccount[] = [
  { account_number: '5030', name: 'Warehouse supplies', account_type: 'expense' },
  { account_number: '5040', name: 'Packaging materials', account_type: 'expense' },
  { account_number: '6310', name: 'Legal fees', account_type: 'expense' },
]

export const VENDOR_SUMMARIES: VendorSummary[] = [
  {
    vendor_id: 'V011', legal_name: 'Summit Packaging Supply', category: 'Packaging', province_or_state: 'ON',
    country: 'CA', status: 'active', preferred_payment_method: 'EFT', payment_terms_days: 30, requires_po: true,
  },
  {
    vendor_id: 'V004', legal_name: 'Cascadia Cartage Ltd.', category: 'Freight & Carriers', province_or_state: 'BC',
    country: 'CA', status: 'active', preferred_payment_method: 'EFT', payment_terms_days: 30, requires_po: false,
  },
]

/** GET /vendors/{id} for V011 (only the fields the bill header reads matter). */
export function vendorDetail(overrides: Partial<VendorDetail> = {}): VendorDetail {
  return { ...VENDOR_SUMMARIES[0], ...overrides } as VendorDetail
}

/** A bill list row. */
export function billSummary(overrides: Partial<BillSummary> = {}): BillSummary {
  return {
    bill_id: 'AP-00407', status: 'scheduled', origin: 'history', vendor_id: 'V011',
    vendor_name: 'Summit Packaging Supply', vendor_invoice_number: '000804', invoice_date: '2026-10-03',
    due_date: '2026-11-02', received_date: '2026-10-10', currency: 'CAD', total: '2457.19', total_cad: '2457.19',
    is_credit_note: false, department_id: 'D01', requester_user_id: 'U013', row_version: 1,
    open_flags: { block: 2, warn: 0, info: 0 }, top_flag_code: 'PO_CLOSED_OR_WRONG_VENDOR', current_step: null,
    ...overrides,
  }
}

/** A page of bills. */
export function billsPage(items: BillSummary[], total = items.length, offset = 0): BillsPage {
  return { items, total, limit: 50, offset }
}

/** An open flag. */
export function flag(overrides: Partial<BillFlag> = {}): BillFlag {
  return {
    id: 89, code: 'DUPLICATE_EXACT', severity: 'block', field: 'invoice_number',
    message: 'Possible duplicate of AP-00394: same vendor, same invoice number 000804, total 2457.19 vs 2457.19.',
    evidence: { matches: ['AP-00394'], kinds: ['exact'], best_score: 1.0 }, resolution: 'open', resolved_by: null,
    resolved_at: null, resolution_comment: null, ...overrides,
  }
}

/** A controls run: AP-00407's, with a closed-PO flag, the duplicate flag and a one-step route. */
export function controlsRun(overrides: Partial<ControlsRun> = {}): ControlsRun {
  return {
    run_id: 401, version: 1, evaluated_at: '2026-11-02T15:00:00Z', can_auto_proceed: false,
    recommendation: 'Hold: PO PO-2026-0044 is closed and fully used.',
    flags: [
      flag({
        id: 88, code: 'PO_CLOSED_OR_WRONG_VENDOR', field: 'po_number', message: 'PO PO-2026-0044 is closed and fully used.',
        evidence: { po: 'PO-2026-0044', po_status: 'closed' },
      }),
      flag(),
    ],
    route: [{
      step_no: 1, role: 'dept_manager', user_id: 'U001', policy_ids: ['P01'], reason: 'Total $2,457.19 <= $10,000',
      delegated_from: null, escalated_from: null, decision: null, decided_by: null, decided_at: null,
    }],
    duplicates: [{ kind: 'exact', score: 1, matched_invoice_id: 'AP-00394', matched_card_txn_id: null, reasons: ['same vendor and number'] }],
    ...overrides,
  }
}

/** GET /bills/{id}: AP-00407 as the seeded database returns it. */
export function billDetail(overrides: Partial<BillDetail> = {}): BillDetail {
  return {
    ...billSummary(),
    subtotal: '2174.50', fx_rate_to_cad: '1', fx_rate_date: null, ship_to_province: 'ON', po_id: 'PO-2026-0044',
    contract_id: null, source_email_id: null, file_hash: null, created_at: '2026-10-10T00:00:00Z', created_by: null,
    updated_at: '2026-10-10T00:00:00Z', department_source: 'history', extracted: null,
    lines: [
      {
        line_no: 1, description: 'Racking components', quantity: '1', unit_price: '1538.65', amount: '1538.65',
        line_type: 'goods', gst_hst_code: 'HST13', pst_qst_code: null, gl_account: '5030', department_id: 'D01',
        suggested_gl_account: null, suggested_department_id: null, suggestion_confidence: null, suggestion_reason: null,
        coding_status: 'accepted', coded_by: null, coded_at: null,
      },
      {
        line_no: 2, description: 'Stretch wrap cases', quantity: '15', unit_price: '42.39', amount: '635.85',
        line_type: 'goods', gst_hst_code: 'HST13', pst_qst_code: null, gl_account: null, department_id: null,
        suggested_gl_account: '5040', suggested_department_id: 'D01', suggestion_confidence: 0.86,
        suggestion_reason: '5040 Packaging: 9 of 10 past lines from this vendor', coding_status: 'suggested',
        coded_by: null, coded_at: null,
      },
    ],
    taxes: [{ tax_code: 'HST13', rate: '0.13', amount: '282.69' }],
    latest_run: controlsRun(),
    decisions: [],
    payments: [{
      payment_id: 'PAY-00398', bill_id: 'AP-00407', vendor_id: 'V011', vendor_name: 'Summit Packaging Supply',
      method: 'EFT', currency: 'CAD', amount: '2457.19', amount_cad: '2457.19', scheduled_date: '2026-11-02',
      paid_date: null, status: 'scheduled', reference: null, prepared_by: 'U005', released_by: null, released_at: null,
    }],
    audit: [],
    allowed_actions: {},
    ...overrides,
  }
}

/** The routes every bill screen needs, signed in as `role`. */
export function billScreenRoutes(role: Parameters<typeof makeMe>[0] = {}) {
  return {
    'GET /auth/me': { body: makeMe(role) },
    'GET /auth/users': { body: PICKER_USERS },
    'GET /reference/departments': { body: DEPARTMENTS },
    'GET /reference/flag-help': { body: FLAG_HELP },
    'GET /reference/gl-accounts': { body: GL_ACCOUNTS },
    'GET /vendors': { body: { items: VENDOR_SUMMARIES, total: VENDOR_SUMMARIES.length, limit: 200, offset: 0 } },
    'GET /vendors/V011': { body: vendorDetail() },
  }
}
