import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AuditEvent, BillDetail } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billDetail, billScreenRoutes, controlsRun, flag } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

/** Renders /bills/:id with `detail` as GET /bills/{id}, signed in as `role` (AP clerk by default). */
function renderBill(detail: BillDetail, role: Parameters<typeof billScreenRoutes>[0] = {}) {
  const fake = installFakeApi({ ...billScreenRoutes(role), [`GET /bills/${detail.bill_id}`]: { body: detail } })
  renderApp(`/bills/${detail.bill_id}`)
  return fake
}

/** Renders /bills/:id for `detail` (AP clerk) and returns the render result, for tests that render several bills. */
function renderAppFor(detail: BillDetail) {
  installFakeApi({ ...billScreenRoutes(), [`GET /bills/${detail.bill_id}`]: { body: detail } })
  return renderApp(`/bills/${detail.bill_id}`)
}

/** Finds the element whose whole text (across child elements) is `text`, e.g. a sentence with a date inside. */
function byFullText(text: string) {
  return (_content: string, element: Element | null) =>
    element?.textContent === text && Array.from(element.children).every((child) => child.textContent !== text)
}

/** The flag section titled `title`. */
async function flagSection(title: string): Promise<HTMLElement> {
  return (await screen.findByRole('region', { name: title }))
}

/** Audit events shaped like the services write them (app/services/intake.py, bills.py, approvals.py). */
const AUDIT: AuditEvent[] = [
  {
    seq: 40, event_id: 'ev-40', at: '2026-11-02T14:00:00Z', actor_user_id: 'system', actor_role: 'system',
    on_behalf_of: null, action: 'bill.created', entity_type: 'bill', entity_id: 'AP-00407', before: null,
    after: { intake_item_id: 7, file_name: 'summit-804.pdf', email_id: 'EM-031', started_by: 'U013',
      status: 'needs_review', department_id: 'D01', department_source: 'submitter', warnings: [] },
    comment: null, request_id: 'r0',
  },
  {
    seq: 41, event_id: 'ev-41', at: '2026-11-02T15:00:00Z', actor_user_id: 'U005', actor_role: 'ap_clerk',
    on_behalf_of: null, action: 'bill.flag_overridden', entity_type: 'bill', entity_id: 'AP-00407',
    before: { flag_id: 89, code: 'DUPLICATE_EXACT', resolution: 'open' },
    after: { flag_id: 89, code: 'DUPLICATE_EXACT', severity: 'block', resolution: 'overridden' },
    comment: 'Different shipment', request_id: 'r1',
  },
  {
    seq: 42, event_id: 'ev-42', at: '2026-11-02T16:00:00Z', actor_user_id: 'U003', actor_role: 'finance_manager',
    on_behalf_of: 'U012', action: 'bill.approved', entity_type: 'bill', entity_id: 'AP-00407',
    before: { status: 'pending_approval', step_no: 1 },
    after: { status: 'approved', step_no: 1, step_role: 'dept_manager', final: true }, comment: null, request_id: 'r2',
  },
  {
    seq: 43, event_id: 'ev-43', at: '2026-11-02T17:00:00Z', actor_user_id: 'system', actor_role: 'system',
    on_behalf_of: null, action: 'intake.already_received', entity_type: 'bill', entity_id: 'AP-00407', before: null,
    after: { intake_item_id: 9, file_name: 'summit-804 (copy).pdf', warnings: [] }, comment: null, request_id: 'r3',
  },
]

