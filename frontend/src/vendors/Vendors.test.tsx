import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { BankChange, VendorDetail } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { VENDOR_SUMMARIES, billScreenRoutes, vendorDetail } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

const CHANGE: BankChange = {
  change_id: 'BCR-0007', vendor_id: 'V011', status: 'pending_verification', request_channel: 'email_request',
  requested_at: '2026-10-30T14:00:00Z', requested_by: 'U005', old_account_last4: '1111', new_account_last4: '4821',
  new_account: null, new_institution: null, new_transit: null, verified_at: null, verified_by: null,
  verified_by_callback: false, origin: 'app',
}

function fullVendor(overrides: Partial<VendorDetail> = {}): VendorDetail {
  return vendorDetail({
    address: '12 Dock Rd, Hamilton ON', ap_contact_email: 'ap@summit.example', gst_hst_number: '123456789RT0001',
    qst_number: null, default_gl_account: '5040', early_pay_discount: null, accepts_card_payment: false,
    onboarded_at: '2024-01-15', origin: 'history',
    bank_account: {
      id: 1, institution: '004', transit: '12345', account: '****1111', account_last4: '1111', masked: true,
      valid_from: '2024-01-15', valid_to: null,
    },
    bank_changes: [CHANGE],
    ...overrides,
  })
}

/** Routes for the vendor screens: the shared ones plus the page and detail endpoints, signed in as AP by default. */
function vendorRoutes(detail = fullVendor(), role: Parameters<typeof billScreenRoutes>[0] = {}) {
  return {
    ...billScreenRoutes(role),
    'GET /vendors/V011': { body: detail },
  }
}

describe('unverified account on file', () => {
  it('warns when the account on file is the new account of a change nobody has verified yet', async () => {
    installFakeApi(vendorRoutes(fullVendor({
      bank_account: { id: 2, institution: '003', transit: '92968', account: '953389679', account_last4: '4821', masked: false,
        valid_from: '2026-10-27', valid_to: null },
    })))
    renderApp('/vendors/V011')
    const warning = await screen.findByRole('status')
    expect(warning).toHaveTextContent('Not verified: this account came in through BCR-0007, which nobody has confirmed by phone yet.')
 
    // Sent in full to this role, but shown by its last four digits, as on every page.
    // (once in the account field and once as the change's new account)
    expect(screen.getAllByText('Ending 4821')).toHaveLength(2)
    expect(screen.queryByText('953389679')).not.toBeInTheDocument()
  })

  it('says nothing when the account on file is the old, settled one', async () => {
    installFakeApi(vendorRoutes())
    renderApp('/vendors/V011')
    await screen.findByRole('table', { name: 'Bank change requests' })
    expect(screen.queryByText(/Not verified/)).not.toBeInTheDocument()
  })
})

describe('lookalike vendors', () => {
  const SAME_NAME = "same name once 'Ltd/Inc/&' are ignored"
  const COPY = { vendor_id: 'V002', legal_name: 'Great Lakes Carriers Inc.', why: SAME_NAME }

  it('tags a suspicious copy in the list with the vendor it looks like', async () => {
    installFakeApi({
      ...vendorRoutes(),
      'GET /vendors': { body: { items: [{ ...VENDOR_SUMMARIES[0], lookalike_of: [COPY] }, VENDOR_SUMMARIES[1]],
        total: 2, limit: 50, offset: 0 } },
    })
    renderApp('/vendors')
    const table = await screen.findByRole('table', { name: 'Vendors' })
    const copy = (await within(table).findByRole('link', { name: 'V011' })).closest('tr')!
    expect(within(copy).getByText('Possible duplicate of V002')).toBeInTheDocument()
    const real = within(table).getByRole('link', { name: 'V004' }).closest('tr')!
    expect(within(real).queryByText(/Possible duplicate/)).not.toBeInTheDocument()
  })

  it('says on the vendor page which record it looks like, with a link to it', async () => {
    installFakeApi(vendorRoutes(fullVendor({ lookalike_of: [COPY] })))
    renderApp('/vendors/V011')
    const note = await screen.findByText(/Possible duplicate of/)
    expect(note).toHaveTextContent(`Possible duplicate of Great Lakes Carriers Inc. (V002): ${SAME_NAME}.`)
    expect(within(note).getByRole('link', { name: 'Great Lakes Carriers Inc.' })).toHaveAttribute('href', '/vendors/V002')
  })

  it('says nothing for a vendor that copies no one', async () => {
    installFakeApi(vendorRoutes())
    renderApp('/vendors/V011')
    await screen.findByRole('table', { name: 'Bank change requests' })
    expect(screen.queryByText(/Possible duplicate/)).not.toBeInTheDocument()
  })
})

