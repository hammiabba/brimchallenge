import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { BillDetail } from '../api/types'
import { envelope, installFakeApi, type FakeRoute } from '../test/fakeApi'
import { billDetail, billScreenRoutes } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const CLERK = { role: 'ap_clerk', user_id: 'U005' } as const
const ALLOWED = { allowed: true, reason: null }

/** AP-00407 as an app bill in review, with the given allowed_actions (everything AP may do, by default). */
function inReview(overrides: Partial<BillDetail> = {}): BillDetail {
  return billDetail({
    status: 'needs_review', origin: 'app', row_version: 4, payments: [],
    allowed_actions: { edit: ALLOWED, code_lines: ALLOWED, resolve_flags: ALLOWED },
    ...overrides,
  })
}

/**
 * Renders the bill screen with a server whose GET /bills/AP-00407 answers `state.bill`, which write routes can
 * replace, so the screen shows what the server holds after each write.
 */
function renderReview(bill: BillDetail, role: Parameters<typeof billScreenRoutes>[0] = CLERK,
  writes: (state: { bill: BillDetail }) => Record<string, FakeRoute> = () => ({})) {
  const state = { bill }
  const fake = installFakeApi({
    ...billScreenRoutes(role),
    'GET /bills/AP-00407': () => ({ body: state.bill }),
    ...writes(state),
  })
  renderApp('/bills/AP-00407')
  return fake
}

describe('line coding', () => {
  it('accepts a suggestion in one click, sending the row version', async () => {
    let sent: unknown = null
    renderReview(inReview(), CLERK, (state) => ({
      'PATCH /bills/AP-00407/lines/2': async (request) => {
        sent = await request.json()
        const lines = state.bill.lines.map((l) => (l.line_no === 2
          ? { ...l, gl_account: '5040', department_id: 'D01', coding_status: 'accepted' as const, coded_by: 'U005' } : l))
        state.bill = { ...state.bill, lines, row_version: 5 }
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    const lines = await screen.findByRole('table', { name: 'Invoice lines' })
    // Line 1 is already confirmed: it can be changed, not accepted.
    expect(within(lines).queryByRole('button', { name: 'Accept suggestion for line 1' })).not.toBeInTheDocument()
    expect(within(lines).getByRole('button', { name: 'Change coding of line 1' })).toBeInTheDocument()

    await user.click(within(lines).getByRole('button', { name: 'Accept suggestion for line 2' }))
    await waitFor(() => expect(sent).toEqual({ row_version: 4, gl_account: '5040', department_id: 'D01' }))
    expect(await screen.findByText('Suggestion accepted')).toBeInTheDocument()
    expect(await within(lines).findByText('Confirmed by clerk (Jordan Okafor)')).toBeInTheDocument()
    expect(within(lines).queryByRole('button', { name: 'Accept suggestion for line 2' })).not.toBeInTheDocument()
  })

  it('changes a line\'s GL account and department', async () => {
    let sent: unknown = null
    renderReview(inReview(), CLERK, (state) => ({
      'PATCH /bills/AP-00407/lines/2': async (request) => {
        sent = await request.json()
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Change coding of line 2' }))
    const dialog = await screen.findByRole('dialog', { name: 'Code line 2' })
    expect(within(dialog).getByText('Suggested: 5040 Packaging: 9 of 10 past lines from this vendor')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('combobox', { name: 'GL account' }))
    await user.click(await screen.findByRole('option', { name: '5030 Warehouse supplies' }))
    await user.click(within(dialog).getByRole('combobox', { name: 'Department' }))
    await user.click(await screen.findByRole('option', { name: 'Finance (D02)' }))
    await user.click(within(dialog).getByRole('button', { name: 'Save coding' }))

    await waitFor(() => expect(sent).toEqual({ row_version: 4, gl_account: '5030', department_id: 'D02' }))
    expect(await screen.findByText('Coding saved')).toBeInTheDocument()
  })

  it('shows a refusal in the dialog', async () => {
    renderReview(inReview(), CLERK, () => ({
      'PATCH /bills/AP-00407/lines/2': {
        status: 409, body: envelope('conflict.stale', 'This bill was changed by someone else. Reload it and try again.', 'rid-cd-1'),
      },
    }))
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change coding of line 2' }))
    const dialog = await screen.findByRole('dialog', { name: 'Code line 2' })
    await user.click(within(dialog).getByRole('button', { name: 'Save coding' }))
    expect(await within(dialog).findByText('Changed by someone else')).toBeInTheDocument()
    expect(within(dialog).getByText('Request id: rid-cd-1')).toBeInTheDocument()
  })

  it('has no coding buttons when the server doesn\'t allow coding', async () => {
    renderReview(inReview({ allowed_actions: { code_lines: { allowed: false, reason: "Your role (approver) can't code lines." } } }),
      { role: 'approver', user_id: 'U001' })
    const lines = await screen.findByRole('table', { name: 'Invoice lines' })
    expect(within(lines).queryByRole('button', { name: /Accept suggestion|Change coding/ })).not.toBeInTheDocument()
  })
})


describe('department', () => {
  it('confirms a department that was only suggested by the coding', async () => {
    let sent: unknown = null
    renderReview(inReview({ department_source: 'coding' }), CLERK, (state) => ({
      'PATCH /bills/AP-00407': async (request) => {
        sent = await request.json()
        state.bill = { ...state.bill, department_source: 'user', row_version: 5 }
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    const summary = await screen.findByRole('region', { name: 'Bill summary' })
    expect(await within(summary).findByText('Not confirmed: suggested from the line coding')).toBeInTheDocument()
    await user.click(within(summary).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(sent).toEqual({ row_version: 4, department_id: 'D01' }))
    expect(await within(summary).findByText('Set by a person')).toBeInTheDocument()
    expect(within(summary).queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
  })

  it('changes the department, and shows a refusal from the server', async () => {
    const bodies: unknown[] = []
    let refuse = true
    renderReview(inReview({ department_source: 'coding' }), CLERK, (state) => ({
      'PATCH /bills/AP-00407': async (request) => {
        bodies.push(await request.json())
        if (refuse) {
          refuse = false
          return { status: 422, body: envelope('bill.unknown_department_id', 'D09 doesn\'t exist.', 'rid-dp-1') }
        }
        state.bill = { ...state.bill, department_id: 'D02', department_source: 'user' }
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Change department' }))
    const dialog = await screen.findByRole('dialog', { name: 'Change department' })
    await user.click(within(dialog).getByRole('combobox', { name: 'Department' }))
    await user.click(await screen.findByRole('option', { name: 'Finance (D02)' }))
    await user.click(within(dialog).getByRole('button', { name: 'Save department' }))
    expect(await within(dialog).findByText('D09 doesn\'t exist.')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Save department' }))
    expect(await screen.findByText('Department saved')).toBeInTheDocument()
    expect(bodies.at(-1)).toEqual({ row_version: 4, department_id: 'D02' })
    const summary = screen.getByRole('region', { name: 'Bill summary' })
    expect(await within(summary).findByText('Finance (D02)')).toBeInTheDocument()
  })

  it('has no department buttons without the edit action', async () => {
    renderReview(inReview({ department_source: 'coding', allowed_actions: {} }), { role: 'finance_manager', user_id: 'U003' })
    const summary = await screen.findByRole('region', { name: 'Bill summary' })
    await within(summary).findByText('Not confirmed: suggested from the line coding')
    expect(within(summary).queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    expect(within(summary).queryByRole('button', { name: 'Change department' })).not.toBeInTheDocument()
  })
})
