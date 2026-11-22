import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { InboxEmail, InboxJob } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

function email(overrides: Partial<InboxEmail>): InboxEmail {
  return {
    email_id: 'E001', from_name: 'Summit Billing', from_address: 'billing@summit.example', subject: 'Invoice 000804',
    received_at: '2026-11-01T13:00:00Z', attachments: ['000804.pdf'], email_class: 'invoice',
    triage_reason: 'One invoice PDF attached', triaged_at: '2026-11-02T15:00:00Z', suggested_action: null, items: [],
    ...overrides,
  }
}

const EMAILS = [
  email({
    items: [{
      item_id: 7, file_name: '000804.pdf', file_hash: 'abc', status: 'ok', error: null, warnings: [],
      bill_id: 'AP-00440', email_id: 'E001', created_at: '2026-11-02T15:00:00Z', created_by: 'U005',
    }],
  }),
  email({
    email_id: 'E002', from_name: null, from_address: 'news@promo.example', subject: 'Fall deals',
    email_class: 'not_ap', triage_reason: 'Marketing newsletter, no invoice', attachments: [],
    suggested_action: { kind: 'ignore', message: 'Nothing to do.', language: 'en' },
  }),
  email({ email_id: 'E003', subject: 'Invoice attached', email_class: 'missing_attachment', attachments: [],
    triage_reason: 'Says an invoice is attached, but nothing is' }),
]

function job(overrides: Partial<InboxJob>): InboxJob {
  return {
    job_id: 'job-1', status: 'running', started_at: '2026-11-02T15:00:00Z', started_by: 'U005', processed_emails: 3,
    total_emails: 12, finished_at: null, error: null, items: [], ...overrides,
  }
}

function emailRequests(urls: URL[]): URL[] {
  return urls.filter((url) => url.pathname === '/api/intake/emails')
}

describe('inbox', () => {
  it('lists every email with its class, reason and the files read from it', async () => {
    installFakeApi({ ...billScreenRoutes(), 'GET /intake/emails': { body: { items: EMAILS, total: 3, limit: 25, offset: 0 } } })
    renderApp('/inbox')

    const table = await screen.findByRole('table', { name: 'Inbox emails' })
    const invoice = (await within(table).findByText('Invoice 000804')).closest('tr')!
    expect(within(invoice).getByText('Invoice')).toBeInTheDocument()
    expect(within(invoice).getByText('One invoice PDF attached')).toBeInTheDocument()
    expect(within(invoice).getByText('Done')).toBeInTheDocument()
    expect(within(invoice).getByRole('link', { name: 'AP-00440' })).toHaveAttribute('href', '/bills/AP-00440')

    const marketing = within(table).getByText('Fall deals').closest('tr')!
    expect(within(marketing).getByText('Not for AP')).toBeInTheDocument()
    expect(within(marketing).getByText('Marketing newsletter, no invoice')).toBeInTheDocument()
    expect(within(marketing).getByText('Nothing to do.')).toBeInTheDocument()
    expect(within(marketing).getByText('No attachments')).toBeInTheDocument()

    const missing = within(table).getByText('Invoice attached').closest('tr')!
    expect(within(missing).getByText('Missing attachment')).toBeInTheDocument()
    expect(screen.getByText('3 emails')).toBeInTheDocument()
  })

  it('starts a run, keeps its id in the URL and follows it until it finishes', async () => {
    let polls = 0
    installFakeApi({
      ...billScreenRoutes(),
      'GET /intake/emails': { body: { items: [], total: 0, limit: 25, offset: 0 } },
      'POST /intake/inbox/jobs': { status: 202, body: job({ status: 'queued', processed_emails: 0 }) },
      'GET /intake/inbox/jobs/job-1': () => {
        polls += 1
        return { body: polls < 2 ? job({}) : job({ status: 'done', processed_emails: 12 }) }
      },
    })
    const user = userEvent.setup()
    renderApp('/inbox')

    await user.click(await screen.findByRole('button', { name: 'Run inbox' }))
    await waitFor(() => expect(currentLocation()).toBe('/inbox?job=job-1'))
    expect(await screen.findByText('Inbox run: Running')).toBeInTheDocument()
    expect(screen.getByText('3 of 12 emails')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inbox run in progress' })).toBeDisabled()
    expect(await screen.findByText('Inbox run: Finished', {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run inbox' })).toBeEnabled()
  })

  it('filters by class through the URL, including emails not triaged yet', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(), 'GET /intake/emails': { body: { items: [], total: 0, limit: 25, offset: 0 } } })
    const user = userEvent.setup()
    renderApp('/inbox?class=statement')

    expect(await screen.findByText('No emails in this class.')).toBeInTheDocument()
    expect(emailRequests(fake.urls)[0]!.searchParams.get('email_class')).toBe('statement')

    await user.click(screen.getByRole('combobox', { name: 'Class' }))
    await user.click(await screen.findByRole('option', { name: 'Not triaged yet' }))
    await waitFor(() => expect(currentLocation()).toBe('/inbox?class=untriaged'))
    await waitFor(() => {
      const last = emailRequests(fake.urls).at(-1)!.searchParams
      expect([last.get('triaged'), last.has('email_class')]).toEqual(['false', false])
    })
  })

  it("shows the server's refusal to start a run", async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'auditor', user_id: 'U015' }),
      'GET /intake/emails': { body: { items: [], total: 0, limit: 25, offset: 0 } },
      'POST /intake/inbox/jobs': { status: 403, body: envelope('auth.forbidden_role', "Your role (auditor) can't do this.") },
    })
    const user = userEvent.setup()
    renderApp('/inbox')
    await user.click(await screen.findByRole('button', { name: 'Run inbox' }))
    expect(await screen.findByText("Your role (auditor) can't do this.")).toBeInTheDocument()
  })
})
