import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { IntakeItem } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const EMPLOYEE = { role: 'employee' as const, user_id: 'U013', full_name: 'Avery Chen', department_id: 'D01' }

function item(overrides: Partial<IntakeItem>): IntakeItem {
  return {
    item_id: 1, file_name: 'a.pdf', file_hash: null, status: 'ok', error: null, warnings: [], bill_id: null,
    email_id: null, created_at: '2026-11-02T15:00:00Z', created_by: 'U013', ...overrides,
  }
}

describe('my submissions', () => {
  it('shows each file with its status, bill link and notes', async () => {
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'GET /submissions': {
        body: [
          item({ item_id: 3, file_name: 'acme-oct.pdf', status: 'ok', bill_id: 'AP-00431', warnings: ['department D03 suggested from coding'] }),
          item({ item_id: 2, file_name: 'scan.png', status: 'failed', error: 'No text could be read from the file.' }),
        ],
      },
    })
    renderApp('/submissions')

    const table = await screen.findByRole('table', { name: 'My submissions' })
    const done = (await within(table).findByText('acme-oct.pdf')).closest('tr')!
    expect(within(done).getByText('Done')).toBeInTheDocument()
    expect(within(done).getByRole('link', { name: 'AP-00431' })).toHaveAttribute('href', '/bills/AP-00431')
    expect(within(done).getByText('department D03 suggested from coding')).toBeInTheDocument()
    const failed = within(table).getByText('scan.png').closest('tr')!
    expect(within(failed).getByText('Failed')).toBeInTheDocument()
    expect(within(failed).getByText('No bill')).toBeInTheDocument()
    expect(within(failed).getByText('No text could be read from the file.')).toBeInTheDocument()
  })

  it('polls while a file is still being read, then stops', async () => {
    let calls = 0
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'GET /submissions': () => {
        calls += 1
        return { body: [calls < 2 ? item({ status: 'processing' }) : item({ status: 'ok', bill_id: 'AP-00432' })] }
      },
    })
    renderApp('/submissions')

    expect(await screen.findByText('1 file is still being read. This list updates by itself.')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'AP-00432' }, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText(/still being read/)).not.toBeInTheDocument()
    await waitFor(() => expect(calls).toBe(2))
  })

  it('says so when nothing was submitted, and shows errors inline', async () => {
    installFakeApi({ ...billScreenRoutes(EMPLOYEE), 'GET /submissions': { body: [] } })
    const { unmount } = renderApp('/submissions')
    expect(await screen.findByText("You haven't submitted any invoices yet.")).toBeInTheDocument()
    unmount()

    installFakeApi({
      ...billScreenRoutes(),
      'GET /submissions': { status: 403, body: envelope('auth.forbidden_role', "Your role can't do this.") },
    })
    renderApp('/submissions')
    expect(await screen.findByText("Your role can't do this.")).toBeInTheDocument()
  })
})
