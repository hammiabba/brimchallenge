import { describe, expect, it } from 'vitest'

import type { AuditEvent } from '../api/types'
import { auditActor, auditChanges, auditFieldLabel, auditSentence, type AuditContext } from './auditText'

const NAMES: Record<string, string> = { U003: 'Elise Tremblay', U004: 'Jordan Okafor', U007: 'Dev Malhotra', U013: 'Aiden Grant' }
const CONTEXT: AuditContext = {
  personLabel: (id) => (NAMES[id] ? `${NAMES[id]} (${id})` : id),
  flagTitle: (code) => ({ DUPLICATE_EXACT: 'Duplicate invoice' } as Record<string, string>)[code] ?? code,
}

/** An audit event with defaults; payloads as the services write them. */
function event(action: string, after: Record<string, unknown> | null, before: Record<string, unknown> | null = null,
  extra: Partial<AuditEvent> = {}): AuditEvent {
  return {
    seq: 1, event_id: 'e1', at: '2026-11-02T15:00:00Z', actor_user_id: 'U004', actor_role: 'ap_clerk',
    on_behalf_of: null, action, entity_type: 'bill', entity_id: 'AP-00427', before, after, comment: null,
    request_id: null, ...extra,
  }
}

describe('auditSentence', () => {
  it('says how a bill was created', () => {
    expect(auditSentence(event('bill.created', { file_name: 'inv.pdf', email_id: 'EM-031', started_by: 'U004' }), CONTEXT))
      .toBe('Created from email EM-031 (inv.pdf).')
    expect(auditSentence(event('bill.created', { file_name: 'inv.pdf', email_id: null }), CONTEXT))
      .toBe('Created from an upload (inv.pdf).')
  })

  it('names the fields an update changed', () => {
    expect(auditSentence(event('bill.updated', { department_id: 'D02', due_date: '2026-12-01' }), CONTEXT))
      .toBe('Updated the department and due date.')
    expect(auditSentence(event('bill.updated', { po_id: 'PO-1' }), CONTEXT)).toBe('Updated the PO.')
  })

  it('describes coding, flags, submission and decisions', () => {
    expect(auditSentence(event('bill.coding_changed', { line_no: 2, gl_account: '5040', department_id: 'D01',
      coding_status: 'accepted' }), CONTEXT)).toBe('Coded line 2 to GL 5040 and department D01, accepting the suggestion.')
    expect(auditSentence(event('bill.coding_changed', { line_no: 1, gl_account: '6310', department_id: 'D04',
      coding_status: 'overridden' }), CONTEXT)).toBe('Coded line 1 to GL 6310 and department D04, changing the suggestion.')
    expect(auditSentence(event('bill.flag_overridden', { code: 'DUPLICATE_EXACT', resolution: 'overridden' }), CONTEXT))
      .toBe('Overrode the "Duplicate invoice" flag.')
    expect(auditSentence(event('bill.flag_resolved', { resolution: 'resolved' }), CONTEXT)).toBe('Resolved a flag.')
    expect(auditSentence(event('bill.submitted', { status: 'pending_approval',
      route: [{ step_no: 1, role: 'dept_manager', user_id: 'U007' }] }), CONTEXT))
      .toBe('Submitted for approval; step 1 goes to Dev Malhotra (U007).')
    expect(auditSentence(event('bill.approved', { status: 'pending_approval', step_no: 1, step_role: 'dept_manager',
      final: false }), CONTEXT)).toBe('Approved step 1 (Department manager).')
    expect(auditSentence(event('bill.approved', { status: 'approved', step_no: 2, step_role: 'finance_manager',
      final: true }), CONTEXT)).toBe('Approved step 2 (Finance manager). Final approval: the bill is approved.')
    expect(auditSentence(event('bill.rejected', { status: 'rejected', step_no: 1 }), CONTEXT)).toBe('Rejected at step 1.')
    expect(auditSentence(event('bill.voided', { status: 'void' }), CONTEXT)).toBe('Voided the bill.')
    expect(auditSentence(event('bill.step_assigned', { step_no: 2, user_id: 'U003' }), CONTEXT))
      .toBe('Assigned step 2 to Elise Tremblay (U003).')
  })

  it('describes payments, with money in its currency', () => {
    expect(auditSentence(event('payment.scheduled', { bill_id: 'AP-00436', amount: '1604.60', currency: 'CAD',
      scheduled_date: '2026-11-02', method: 'EFT' }), CONTEXT)).toBe('Scheduled a payment of $1,604.60 by EFT for Nov 2, 2026.')
    expect(auditSentence(event('payment.released', { status: 'released', amount_cad: '7024.81',
      reference: 'EFT-SIM-123456' }), CONTEXT)).toBe('Released the payment of $7,024.81 (reference EFT-SIM-123456).')
    expect(auditSentence(event('payment.cancelled', { status: 'cancelled' }), CONTEXT)).toBe('Cancelled the payment.')
  })

  it('has no sentence for other actions', () => {
    expect(auditSentence(event('intake.already_received', { file_name: 'x.pdf' }), CONTEXT)).toBeNull()
  })
})

