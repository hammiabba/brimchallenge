import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { envelope, installFakeApi, type FakeRoute } from '../../test/fakeApi'
import { billDetail, billScreenRoutes } from '../../test/fixtures'
import { currentLocation, renderApp } from '../../test/renderApp'
import { EMAIL_CLASS } from '../common/labels'
import { intakeItem } from '../common/testData'
import { EM058_REPLY, EM_057, EM_058, emailSummary, jobOf } from './inboxTestData'
import { JOB_POLL_MS } from './queries'

const CLERK = { user_id: 'U004', full_name: 'Jordan Okafor', role: 'ap_clerk' as const, department_id: 'D04' }

/** A GET /intake/emails page. */
function page(items: ReturnType<typeof emailSummary>[], total = items.length) {
  return { items, total, limit: 50, offset: 0 }
}

/**
 * Serves GET /intake/emails from one fixed reply, the way the server filters it for the untriaged count the page asks
 * for (triaged=false): only the emails with no class yet. Other queries get the reply as it is.
 */
function emailsRoute(route: FakeRoute): FakeRoute {
  if (typeof route === 'function') return route
  return (request) => {
    const body = route.body as ReturnType<typeof page> | undefined
    if (new URL(request.url).searchParams.get('triaged') !== 'false' || !body?.items) return route
    return { body: page(body.items.filter((email) => !email.email_class)) }
  }
}

function routes(extra: Record<string, FakeRoute> = {}, me: Parameters<typeof billScreenRoutes>[0] = CLERK) {
  const all: Record<string, FakeRoute> = { ...billScreenRoutes(me), 'GET /intake/emails': { body: page([emailSummary()]) }, ...extra }
  return { ...all, 'GET /intake/emails': emailsRoute(all['GET /intake/emails']!) }
}

afterEach(() => vi.useRealTimers())

