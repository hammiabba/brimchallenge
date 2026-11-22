import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes, billSummary, billsPage } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

const USD_BILL = billSummary({
  bill_id: 'AP-00004', status: 'pending_approval', vendor_name: 'Granite Peak Software', vendor_invoice_number: 'GP-2210',
  currency: 'USD', total: '5124.23', total_cad: '7024.81', open_flags: { block: 0, warn: 1, info: 1 },
  top_flag_code: 'TAX_WRONG_FOR_PROVINCE',
  current_step: { step_no: 1, role: 'dept_manager', user_id: 'U003', delegated_from: 'U012' },
})

/** The URLs the list fetched (GET /bills only). */
function billRequests(urls: URL[]): URL[] {
  return urls.filter((url) => url.pathname === '/api/bills')
}

describe('bills list', () => {
  it('shows each bill as a dense row', async () => {
    installFakeApi({ ...billScreenRoutes(), 'GET /bills': { body: billsPage([billSummary(), USD_BILL]) } })
    renderApp('/bills')

    const table = await screen.findByRole('table', { name: 'Bills' })
    // Seven columns: the invoice number sits under the vendor, the flag counts and the top flag share "Flags".
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Bill', 'Vendor', 'Invoice date', 'Total (CAD)', 'Status', 'Flags', 'Current step',
    ])
    const link = await within(table).findByRole('link', { name: 'AP-00407' })
    expect(link).toHaveAttribute('href', '/bills/AP-00407')
    const row = link.closest('tr')!
    expect(within(row).getByText('Summit Packaging Supply')).toBeInTheDocument()
    // The invoice number, under the vendor, read out as "Invoice number 000804".
    expect(within(row).getByText('Invoice number', { exact: false }).parentElement).toHaveTextContent('Invoice number 000804')
    expect(within(row).getByText('Oct 3, 2026')).toBeInTheDocument()
    expect(within(row).getByText('$2,457.19')).toBeInTheDocument()
    expect(within(row).getByText('Scheduled')).toBeInTheDocument()
    expect(within(row).getByText('2 block')).toBeInTheDocument()
    expect(await within(row).findByText('PO closed or wrong vendor')).toBeInTheDocument()

    const usd = within(table).getByRole('link', { name: 'AP-00004' }).closest('tr')!
    expect(within(usd).getByText('$7,024.81')).toBeInTheDocument()
    expect(within(usd).getByText('US$5,124.23')).toBeInTheDocument()
    expect(within(usd).getByText('1 warning')).toBeInTheDocument()
    expect(within(usd).getByText('1 info')).toBeInTheDocument()
    expect(await within(usd).findByText('Step 1, Department manager: Priya Natarajan')).toBeInTheDocument()
    expect(within(usd).getByText('delegate for Sam Rivera')).toBeInTheDocument()
    expect(screen.getByText('Showing 1 to 2 of 2 bills')).toBeInTheDocument()
  })

  it('reads its filters from the URL and sends exactly those to the API', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(), 'GET /bills': { body: billsPage([billSummary()]) } })
    renderApp('/bills?status=paid&status=void&vendor=V011&department=D01&q=000804&page=2')

    await screen.findByRole('table', { name: 'Bills' })
    await waitFor(() => expect(billRequests(fake.urls)).toHaveLength(1))
    const query = billRequests(fake.urls)[0]!.searchParams
    expect(query.getAll('status')).toEqual(['paid', 'void'])
    expect([query.get('vendor_id'), query.get('department_id'), query.get('q')]).toEqual(['V011', 'D01', '000804'])
    expect([query.get('limit'), query.get('offset')]).toEqual(['50', '50'])
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveValue('000804')
  })

  it('writes the filters to the URL as they change', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(), 'GET /bills': { body: billsPage([billSummary()]) } })
    const user = userEvent.setup()
    renderApp('/bills')
    await screen.findByRole('link', { name: 'AP-00407' })

    // Status (multi-select).
    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Needs review' }))
    await waitFor(() => expect(currentLocation()).toBe('/bills?status=needs_review'))

    // Vendor.
    await user.click(screen.getByRole('combobox', { name: 'Vendor' }))
    await user.click(await screen.findByRole('option', { name: 'Summit Packaging Supply (V011)' }))
    await waitFor(() => expect(currentLocation()).toBe('/bills?status=needs_review&vendor=V011'))

    // Search, written once typing pauses.
    await user.type(screen.getByRole('textbox', { name: 'Search' }), 'acme')
    await waitFor(() => expect(currentLocation()).toBe('/bills?status=needs_review&vendor=V011&q=acme'))

    await waitFor(() => {
      const last = billRequests(fake.urls).at(-1)!.searchParams
      expect([last.getAll('status'), last.get('vendor_id'), last.get('q')]).toEqual([['needs_review'], 'V011', 'acme'])
    })
  })

  it('pages with offset and keeps the page in the URL', async () => {
    const fake = installFakeApi({
      ...billScreenRoutes(),
      'GET /bills': (request) => {
        const offset = new URL(request.url).searchParams.get('offset') ?? '0'
        return { body: billsPage([billSummary()], 120, Number.parseInt(offset, 10)) }
      },
    })
    const user = userEvent.setup()
    renderApp('/bills')
    await screen.findByRole('link', { name: 'AP-00407' })

    await user.click(screen.getByRole('button', { name: '2' }))
    await waitFor(() => expect(currentLocation()).toBe('/bills?page=2'))
    await waitFor(() => expect(billRequests(fake.urls).at(-1)!.searchParams.get('offset')).toBe('50'))
  })

  it('says so in one line when there are no bills, or none match', async () => {
    installFakeApi({ ...billScreenRoutes(), 'GET /bills': { body: billsPage([]) } })
    const { unmount } = renderApp('/bills')
    expect(await screen.findByText('No bills yet.')).toBeInTheDocument()
    unmount()

    renderApp('/bills?q=nothing')
    expect(await screen.findByText('No bills match these filters.')).toBeInTheDocument()
  })

  it('shows the API error inline', async () => {
    installFakeApi({
      ...billScreenRoutes(),
      // A 4xx isn't retried, so the error shows at once.
      'GET /bills': { status: 403, body: envelope('auth.forbidden_role', "Your role can't do this.", 'rid-list-01') },
    })
    renderApp('/bills')
    expect(await screen.findByText("Can't load bills")).toBeInTheDocument()
    expect(screen.getByText("Your role can't do this.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-list-01')).toBeInTheDocument()
  })
})

describe('review queue', () => {
  it('reuses the table, fixed to needs review and on hold, without a status filter', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(), 'GET /bills': { body: billsPage([]) } })
    renderApp('/review')

    expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeInTheDocument()
    expect(await screen.findByText('No bills need review.')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Status' })).not.toBeInTheDocument()
    expect(billRequests(fake.urls)[0]!.searchParams.getAll('status')).toEqual(['needs_review', 'on_hold'])
  })
})
