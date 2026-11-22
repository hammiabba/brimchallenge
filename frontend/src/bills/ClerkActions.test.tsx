import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { BillDetail } from '../api/types'
import { envelope, installFakeApi, type FakeRoute } from '../test/fakeApi'
import { billDetail, billScreenRoutes, controlsRun, flag } from '../test/fixtures'
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

describe('edit the header', () => {
  it('sends only the changed fields and shows the re-run controls', async () => {
    let sent: unknown = null
    renderReview(inReview(), CLERK, (state) => ({
      'PATCH /bills/AP-00407': async (request) => {
        sent = await request.json()
        state.bill = {
          ...state.bill, vendor_invoice_number: '000805', po_id: null, row_version: 5,
          latest_run: controlsRun({ version: 2, flags: [] }),
        }
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit details' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit bill details' })
    expect(within(dialog).getByText(/Amounts and lines come from the invoice and can't be edited here/)).toBeInTheDocument()
    const save = within(dialog).getByRole('button', { name: 'Save and re-run controls' })
    expect(save).toBeDisabled() // nothing changed yet

    const number = within(dialog).getByRole('textbox', { name: /Invoice number/ })
    await user.clear(number)
    await user.type(number, '000805')
    await user.clear(within(dialog).getByRole('textbox', { name: 'PO' }))
    await user.click(save)

    await waitFor(() => expect(sent).toEqual({ row_version: 4, vendor_invoice_number: '000805', po_id: null }))
    expect(await screen.findByText('AP-00407: controls ran again, 0 open flags.')).toBeInTheDocument()
    expect(await screen.findByText('No flags on this bill.')).toBeInTheDocument()

    // Opening the form again starts from the saved values.
    await user.click(screen.getByRole('button', { name: 'Edit details' }))
    const again = await screen.findByRole('dialog', { name: 'Edit bill details' })
    expect(within(again).getByRole('textbox', { name: /Invoice number/ })).toHaveValue('000805')
  })

  it('shows a refusal in the form', async () => {
    renderReview(inReview(), CLERK, () => ({
      'PATCH /bills/AP-00407': {
        status: 422, body: envelope('bill.unknown_po_id', 'PO-2099-0001 doesn\'t exist.', 'rid-ed-1', { field: 'po_id' }),
      },
    }))
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Edit details' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit bill details' })
    const po = within(dialog).getByRole('textbox', { name: 'PO' })
    await user.clear(po)
    await user.type(po, 'PO-2099-0001')
    await user.click(within(dialog).getByRole('button', { name: 'Save and re-run controls' }))
    expect(await within(dialog).findByText('PO-2099-0001 doesn\'t exist.')).toBeInTheDocument()
    expect(within(dialog).getByText('Request id: rid-ed-1')).toBeInTheDocument()
  })

  it('has no Edit details button without the edit action', async () => {
    renderReview(inReview({ status: 'pending_approval', allowed_actions: {
      edit: { allowed: false, reason: 'The bill is pending_approval; it can only change while in review.' },
    } }))
    await screen.findByRole('heading', { level: 1, name: 'Bill AP-00407' })
    expect(screen.queryByRole('button', { name: 'Edit details' })).not.toBeInTheDocument()
  })
})

/** AP-00407 in review with a blocking duplicate and a wrong-tax warning, both open. */
function withFlags(actions: BillDetail['allowed_actions']): BillDetail {
  return inReview({
    allowed_actions: actions,
    latest_run: controlsRun({
      flags: [
        flag(),
        flag({ id: 90, code: 'TAX_WRONG_FOR_PROVINCE', severity: 'warn', field: 'taxes',
          message: 'Tax charged is HST $282.69, but delivery to AB should be GST $108.73.', evidence: {} }),
      ],
    }),
  })
}

describe('resolve and override flags', () => {
  it('shows the flag help, resolves with a required comment, and refreshes the flags', async () => {
    let sent: unknown = null
    renderReview(withFlags({ resolve_flags: ALLOWED }), CLERK, (state) => ({
      'POST /bills/AP-00407/flags/89/resolve': async (request) => {
        sent = await request.json()
        const run = state.bill.latest_run!
        state.bill = { ...state.bill, row_version: 5, latest_run: { ...run, flags: run.flags.map((f) => (f.id === 89
          ? { ...f, resolution: 'resolved' as const, resolved_by: 'U005', resolution_comment: 'Credit note received' } : f)) } }
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    const duplicate = await screen.findByRole('region', { name: 'Exact duplicate' })
    expect(within(duplicate).getByText(/check whether it was paid before approving/)).toBeInTheDocument()
    // AP can't override a blocking flag: no Override button, and they're told who can.
    expect(within(duplicate).queryByRole('button', { name: 'Override' })).not.toBeInTheDocument()
    expect(within(duplicate).getByText('Only a finance manager or the controller can override a blocking flag.')).toBeInTheDocument()

    await user.click(within(duplicate).getByRole('button', { name: 'Resolve' }))
    const dialog = await screen.findByRole('dialog', { name: 'Resolve flag' })
    const confirm = within(dialog).getByRole('button', { name: 'Resolve flag' })
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox', { name: /Comment/ }), 'Credit note received')
    await user.click(confirm)

    await waitFor(() => expect(sent).toEqual({ row_version: 4, resolution: 'resolved', comment: 'Credit note received' }))
    expect(await screen.findByText('Flag resolved')).toBeInTheDocument()
    expect(await within(duplicate).findByText('Reason: Credit note received')).toBeInTheDocument()
    expect(within(duplicate).queryByRole('button', { name: 'Resolve' })).not.toBeInTheDocument()
  })

  it('lets AP override a warning, with a comment', async () => {
    let sent: unknown = null
    renderReview(withFlags({ resolve_flags: ALLOWED }), CLERK, (state) => ({
      'POST /bills/AP-00407/flags/90/resolve': async (request) => {
        sent = await request.json()
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    const tax = await screen.findByRole('region', { name: 'Wrong tax for province' })
    await user.click(within(tax).getByRole('button', { name: 'Override' }))
    const dialog = await screen.findByRole('dialog', { name: 'Override flag' })
    await user.type(within(dialog).getByRole('textbox', { name: /Comment/ }), 'Vendor confirmed ON delivery')
    await user.click(within(dialog).getByRole('button', { name: 'Override flag' }))
    await waitFor(() => expect(sent).toEqual({ row_version: 4, resolution: 'overridden', comment: 'Vendor confirmed ON delivery' }))
  })

  it('lets the finance manager override a blocking flag, and shows a refusal', async () => {
    renderReview(withFlags({ resolve_flags: ALLOWED, override_blocking_flags: ALLOWED }),
      { role: 'finance_manager', user_id: 'U003' }, () => ({
        'POST /bills/AP-00407/flags/89/resolve': {
          status: 409, body: envelope('flag.invalid_state', 'The flag is resolved; it must be open.', 'rid-fl-1'),
        },
      }))
    const user = userEvent.setup()

    const duplicate = await screen.findByRole('region', { name: 'Exact duplicate' })
    expect(within(duplicate).queryByText(/Only a finance manager/)).not.toBeInTheDocument()
    await user.click(within(duplicate).getByRole('button', { name: 'Override' }))
    const dialog = await screen.findByRole('dialog', { name: 'Override flag' })
    expect(within(dialog).getByText(/This lets a blocked bill go on to approval/)).toBeInTheDocument()
    await user.type(within(dialog).getByRole('textbox', { name: /Comment/ }), 'Different shipment')
    await user.click(within(dialog).getByRole('button', { name: 'Override flag' }))
    expect(await within(dialog).findByText('The flag is resolved; it must be open.')).toBeInTheDocument()
  })

  it('has no flag buttons without the actions', async () => {
    renderReview(withFlags({}), { role: 'auditor', user_id: 'U015' })
    const duplicate = await screen.findByRole('region', { name: 'Exact duplicate' })
    expect(within(duplicate).queryByRole('button', { name: /Resolve|Override/ })).not.toBeInTheDocument()
  })
})

describe('submit for approval', () => {
  it('submits a bill with nothing blocking, sending the row version', async () => {
    let sent: unknown = null
    renderReview(inReview({ allowed_actions: { submit: { allowed: true, reason: 'Ready for approval.' } },
      latest_run: controlsRun({ flags: [] }) }), CLERK, (state) => ({
      'POST /bills/AP-00407/submit': async (request) => {
        sent = await request.json()
        state.bill = { ...state.bill, status: 'pending_approval', allowed_actions: {},
          current_step: { step_no: 1, role: 'dept_manager', user_id: 'U001', delegated_from: null } }
        return { body: state.bill }
      },
    }))
    const user = userEvent.setup()

    const bar = await screen.findByRole('region', { name: 'Ready for approval' })
    expect(within(bar).getByText('Ready for approval: the controls found nothing blocking.')).toBeInTheDocument()
    await user.click(within(bar).getByRole('button', { name: 'Submit for approval' }))
    await waitFor(() => expect(sent).toEqual({ row_version: 4 }))
    expect(await screen.findByText('AP-00407: step 1 (Department manager) goes to Morgan Lee.')).toBeInTheDocument()
    // Pending approval: no longer AP's to submit.
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Ready for approval' })).not.toBeInTheDocument())
  })

  it('is disabled with the open blocking flags listed by name', async () => {
    renderReview(inReview({ allowed_actions: {
      submit: { allowed: false, reason: 'Resolve or override first: PO_CLOSED_OR_WRONG_VENDOR, DUPLICATE_EXACT.' },
    } }))
    const bar = await screen.findByRole('region', { name: 'Ready for approval' })
    expect(within(bar).getByRole('button', { name: 'Submit for approval' })).toBeDisabled()
    expect(within(bar).getByText('Resolve or override these blocking flags first:')).toBeInTheDocument()
    expect(await within(bar).findByText('PO closed or wrong vendor')).toBeInTheDocument()
    expect(within(bar).getByText('Exact duplicate')).toBeInTheDocument()
  })

  it('shows the server\'s reason when there is no blocking flag to list', async () => {
    renderReview(inReview({ latest_run: controlsRun({ flags: [], route: [] }), allowed_actions: {
      submit: { allowed: false, reason: "Controls haven't produced an approval route yet." },
    } }))
    const bar = await screen.findByRole('region', { name: 'Ready for approval' })
    expect(within(bar).getByText("Controls haven't produced an approval route yet.")).toBeInTheDocument()
  })

  it('shows a refusal with the blocking flags it names', async () => {
    renderReview(inReview({ allowed_actions: { submit: { allowed: true, reason: 'Ready for approval.' } },
      latest_run: controlsRun({ flags: [] }) }), CLERK, () => ({
      'POST /bills/AP-00407/submit': {
        status: 409,
        body: envelope('bill.blocked', 'Resolve or override the blocking flags before submitting.', 'rid-sb-1',
          { open_blocking_flags: ['VENDOR_LOOKALIKE'] }),
      },
    }))
    const user = userEvent.setup()
    const bar = await screen.findByRole('region', { name: 'Ready for approval' })
    await user.click(within(bar).getByRole('button', { name: 'Submit for approval' }))
    expect(await within(bar).findByText('Not submitted')).toBeInTheDocument()
    expect(within(bar).getByText('Resolve or override the blocking flags before submitting.')).toBeInTheDocument()
    expect(within(within(bar).getByRole('list', { name: 'Blocking flags' })).getByText('Lookalike vendor')).toBeInTheDocument()
    expect(within(bar).getByText('Request id: rid-sb-1')).toBeInTheDocument()
  })

  it('isn\'t shown to other roles', async () => {
    renderReview(inReview({ allowed_actions: { submit: { allowed: false, reason: "Your role (finance_manager) can't submit bills." } } }),
      { role: 'finance_manager', user_id: 'U003' })
    await screen.findByRole('heading', { level: 1, name: 'Bill AP-00407' })
    expect(screen.queryByRole('region', { name: 'Ready for approval' })).not.toBeInTheDocument()
  })
})