describe('bill detail', () => {
  it('shows the header, the invoice and a duplicate flag that links to the bill it duplicates', async () => {
    renderBill(billDetail())

    expect(await screen.findByRole('heading', { level: 1, name: 'Bill AP-00407' })).toBeInTheDocument()
    const summary = screen.getByRole('region', { name: 'Bill summary' })
    expect(await within(summary).findByText('Active')).toBeInTheDocument() // vendor status, from GET /vendors/V011
    expect(await within(summary).findByText('Operations (D01)')).toBeInTheDocument()
    expect(within(summary).getByText('From the dataset history')).toBeInTheDocument()
    expect(within(summary).getByText('000804')).toBeInTheDocument()

    const duplicate = await flagSection('Exact duplicate')
    expect(within(duplicate).getByText('Blocking')).toBeInTheDocument()
    expect(within(duplicate).getByText(/Possible duplicate of AP-00394/)).toBeInTheDocument()
    expect(within(duplicate).getByText(/check whether it was paid before approving/)).toBeInTheDocument()
    expect(within(duplicate).getByRole('link', { name: 'AP-00394' })).toHaveAttribute('href', '/bills/AP-00394')
    expect(within(duplicate).getByText('100% alike')).toBeInTheDocument()
    expect(within(duplicate).getByText('same vendor and number')).toBeInTheDocument()
    expect(within(duplicate).getByText('Open')).toBeInTheDocument()

    // Lines with their coding, and the taxes.
    const lines = screen.getByRole('table', { name: 'Invoice lines' })
    expect(within(lines).getByText('Warehouse supplies')).toBeInTheDocument()
    expect(within(lines).getByText('Confirmed by clerk')).toBeInTheDocument()
    // Each fact once: GL and name, then department name and id, then how it was set; the reason behind "Why?".
    expect(within(lines).getByText('Packaging materials')).toBeInTheDocument()
    expect(within(lines).getAllByText('Operations (D01)')).toHaveLength(2)
    expect(within(lines).getByText('Suggested \u00b7 86%')).toBeInTheDocument()
    expect(within(lines).queryByText(/9 of 10 past lines/)).not.toBeInTheDocument()
    await userEvent.setup().click(within(lines).getByRole('button', { name: /^Why\? The reason for line 2/ }))
    expect(await screen.findByText('5040 Packaging: 9 of 10 past lines from this vendor')).toBeInTheDocument()
    // Unit prices read like money.
    expect(within(lines).getByText('$42.39')).toBeInTheDocument()
    const taxes = screen.getByRole('table', { name: 'Taxes and totals' })
    expect(within(taxes).getByText('13%')).toBeInTheDocument()
    expect(within(taxes).getByText('$2,457.19')).toBeInTheDocument()

    // Payments.
    const payments = screen.getByRole('table', { name: 'Payments' })
    expect(within(payments).getByText('PAY-00398')).toBeInTheDocument()
    expect(within(payments).getByText('Not released')).toBeInTheDocument()
  })

  it('sorts flags block, then warn, then info', async () => {
    renderBill(billDetail({
      latest_run: controlsRun({
        flags: [
          flag({ id: 1, code: 'FOREIGN_CURRENCY', severity: 'info', field: 'currency', evidence: {} }),
          flag({ id: 2, code: 'TAX_WRONG_FOR_PROVINCE', severity: 'warn', field: 'taxes', evidence: {} }),
          flag({ id: 3 }),
        ],
      }),
    }))
    await flagSection('Exact duplicate')
    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
      .filter((t) => ['Exact duplicate', 'Wrong tax for province', 'Foreign currency'].includes(t ?? ''))
    expect(titles).toEqual(['Exact duplicate', 'Wrong tax for province', 'Foreign currency'])
  })

  it('shows who overrode a flag, when and why', async () => {
    renderBill(billDetail({
      latest_run: controlsRun({
        flags: [flag({
          resolution: 'overridden', resolved_by: 'U003', resolved_at: '2026-11-02T15:30:00Z',
          resolution_comment: 'Confirmed with the vendor: a different shipment',
        })],
      }),
    }))
    const section = await flagSection('Exact duplicate')
    expect(within(section).getByText('Overridden')).toBeInTheDocument()
    expect(await within(section).findByText(byFullText('Overridden by Priya Natarajan on Nov 2, 2026, 10:30 AM EST')))
      .toBeInTheDocument()
    expect(within(section).getByText('Reason: Confirmed with the vendor: a different shipment')).toBeInTheDocument()
  })

  it('shows a USD bill in CAD with the original amount, rate and rate date', async () => {
    renderBill(billDetail({
      bill_id: 'AP-00004', currency: 'USD', total: '5124.23', total_cad: '7024.81', subtotal: '5124.23',
      fx_rate_to_cad: '1.3709', fx_rate_date: '2026-01-01', taxes: [], latest_run: controlsRun({ flags: [] }),
    }))
    expect(await screen.findByText('$7,024.81')).toBeInTheDocument()
    expect(screen.getByText(byFullText('US$5,124.23 at 1.3709 USD/CAD, rate of Jan 1, 2026'))).toBeInTheDocument()
    // Line unit prices and amounts stay in the bill's currency (line 1: quantity 1, so both read US$1,538.65).
    expect(within(screen.getByRole('table', { name: 'Invoice lines' })).getAllByText('US$1,538.65')).toHaveLength(2)
  })

  it('shows a delegated step and the decision made on someone\'s behalf', async () => {
    renderBill(billDetail({
      status: 'approved',
      latest_run: controlsRun({
        flags: [],
        route: [{
          step_no: 1, role: 'dept_manager', user_id: 'U003', policy_ids: ['P01', 'P08'], reason: 'Sam Rivera is away',
          delegated_from: 'U012', escalated_from: null, decision: 'approved', decided_by: 'U003',
          decided_at: '2026-11-02T16:00:00Z',
        }],
      }),
      decisions: [{
        decision_id: 'AD-1', step_no: 1, actor_user_id: 'U003', actor_role: 'finance_manager', step_role: 'dept_manager',
        on_behalf_of: 'U012', decision: 'approved', comment: 'Fine while Sam is away', acted_at: '2026-11-02T16:00:00Z',
        origin: 'app',
      }],
    }))
    const steps = await screen.findByRole('list', { name: 'Approval steps' })
    expect(within(steps).getByText('Step 1: Department manager')).toBeInTheDocument()
    expect(await within(steps).findByText('Delegate for Sam Rivera')).toBeInTheDocument()
    expect(within(steps).getByText('P08')).toBeInTheDocument()
    expect(within(steps).getByText(byFullText(
      'Approved by Priya Natarajan U003, on behalf of Sam Rivera, Nov 2, 2026, 11:00 AM EST'))).toBeInTheDocument()
    expect(within(steps).getByText('Comment: Fine while Sam is away')).toBeInTheDocument()
    expect(screen.getByText(byFullText('Last checked Nov 2, 2026, 10:00 AM EST.'))).toBeInTheDocument()
  })

  it('says how many times the checks have run once they ran again after an edit', async () => {
    renderBill(billDetail({ latest_run: controlsRun({ version: 3, flags: [] }) }))
    expect(await screen.findByText(byFullText('Last checked Nov 2, 2026, 10:00 AM EST, 3 checks in all.'))).toBeInTheDocument()
    expect(screen.queryByText(/Controls run version/)).not.toBeInTheDocument()
  })

  it('says plainly when a bill has no controls run', async () => {
    renderBill(billDetail({ latest_run: null }))
    expect(await screen.findByText('Not checked yet, so this bill has no flags.')).toBeInTheDocument()
    expect(screen.getByText('Not checked yet, so this bill has no approval route.')).toBeInTheDocument()
  })

  it('shows "Bill not found" for a 404, which also covers bills outside the user\'s scope', async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'employee' }),
      'GET /bills/AP-00300': { status: 404, body: envelope('bill.not_found', 'No bill AP-00300.') },
    })
    renderApp('/bills/AP-00300')
    expect(await screen.findByRole('heading', { name: 'Bill not found' })).toBeInTheDocument()
    expect(screen.getByText(byFullText('There is no bill AP-00300 that you can see.'))).toBeInTheDocument()
    // An employee has no Bills list in the sidebar, so the way back is My submissions.
    expect(screen.getByRole('link', { name: 'Back to my submissions' })).toHaveAttribute('href', '/submissions')
  })

  it('sends a role with the Bills list back to it from "Bill not found"', async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'ap_clerk' }),
      'GET /bills/AP-00300': { status: 404, body: envelope('bill.not_found', 'No bill AP-00300.') },
    })
    renderApp('/bills/AP-00300')
    expect(await screen.findByRole('link', { name: 'Back to bills' })).toHaveAttribute('href', '/bills')
  })

  it('marks fields a person corrected, low extraction confidence, and an unconfirmed department', async () => {
    renderBill(billDetail({
      origin: 'app', status: 'needs_review', vendor_invoice_number: 'INV-101', department_source: 'coding',
      extracted: {
        invoice_number: 'INV-1O1', invoice_date: '2026-10-03', due_date: '2026-11-02', currency: 'CAD',
        po_number: 'PO-2026-0044', subtotal: '2174.5', total: '2457.19', ship_to_province: 'ON',
        field_confidence: { invoice_number: 0.62, total: 0.95 },
        extraction_warnings: ['subtotal + taxes != total'],
        vendor: {
          name_on_invoice: 'Summit Packaging', gst_number: '123456789RT0001', match_method: 'gst_number', match_score: 1,
          bank: { institution: '004', transit: '05541', account: '*****4216' },
        },
        source: { file_name: 'summit-804.pdf', email_id: 'EM-031' },
      },
    }))
    await screen.findByRole('region', { name: 'Bill summary' })
    const field = within(document.querySelector<HTMLElement>('[data-region="invoice_number"]')!)
    expect(field.getByText('INV-101').closest('.app-changed')).not.toBeNull()
    expect(field.getByText('INV-1O1')).toBeInTheDocument()
    expect(field.getByText('(low confidence, 62%)')).toBeInTheDocument()
    // "2174.5" and "2174.50" are the same amount: not marked as changed.
    expect(screen.getByText('$2,174.50').closest('.app-changed')).toBeNull()
    expect(screen.getByText('subtotal + taxes != total')).toBeInTheDocument()
    // An exact match says nothing more: no score.
    expect(screen.getByText('Matched by GST number')).toBeInTheDocument()
    // The account by its last four digits, the one format every page uses.
    expect(screen.getByText(/account ending 4216/)).toBeInTheDocument()
    expect(screen.queryByText(/\*{5}4216/)).not.toBeInTheDocument()
    expect(screen.getByText('Not confirmed: suggested from the line coding')).toBeInTheDocument()
  })

  it('highlights the part of the invoice a flag is about', async () => {
    const user = userEvent.setup()
    renderBill(billDetail())
    const duplicate = await flagSection('Exact duplicate')
    const region = document.querySelector('[data-region="invoice_number"]')!
    expect(region).not.toHaveAttribute('data-highlighted')

    await user.hover(duplicate)
    expect(region).toHaveAttribute('data-highlighted')
    await user.unhover(duplicate)
    expect(region).not.toHaveAttribute('data-highlighted')

    await user.click(within(duplicate).getByRole('button', { name: 'Show on invoice' }))
    await user.unhover(duplicate)
    expect(region).toHaveAttribute('data-highlighted')
  })
})

