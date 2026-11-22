/**
 * Exact decimal strings that aren't plain money (tax rates, FX rates, quantities, unit prices with more than two
 * decimals), handled as strings like money is.
 */

import { formatMoney } from './money'

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/

/**
 * A rate as a percentage, by moving the decimal point two places (no floating point):
 * "0.13" -> "13%", "0.09975" -> "9.975%", "0.05" -> "5%", "1" -> "100%". Anything that isn't a plain decimal is
 * returned unchanged, so an unexpected value is shown as the server sent it.
 */
export function decimalToPercent(rate: string): string {
  const match = DECIMAL.exec(rate.trim())
  if (!match) return rate
  const [, sign = '', whole = '', fraction = ''] = match
  const padded = fraction.padEnd(2, '0')
  const percentWhole = `${whole}${padded.slice(0, 2)}`.replace(/^0+(?=\d)/, '')
  const percentFraction = padded.slice(2).replace(/0+$/, '')
  const isZero = /^0+$/.test(percentWhole) && percentFraction === ''
  return `${isZero ? '' : sign}${percentWhole}${percentFraction ? `.${percentFraction}` : ''}%`
}

/**
 * A unit price for display, like money ("$1,538.65", "US$42.39") but keeping any decimals beyond two, as invoices
 * sometimes price per unit to the tenth of a cent: "1.459" -> "$1.459", "42.390" -> "$42.39". The first two
 * decimals go through formatMoney (currency prefix, thousands separators); the extra digits are appended as sent,
 * minus trailing zeros. String handling only, never a number. Anything that isn't a plain decimal is returned as is.
 */
export function formatUnitPrice(value: string, currency = 'CAD'): string {
  const match = DECIMAL.exec(value.trim())
  if (!match) return value
  const [, sign = '', whole = '', fraction = ''] = match
  const padded = fraction.padEnd(2, '0')
  const extra = padded.slice(2).replace(/0+$/, '')
  const head = formatMoney(`${whole}.${padded.slice(0, 2)}`, currency)
  // formatMoney shows "-0.00" as "$0.00", so the sign is added here, only when some digit isn't zero.
  const negative = sign === '-' && /[1-9]/.test(whole + padded)
  return `${negative ? '-' : ''}${head}${extra}`
}
