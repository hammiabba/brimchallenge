import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { BillDetail, BillSummary } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billDetail, billScreenRoutes, billSummary, billsPage, controlsRun } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const FINANCE = { role: 'finance_manager', user_id: 'U003', full_name: 'Priya Natarajan', approval_limit_cad: '50000.00' } as const
const APPROVER = { role: 'approver', user_id: 'U001', full_name: 'Morgan Lee', approval_limit_cad: '10000.00' } as const

/** A pending bill whose current step is U003's, signed as the delegate of U012 (on leave). */
function delegated(overrides: Partial<BillSummary> = {}): BillSummary {
  return billSummary({
    bill_id: 'AP-00433', status: 'pending_approval', origin: 'app', vendor_id: 'V040',
    vendor_name: 'Lakeshore Hydro Services', vendor_invoice_number: 'DM-1007', total: '2101.80', total_cad: '2101.80',
    department_id: 'D04', open_flags: { block: 0, warn: 1, info: 0 }, top_flag_code: null,
    current_step: { step_no: 1, role: 'dept_manager', user_id: 'U003', delegated_from: 'U012' },
    ...overrides,
  })
}

/** A pending bill at its second step (finance manager), U003's own. */
const SECOND_STEP = billSummary({
  bill_id: 'AP-00434', status: 'pending_approval', origin: 'app', vendor_name: 'Great Lakes Carriers Inc.',
  vendor_invoice_number: 'DM-1008', total: '13334.00', total_cad: '13334.00', open_flags: { block: 0, warn: 0, info: 0 },
  top_flag_code: null, current_step: { step_no: 2, role: 'finance_manager', user_id: 'U003', delegated_from: null },
})

/** GET /bills/{id} for a pending app bill on step 1 of 2, with the given allowed_actions. */
function pendingDetail(actions: BillDetail['allowed_actions'], summary: BillSummary = delegated()): BillDetail {
  return billDetail({
    ...summary,
    row_version: 3,
    latest_run: controlsRun({
      flags: [],
      route: [
        { step_no: 1, role: 'dept_manager', user_id: 'U003', policy_ids: ['P01', 'P08'], reason: 'Delegate of U012',
          delegated_from: 'U012', escalated_from: null, decision: null, decided_by: null, decided_at: null },
        { step_no: 2, role: 'finance_manager', user_id: 'U003', policy_ids: ['P02'], reason: 'Over $10,000',
          delegated_from: null, escalated_from: null, decision: null, decided_by: null, decided_at: null },
      ],
    }),
    payments: [],
    allowed_actions: actions,
  })
}

const MAY_DECIDE = {
  approve: { allowed: true, reason: 'Step 1 (dept_manager) is yours, as delegate for U012.' },
  reject: { allowed: true, reason: 'Step 1 (dept_manager) is yours, as delegate for U012.' },
}