/** A one-step route assigned to `assigned`, with one approval by `signer` (on behalf of `onBehalfOf`, if set). */
function signedBill(assigned: string, signer: string, extra: { onBehalfOf?: string; delegatedFrom?: string } = {}) {
  return billDetail({
    status: 'paid', requester_user_id: 'U013',
    latest_run: controlsRun({
      flags: [],
      route: [{
        step_no: 1, role: 'dept_manager', user_id: assigned, policy_ids: ['P01', 'P07'], reason: 'Total under $10,000',
        delegated_from: extra.delegatedFrom ?? null, escalated_from: null, decision: 'approved', decided_by: signer,
        decided_at: '2026-03-09T15:52:00Z',
      }],
    }),
    decisions: [{
      decision_id: 'AP-A-1', step_no: 1, actor_user_id: signer, actor_role: 'approver', step_role: 'dept_manager',
      on_behalf_of: extra.onBehalfOf ?? null, decision: 'approved', comment: null, acted_at: '2026-03-09T15:52:00Z',
      origin: 'history',
    }],
  })
}

/** The icon in a step's timeline bullet ("circle-check", "alert-triangle", ...), from its Tabler class. */
function bulletIcon(steps: HTMLElement): string | undefined {
  const svg = steps.querySelector('.app-timeline-bullet svg')
  return [...(svg?.classList ?? [])].find((c) => c.startsWith('tabler-icon-'))?.replace('tabler-icon-', '')
}

