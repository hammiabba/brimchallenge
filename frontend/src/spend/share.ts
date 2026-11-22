import { asMoney, toCents } from '../lib/money'

/**
 * A row's share of the total as "12.3%", computed exactly in integer cents (never as a float of money), rounded to
 * one decimal place. A credit row gives a negative share.
 */
export function shareOf(part: string, total: string): string {
  const whole = toCents(asMoney(total))
  if (whole <= 0n) return ''
  const cents = toCents(asMoney(part))
  const magnitude = cents < 0n ? -cents : cents
  // Round half up on the magnitude, so a credit (negative row) rounds the same way as a charge.
  const tenths = (magnitude * 1000n * 2n + whole) / (whole * 2n)
  const sign = cents < 0n && tenths > 0n ? '-' : ''
  return `${sign}${tenths / 10n}.${tenths % 10n}%`
}
