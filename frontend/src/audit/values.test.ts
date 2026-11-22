import { describe, expect, it } from 'vitest'

import { EMPTY_VALUE, eventCurrency, formatAuditValue, type AuditValueContext } from './values'

/** A context for a bill event in CAD, with one known person and one known flag. */
function context(overrides: Partial<AuditValueContext> = {}): AuditValueContext {
  return {
    entityType: 'bill',
    currency: 'CAD',
    personLabel: (id) => (id === 'U004' ? 'Jordan Okafor (U004)' : id),
    flagTitle: (code) => (code === 'DUPLICATE_EXACT' ? 'Duplicate invoice' : code),
    ...overrides,
  }
}

/** The text lines of a formatted value (fails if it came out as JSON). */
function words(key: string, value: unknown, ctx = context()): string[] {
  const view = formatAuditValue(key, value, ctx)
  if (view.kind !== 'text') throw new Error(`expected text, got JSON for ${key}`)
  return view.lines
}

describe('audit values', () => {
  it('words statuses by the event entity, by the field name, or by any status kind', () => {
    expect(words('status', 'pending_approval')).toEqual(['Pending approval'])
    expect(words('status', 'on_hold', context({ entityType: 'vendor' }))).toEqual(['On hold'])
    expect(words('status', 'ok', context({ entityType: 'intake_item' }))).toEqual(['Done'])
    expect(words('status', 'on_leave', context({ entityType: 'user' }))).toEqual(['On leave'])
    // A rejected bank change is recorded on the vendor: the bank-change words still apply.
    expect(words('status', 'rejected', context({ entityType: 'vendor' }))).toEqual(['Rejected'])
    expect(words('vendor_status', 'on_hold')).toEqual(['On hold'])
    expect(words('resolution', 'overridden')).toEqual(['Overridden'])
    expect(words('status', 'something_new')).toEqual(['something_new'])
  })

  it('words roles, step roles, channels, severities, flag codes, entity types and payment methods', () => {
    expect(words('role', 'finance_manager')).toEqual(['Finance manager'])
    expect(words('role', 'controller_admin')).toEqual(['Controller / admin'])
    expect(words('step_role', 'cfo')).toEqual(['CFO'])
    expect(words('request_channel', 'email_request')).toEqual(['Email request'])
    expect(words('severity', 'warn')).toEqual(['Warning'])
    expect(words('code', 'DUPLICATE_EXACT')).toEqual(['Duplicate invoice'])
    expect(words('entity_type', 'intake_item')).toEqual(['Intake item'])
    expect(words('method', 'CHEQUE')).toEqual(['Cheque'])
  })

  it('names people with their id, or the id alone when the name is unknown', () => {
    expect(words('started_by', 'U004')).toEqual(['Jordan Okafor (U004)'])
    expect(words('delegate_user_id', 'U099')).toEqual(['U099'])
  })

  it('formats money in the event currency (CAD for _cad fields), dates, and timestamps in UTC', () => {
    expect(words('amount', '1604.60', context({ currency: 'USD' }))).toEqual(['US$1,604.60'])
    expect(words('amount_cad', '2200.00', context({ currency: 'USD' }))).toEqual(['$2,200.00'])
    expect(words('approval_limit_cad', '10000.00')).toEqual(['$10,000.00'])
    expect(words('scheduled_date', '2026-11-02')).toEqual(['Nov 2, 2026'])
    expect(words('verified_at', '2026-10-30T14:00:00Z')).toEqual(['Oct 30, 2026, 2:00 PM UTC'])
  })

  it('shows empty values as an em dash, booleans as Yes / No, and numbers and unknown text as stored', () => {
    for (const empty of [null, undefined, '', [], {}]) expect(words('anything', empty)).toEqual([EMPTY_VALUE])
    expect(words('final', true)).toEqual(['Yes'])
    expect(words('final', false)).toEqual(['No'])
    expect(words('line_no', 3)).toEqual(['3'])
    expect(words('file_name', 'scan.pdf')).toEqual(['scan.pdf'])
  })

  it('pretty-prints unknown objects and arrays as JSON, never "[object Object]"', () => {
    expect(formatAuditValue('filters', { action: 'auth.login' }, context()))
      .toEqual({ kind: 'json', text: '{\n  "action": "auth.login"\n}' })
    expect(formatAuditValue('files', ['a.pdf', 'b.pdf'], context()))
      .toEqual({ kind: 'json', text: '[\n  "a.pdf",\n  "b.pdf"\n]' })
  })

  it('writes a route one step per line, "unassigned" for a step with nobody on it', () => {
    expect(words('route', [
      { step_no: 1, role: 'dept_manager', user_id: 'U004' },
      { step_no: 2, role: 'finance_manager', user_id: null },
    ])).toEqual(['Step 1: Department manager, Jordan Okafor (U004)', 'Step 2: Finance manager, unassigned'])
  })

  it('takes the currency from after, then before, then CAD', () => {
    expect(eventCurrency({ currency: 'CAD' }, { currency: 'USD' })).toBe('USD')
    expect(eventCurrency({ currency: 'USD' }, {})).toBe('USD')
    expect(eventCurrency({}, {})).toBe('CAD')
  })
})
