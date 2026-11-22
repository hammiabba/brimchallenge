import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { SpendReport } from '../api/types'
import { installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'
import { shareOf } from './share'

function report(overrides: Partial<SpendReport> = {}): SpendReport {
  return {
    group_by: 'department', from_date: null, to_date: null, department_id: null, total_cad: '30000.00',
    rows: [
      { key: 'D01', label: 'Operations', bill_count: 4, total_cad: '20000.00' },
      { key: 'D02', label: 'Finance', bill_count: 1, total_cad: '10000.00' },
    ],
    ...overrides,
  }
}

function spendRequests(urls: URL[]): URL[] {
  return urls.filter((url) => url.pathname === '/api/spend')
}

describe('spend', () => {
  it('computes shares exactly from money strings', () => {
    expect(shareOf('20000.00', '30000.00')).toBe('66.7%')
    expect(shareOf('10000.00', '30000.00')).toBe('33.3%')
    expect(shareOf('0.01', '0.03')).toBe('33.3%')
    expect(shareOf('-250.00', '30000.00')).toBe('-0.8%')
    expect(shareOf('5.00', '0.00')).toBe('')
  })

  it('shows the report with a total row and sends the URL filters', async () => {
    const fake = installFakeApi({ ...billScreenRoutes({ role: 'finance_manager', user_id: 'U003' }), 'GET /spend': { body: report() } })
    renderApp('/spend?from=2026-01-01&to=2026-10-31&department=D01')

    const table = await screen.findByRole('table', { name: 'Spend' })
    const row = (await within(table).findByText('Operations')).closest('tr')!
    expect(within(row).getByText('$20,000.00')).toBeInTheDocument()
    expect(within(row).getByText('66.7%')).toBeInTheDocument()
    expect(within(table).getByText('$30,000.00')).toBeInTheDocument()
    // One column for the name and its code; the total row adds up the bills and the share.
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['Department', 'Bills', 'Total (CAD)', 'Share'])
    expect(within(table).getByText('100.0%')).toBeInTheDocument()
    expect(Object.fromEntries(spendRequests(fake.urls)[0]!.searchParams)).toEqual({
      group_by: 'department', from_date: '2026-01-01', to_date: '2026-10-31', department_id: 'D01',
    })
  })

  it('regroups by vendor through the URL and links each vendor', async () => {
    const fake = installFakeApi({
      ...billScreenRoutes(),
      'GET /spend': (request) => new URL(request.url).searchParams.get('group_by') === 'vendor'
        ? { body: report({ group_by: 'vendor', rows: [{ key: 'V011', label: 'Summit Packaging Supply', bill_count: 2, total_cad: '30000.00' }] }) }
        : { body: report() },
    })
    const user = userEvent.setup()
    renderApp('/spend')
    await screen.findByText('Operations')

    await user.click(screen.getByText('Vendor'))
    await waitFor(() => expect(currentLocation()).toBe('/spend?group_by=vendor'))
    expect(await screen.findByRole('link', { name: 'V011' })).toHaveAttribute('href', '/vendors/V011')
    expect(spendRequests(fake.urls).at(-1)!.searchParams.get('group_by')).toBe('vendor')
  })

  it("says when the server limited the report to the approver's department", async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'approver', user_id: 'U001', department_id: 'D01' }),
      'GET /spend': { body: report({ department_id: 'D01', rows: [], total_cad: '0.00' }) },
    })
    renderApp('/spend')
    // The select shows the approver's own department, locked, not "All departments".
    const select = await screen.findByRole('combobox', { name: 'Department' })
    await waitFor(() => expect(select).toHaveValue('Operations (D01)'))
    expect(select).toBeDisabled()
    expect(screen.getByText('Approvers see their own department.')).toBeInTheDocument()
    expect(screen.getByText('No committed spend in this range.')).toBeInTheDocument()
  })
})
