import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AuditEvent } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

function event(seq: number, overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    seq, event_id: `evt-${seq}`, at: '2026-10-30T14:00:00Z', actor_user_id: 'U002', actor_role: 'controller_admin',
    on_behalf_of: null, action: 'bill.approved', entity_type: 'bill', entity_id: 'AP-00407',
    before: { status: 'pending_approval' }, after: { status: 'approved' }, comment: null, request_id: 'rid-a',
    ...overrides,
  }
}

const AUDITOR = { role: 'auditor' as const, user_id: 'U015' }

/** The URLs of GET /audit requests. */
function auditRequests(urls: URL[]): URL[] {
  return urls.filter((url) => url.pathname === '/api/audit')
}

describe('audit log', () => {
  it('lists events and expands one to show what changed', async () => {
    installFakeApi({
      ...billScreenRoutes(AUDITOR),
      'GET /audit': { body: { items: [event(1), event(2, { on_behalf_of: 'U012', comment: 'ok to pay' })], next_after_seq: null } },
    })
    const user = userEvent.setup()
    renderApp('/audit')

    const table = await screen.findByRole('table', { name: 'Audit log' })
    expect(await within(table).findByText('ok to pay')).toBeInTheDocument()
    expect(await within(table).findByText('Controller / admin, for Sam Rivera')).toBeInTheDocument()
    // Words, not codes: the action, the role and the entity type; the entity links to its page; times in UTC.
    expect(within(table).getAllByText('Bill approved')).toHaveLength(2)
    expect(within(table).getAllByText('Bill')).toHaveLength(2)
    expect(within(table).getAllByRole('link', { name: 'AP-00407' })[0]).toHaveAttribute('href', '/bills/AP-00407')
    expect(within(table).getAllByText('Oct 30, 2026, 2:00 PM UTC')).toHaveLength(2)
    expect(within(table).getByText('No. 2')).toBeInTheDocument()

    await user.click(within(table).getByRole('button', { name: 'Show changes in event 2' }))
    const changes = await screen.findByRole('table', { name: 'Changes in event 2' })
    expect(within(changes).getByText('pending_approval')).toBeInTheDocument()
    expect(within(changes).getByText('approved')).toBeInTheDocument()
  })

  it('shows the system as one line, not "system / system"', async () => {
    installFakeApi({
      ...billScreenRoutes(AUDITOR),
      'GET /audit': { body: { items: [event(1, { actor_user_id: 'system', actor_role: 'system', action: 'bill.created' })],
        next_after_seq: null } },
    })
    renderApp('/audit')
    const table = await screen.findByRole('table', { name: 'Audit log' })
    expect(await within(table).findByText('System')).toBeInTheDocument()
    expect(within(table).queryByText('system')).not.toBeInTheDocument()
    expect(within(table).getByText('Bill created')).toBeInTheDocument()
  })

  it('sends the URL filters, with whole UTC days, and exports the same filter', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(AUDITOR), 'GET /audit': { body: { items: [], next_after_seq: null } } })
    renderApp('/audit?entity_type=bill&entity_id=AP-00407&actor=U005&from=2026-10-01&to=2026-10-31')

    expect(await screen.findByText('No events match these filters.')).toBeInTheDocument()
    const query = auditRequests(fake.urls)[0]!.searchParams
    expect(Object.fromEntries(query)).toEqual({
      entity_type: 'bill', entity_id: 'AP-00407', actor: 'U005', since: '2026-10-01T00:00:00Z',
      until: '2026-10-31T23:59:59Z', limit: '100',
    })
    const href = screen.getByRole('link', { name: 'Export CSV' }).getAttribute('href')!
    expect(href.startsWith('/api/audit/export?')).toBe(true)
    expect(new URLSearchParams(href.split('?')[1]).get('since')).toBe('2026-10-01T00:00:00Z')
  })

  it('pages forward with after_seq and back again, and restarts when a filter changes', async () => {
    const fake = installFakeApi({
      ...billScreenRoutes(AUDITOR),
      'GET /audit': (request) => {
        const after = new URL(request.url).searchParams.get('after_seq')
        return after === '100'
          ? { body: { items: [event(101)], next_after_seq: null } }
          : { body: { items: [event(1), event(100)], next_after_seq: 100 } }
      },
    })
    const user = userEvent.setup()
    renderApp('/audit')

    expect(await screen.findByText('Page 1: 2 events, numbers 1 to 100')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next page' }))
    expect(await screen.findByText('Page 2: 1 event, numbers 101 to 101')).toBeInTheDocument()
    expect(auditRequests(fake.urls).at(-1)!.searchParams.get('after_seq')).toBe('100')
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(await screen.findByText('Page 1: 2 events, numbers 1 to 100')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next page' }))
    await screen.findByText('Page 2: 1 event, numbers 101 to 101')
    fireEvent.change(screen.getByLabelText('From (UTC)'), { target: { value: '2026-10-01' } })
    await waitFor(() => expect(currentLocation()).toBe('/audit?from=2026-10-01'))
    expect(await screen.findByText('Page 1: 2 events, numbers 1 to 100')).toBeInTheDocument()
    expect(auditRequests(fake.urls).at(-1)!.searchParams.has('after_seq')).toBe(false)
  })

  it("shows the server's 403 to other roles", async () => {
    installFakeApi({
      ...billScreenRoutes(),
      'GET /audit': { status: 403, body: envelope('auth.forbidden_role', "Your role (ap_clerk) can't do this.") },
    })
    renderApp('/audit')
    expect(await screen.findByText("Your role (ap_clerk) can't do this.")).toBeInTheDocument()
  })
})