describe('auditActor', () => {
  it('names a person with their id, and whom a delegate acted for', () => {
    expect(auditActor(event('bill.approved', {}, null, { actor_user_id: 'U003', on_behalf_of: 'U007' }), CONTEXT))
      .toEqual({ who: 'Elise Tremblay (U003)', onBehalfOf: 'Dev Malhotra (U007)' })
  })

  it('says whom the system acted for when the event names a user', () => {
    expect(auditActor(event('bill.created', { started_by: 'U013' }, null, { actor_user_id: 'system' }), CONTEXT))
      .toEqual({ who: 'System, for Aiden Grant (U013)', onBehalfOf: null })
    expect(auditActor(event('bill.rechecked', {}, null, { actor_user_id: 'system' }), CONTEXT))
      .toEqual({ who: 'System', onBehalfOf: null })
  })
})

describe('auditChanges', () => {
  it('lists changed values with readable labels, leaving out empty and unchanged ones', () => {
    const rows = auditChanges(event('bill.created', {
      intake_item_id: 7, file_name: 'inv.pdf', email_id: null, started_by: 'U013', status: 'needs_review',
      department_id: 'D01', warnings: [],
    }), CONTEXT)
    expect(rows.map((r) => [r.label, r.after])).toEqual([
      ['Intake item', ['7']], ['File', ['inv.pdf']], ['Started by', ['Aiden Grant (U013)']], ['Status', ['Needs review']],
      ['Department', ['D01']],
    ])
    const approved = auditChanges(event('bill.approved', { status: 'approved', step_no: 1 },
      { status: 'pending_approval', step_no: 1 }), CONTEXT)
    expect(approved).toEqual([{ key: 'status', label: 'Status', before: ['Pending approval'], after: ['Approved'] }])
  })

  it('formats money and dates, and lists a route one step per line', () => {
    const rows = auditChanges(event('payment.scheduled', { amount: '1604.60', currency: 'USD', scheduled_date: '2026-11-02' }), CONTEXT)
    expect(rows).toEqual([
      { key: 'amount', label: 'Amount', after: ['US$1,604.60'] },
      { key: 'scheduled_date', label: 'Scheduled date', after: ['Nov 2, 2026'] },
    ])
    const route = auditChanges(event('bill.submitted', { route: [
      { step_no: 1, role: 'dept_manager', user_id: 'U007' }, { step_no: 2, role: 'finance_manager', user_id: null },
    ] }), CONTEXT)
    expect(route[0]!.after).toEqual(['Step 1, Department manager: Dev Malhotra (U007)', 'Step 2, Finance manager: unassigned'])
  })

  it('humanises field labels', () => {
    expect(auditFieldLabel('department_id')).toBe('Department')
    expect(auditFieldLabel('due_date')).toBe('Due date')
    expect(auditFieldLabel('line_no')).toBe('Line')
    expect(auditFieldLabel('gl_account')).toBe('GL account')
  })
})