describe('inbox', () => {
  it('lists each email with its class, reason, suggested action and bills', async () => {
    installFakeApi(routes({
      'GET /intake/emails': {
        body: page([emailSummary({ items: [intakeItem({ email_id: 'EM-001', bill_id: 'AP-00431' })] })]),
      },
    }))
    renderApp('/inbox')

    const table = await screen.findByRole('table', { name: 'Inbox emails' })
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Email', 'From', 'Subject', 'Received', 'Class', 'Reason', 'Suggested action', 'Bills',
    ])
    const row = (await within(table).findByRole('link', { name: 'EM-001' })).closest('tr')!
    expect(within(row).getByRole('link', { name: 'EM-001' })).toHaveAttribute('href', '/inbox/EM-001')
    expect(within(row).getByText('Summit Packaging Supply Accounts Receivable')).toBeInTheDocument()
    expect(within(row).getByText('Invoice 000804 attached')).toBeInTheDocument()
    expect(within(row).getByText('Invoice')).toBeInTheDocument()
    expect(within(row).getByText('Invoice attached from a known vendor')).toBeInTheDocument()
    expect(within(row).getByText('Review the draft bill made from the attachment.')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'AP-00431' })).toHaveAttribute('href', '/bills/AP-00431')
    expect(screen.getByText('Showing 1 to 1 of 1 email')).toBeInTheDocument()
  })

  it('gives each class its own badge, and "Not triaged" before a run', async () => {
    const classes = [...Object.keys(EMAIL_CLASS), null]
    installFakeApi(routes({
      'GET /intake/emails': {
        body: page(classes.map((emailClass, i) => emailSummary({ email_id: `EM-10${i}`, email_class: emailClass }))),
      },
    }))
    renderApp('/inbox')
    const table = await screen.findByRole('table', { name: 'Inbox emails' })
    for (const [i, label] of [...Object.values(EMAIL_CLASS).map((s) => s.label), 'Not triaged'].entries()) {
      const row = (await within(table).findByRole('link', { name: `EM-10${i}` })).closest('tr')!
      expect(within(row).getByText(label)).toBeInTheDocument()
    }
  })

  it('leaves out the triage columns until a run sorts the emails, and says how many wait', async () => {
    const untriaged = { email_class: null, triage_reason: null, triaged_at: null, suggested_action: null }
    installFakeApi(routes({
      'GET /intake/emails': {
        body: page([emailSummary({ email_id: 'EM-051', ...untriaged }), emailSummary({ email_id: 'EM-052', ...untriaged })]),
      },
    }))
    renderApp('/inbox')

    const table = await screen.findByRole('table', { name: 'Inbox emails' })
    await within(table).findByRole('link', { name: 'EM-051' })
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['Email', 'From', 'Subject', 'Received'])
    expect(await screen.findByText('2 emails not triaged yet. Run the inbox to sort them.')).toBeInTheDocument()
  })

  it('shows no "not triaged" line when every email is sorted', async () => {
    installFakeApi(routes())
    renderApp('/inbox')
    const table = await screen.findByRole('table', { name: 'Inbox emails' })
    await within(table).findByRole('link', { name: 'EM-001' })
    expect(screen.queryByText(/not triaged yet/)).not.toBeInTheDocument()
  })

  it('reads the class filter from the URL and writes changes back', async () => {
    const fake = installFakeApi(routes())
    const user = userEvent.setup()
    renderApp('/inbox?class=payment_inquiry')
    await screen.findByRole('table', { name: 'Inbox emails' })
    const requests = () => fake.urls.filter((url) => url.pathname === '/api/intake/emails')
    await waitFor(() => expect(requests()[0]!.searchParams.get('email_class')).toBe('payment_inquiry'))

    await user.click(screen.getByRole('combobox', { name: 'Class' }))
    await user.click(await screen.findByRole('option', { name: 'Not triaged' }))
    await waitFor(() => expect(currentLocation()).toBe('/inbox?class=untriaged'))
    await waitFor(() => {
      const last = requests().at(-1)!.searchParams
      expect([last.get('triaged'), last.get('email_class')]).toEqual(['false', null])
    })
  })

  it('starts a run and follows it to the end, then reloads the list', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let job = jobOf({ status: 'queued' })
    const fake = installFakeApi(routes({
      'POST /intake/inbox/jobs': { status: 202, body: jobOf({ status: 'queued' }) },
      'GET /intake/inbox/jobs/b14d2229de36': () => ({ body: job }),
    }))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp('/inbox')

    await user.click(await screen.findByRole('button', { name: 'Run inbox' }))
    await waitFor(() => expect(currentLocation()).toBe('/inbox?job=b14d2229de36'))
    expect(await screen.findByText('Processing emails: 0 of 59')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run inbox' })).toBeDisabled()

    job = jobOf({ processed_emails: 30 })
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS))
    expect(await screen.findByText('Processing emails: 30 of 59')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Inbox run progress, 30 of 59 emails' })).toBeInTheDocument()

    const listCallsBefore = fake.calls.filter((call) => call === 'GET /intake/emails').length
    job = jobOf({
      status: 'done', processed_emails: 59, finished_at: '2026-11-02T15:03:00Z',
      items: [intakeItem(), intakeItem({ item_id: 102, status: 'failed', bill_id: null })],
    })
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS))
    expect(await screen.findByText(/59 of 59 emails, 2 files read, 1 could not be read\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run inbox' })).toBeEnabled()
    await waitFor(() => expect(fake.calls.filter((c) => c === 'GET /intake/emails').length).toBeGreaterThan(listCallsBefore))

    const jobCalls = fake.calls.filter((c) => c.startsWith('GET /intake/inbox/jobs')).length
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS * 3))
    expect(fake.calls.filter((c) => c.startsWith('GET /intake/inbox/jobs')).length).toBe(jobCalls)
  })

  it('shows the run already in progress instead of starting another', async () => {
    installFakeApi(routes({
      'POST /intake/inbox/jobs': {
        status: 409,
        body: envelope('intake.job_running', 'Inbox run b14d2229de36 is still going.', 'rid-409', { job_id: 'b14d2229de36' }),
      },
      'GET /intake/inbox/jobs/b14d2229de36': { body: jobOf({ processed_emails: 12 }) },
    }))
    const user = userEvent.setup()
    renderApp('/inbox')
    await user.click(await screen.findByRole('button', { name: 'Run inbox' }))

    expect(await screen.findByText('Processing emails: 12 of 59')).toBeInTheDocument()
    expect(screen.getByText('A run was already in progress, so it is shown here.')).toBeInTheDocument()
    expect(currentLocation()).toBe('/inbox?job=b14d2229de36')
  })

  it('lets the server refuse a run to a role that may only read the inbox', async () => {
    installFakeApi(routes({
      'POST /intake/inbox/jobs': { status: 403, body: envelope('auth.forbidden_role', "Your role (auditor) can't do this.", 'rid-403') },
    }, { role: 'auditor', user_id: 'U015' }))
    const user = userEvent.setup()
    renderApp('/inbox')
    await user.click(await screen.findByRole('button', { name: 'Run inbox' }))
    expect(await screen.findByText("Your role (auditor) can't do this.")).toBeInTheDocument()
    expect(screen.getByText("Can't start the inbox run")).toBeInTheDocument()
  })

  it('shows only the 403 to an employee', async () => {
    installFakeApi(routes({
      'GET /intake/emails': { status: 403, body: envelope('auth.forbidden_role', "Your role (employee) can't do this.", 'rid-emp') },
    }, { user_id: 'U013', role: 'employee', department_id: 'D01' }))
    renderApp('/inbox')
    expect(await screen.findByText("Your role (employee) can't do this.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-emp')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run inbox' })).not.toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Inbox emails' })).not.toBeInTheDocument()
  })

  it('says so in one line when the inbox is empty, or nothing matches', async () => {
    installFakeApi(routes({ 'GET /intake/emails': { body: page([]) } }))
    const { unmount } = renderApp('/inbox')
    expect(await screen.findByText('The inbox is empty.')).toBeInTheDocument()
    unmount()
    renderApp('/inbox?class=statement')
    expect(await screen.findByText('No emails match this filter.')).toBeInTheDocument()
  })

  it('shows a server error inline with a retry', async () => {
    installFakeApi(routes({ 'GET /intake/emails': { status: 500, body: envelope('internal', 'Something broke.', 'rid-500') } }))
    renderApp('/inbox')
    expect(await screen.findByText("Can't load the inbox", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('Something broke.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('inbox email', () => {
  it('answers EM-057 from payment history', async () => {
    installFakeApi(routes({
      'GET /intake/emails/EM-057': { body: EM_057 },
      'GET /bills/AP-00049': { body: billDetail({ bill_id: 'AP-00049', status: 'paid' }) },
    }))
    renderApp('/inbox/EM-057')

    expect(await screen.findByRole('heading', { level: 1, name: 'Where is payment for invoice 1743?' })).toBeInTheDocument()
    expect(screen.getByText('Payment inquiry')).toBeInTheDocument()
    expect(screen.getByText('Vendor asks about the status of a payment; no invoice attached')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'AP-00049' })).toHaveAttribute('href', '/bills/AP-00049')
    const payments = screen.getByRole('table', { name: 'Payments' })
    const row = within(payments).getByText('PAY-00047').closest('tr')!
    expect(within(row).getByText('EFT')).toBeInTheDocument()
    expect(within(row).getByText('Mar 9, 2026')).toBeInTheDocument()
    expect(within(row).getByText('BRIM-EFT-26388945')).toBeInTheDocument()
    expect(within(row).getByText('$369.75')).toBeInTheDocument()
    expect(screen.getByTestId('reply-text')).toHaveTextContent('was paid on 2026-03-09 by EFT')
    expect(screen.getByText('No attachments.')).toBeInTheDocument()
  })

  it('gives EM-058 a resend reply that can be copied', async () => {
    installFakeApi(routes({ 'GET /intake/emails/EM-058': { body: EM_058 } }))
    const user = userEvent.setup()
    renderApp('/inbox/EM-058')

    expect(await screen.findByText('Missing attachment')).toBeInTheDocument()
    expect(screen.getByText(/has no attachment\. Send the reply asking for the file\./)).toBeInTheDocument()
    expect(screen.getByTestId('reply-text').textContent).toBe(EM058_REPLY)
    await user.click(screen.getByRole('button', { name: 'Copy reply' }))
    expect(await navigator.clipboard.readText()).toBe(EM058_REPLY)
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('links each read attachment to its original file and its bill', async () => {
    installFakeApi(routes({
      'GET /intake/emails/EM-001': {
        body: {
          ...EM_057, email_id: 'EM-001', email_class: 'invoice', suggested_action: null,
          attachments: ['summit-inv-001.pdf', 'notes.pdf'], bill_ids: ['AP-00431'],
          items: [{ item_id: 7, file_name: 'summit-inv-001.pdf', file_hash: 'b'.repeat(64), status: 'ok', error: null, warnings: [], bill_id: 'AP-00431' }],
        },
      },
      'GET /bills/AP-00431': { body: billDetail({ bill_id: 'AP-00431', status: 'needs_review' }) },
    }))
    renderApp('/inbox/EM-001')
    expect(await screen.findByRole('link', { name: 'summit-inv-001.pdf' })).toHaveAttribute('href', `/api/intake/files/${'b'.repeat(64)}`)
    expect(screen.getByText('notes.pdf')).toBeInTheDocument()
    expect(await screen.findByText('Needs review')).toBeInTheDocument()
  })

  it('says when the email does not exist', async () => {
    installFakeApi(routes({ 'GET /intake/emails/EM-999': { status: 404, body: envelope('email.not_found', 'No email EM-999.') } }))
    renderApp('/inbox/EM-999')
    expect(await screen.findByRole('heading', { name: 'Email not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to inbox' })).toHaveAttribute('href', '/inbox')
  })
})
