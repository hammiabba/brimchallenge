import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { IntakeItem } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

const EMPLOYEE = { role: 'employee' as const, user_id: 'U013', full_name: 'Avery Chen', department_id: 'D01' }

const QUEUED: IntakeItem = {
  item_id: 41, file_name: 'acme-oct.pdf', file_hash: null, status: 'queued', error: null, warnings: [],
  bill_id: null, email_id: null, created_at: '2026-11-02T15:00:00Z', created_by: 'U013',
}

describe('submit invoice', () => {
  it('uploads the file as multipart with the department, then opens My submissions', async () => {
    // jsdom's FormData can't travel through Node's Request in tests, so record what the page puts in the form.
    const fields: Record<string, string> = {}
    vi.spyOn(FormData.prototype, 'append').mockImplementation((name: string, value: string | Blob) => {
      fields[name] = value instanceof File ? value.name : String(value)
    })
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': { status: 202, body: QUEUED },
      'GET /submissions': { body: [QUEUED] },
    })
    const user = userEvent.setup()
    renderApp('/submit')

    await screen.findByRole('heading', { name: 'Submit invoice' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['%PDF-1.4'], 'acme-oct.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Submit invoice' }))

    await waitFor(() => expect(currentLocation()).toBe('/submissions'))
    expect(fields).toEqual({ file: 'acme-oct.pdf', department_id: 'D01' })
  })

  it("shows the server's refusal of a file type", async () => {
    installFakeApi({
      ...billScreenRoutes(EMPLOYEE),
      'POST /submissions': { status: 415, body: envelope('intake.unsupported_file', 'Allowed file types: .pdf, .png.') },
    })
    const user = userEvent.setup()
    renderApp('/submit')

    await screen.findByRole('heading', { name: 'Submit invoice' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['x'], 'invoice.png', { type: 'image/png' }))
    await user.click(screen.getByRole('button', { name: 'Submit invoice' }))
    expect(await screen.findByText('Allowed file types: .pdf, .png.')).toBeInTheDocument()
    expect(currentLocation()).toBe('/submit')
  })

  it('needs a file before it can send', async () => {
    installFakeApi(billScreenRoutes(EMPLOYEE))
    renderApp('/submit')
    expect(await screen.findByRole('button', { name: 'Submit invoice' })).toBeDisabled()
  })
})
