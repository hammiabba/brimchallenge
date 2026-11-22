import { describe, expect, it } from 'vitest'

import { similarityText, vendorMatchLine } from './labels'

describe('vendor match line', () => {
  it('says only how an exact match was made', () => {
    expect(vendorMatchLine('gst_number', 1)).toBe('Matched by GST number')
    expect(vendorMatchLine('bank_account', 0.999)).toBe('Matched by bank account')
    expect(vendorMatchLine('email_domain', null)).toBe('Matched by email domain')
  })

  it('adds how alike a partial match is, in the same words as duplicate matches', () => {
    expect(vendorMatchLine('fuzzy_name', 0.87)).toBe('Matched by similar name (87% alike)')
    expect(similarityText(0.87)).toBe('87% alike')
    expect(similarityText(1)).toBe('100% alike')
  })

  it('says so when there is no match', () => {
    expect(vendorMatchLine(null, null)).toBe('Not matched to a vendor')
    expect(vendorMatchLine('something_new', 1)).toBe('Not matched to a vendor')
  })
})
