import { describe, expect, it } from 'vitest'

import { classifyEvidence, evidenceValue, keyLabel } from './evidence'

const CAD = { currency: 'CAD' }

describe('expected vs found', () => {
  it('pairs tax codes and amounts side by side, with the rest as facts', () => {
    // TAX_WRONG_FOR_PROVINCE on AP-00253.
    const blocks = classifyEvidence({
      ship_to: 'AB', expected_codes: ['GST5'], charged_codes: ['HST13'], expected_gst_hst: '264.87',
      expected_pst_qst: '0.00', charged_gst_hst: '688.66', charged_pst_qst: '0',
    }, CAD)
    expect(blocks.map((b) => b.type)).toEqual(['pairs', 'facts'])
    const pairs = blocks[0]!
    if (pairs.type !== 'pairs') throw new Error('expected pairs')
    expect([pairs.expectedLabel, pairs.foundLabel]).toEqual(['Expected', 'Charged'])
    expect(pairs.rows.map((r) => r.label)).toEqual(['Tax codes', 'GST/HST', 'PST/QST'])
    expect(pairs.rows[1]).toEqual({
      label: 'GST/HST',
      expected: { kind: 'money', value: '264.87', currency: 'CAD' },
      found: { kind: 'money', value: '688.66', currency: 'CAD' },
    })
    // "0" isn't in the API's money format; it is normalised, never turned into a number.
    expect(pairs.rows[2]!.found).toEqual({ kind: 'money', value: '0.00', currency: 'CAD' })
    expect(blocks[1]).toEqual({ type: 'facts', rows: [{ key: 'ship_to', label: 'Ship to', value: { kind: 'text', value: 'AB' } }] })
  })

  it('shows bank fields on file vs on the invoice one row per field', () => {
    const [block] = classifyEvidence({
      fields: ['account'], invoice: { account: '*****9679', transit: '40238' }, master: { account: '*****7504', transit: '40238' },
    }, CAD)
    if (block?.type !== 'pairs') throw new Error('expected pairs')
    expect([block.expectedLabel, block.foundLabel]).toEqual(['On file', 'On the invoice'])
    expect(block.rows).toEqual([
      { label: 'Account', expected: { kind: 'text', value: '*****7504' }, found: { kind: 'text', value: '*****9679' } },
      { label: 'Transit', expected: { kind: 'text', value: '40238' }, found: { kind: 'text', value: '40238' } },
    ])
  })

  it('uses the bill currency for amounts that are not CAD', () => {
    const [block] = classifyEvidence({ computed: '5124.23', total: '5124.00' }, { currency: 'USD' })
    if (block?.type !== 'pairs') throw new Error('expected pairs')
    expect(block.rows[0]!.expected).toEqual({ kind: 'money', value: '5124.23', currency: 'USD' })
  })
})

describe('duplicates', () => {
  it('lists bill matches as links with the run\'s kind and score', () => {
    // DUPLICATE_EXACT on AP-00407.
    const blocks = classifyEvidence({ matches: ['AP-00394'], kinds: ['exact'], best_score: 1.0 }, {
      currency: 'CAD',
      duplicates: [{ kind: 'exact', score: 1, matched_invoice_id: 'AP-00394', matched_card_txn_id: null, reasons: ['same number'] }],
    })
    expect(blocks).toEqual([{
      type: 'matches',
      rows: [{ id: 'AP-00394', isBill: true, kind: 'exact', score: 1, reasons: ['same number'] }],
    }])
  })

  it('keeps a card transaction as an id, not a link, and falls back to the flag\'s own kinds', () => {
    // ALREADY_PAID_BY_CARD on AP-00015, without the run's duplicate list.
    const [block] = classifyEvidence({ matches: ['CT-00017'], kinds: ['card_paid'], best_score: 0.87 }, CAD)
    expect(block).toEqual({
      type: 'matches',
      rows: [{ id: 'CT-00017', isBill: false, kind: 'card_paid', score: 0.87, reasons: [] }],
    })
  })

  it('shows the related bills of a possible split with their combined total', () => {
    // POSSIBLE_SPLIT on AP-00207.
    const blocks = classifyEvidence({ related: ['AP-00200', 'AP-00206'], combined_cad: '14070.00', policy: 'P01' }, CAD)
    expect(blocks).toEqual([
      { type: 'related', bills: ['AP-00200', 'AP-00206'], combinedCad: { kind: 'money', value: '14070.00', currency: 'CAD' } },
      { type: 'facts', rows: [{ key: 'policy', label: 'Policy', value: { kind: 'id', value: 'P01' } }] },
    ])
  })
})

