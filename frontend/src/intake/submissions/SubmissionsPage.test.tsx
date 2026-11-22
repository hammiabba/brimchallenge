import { focusManager } from '@tanstack/react-query'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { envelope, installFakeApi } from '../../test/fakeApi'
import { billDetail, billScreenRoutes, billSummary } from '../../test/fixtures'
import { currentLocation, renderApp } from '../../test/renderApp'
import { POLL_MS } from '../common/queries'
import { intakeItem } from '../common/testData'

const EMPLOYEE = { user_id: 'U013', full_name: 'Aiden Grant', role: 'employee' as const, department_id: 'D01' }

const DONE = intakeItem({ item_id: 3, file_name: 'Invoice HA26-2766.pdf', bill_id: 'AP-00427' })
const FAILED = intakeItem({
  item_id: 2, file_name: 'scan-blurry.png', status: 'failed', bill_id: null,
  error: 'No text could be read from this image.',
})
const DUPLICATE = intakeItem({
  item_id: 1, file_name: 'Invoice HA26-2766 copy.pdf', bill_id: 'AP-00427',
  warnings: ['already_received: this exact file was already received as bill AP-00427 (status needs_review); no new bill was created'],
})

/** GET /bills?mine=true answering `items` (no bills by default). */
function requested(items: unknown[] = []) {
  return { body: { items, total: items.length, limit: 20, offset: 0 } }
}

/** The routes the page needs, with GET /submissions answering `items` and the bill AP-00427 behind it. */
function routes(items: unknown) {
  return {
    ...billScreenRoutes(EMPLOYEE),
    'GET /submissions': { body: items },
    'GET /bills': requested(),
    'GET /bills/AP-00427': {
      body: billDetail({ bill_id: 'AP-00427', vendor_name: 'Harlow and Stern LLP', total: '6452.30', currency: 'CAD' }),
    },
  }
}

/** How many times GET /submissions was called. */
function listCalls(calls: string[]): number {
  return calls.filter((call) => call === 'GET /submissions').length
}

afterEach(() => {
  vi.useRealTimers()
  focusManager.setFocused(undefined)
})