describe('bill header and panels', () => {
  it('warns when blocking flags are open but a payment is still scheduled, and links to it', async () => {
    renderBill(billDetail())
    const warning = await screen.findByRole('status')
    expect(warning).toHaveTextContent('2 blocking flags are open, but PAY-00398 is scheduled for Nov 2, 2026. Cancel the payment if the flags hold.')
    expect(within(warning).getByRole('link', { name: 'PAY-00398' })).toHaveAttribute('href', '/payments/PAY-00398')
  })

  it('links the vendor to its page', async () => {
    renderBill(billDetail())
    const summary = await screen.findByRole('region', { name: 'Bill summary' })
    expect(within(summary).getByRole('link', { name: 'Summit Packaging Supply' })).toHaveAttribute('href', '/vendors/V011')
  })

  it('says a flag on a paid bill was found after payment', async () => {
    renderBill(billDetail({ status: 'paid', payments: [] }))
    expect((await screen.findAllByText(/^Found after payment: this bill was already paid/)).length).toBeGreaterThan(0)
    expect(screen.queryByRole('status')).not.toBeInTheDocument() // nothing scheduled, so no banner
  })

  it('lists the subtotal, then each tax, then the total', async () => {
    renderBill(billDetail({ taxes: [{ tax_code: 'HST13', rate: '0.13', amount: '282.69' }] }))
    const taxes = await screen.findByRole('table', { name: 'Taxes and totals' })
    const rows = within(taxes).getAllByRole('row').slice(1).map((row) => row.textContent)
    expect(rows).toEqual(['Subtotal$2,174.50', 'HST1313%$282.69', 'Total$2,457.19'])
  })
})