describe('bank change', () => {
  it('shows old and new last 4 with date, channel and verification', () => {
    // BANK_CHANGE_UNVERIFIED: the evidence is the bank_change_history row.
    const blocks = classifyEvidence({
      change_id: 'BC-009', vendor_id: 'V004', changed_at: '2026-10-27', changed_by: 'U005', request_channel: 'email_request',
      old_account_last4: '7504', new_account_last4: '9679', verified_by_callback: 'no',
    }, CAD)
    expect(blocks[0]).toEqual({
      type: 'bankChange', oldLast4: '7504', newLast4: '9679', changedOn: { kind: 'date', value: '2026-10-27' },
      channel: 'email_request', verified: false,
    })
    expect(blocks[1]).toEqual({
      type: 'facts',
      rows: [
        { key: 'change_id', label: 'Change ID', value: { kind: 'id', value: 'BC-009' } },
        { key: 'vendor_id', label: 'Vendor ID', value: { kind: 'id', value: 'V004' } },
        { key: 'changed_by', label: 'Changed by', value: { kind: 'id', value: 'U005' } },
      ],
    })
  })
})

describe('fallback', () => {
  it('lists unknown keys as facts, formatting by key and type', () => {
    // VENDOR_LOOKALIKE on AP-00109, plus a contract end date.
    const [block] = classifyEvidence({
      similar_vendor: 'V002', why: "same name once 'Ltd/Inc/&' are ignored", this_invoices: 0, end_date: '2026-06-30',
      po_remaining: '2321.43', lines: [2], urgent: true,
    }, CAD)
    expect(block).toEqual({
      type: 'facts',
      rows: [
        { key: 'similar_vendor', label: 'Similar vendor', value: { kind: 'id', value: 'V002' } },
        { key: 'why', label: 'Why', value: { kind: 'text', value: "same name once 'Ltd/Inc/&' are ignored" } },
        { key: 'this_invoices', label: 'This invoices', value: { kind: 'text', value: '0' } },
        { key: 'end_date', label: 'End date', value: { kind: 'date', value: '2026-06-30' } },
        { key: 'po_remaining', label: 'PO remaining', value: { kind: 'money', value: '2321.43', currency: 'CAD' } },
        { key: 'lines', label: 'Lines', value: { kind: 'list', items: [{ kind: 'text', value: '2' }] } },
        { key: 'urgent', label: 'Urgent', value: { kind: 'text', value: 'Yes' } },
      ],
    })
  })

  it('gives no blocks for empty evidence', () => {
    expect(classifyEvidence({}, CAD)).toEqual([])
    expect(classifyEvidence(null, CAD)).toEqual([])
  })

  it('keeps a value with too many decimals as text rather than rounding it', () => {
    expect(evidenceValue('overage', '324.234', CAD)).toEqual({ kind: 'text', value: '324.234' })
    expect(evidenceValue('rate', '1.3709', CAD)).toEqual({ kind: 'text', value: '1.3709' })
  })

  it('labels keys in plain words with acronyms kept', () => {
    expect(keyLabel('po_remaining')).toBe('PO remaining')
    expect(keyLabel('expected_gst_hst')).toBe('Expected GST HST')
  })
})