describe('my approvals', () => {
  it('lists the bills waiting for me, marking the ones I sign as a delegate', async () => {
    installFakeApi({ ...billScreenRoutes(FINANCE), 'GET /approvals/queue': { body: [delegated(), SECOND_STEP] } })
    renderApp('/approvals')

    expect(await screen.findByRole('heading', { level: 1, name: 'My approvals' })).toBeInTheDocument()
    expect(screen.getByText('$50,000.00')).toBeInTheDocument() // the limit line
    const table = await screen.findByRole('table', { name: 'My approvals' })
    const row = (await within(table).findByText('AP-00433')).closest('tr')!
    expect(within(row).getByRole('link', { name: 'AP-00433' })).toHaveAttribute('href', '/bills/AP-00433')
    expect(within(row).getByText('Lakeshore Hydro Services')).toBeInTheDocument()
    expect(within(row).getByText('$2,101.80')).toBeInTheDocument()
    expect(within(row).getByText('Step 1, Department manager')).toBeInTheDocument()
    expect(await within(row).findByText('Acting for Sam Rivera')).toBeInTheDocument()

    const own = within(table).getByText('AP-00434').closest('tr')!
    expect(within(own).getByText('Step 2, Finance manager')).toBeInTheDocument()
    expect(within(own).queryByText(/Acting for/)).not.toBeInTheDocument()
    expect(screen.getByText('2 bills waiting')).toBeInTheDocument()
  })

  it('says when nothing is waiting', async () => {
    installFakeApi({ ...billScreenRoutes(APPROVER), 'GET /approvals/queue': { body: [] } })
    renderApp('/approvals')
    expect(await screen.findByText('No bills are waiting for your decision.')).toBeInTheDocument()
  })

  it('shows the server\'s message when the queue can\'t load', async () => {
    installFakeApi({
      ...billScreenRoutes(APPROVER),
      'GET /approvals/queue': { status: 403, body: envelope('auth.forbidden_role', "Your role (auditor) can't do this.", 'rid-q-1') },
    })
    renderApp('/approvals')
    expect(await screen.findByText("Your role (auditor) can't do this.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-q-1')).toBeInTheDocument()
  })
})

describe('approve and reject on the bill screen', () => {
  it('has no buttons when allowed_actions doesn\'t allow a decision', async () => {
    installFakeApi({
      ...billScreenRoutes(APPROVER),
      'GET /bills/AP-00433': { body: pendingDetail({
        approve: { allowed: false, reason: 'This step is assigned to U003.' },
        reject: { allowed: false, reason: 'This step is assigned to U003.' },
      }) },
    })
    renderApp('/bills/AP-00433')
    expect(await screen.findByRole('heading', { level: 1, name: 'Bill AP-00433' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
  })

  it('approves as a delegate, sending the row version, and refreshes the bill', async () => {
    let sent: unknown = null
    let current = pendingDetail(MAY_DECIDE)
    const fake = installFakeApi({
      ...billScreenRoutes(FINANCE),
      'GET /bills/AP-00433': () => ({ body: current }),
      'POST /bills/AP-00433/approve': async (request) => {
        sent = await request.json()
        current = pendingDetail({}) // step 2 is next: nothing more for this user to decide right now
        return { body: current }
      },
    })
    const user = userEvent.setup()
    renderApp('/bills/AP-00433')

    const bar = await screen.findByRole('region', { name: 'Your decision' })
    expect(within(bar).getByText('Step 1, Department manager, is waiting for you')).toBeInTheDocument()
    expect(await within(bar).findByText('Acting for Sam Rivera: your decision is recorded on their behalf.')).toBeInTheDocument()

    await user.click(within(bar).getByRole('button', { name: 'Approve' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve bill' })
    expect(within(dialog).getByText('The bill moves on to the next step of its approval route.')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Approve bill' }))

    await waitFor(() => expect(sent).toEqual({ row_version: 3, comment: null }))
    expect(await screen.findByText('Bill approved')).toBeInTheDocument()
    // The new detail has no decision allowed, so the buttons go away.
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Your decision' })).not.toBeInTheDocument())
    expect(fake.calls).toContain('POST /bills/AP-00433/approve')
  })

  it('needs a comment to reject, and shows a refusal from the server', async () => {
    let sent: unknown = null
    installFakeApi({
      ...billScreenRoutes(FINANCE),
      'GET /bills/AP-00433': { body: pendingDetail(MAY_DECIDE) },
      'POST /bills/AP-00433/reject': async (request) => {
        sent = await request.json()
        return {
          status: 409,
          body: envelope('conflict.stale', 'This bill was changed by someone else. Reload it and try again.', 'rid-rj-1'),
        }
      },
    })
    const user = userEvent.setup()
    renderApp('/bills/AP-00433')

    await user.click(await screen.findByRole('button', { name: 'Reject' }))
    const dialog = await screen.findByRole('dialog', { name: 'Reject bill' })
    const confirm = within(dialog).getByRole('button', { name: 'Reject bill' })
    expect(confirm).toBeDisabled()
    expect(within(dialog).getByText('Required. Kept in the audit log.')).toBeInTheDocument()

    await user.type(within(dialog).getByRole('textbox', { name: /Comment/ }), 'Not our shipment')
    expect(confirm).toBeEnabled()
    await user.click(confirm)

    await waitFor(() => expect(sent).toEqual({ row_version: 3, comment: 'Not our shipment' }))
    expect(await within(dialog).findByText('Changed by someone else')).toBeInTheDocument()
    expect(within(dialog).getByText('This bill was changed by someone else. Reload it and try again.')).toBeInTheDocument()
    expect(within(dialog).getByText('Request id: rid-rj-1')).toBeInTheDocument()
  })

  it('says it is the last step when approving the final one', async () => {
    installFakeApi({
      ...billScreenRoutes(FINANCE),
      'GET /bills/AP-00434': { body: pendingDetail(MAY_DECIDE, SECOND_STEP) },
    })
    const user = userEvent.setup()
    renderApp('/bills/AP-00434')
    await user.click(await screen.findByRole('button', { name: 'Approve' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve bill' })
    expect(within(dialog).getByText(/This is the last step/)).toBeInTheDocument()
  })
})

describe('unassigned steps', () => {
  const UNASSIGNED = delegated({
    bill_id: 'AP-00440', vendor_name: 'ClearView Janitorial', department_id: 'D01', requester_user_id: 'U001',
    row_version: 2, current_step: { step_no: 1, role: 'dept_manager', user_id: null, delegated_from: null },
  })

  it('lists only pending bills whose current step has no approver', async () => {
    const fake = installFakeApi({
      ...billScreenRoutes(FINANCE),
      'GET /bills': { body: billsPage([UNASSIGNED, delegated(), SECOND_STEP]) },
    })
    renderApp('/unassigned-steps')

    const table = await screen.findByRole('table', { name: 'Unassigned steps' })
    const row = (await within(table).findByText('AP-00440')).closest('tr')!
    expect(within(row).getByText('Step 1, Department manager')).toBeInTheDocument()
    expect(await within(row).findByText('Operations (D01)')).toBeInTheDocument()
    expect(await within(row).findByText('Morgan Lee')).toBeInTheDocument()
    expect(within(table).queryByText('AP-00433')).not.toBeInTheDocument()
    expect(within(table).queryByText('AP-00434')).not.toBeInTheDocument()
    expect(screen.getByText('1 step need an approver')).toBeInTheDocument()
    const url = fake.urls.find((u) => u.pathname === '/api/bills')!
    expect(url.searchParams.get('status')).toBe('pending_approval')
    expect(url.searchParams.get('limit')).toBe('200')
  })

  it('assigns someone whose role may sign the step, never the requester', async () => {
    let sent: unknown = null
    installFakeApi({
      ...billScreenRoutes(FINANCE),
      'GET /bills': { body: billsPage([UNASSIGNED]) },
      'POST /bills/AP-00440/route/1/assign': async (request) => {
        sent = await request.json()
        return { body: pendingDetail({}, { ...UNASSIGNED, current_step: { ...UNASSIGNED.current_step!, user_id: 'U002' } }) }
      },
    })
    const user = userEvent.setup()
    renderApp('/unassigned-steps')

    await user.click(await screen.findByRole('button', { name: 'Assign' }))
    const dialog = await screen.findByRole('dialog', { name: 'Assign approver' })
    expect(within(dialog).getByRole('button', { name: 'Assign approver' })).toBeDisabled()
    await user.click(within(dialog).getByRole('combobox', { name: 'Approver' }))
    // Approvers, the finance manager and the controller may sign a department manager step; the requester (Morgan
    // Lee), people on leave and other roles are left out.
    const options = (await screen.findAllByRole('option')).map((o) => o.textContent)
    expect(options).toEqual([
      'Priya Natarajan, Finance Manager (U003)',
      'Elena Duarte, Controller (U002)',
    ])
    await user.click(screen.getByRole('option', { name: 'Elena Duarte, Controller (U002)' }))
    await user.click(within(dialog).getByRole('button', { name: 'Assign approver' }))

    await waitFor(() => expect(sent).toEqual({ row_version: 2, user_id: 'U002' }))
    expect(await screen.findByText('Approver assigned')).toBeInTheDocument()
  })

  it('shows the server\'s refusal in the dialog', async () => {
    installFakeApi({
      ...billScreenRoutes(FINANCE),
      'GET /bills': { body: billsPage([UNASSIGNED]) },
      'POST /bills/AP-00440/route/1/assign': {
        status: 409, body: envelope('route_step.already_assigned', 'Step 1 is already assigned to U002.', 'rid-as-1'),
      },
    })
    const user = userEvent.setup()
    renderApp('/unassigned-steps')

    await user.click(await screen.findByRole('button', { name: 'Assign' }))
    const dialog = await screen.findByRole('dialog', { name: 'Assign approver' })
    await user.click(within(dialog).getByRole('combobox', { name: 'Approver' }))
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan, Finance Manager (U003)' }))
    await user.click(within(dialog).getByRole('button', { name: 'Assign approver' }))
    expect(await within(dialog).findByText('Step 1 is already assigned to U002.')).toBeInTheDocument()
  })

  it('has no Assign button for a role that can\'t assign', async () => {
    installFakeApi({ ...billScreenRoutes({ role: 'auditor', user_id: 'U015' }), 'GET /bills': { body: billsPage([UNASSIGNED]) } })
    renderApp('/unassigned-steps')
    const table = await screen.findByRole('table', { name: 'Unassigned steps' })
    await within(table).findByText('AP-00440')
    expect(within(table).queryByRole('button', { name: 'Assign' })).not.toBeInTheDocument()
    expect(within(table).queryByText('Actions')).not.toBeInTheDocument()
  })

  it('says when no step needs an approver', async () => {
    installFakeApi({ ...billScreenRoutes(FINANCE), 'GET /bills': { body: billsPage([delegated()]) } })
    renderApp('/unassigned-steps')
    expect(await screen.findByText('No approval step is waiting for an approver.')).toBeInTheDocument()
  })
})