describe('who signed each step', () => {
  it('marks the requester approving their own bill in the danger tone, with a warning bullet (AP-00092)', async () => {
    renderBill(signedBill('U001', 'U013'))
    const steps = await screen.findByRole('list', { name: 'Approval steps' })
    expect(await within(steps).findByText('Avery Chen approved their own bill; policy P07 needed their manager, '
      + 'Morgan Lee, to sign.')).toBeInTheDocument()
    // Not a green check: the step is broken.
    expect(bulletIcon(steps)).toBe('alert-triangle')
  })

  it('marks a step signed by someone other than its assignee', async () => {
    renderBill(signedBill('U001', 'U002'))
    const steps = await screen.findByRole('list', { name: 'Approval steps' })
    expect(await within(steps).findByText('Signed by Elena Duarte (U002), not the assigned approver Morgan Lee (U001).'))
      .toBeInTheDocument()
    expect(within(steps).queryByText(/their own bill/)).not.toBeInTheDocument()
    expect(bulletIcon(steps)).toBe('alert-triangle')
  })

  it('does not mark the assignee, a delegate assigned to the step, or a delegate acting for the assignee', async () => {
    for (const bill of [
      signedBill('U001', 'U001'),
      signedBill('U003', 'U003', { delegatedFrom: 'U012', onBehalfOf: 'U012' }),
      signedBill('U012', 'U003', { onBehalfOf: 'U012' }),
    ]) {
      const { unmount } = renderAppFor(bill)
      const steps = await screen.findByRole('list', { name: 'Approval steps' })
      await within(steps).findAllByText(/^Approved by/)
      expect(within(steps).queryByText(/not the assigned approver/)).not.toBeInTheDocument()
      expect(bulletIcon(steps)).toBe('circle-check')
      unmount()
    }
  })
})

describe('links', () => {
  it('links each payment id to the payment', async () => {
    renderBill(billDetail())
    const payments = await screen.findByRole('table', { name: 'Payments' })
    expect(within(payments).getByRole('link', { name: 'PAY-00398' })).toHaveAttribute('href', '/payments/PAY-00398')
  })

  it('links the original file only when view_document is allowed', async () => {
    const fileHash = 'ab'.repeat(32)
    const appBill = (allowed: boolean) => billDetail({
      origin: 'app', status: 'needs_review', file_hash: fileHash,
      extracted: { invoice_number: '000804', source: { file_name: 'summit-804.pdf', email_id: 'EM-031' } },
      allowed_actions: { view_document: { allowed, reason: allowed ? null : "Your role can't open original files." } },
    })

    const { unmount } = renderAppFor(appBill(true))
    const link = await screen.findByRole('link', { name: /summit-804\.pdf/ })
    expect(link).toHaveAttribute('href', `/api/intake/files/${fileHash}`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    unmount()

    renderAppFor(appBill(false))
    expect(await screen.findByText(/summit-804\.pdf/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /summit-804\.pdf/ })).not.toBeInTheDocument()
  })
})

