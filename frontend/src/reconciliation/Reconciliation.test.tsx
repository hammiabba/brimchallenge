import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { BankReconciliation } from '../api/types'
import { navItemsFor } from '../shell/navigation'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

const CONTROLLER = { role: 'controller_admin', user_id: 'U002' } as const
const review = (code: string, message: string) => ({ code, severity: 'review' as const, message })
const info = (code: string, message: string) => ({ code, severity: 'info' as const, message })
const CARD_NOTE = 'Paid by card: settles on the card account, not this bank account.'

/** A small statement shaped like the dataset's: one line of each kind, a double payment and a payment at risk. */
const REPORT: BankReconciliation = {
  statement_from: '2026-01-05', statement_to: '2026-11-02',
  summary: {
    lines: 354, debits_cad: '1742643.22', matched: 333, matched_cad: '1740825.21', bank_fees: 16, bank_fees_cad: '385.00',
    unexplained: 5, unexplained_cad: '1433.01', double_payments: 10, double_paid_extra_cad: '23536.76',
    double_at_risk_cad: '2457.19', needs_review: 43, issues: { UNEXPLAINED_DEBIT: 5 },
  },
  lines: [
    { bank_txn_id: 'BK-00296', posted_date: '2026-09-13', description: 'CHEQUE 5018 CLEARED', amount: '6990.53',
      status: 'matched', payment_ids: ['PAY-00347'], bill_ids: ['AP-00356'], vendor_id: 'V039', difference: '0.05',
      issues: [review('AMOUNT_DIFFERS', 'Bank took $6,990.53 but PAY-00347 is for $6,990.48 (+$0.05).')] },
    { bank_txn_id: 'BK-00063', posted_date: '2026-03-11', description: 'WIRE FEE', amount: '15.00', status: 'bank_fee',
      payment_ids: [], bill_ids: [], vendor_id: null, difference: null,
      issues: [info('BANK_FEE', 'Bank fee.'), review('WIRE_FEE_WITHOUT_WIRE', 'Wire fee of $15.00 on 2026-03-11, but no payment went out by wire.')] },
    { bank_txn_id: 'BK-00064', posted_date: '2026-03-11', description: 'PREAUTH DEBIT 913114', amount: '174.90',
      status: 'unexplained', payment_ids: [], bill_ids: [], vendor_id: null, difference: null,
      issues: [review('UNEXPLAINED_DEBIT', 'Pre-authorized debit of $174.90 with no payment, bill or fee behind it.')] },
  ],
  payments: [
    { payment_id: 'PAY-00399', bill_id: 'AP-00407', vendor_id: 'V011', method: 'EFT', status: 'scheduled', amount_cad: '2457.19',
      on_date: '2026-11-02', bank_txn_id: null,
      issues: [info('SCHEDULED', 'Scheduled for 2026-11-02, not sent yet.'), review('DOUBLE_PAYMENT_AT_RISK', 'Summit Packaging Supply: AP-00394 / AP-00407 are one bill. Cancel PAY-00399 before it is sent.')] },
    { payment_id: 'PAY-00201', bill_id: 'AP-00210', vendor_id: 'V020', method: 'CARD', status: 'settled', amount_cad: '120.00',
      on_date: '2026-06-01', bank_txn_id: null, issues: [info('PAID_BY_CARD', CARD_NOTE)] },
  ],
  double_payments: [
    { bill_ids: ['AP-00136', 'AP-00155'], card_txn_ids: [], payment_ids: ['PAY-00133', 'PAY-00150'],
      bank_txn_ids: ['BK-00112'], extra_payment_ids: ['PAY-00133'], at_risk_payment_ids: [], confirmed: true,
      extra_paid_cad: '7456.10', at_risk_cad: '0.00', message: 'Redline Fleet Cards Inc.: AP-00136 / AP-00155 are one bill (same invoice number).' },
    { bill_ids: ['AP-00015'], card_txn_ids: ['CT-00017'], payment_ids: ['PAY-00015'], bank_txn_ids: ['BK-00005'],
      extra_payment_ids: ['PAY-00015'], at_risk_payment_ids: [], confirmed: false, extra_paid_cad: '2042.32', at_risk_cad: '0.00',
      message: 'Paper Trail Office Supply: AP-00015 / CT-00017 are one bill.' },
  ],
}