describe('vendor list', () => {
  it('lists vendors and sends the URL filters to the API', async () => {
    const fake = installFakeApi(vendorRoutes())
    renderApp('/vendors?status=active&q=summit')

    const table = await screen.findByRole('table', { name: 'Vendors' })
    const link = await within(table).findByRole('link', { name: 'V011' })
    expect(link).toHaveAttribute('href', '/vendors/V011')
    const row = link.closest('tr')!
    expect(within(row).getByText('Summit Packaging Supply')).toBeInTheDocument()
    expect(within(row).getByText('Net 30')).toBeInTheDocument()
    expect(within(row).getByText('Active')).toBeInTheDocument()

    const request = fake.urls.find((url) => url.pathname === '/api/vendors' && url.searchParams.get('limit') === '50')!
    expect(request.searchParams.getAll('status')).toEqual(['active'])
    expect(request.searchParams.get('q')).toBe('summit')
    expect(screen.getByText(`Showing 1 to 2 of ${VENDOR_SUMMARIES.length} vendors`)).toBeInTheDocument()
  })

  it('onboards a vendor and opens its page', async () => {
    let sent: unknown = null
    installFakeApi({
      ...vendorRoutes(),
      'POST /vendors': async (request) => {
        sent = await request.json()
        return { status: 201, body: fullVendor({ vendor_id: 'V099', legal_name: 'Northwind Pallets', status: 'pending_review' }) }
      },
      'GET /vendors/V099': { body: fullVendor({ vendor_id: 'V099', legal_name: 'Northwind Pallets', status: 'pending_review' }) },
    })
    const user = userEvent.setup()
    renderApp('/vendors')

    await user.click(await screen.findByRole('button', { name: 'Onboard vendor' }))
    const dialog = await screen.findByRole('dialog', { name: 'Onboard vendor' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Legal name' }), 'Northwind Pallets')
    await user.type(within(dialog).getByRole('textbox', { name: 'Category' }), 'Packaging')
    await user.type(within(dialog).getByRole('textbox', { name: 'AP contact email' }), 'ap@northwind.example')
    await user.type(within(dialog).getByRole('textbox', { name: 'Address' }), '5 Mill St, Guelph')
    await user.type(within(dialog).getByRole('textbox', { name: 'Province or state' }), 'on')
    await user.click(within(dialog).getByRole('button', { name: 'Onboard vendor' }))

    await waitFor(() => expect(currentLocation()).toBe('/vendors/V099'))
    expect(sent).toMatchObject({
      legal_name: 'Northwind Pallets', province_or_state: 'ON', country: 'CA', payment_terms_days: 30,
      preferred_payment_method: 'EFT', gst_hst_number: null,
    })
    expect(await screen.findByRole('heading', { name: 'Northwind Pallets' })).toBeInTheDocument()
  })
})

describe('vendor page', () => {
  it('shows details, the masked account and the bank change history', async () => {
    installFakeApi(vendorRoutes())
    renderApp('/vendors/V011')

    expect(await screen.findByRole('heading', { name: 'Summit Packaging Supply' })).toBeInTheDocument()
    expect(screen.getByText('ap@summit.example')).toBeInTheDocument()
    // On file, and as the old account of the pending change.
    expect(screen.getAllByText('Ending 1111')).toHaveLength(2)
    const history = screen.getByRole('table', { name: 'Bank change requests' })
    // The same table as the queue, without the vendor (this page is the vendor) or actions.
    expect(within(history).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Change', 'Requested', 'Account', 'Status', 'Decided by',
    ])
    expect(within(history).getByText('BCR-0007')).toBeInTheDocument()
    expect(within(history).queryByRole('link', { name: 'V011' })).not.toBeInTheDocument()
    expect(within(history).getByText('Ending 4821')).toBeInTheDocument()
    expect(within(history).getByText('Ending 4821').closest('td')).toHaveTextContent('Ending 1111→ changed to Ending 4821')
    expect(within(history).getByText('Email request')).toBeInTheDocument()
    expect(within(history).getByText('Pending verification')).toBeInTheDocument()
    // Active: hold is offered, approve isn't.
    expect(screen.getByRole('button', { name: 'Put on hold' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve vendor' })).not.toBeInTheDocument()
  })

  it('shows the server refusal inside the dialog', async () => {
    installFakeApi({
      ...vendorRoutes(fullVendor({ status: 'pending_review' }), { role: 'finance_manager', user_id: 'U003' }),
      'POST /vendors/V011/approve': {
        status: 409, body: envelope('vendor.invalid_state', 'The vendor is active; it must be pending review or on hold.', 'rid-v-01'),
      },
    })
    const user = userEvent.setup()
    renderApp('/vendors/V011')

    await user.click(await screen.findByRole('button', { name: 'Approve vendor' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve vendor' })
    await user.click(within(dialog).getByRole('button', { name: 'Approve vendor' }))
    expect(await within(dialog).findByText('The vendor is active; it must be pending review or on hold.')).toBeInTheDocument()
    expect(within(dialog).getByText('Request id: rid-v-01')).toBeInTheDocument()
  })

  it('requests a bank change with digits only', async () => {
    let sent: unknown = null
    installFakeApi({
      ...vendorRoutes(),
      'POST /vendors/V011/bank-changes': async (request) => {
        sent = await request.json()
        return { status: 201, body: { ...CHANGE, change_id: 'BCR-0008' } }
      },
    })
    const user = userEvent.setup()
    renderApp('/vendors/V011')

    await user.click(await screen.findByRole('button', { name: 'Request bank change' }))
    const dialog = await screen.findByRole('dialog', { name: 'Request bank change' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Institution' }), '010')
    await user.type(within(dialog).getByRole('textbox', { name: 'Transit' }), '54-321')
    await user.type(within(dialog).getByRole('textbox', { name: 'Account number' }), '9876 5432')
    await user.click(within(dialog).getByRole('combobox', { name: 'How the request came in' }))
    await user.click(await screen.findByRole('option', { name: 'Vendor portal' }))
    await user.click(within(dialog).getByRole('button', { name: 'Request change' }))

    await waitFor(() => expect(sent).toEqual({
      institution: '010', transit: '54321', account: '98765432', request_channel: 'vendor_portal',
    }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Request bank change' })).not.toBeInTheDocument())
  })

  it('says so when the vendor does not exist', async () => {
    installFakeApi(billScreenRoutes())
    renderApp('/vendors/V404')
    expect(await screen.findByRole('heading', { name: 'Vendor not found' })).toBeInTheDocument()
  })
})

describe('vendor buttons by role', () => {
  const buttons = () => ['Onboard vendor', 'Approve vendor', 'Put on hold', 'Request bank change']
    .filter((name) => screen.queryByRole('button', { name }) !== null)

  it('AP onboards, holds and requests bank changes, but doesn\'t approve', async () => {
    installFakeApi(vendorRoutes(fullVendor({ status: 'pending_review' })))
    renderApp('/vendors/V011')
    await screen.findByRole('button', { name: 'Put on hold' })
    expect(buttons()).toEqual(['Put on hold', 'Request bank change'])
  })

  it('finance approves and holds, but doesn\'t request bank changes or onboard', async () => {
    installFakeApi(vendorRoutes(fullVendor({ status: 'pending_review' }), { role: 'finance_manager', user_id: 'U003' }))
    renderApp('/vendors/V011')
    await screen.findByRole('button', { name: 'Approve vendor' })
    expect(buttons()).toEqual(['Approve vendor', 'Put on hold'])
  })

  it('an auditor sees no vendor buttons, on the page or the list', async () => {
    installFakeApi({
      ...vendorRoutes(fullVendor({ status: 'pending_review' }), { role: 'auditor', user_id: 'U015' }),
      'GET /vendors': { body: { items: [], total: 0, limit: 50, offset: 0 } },
    })
    renderApp('/vendors/V011')
    await screen.findByRole('heading', { level: 1 })
    expect(buttons()).toEqual([])
    expect(screen.queryByText('No bank account on file. Request a change to add one.')).not.toBeInTheDocument()
  })

  it('only AP gets Onboard vendor on the list', async () => {
    installFakeApi({ ...vendorRoutes(fullVendor(), { role: 'controller_admin', user_id: 'U002' }),
      'GET /vendors': { body: { items: [], total: 0, limit: 50, offset: 0 } } })
    renderApp('/vendors')
    await screen.findByRole('heading', { level: 1, name: 'Vendors' })
    expect(screen.queryByRole('button', { name: 'Onboard vendor' })).not.toBeInTheDocument()
  })
})