describe('my submissions', () => {
  it('lists each file with when, status, vendor, total and bill', async () => {
    installFakeApi(routes([DONE, FAILED, DUPLICATE]))
    renderApp('/submissions')

    const table = await screen.findByRole('table', { name: 'My submissions' })
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'File', 'Submitted', 'Status', 'Vendor', 'Total', 'Bill',
    ])
    const row = (await within(table).findByText('Invoice HA26-2766.pdf')).closest('tr')!
    expect(within(row).getByText('Done')).toBeInTheDocument()
    expect(within(row).getByRole('time')).toHaveAttribute('dateTime', DONE.created_at)
    expect(await within(row).findByText('Harlow and Stern LLP')).toBeInTheDocument()
    expect(within(row).getByText('$6,452.30')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'AP-00427' })).toHaveAttribute('href', '/bills/AP-00427')

    const duplicate = within(table).getByText('Invoice HA26-2766 copy.pdf').closest('tr')!
    expect(within(duplicate).getByText('Already received')).toBeInTheDocument()
  })

  it('shows why a file failed, in one line', async () => {
    installFakeApi(routes([FAILED]))
    renderApp('/submissions')
    const row = (await screen.findByText('scan-blurry.png')).closest('tr')!
    expect(within(row).getByText('Failed')).toBeInTheDocument()
    expect(within(row).getByText('No text could be read from this image.')).toBeInTheDocument()
    expect(within(row).queryByRole('link')).not.toBeInTheDocument()
  })

  it.each([
    ['queued', 'Queued'],
    ['processing', 'Processing'],
    ['ok', 'Done'],
    ['llm_skipped', 'Not read'],
    ['failed', 'Failed'],
  ] as const)('labels status %s as "%s"', async (status, label) => {
    installFakeApi(routes([intakeItem({ status, bill_id: null })]))
    renderApp('/submissions')
    const row = (await screen.findByText('Invoice HA26-2766.pdf')).closest('tr')!
    expect(within(row).getByText(label)).toBeInTheDocument()
  })

  it('polls while a file is processing and stops once all are final', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let answer = [intakeItem({ status: 'processing', bill_id: null })]
    const fake = installFakeApi({ ...routes([]), 'GET /submissions': () => ({ body: answer }) })
    renderApp('/submissions')
    expect(await screen.findByRole('cell', { name: 'Processing' })).toBeInTheDocument()
    expect(listCalls(fake.calls)).toBe(1)

    answer = [DONE]
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS))
    const table = screen.getByRole('table', { name: 'My submissions' })
    expect(await within(table).findByText('Done')).toBeInTheDocument()
    const afterFinal = listCalls(fake.calls)
    expect(afterFinal).toBe(2)

    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 3))
    expect(listCalls(fake.calls)).toBe(afterFinal)
  })

  it('does not poll while the tab is hidden', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const fake = installFakeApi(routes([intakeItem({ status: 'queued', bill_id: null })]))
    renderApp('/submissions')
    expect(await screen.findByText('Queued')).toBeInTheDocument()

    act(() => focusManager.setFocused(false))
    const before = listCalls(fake.calls)
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 3))
    expect(listCalls(fake.calls)).toBe(before)
  })

  it('filters by status through the URL', async () => {
    installFakeApi(routes([DONE, FAILED]))
    const user = userEvent.setup()
    renderApp('/submissions?status=failed')

    expect(await screen.findByText('scan-blurry.png')).toBeInTheDocument()
    expect(screen.queryByText('Invoice HA26-2766.pdf')).not.toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Done' }))
    await waitFor(() => expect(currentLocation()).toBe('/submissions?status=ok'))
    expect(await screen.findByText('Invoice HA26-2766.pdf')).toBeInTheDocument()
    expect(screen.queryByText('scan-blurry.png')).not.toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Queued' }))
    expect(await screen.findByText('No submissions match this filter.')).toBeInTheDocument()
  })

  it('says so in one line when there are none, with a way to submit', async () => {
    installFakeApi(routes([]))
    renderApp('/submissions')
    expect(await screen.findByText(/You haven't submitted a file yet\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Submit an invoice.' })).toHaveAttribute('href', '/submit')
  })

  it("lists the bills where the user is the requester, asking with mine=true", async () => {
    const fake = installFakeApi({
      ...routes([]),
      'GET /bills': requested([billSummary({
        bill_id: 'AP-00427', vendor_name: 'Harlow and Stern LLP', vendor_invoice_number: 'HA26-2766',
        received_date: '2026-10-30', status: 'needs_review', total: '6452.30', currency: 'CAD',
      })]),
    })
    renderApp('/submissions')

    const table = await screen.findByRole('table', { name: "Bills where you're the requester" })
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Bill', 'Vendor', 'Invoice number', 'Received', 'Status', 'Total',
    ])
    const row = (await within(table).findByText('Harlow and Stern LLP')).closest('tr')!
    expect(within(row).getByRole('link', { name: 'AP-00427' })).toHaveAttribute('href', '/bills/AP-00427')
    expect(within(row).getByText('HA26-2766')).toBeInTheDocument()
    expect(within(row).getByText('Oct 30, 2026')).toBeInTheDocument()
    expect(within(row).getByText('$6,452.30')).toBeInTheDocument()
    const asked = fake.urls.filter((url) => url.pathname.endsWith('/bills'))
    expect(asked.length).toBeGreaterThan(0)
    expect(asked.every((url) => url.searchParams.get('mine') === 'true')).toBe(true)
    // The files table still says it has none: the two lists answer different questions.
    expect(screen.getByText(/You haven't submitted a file yet\./)).toBeInTheDocument()
  })

  it('says so in one line when no bill names the user as requester', async () => {
    installFakeApi(routes([]))
    renderApp('/submissions')
    expect(await screen.findByText('No bill names you as the requester yet.')).toBeInTheDocument()
  })

  it('shows the server error inline', async () => {
    installFakeApi({
      ...routes([]),
      'GET /submissions': { status: 403, body: envelope('auth.forbidden_role', "Your role (approver) can't do this.", 'rid-subs') },
    })
    renderApp('/submissions')
    expect(await screen.findByText("Can't load your submissions")).toBeInTheDocument()
    expect(screen.getByText("Your role (approver) can't do this.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-subs')).toBeInTheDocument()
  })
})
