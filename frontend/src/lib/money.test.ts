import { describe, expect, it } from 'vitest'

import spec from '../../openapi.json?raw'

import {
  MONEY_INPUT_PATTERN,
  MONEY_PATTERN,
  asMoney,
  formatMoney,
  fromCents,
  isMoney,
  parseMoneyInput,
  sumMoney,
  toCents,
  type Money,
} from './money'

const m = (s: string) => asMoney(s)

describe('isMoney', () => {
  it('accepts the API format', () => {
    for (const s of ['0.00', '742.30', '-15.00', '999999999999.99', '1000000000000000.00']) {
      expect(isMoney(s)).toBe(true)
    }
  })

  it('refuses anything else', () => {
    for (const s of ['', '742.3', '742', '742.300', '1,000.00', '$5.00', ' 1.00', '1.00 ', '+1.00', '1e3', '.50']) {
      expect(isMoney(s)).toBe(false)
    }
    expect(isMoney(742.3)).toBe(false)
    expect(isMoney(null)).toBe(false)
  })
})

describe('formatMoney', () => {
  it('formats CAD with a plain dollar sign and thousands separators', () => {
    expect(formatMoney('12345.60', 'CAD')).toBe('$12,345.60')
    expect(formatMoney('742.30')).toBe('$742.30')
    expect(formatMoney('1000.00', 'cad')).toBe('$1,000.00')
  })

  it('prefixes USD so it is never mistaken for CAD', () => {
    expect(formatMoney('1000.00', 'USD')).toBe('US$1,000.00')
    expect(formatMoney('-50.00', 'USD')).toBe('-US$50.00')
  })

  it('shows other currencies by their code', () => {
    expect(formatMoney('1000.00', 'EUR')).toBe('EUR 1,000.00')
  })

  it('handles large values without losing a cent', () => {
    expect(formatMoney('999999999999.99')).toBe('$999,999,999,999.99')
    expect(formatMoney('12345678901234567890.01')).toBe('$12,345,678,901,234,567,890.01')
  })

  it('puts the minus sign first', () => {
    expect(formatMoney('-50.00')).toBe('-$50.00')
    expect(formatMoney('-1234567.89')).toBe('-$1,234,567.89')
  })

  it('shows zero without a sign and drops leading zeros', () => {
    expect(formatMoney('0.00')).toBe('$0.00')
    expect(formatMoney('-0.00')).toBe('$0.00')
    expect(formatMoney('0.05')).toBe('$0.05')
    expect(formatMoney('-0.05')).toBe('-$0.05')
    expect(formatMoney('007.50')).toBe('$7.50')
  })

  it('throws on a value that is not a money string', () => {
    expect(() => formatMoney('742.3')).toThrow(TypeError)
    expect(() => formatMoney('abc')).toThrow(TypeError)
  })
})

describe('cents', () => {
  it('round-trips through BigInt cents', () => {
    for (const s of ['0.00', '0.05', '-0.05', '742.30', '-15.00', '999999999999.99']) {
      expect(fromCents(toCents(m(s)))).toBe(s)
    }
  })

  it('converts exactly', () => {
    expect(toCents(m('999999999999.99'))).toBe(99999999999999n)
    expect(toCents(m('-12.34'))).toBe(-1234n)
    expect(toCents(m('-0.00'))).toBe(0n)
    expect(fromCents(0n)).toBe('0.00')
    expect(fromCents(5n)).toBe('0.05')
    expect(fromCents(-5n)).toBe('-0.05')
    expect(fromCents(123456n)).toBe('1234.56')
  })

  it('sums exactly where floats would drift', () => {
    // 0.1 + 0.2 is 0.30000000000000004 as floats.
    expect(sumMoney([m('0.10'), m('0.20')])).toBe('0.30')
    expect(sumMoney([m('999999999999.99'), m('0.01')])).toBe('1000000000000.00')
    expect(sumMoney([m('100.00'), m('-150.25')])).toBe('-50.25')
    expect(sumMoney([])).toBe('0.00')
  })

  it('refuses a non-money string at the type boundary', () => {
    expect(() => toCents('12.3' as Money)).toThrow(TypeError)
  })
})

describe('parseMoneyInput', () => {
  it('pads to two decimals', () => {
    expect(parseMoneyInput('742.3')).toBe('742.30')
    expect(parseMoneyInput('15')).toBe('15.00')
    expect(parseMoneyInput('15.')).toBeNull()
    expect(parseMoneyInput('0.5')).toBe('0.50')
  })

  it('accepts negatives and trims spaces', () => {
    expect(parseMoneyInput('-15')).toBe('-15.00')
    expect(parseMoneyInput('  12.34 ')).toBe('12.34')
  })

  it('normalises zero and leading zeros', () => {
    expect(parseMoneyInput('0')).toBe('0.00')
    expect(parseMoneyInput('-0')).toBe('0.00')
    expect(parseMoneyInput('007.5')).toBe('7.50')
  })

  it('accepts the largest value the server allows', () => {
    expect(parseMoneyInput('999999999999.99')).toBe('999999999999.99')
    expect(parseMoneyInput('999999999999')).toBe('999999999999.00')
  })

  it('refuses invalid input', () => {
    for (const s of ['', ' ', 'abc', '1,000.00', '$5', '1.234', '1e3', '+5', '.5', '--1', '1.2.3',
      '1000000000000', '1000000000000.00', 'NaN', 'Infinity']) {
      expect(parseMoneyInput(s), s).toBeNull()
    }
  })
})

describe('patterns match the API contract', () => {
  // openapi.json is generated from the backend (npm run gen:api); if the server's pattern changes, this fails.
  it('uses the Money output pattern from openapi.json', () => {
    expect(spec).toContain(JSON.stringify(MONEY_PATTERN.source))
  })

  it('uses the MoneyIn input pattern from openapi.json', () => {
    expect(spec).toContain(JSON.stringify(MONEY_INPUT_PATTERN.source))
  })
})
