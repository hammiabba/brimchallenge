/**
 * Exact decimal strings that aren't money (tax rates, FX rates, quantities), handled as strings like money is.
 */

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