describe('audit trail', () => {
  it.each(['auditor', 'employee'] as const)('comes from the bill itself, collapsed, for the %s role', async (role) => {
    const user = userEvent.setup()
    const fake = renderBill(billDetail({ audit: AUDIT }), { role })

    const toggle = await screen.findByRole('button', { name: 'Show 4 events' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(screen.getByRole('button', { name: 'Hide 4 events' })).toHaveAttribute('aria-expanded', 'true')

    const table = screen.getByRole('table', { name: 'Audit trail' })
    expect(within(table).getByText('Flag overridden')).toBeInTheDocument()
    // A sentence per common action; who acted by name and id; system work names the user it was for.
    expect(within(table).getByText('Created from email EM-031 (summit-804.pdf).')).toBeInTheDocument()
    expect(await within(table).findByText('System, for Avery Chen (U013)')).toBeInTheDocument()
    expect(within(table).getByText('Overrode the "Exact duplicate" flag.')).toBeInTheDocument()
    expect(within(table).getByText('Jordan Okafor (U005)')).toBeInTheDocument()
    expect(within(table).getByText('Comment: Different shipment')).toBeInTheDocument()
    expect(within(table).getByText('Approved step 1 (Department manager). Final approval: the bill is approved.'))
      .toBeInTheDocument()
    expect(within(table).getByText('on behalf of Sam Rivera (U012)')).toBeInTheDocument()
    // The before/after values behind "Show changes", as label: value rows, unchanged and empty values left out.
    const overriddenRow = within(table).getByText('Overrode the "Exact duplicate" flag.').closest('tr')!
    const showChanges = within(overriddenRow).getByRole('button', { name: 'Show changes' })
    expect(showChanges).toHaveAttribute('aria-expanded', 'false')
    await user.click(showChanges)
    expect(within(overriddenRow).getByText('Resolution:')).toBeVisible()
    expect(within(overriddenRow).getByText('open \u2192 overridden')).toBeVisible()
    expect(within(overriddenRow).queryByText('Flag:')).not.toBeInTheDocument()
    // An action without a sentence shows its values directly, never a semicolon-joined dump.
    const copyRow = within(table).getByText('Intake already received').closest('tr')!
    expect(within(copyRow).getByText('File:')).toBeInTheDocument()
    expect(within(copyRow).getByText('summit-804 (copy).pdf')).toBeInTheDocument()
    expect(within(table).queryByText(/;\s*"/)).not.toBeInTheDocument()
    // Never the controller/auditor-only audit endpoints.
    expect(fake.calls.some((call) => call.startsWith('GET /audit'))).toBe(false)
  })

  it('says so when the bill has no audit events', async () => {
    const { unmount } = renderAppFor(billDetail({ audit: [], origin: 'app' }))
    expect(await screen.findByText('No audit events for this bill yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /events/ })).not.toBeInTheDocument()
    unmount()
    // A bill imported from the history: its earlier events were never logged, which is not the same as "none yet".
    renderBill(billDetail({ audit: [], origin: 'history' }))
    expect(await screen.findByText("Imported from the dataset history: what happened before the import isn't in the audit log."))
      .toBeInTheDocument()
  })
})

describe('accessibility basics', () => {
  it('gives every table column headers and every link and button a name', async () => {
    renderBill(billDetail({ audit: AUDIT }))
    await flagSection('Exact duplicate')
    await waitFor(() => expect(screen.getByText('Active')).toBeInTheDocument())

    for (const table of screen.getAllByRole('table')) {
      expect(within(table).getAllByRole('columnheader').length, table.getAttribute('aria-label') ?? '').toBeGreaterThan(0)
      expect(table).toHaveAccessibleName()
    }
    for (const link of screen.getAllByRole('link')) expect(link).toHaveAccessibleName()
    for (const button of screen.getAllByRole('button')) expect(button).toHaveAccessibleName()
  })
})
