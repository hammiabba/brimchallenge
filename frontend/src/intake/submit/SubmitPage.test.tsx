import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { envelope, installFakeApi, type FakeReply } from '../../test/fakeApi'
import { billScreenRoutes } from '../../test/fixtures'
import { renderApp } from '../../test/renderApp'
import { fileOf, intakeItem } from '../common/testData'

const EMPLOYEE = { user_id: 'U013', full_name: 'Avery Chen', role: 'employee' as const, department_id: 'D01' }

/** The file input (hidden behind the "Choose files" button). */
function fileInput(): HTMLInputElement {
  return screen.getByLabelText('Invoice files')
}

/** The table row for a file name. */
async function rowFor(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole('table', { name: 'Files' })
  return within(table).getByText(name).closest('tr')!
}

/**
 * Records the files the page puts in each POST /submissions form. (The test fetch turns jsdom Files into plain blobs,
 * so their names can't be read back from the request body itself.)
 */
function spyOnSentFiles(): () => string[] {
  const append = vi.spyOn(FormData.prototype, 'append')
  return () => append.mock.calls.filter(([field]) => field === 'file').map(([, , name]) => name as string)
}

describe('submit invoice', () => {
  it('sends a file and follows it to its bill', async () => {
    const sentFiles = spyOnSentFiles()
    const fake = installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': { status: 202, body: intakeItem({ status: 'queued', bill_id: null, file_hash: null }) },
      'GET /submissions': { body: [intakeItem()] },
    })
    const user = userEvent.setup()
    renderApp('/submit')

    expect(await screen.findByRole('heading', { name: 'Submit invoice' })).toBeInTheDocument()
    await user.upload(fileInput(), fileOf('Invoice HA26-2766.pdf'))
    expect(within(await rowFor('Invoice HA26-2766.pdf')).getByText('Ready to send')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Submit' }))
    const row = await rowFor('Invoice HA26-2766.pdf')
    expect(await within(row).findByText('Done')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'AP-00431' })).toHaveAttribute('href', '/bills/AP-00431')
    expect(screen.getByRole('link', { name: 'See all in My submissions' })).toHaveAttribute('href', '/submissions')
    expect(sentFiles()).toEqual(['Invoice HA26-2766.pdf'])
    expect(fake.calls.filter((call) => call === 'POST /submissions')).toHaveLength(1)
  })

  it('says what happens to a file once sent, and why Submit is disabled before one is chosen', async () => {
    installFakeApi({ ...billScreenRoutes(EMPLOYEE), 'GET /submissions': { body: [] } })
    const user = userEvent.setup()
    renderApp('/submit')

    expect(await screen.findByText(/Each file you send becomes a bill/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Submit' })
    expect(submit).toBeDisabled()
    expect(submit).toHaveAccessibleDescription('Choose at least one PDF or image file to submit.')

    await user.upload(fileInput(), fileOf('Invoice HA26-2766.pdf'))
    expect(screen.getByRole('button', { name: 'Submit' })).toBeEnabled()
    expect(screen.queryByText('Choose at least one PDF or image file to submit.')).not.toBeInTheDocument()
  })

  it('keeps Submit disabled while uploading', async () => {
    let release: (reply: FakeReply) => void = () => {}
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': () => new Promise<FakeReply>((resolve) => { release = resolve }),
      'GET /submissions': { body: [intakeItem({ status: 'processing', bill_id: null })] },
    })
    const user = userEvent.setup()
    renderApp('/submit')
    await user.upload(await screen.findByLabelText('Invoice files'), fileOf('a.pdf'))
    await user.click(screen.getByRole('button', { name: 'Submit' }))

    expect(await screen.findByRole('button', { name: 'Uploading' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Choose files' })).toBeDisabled()
    release({ status: 202, body: intakeItem({ status: 'queued', bill_id: null }) })
    expect(await within(await rowFor('a.pdf')).findByText('Processing')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit' })).toBeDisabled()
  })

  it('refuses a file type the server would not take, without sending it', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(EMPLOYEE) })
    renderApp('/submit')
    const zone = await screen.findByTestId('drop-zone')
    fireEvent.drop(zone, { dataTransfer: { files: [fileOf('notes.docx', 100, 'application/msword')] } })

    const row = await rowFor('notes.docx')
    expect(within(row).getByText('Not sent')).toBeInTheDocument()
    expect(within(row).getByText(/Only PDF and image files/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit' })).toBeDisabled()
    expect(fake.calls).not.toContain('POST /submissions')
  })

  it('refuses a file over 10 MB', async () => {
    installFakeApi({ ...billScreenRoutes(EMPLOYEE) })
    const user = userEvent.setup()
    renderApp('/submit')
    const big = fileOf('scan.png', 10, 'image/png')
    Object.defineProperty(big, 'size', { value: 11 * 1024 * 1024 })
    await user.upload(await screen.findByLabelText('Invoice files'), big)

    expect(within(await rowFor('scan.png')).getByText('The file is larger than 10 MB.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit' })).toBeDisabled()
  })

  it.each([
    [422, 'request.invalid', 'Department D99 does not exist.'],
    [415, 'intake.unsupported_file', 'Allowed file types: .pdf, .png.'],
    [403, 'auth.forbidden_role', "Your role (approver) can't do this."],
  ])('shows the server refusal (%i) on the file row', async (status, code, message) => {
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': { status, body: envelope(code, message, 'rid-sub-1') },
    })
    const user = userEvent.setup()
    renderApp('/submit')
    await user.upload(await screen.findByLabelText('Invoice files'), fileOf('a.pdf'))
    await user.click(screen.getByRole('button', { name: 'Submit' }))

    const row = await rowFor('a.pdf')
    expect(await within(row).findByText('Not accepted')).toBeInTheDocument()
    expect(within(row).getByText(message)).toBeInTheDocument()
    expect(within(row).getByText('Request id: rid-sub-1')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'See all in My submissions' })).not.toBeInTheDocument()
  })

  it('links a file that was already received to the existing bill', async () => {
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': { status: 202, body: intakeItem({ status: 'queued', bill_id: null }) },
      'GET /submissions': {
        body: [intakeItem({
          bill_id: 'AP-00049',
          warnings: ['already_received: this exact file was already received as bill AP-00049 (status paid); no new bill was created'],
        })],
      },
    })
    const user = userEvent.setup()
    renderApp('/submit')
    await user.upload(await screen.findByLabelText('Invoice files'), fileOf('a.pdf'))
    await user.click(screen.getByRole('button', { name: 'Submit' }))

    const row = await rowFor('a.pdf')
    expect(await within(row).findByText(/Already received as/)).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'AP-00049' })).toHaveAttribute('href', '/bills/AP-00049')
  })

  it('sends several files one by one, each with its own result', async () => {
    const sentFiles = spyOnSentFiles()
    const names = ['a.pdf', 'b.png']
    let next = 200
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': () => {
        const item = intakeItem({ item_id: next, file_name: names[next - 200], status: 'queued', bill_id: null })
        next += 1
        return { status: 202, body: item }
      },
      'GET /submissions': {
        body: [
          intakeItem({ item_id: 201, file_name: 'b.png', status: 'failed', bill_id: null, error: 'The file is not an invoice.' }),
          intakeItem({ item_id: 200, file_name: 'a.pdf', bill_id: 'AP-00432' }),
        ],
      },
    })
    const user = userEvent.setup()
    renderApp('/submit')
    await user.upload(await screen.findByLabelText('Invoice files'), [fileOf('a.pdf'), fileOf('b.png', 50, 'image/png')])
    await user.click(screen.getByRole('button', { name: 'Submit 2 files' }))

    expect(await within(await rowFor('a.pdf')).findByRole('link', { name: 'AP-00432' })).toBeInTheDocument()
    const failed = await rowFor('b.png')
    expect(await within(failed).findByText('Failed')).toBeInTheDocument()
    expect(within(failed).getByText('The file is not an invoice.')).toBeInTheDocument()
    expect(sentFiles()).toEqual(['a.pdf', 'b.png'])
  })
})

describe('submit invoice for roles that may not submit', () => {
  it('says who submits instead of showing the upload controls', async () => {
    installFakeApi(billScreenRoutes({ role: 'auditor', user_id: 'U015' }))
    renderApp('/submit')
    expect(await screen.findByText('Employees and AP submit invoices; your role reads them in Bills.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Choose files|Submit/ })).not.toBeInTheDocument()
  })

  it('gives AP the upload form', async () => {
    installFakeApi(billScreenRoutes({ role: 'ap_clerk', user_id: 'U005' }))
    renderApp('/submit')
    expect(await screen.findByRole('button', { name: 'Choose files' })).toBeInTheDocument()
  })
})
