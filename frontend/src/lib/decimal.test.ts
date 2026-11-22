import { describe, expect, it } from 'vitest'

import { decimalToPercent, formatUnitPrice } from './decimal'

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

describe('formatUnitPrice', () => {
  it('formats like money with the currency prefix and thousands separators', () => {
    expect(formatUnitPrice('1538.65')).toBe('$1,538.65')
    expect(formatUnitPrice('42.39', 'USD')).toBe('US$42.39')
    expect(formatUnitPrice('15')).toBe('$15.00')
    expect(formatUnitPrice('1234567.5')).toBe('$1,234,567.50')
  })

  it('keeps decimals beyond two, without trailing zeros', () => {
    expect(formatUnitPrice('1.459')).toBe('$1.459')
    expect(formatUnitPrice('0.0125', 'USD')).toBe('US$0.0125')
    expect(formatUnitPrice('42.390')).toBe('$42.39')
    expect(formatUnitPrice('42.3900')).toBe('$42.39')
  })

  it('keeps the sign of a negative price, including one under a cent', () => {
    expect(formatUnitPrice('-12.50')).toBe('-$12.50')
    expect(formatUnitPrice('-0.005')).toBe('-$0.005')
    expect(formatUnitPrice('-0.000')).toBe('$0.00')
  })

  it('returns anything else unchanged', () => {
    expect(formatUnitPrice('n/a')).toBe('n/a')
    expect(formatUnitPrice('1e3')).toBe('1e3')
  })
})
