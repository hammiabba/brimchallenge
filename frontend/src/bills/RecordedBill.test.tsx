import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { RECORDED } from '../test/recorded'
import { renderApp } from '../test/renderApp'

const FINANCE = { role: 'finance_manager', user_id: 'U003' } as const

/** The bill screen on real recorded responses: current_step comes from the server, not from a hand-written fixture. */
describe('bill screen on recorded responses', () => {
  it('says the step is signed as a delegate, from the detail\'s current_step', async () => {
    const bill = RECORDED.delegatedStep
    expect(bill.current_step).toEqual({ step_no: 1, role: 'dept_manager', user_id: 'U003', delegated_from: 'U012' })
    installFakeApi({ ...billScreenRoutes(FINANCE), [`GET /bills/${bill.bill_id}`]: { body: bill } })
    renderApp(`/bills/${bill.bill_id}`)

    const bar = await screen.findByRole('region', { name: 'Your decision' })
    expect(within(bar).getByText('Step 1, Department manager, is waiting for you')).toBeInTheDocument()
    // U012 is Sam Rivera in the test people list.
    expect(await within(bar).findByText('Acting for Sam Rivera: your decision is recorded on their behalf.')).toBeInTheDocument()
  })

  it('says when the step is the last one', async () => {
    const bill = RECORDED.lastStep
    expect(bill.current_step?.step_no).toBe(Math.max(...bill.latest_run!.route.map((s) => s.step_no)))
    installFakeApi({ ...billScreenRoutes(FINANCE), [`GET /bills/${bill.bill_id}`]: { body: bill } })
    const user = userEvent.setup()
    renderApp(`/bills/${bill.bill_id}`)

    const bar = await screen.findByRole('region', { name: 'Your decision' })
    expect(within(bar).getByText('Step 2, Finance manager, is waiting for you')).toBeInTheDocument()
    await user.click(within(bar).getByRole('button', { name: 'Approve' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve bill' })
    expect(within(dialog).getByText(/This is the last step/)).toBeInTheDocument()
  })

  it('says who step 1 goes to after a submit, from the submit answer', async () => {
    let current = RECORDED.readyToSubmit
    installFakeApi({
      ...billScreenRoutes({ role: 'ap_clerk', user_id: 'U004' }),
      [`GET /bills/${current.bill_id}`]: () => ({ body: current }),
      [`POST /bills/${current.bill_id}/submit`]: () => {
        current = RECORDED.submitted
        return { body: current }
      },
    })
    const user = userEvent.setup()
    renderApp(`/bills/${current.bill_id}`)

    const bar = await screen.findByRole('region', { name: 'Ready for approval' })
    await user.click(within(bar).getByRole('button', { name: 'Submit for approval' }))
    // U007 isn't in the test people list, so the id is shown.
    expect(await screen.findByText('AP-00435: step 1 (Department manager) goes to U007.')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Ready for approval' })).not.toBeInTheDocument())
  })
})
