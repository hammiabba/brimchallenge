import { describe, expect, it } from 'vitest'

import { decimalToPercent } from './decimal'

describe('decimalToPercent', () => {
  it('moves the decimal point two places', () => {
    expect(decimalToPercent('0.13')).toBe('13%')
    expect(decimalToPercent('0.05')).toBe('5%')
    expect(decimalToPercent('0.09975')).toBe('9.975%')
    expect(decimalToPercent('0.14975')).toBe('14.975%')
    expect(decimalToPercent('1')).toBe('100%')
    expect(decimalToPercent('0.5')).toBe('50%')
  })

  it('handles zero and negatives', () => {
    expect(decimalToPercent('0')).toBe('0%')
    expect(decimalToPercent('0.000')).toBe('0%')
    expect(decimalToPercent('-0.13')).toBe('-13%')
  })

  it('returns anything else unchanged', () => {
    expect(decimalToPercent('abc')).toBe('abc')
    expect(decimalToPercent('1e-2')).toBe('1e-2')
  })
})
