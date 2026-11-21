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

/** Finds the element whose whole text (across child elements) is `text`, e.g. a sentence with a date inside. */
function byFullText(text: string) {
  return (_content: string, element: Element | null) =>
    element?.textContent === text && Array.from(element.children).every((child) => child.textContent !== text)
}

/** The flag section titled `title`. */
async function flagSection(title: string): Promise<HTMLElement> {
  return (await screen.findByRole('region', { name: title }))
}

const AUDIT: AuditEvent[] = [
  {
    seq: 41, event_id: 'ev-41', at: '2026-11-02T15:00:00Z', actor_user_id: 'U005', actor_role: 'ap_clerk',
    on_behalf_of: null, action: 'bill.flag_overridden', entity_type: 'bill', entity_id: 'AP-00407',
    before: { resolution: 'open' }, after: { resolution: 'overridden' }, comment: 'Different shipment', request_id: 'r1',
  },
  {
    seq: 42, event_id: 'ev-42', at: '2026-11-02T16:00:00Z', actor_user_id: 'U003', actor_role: 'finance_manager',
    on_behalf_of: 'U012', action: 'bill.approved', entity_type: 'bill', entity_id: 'AP-00407',
    before: { status: 'pending_approval' }, after: { status: 'approved' }, comment: null, request_id: 'r2',
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
    expect(within(duplicate).getByText('Block')).toBeInTheDocument()
    expect(within(duplicate).getByText(/Possible duplicate of AP-00394/)).toBeInTheDocument()
    expect(within(duplicate).getByText(/check whether it was paid before approving/)).toBeInTheDocument()
    expect(within(duplicate).getByRole('link', { name: 'AP-00394' })).toHaveAttribute('href', '/bills/AP-00394')
    expect(within(duplicate).getByText('score 100%')).toBeInTheDocument()
    expect(within(duplicate).getByText('same vendor and number')).toBeInTheDocument()
    expect(within(duplicate).getByText('Open')).toBeInTheDocument()

    // Lines with their coding, and the taxes.
    const lines = screen.getByRole('table', { name: 'Invoice lines' })
    expect(within(lines).getByText('Warehouse supplies')).toBeInTheDocument()
    expect(within(lines).getByText('Confirmed by clerk')).toBeInTheDocument()
    expect(within(lines).getByText('Suggested, 86%: 5040 Packaging: 9 of 10 past lines from this vendor')).toBeInTheDocument()
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
    // Line amounts and totals stay in the bill's currency.
    expect(within(screen.getByRole('table', { name: 'Invoice lines' })).getByText('US$1,538.65')).toBeInTheDocument()
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
    expect(screen.getByText(byFullText('Controls run version 1, evaluated Nov 2, 2026, 10:00 AM EST.'))).toBeInTheDocument()
  })

  it('says plainly when a bill has no controls run', async () => {
    renderBill(billDetail({ latest_run: null }))
    expect(await screen.findByText('No controls run yet, so this bill has no flags.')).toBeInTheDocument()
    expect(screen.getByText('No controls run yet, so this bill has no approval route.')).toBeInTheDocument()
  })

  it('shows "Bill not found" for a 404, which also covers bills outside the user\'s scope', async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'employee' }),
      'GET /bills/AP-00300': { status: 404, body: envelope('bill.not_found', 'No bill AP-00300.') },
    })
    renderApp('/bills/AP-00300')
    expect(await screen.findByRole('heading', { name: 'Bill not found' })).toBeInTheDocument()
    expect(screen.getByText(byFullText('There is no bill AP-00300 that you can see.'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to bills' })).toHaveAttribute('href', '/bills')
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
    expect(screen.getByText('Matched by GST number (score 1.00)')).toBeInTheDocument()
    expect(screen.getByText('*****4216')).toBeInTheDocument()
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

describe('audit trail', () => {
  it.each(['auditor', 'employee'] as const)('comes from the bill itself, collapsed, for the %s role', async (role) => {
    const user = userEvent.setup()
    const fake = renderBill(billDetail({ audit: AUDIT }), { role })

    const toggle = await screen.findByRole('button', { name: 'Show 2 events' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(screen.getByRole('button', { name: 'Hide 2 events' })).toHaveAttribute('aria-expanded', 'true')

    const table = screen.getByRole('table', { name: 'Audit trail' })
    expect(within(table).getByText('Flag overridden')).toBeInTheDocument()
    expect(within(table).getByText('resolution: open → overridden; "Different shipment"')).toBeInTheDocument()
    expect(await within(table).findByText('on behalf of Sam Rivera')).toBeInTheDocument()
    // Never the controller/auditor-only audit endpoints.
    expect(fake.calls.some((call) => call.startsWith('GET /audit'))).toBe(false)
  })

  it('says so when the bill has no audit events', async () => {
    renderBill(billDetail({ audit: [] }))
    expect(await screen.findByText('No audit events for this bill yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /events/ })).not.toBeInTheDocument()
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