describe('bank reconciliation', () => {
  it('shows the totals and every group, with links to payments and bills', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(CONTROLLER), 'GET /reconciliation/bank': { body: REPORT } })
    const user = userEvent.setup()
    renderApp('/reconciliation?view=all')

    expect(await screen.findByRole('heading', { level: 1, name: 'Bank reconciliation' })).toBeInTheDocument()
    const summary = await screen.findByLabelText('Summary')
    expect(within(summary).getByText('$1,740,825.21')).toBeInTheDocument()
    expect(within(summary).getByText('43 lines or payments')).toBeInTheDocument()
    expect(fake.urls.find((u) => u.pathname === '/api/reconciliation/bank')!.searchParams.get('only_issues')).toBe('false')

    const unexplained = screen.getByRole('table', { name: 'Unexplained debits' })
    expect(within(unexplained).getByText('PREAUTH DEBIT 913114')).toBeInTheDocument()
    expect(within(unexplained).getByText(/Pre-authorized debit of \$174.90/)).toBeInTheDocument()

    const doubles = screen.getByRole('table', { name: 'Double payments' })
    const redline = within(doubles).getByRole('link', { name: 'AP-00136' }).closest('tr')!
    expect(within(redline).getByRole('link', { name: 'PAY-00133' })).toHaveAttribute('href', '/payments/PAY-00133')
    expect(within(redline).getByText('$7,456.10')).toBeInTheDocument()
    expect(within(redline).getByText('Confirmed: same invoice number')).toBeInTheDocument()
    expect(within(doubles).getByText('Likely: AP payment and a card charge')).toBeInTheDocument()

    const fees = screen.getByRole('table', { name: 'Bank fees' })
    expect(within(fees).getByText(/no payment went out by wire/)).toBeInTheDocument()
    expect(within(fees).queryByText('Bank fee.')).not.toBeInTheDocument() // the fee's own note isn't repeated

    // Matched lines need nothing, so in this view they are folded behind a toggle until asked for.
    expect(screen.queryByRole('table', { name: 'Matched lines' })).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: 'Show 1 matched line' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(screen.getByRole('button', { name: 'Hide matched lines' })).toHaveAttribute('aria-expanded', 'true')
    const matched = screen.getByRole('table', { name: 'Matched lines' })
    const cheque = within(matched).getByText('CHEQUE 5018 CLEARED').closest('tr')!
    expect(within(cheque).getByRole('link', { name: 'PAY-00347' })).toHaveAttribute('href', '/payments/PAY-00347')
    expect(within(cheque).getByRole('link', { name: 'AP-00356' })).toHaveAttribute('href', '/bills/AP-00356')
    expect(within(cheque).getByText('$0.05')).toBeInTheDocument()

    const off = screen.getByRole('table', { name: 'Payments not on the statement' })
    expect(within(off).getByText(/AP-00394 \/ AP-00407 are one bill/)).toBeInTheDocument()
    // The card note is said once, in the section's intro, not on every card payment's row.
    expect(within(off).getByRole('link', { name: 'PAY-00201' })).toBeInTheDocument()
    expect(within(off).queryByText(CARD_NOTE)).not.toBeInTheDocument()
    const section = screen.getByRole('region', { name: 'Payments not on the statement' })
    expect(within(section).getByText(CARD_NOTE, { exact: false })).toBeInTheDocument()
  })

  it('links a payment that should be cancelled to its page, where Cancel is', async () => {
    installFakeApi({ ...billScreenRoutes(CONTROLLER), 'GET /reconciliation/bank': { body: REPORT } })
    renderApp('/reconciliation?view=all')
    const note = await screen.findByText(/Cancel PAY-00399 before it is sent\./)
    expect(within(note).getByRole('link', { name: 'Open PAY-00399' })).toHaveAttribute('href', '/payments/PAY-00399')
  })

  it('opens on only issues, switches to all lines through the URL and asks the server for each', async () => {
    const fake = installFakeApi({
      ...billScreenRoutes(CONTROLLER),
      'GET /reconciliation/bank': (request) => ({
        body: new URL(request.url).searchParams.get('only_issues') === 'true' ? { ...REPORT, lines: REPORT.lines.slice(2) } : REPORT,
      }),
    })
    const user = userEvent.setup()
    renderApp('/reconciliation')
    const lastQuery = () => fake.urls.filter((u) => u.pathname === '/api/reconciliation/bank').at(-1)!.searchParams

    // Only issues is the default: no query string, and the server is asked for issues only.
    expect(await screen.findByText('No matched line needs review.')).toBeInTheDocument()
    expect(screen.getByText('No bank fee needs review.')).toBeInTheDocument()
    expect(currentLocation()).toBe('/reconciliation')
    expect(lastQuery().get('only_issues')).toBe('true')

    await user.click(screen.getByText('All lines'))
    await waitFor(() => expect(currentLocation()).toBe('/reconciliation?view=all'))
    expect(await screen.findByRole('button', { name: 'Show 1 matched line' })).toBeInTheDocument()
    expect(lastQuery().get('only_issues')).toBe('false')
  })

  it('shows the server\'s refusal for other roles', async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'finance_manager', user_id: 'U003' }),
      'GET /reconciliation/bank': { status: 403, body: envelope('auth.forbidden_role', "Your role (finance_manager) can't do this.", 'rid-rc-1') },
    })
    renderApp('/reconciliation')
    expect(await screen.findByText("Your role (finance_manager) can't do this.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-rc-1')).toBeInTheDocument()
  })

  it('is in the controller\'s and auditor\'s menus only', () => {
    const has = (role: Parameters<typeof navItemsFor>[0]) => navItemsFor(role).some((item) => item.key === 'reconciliation')
    expect(has('controller_admin')).toBe(true)
    expect(has('auditor')).toBe(true)
    for (const role of ['employee', 'ap_clerk', 'approver', 'finance_manager'] as const) expect(has(role), role).toBe(false)
  })
})
