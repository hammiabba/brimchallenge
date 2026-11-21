/**
 * Money as exact decimal strings. The API sends every amount as a string with two decimals ("742.30") and accepts
 * only strings, because a JavaScript number (a binary float) can't represent most cent amounts exactly.
 *
 * Rules for the whole UI:
 * - Never turn money into a JS number: no Number(), parseFloat, unary +, or arithmetic on money strings.
 * - Display goes through formatMoney (pure string operations).
 * - The rare sum goes through BigInt cents: toCents / fromCents / sumMoney.
 * - User input goes through parseMoneyInput before it is sent.
 *
 * Currency display convention: CAD is the home currency and shows a plain "$" ("$1,000.00"). Every other currency
 * is prefixed so it can't be mistaken for CAD: USD shows "US$1,000.00"; anything else shows its ISO code and a
 * space ("EUR 1,000.00"). The minus sign goes first: "-$50.00", "-US$50.00".
 */

/** A string the API produced or parseMoneyInput validated: optional minus, digits, a dot and exactly two decimals. */
export type Money = string & { readonly __brand: 'Money' }

/**
 * The API's output pattern for money (Money in backend/app/api/schemas_api.py, and every money field's "pattern"
 * in openapi.json). A test checks this against the generated openapi.json, so a change on the server shows up.
 */
export const MONEY_PATTERN = /^-?\d+\.\d{2}$/

/**
 * The API's input pattern (MoneyIn / MONEY_PATTERN in schemas_api.py): up to 12 integer digits and up to 2 decimals.
 * Also checked against openapi.json by a test.
 */
export const MONEY_INPUT_PATTERN = /^-?\d{1,12}(\.\d{1,2})?$/

/** True when `s` is a money string in the API's output format, e.g. "742.30" or "-15.00". */
export function isMoney(s: unknown): s is Money {
  return typeof s === 'string' && MONEY_PATTERN.test(s)
}

/** `s` as Money, or a TypeError when it isn't in the API's format. Use at the edge where API strings come in. */
export function asMoney(s: string): Money {
  if (!isMoney(s)) {
    throw new TypeError(`Not a money string: ${JSON.stringify(s)}`)
  }
  return s
}

/** Splits a valid money string into its sign, integer digits and two decimal digits. */
function split(m: Money): { negative: boolean; whole: string; cents: string } {
  const negative = m.startsWith('-')
  const unsigned = negative ? m.slice(1) : m
  const dot = unsigned.indexOf('.')
  return { negative, whole: unsigned.slice(0, dot), cents: unsigned.slice(dot + 1) }
}

/** "1234567" -> "1,234,567", by inserting commas every three digits from the right (string operations only). */
function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** The symbol or prefix shown before an amount in `currency` (see the convention at the top of this file). */
function currencyPrefix(currency: string): string {
  const code = currency.trim().toUpperCase()
  if (code === '' || code === 'CAD') return '$'
  if (code === 'USD') return 'US$'
  return `${code} `
}

/**
 * Formats money for display: ("12345.60", "CAD") -> "$12,345.60", ("1000.00", "USD") -> "US$1,000.00",
 * ("-50.00", "CAD") -> "-$50.00". Leading zeros are dropped and "-0.00" shows as "$0.00".
 * Throws a TypeError when `m` isn't a money string, so a contract break is loud rather than shown as a wrong number.
 */
export function formatMoney(m: string, currency = 'CAD'): string {
  const { negative, whole, cents } = split(asMoney(m))
  const trimmed = whole.replace(/^0+(?=\d)/, '')
  const isZero = /^0+$/.test(trimmed) && cents === '00'
  const sign = negative && !isZero ? '-' : ''
  return `${sign}${currencyPrefix(currency)}${groupThousands(trimmed)}.${cents}`
}

/** Money -> integer cents as a BigInt: "-12.34" -> -1234n. Exact for any length. */
export function toCents(m: Money): bigint {
  const { negative, whole, cents } = split(asMoney(m))
  const value = BigInt(whole + cents)
  return negative ? -value : value
}

/** Integer cents -> Money: 123456n -> "1234.56", -5n -> "-0.05", 0n -> "0.00". */
export function fromCents(c: bigint): Money {
  const negative = c < 0n
  const digits = (negative ? -c : c).toString().padStart(3, '0')
  const result = `${negative ? '-' : ''}${digits.slice(0, -2)}.${digits.slice(-2)}`
  return result as Money
}

/** The exact sum of a list of money strings ("0.00" for an empty list). */
export function sumMoney(list: readonly Money[]): Money {
  let total = 0n
  for (const m of list) {
    total += toCents(m)
  }
  return fromCents(total)
}

/**
 * Validates what a user typed into a money field and normalises it to the API's format, or returns null.
 * Accepts what the server accepts (MONEY_INPUT_PATTERN, after trimming spaces): "742.3" -> "742.30",
 * "15" -> "15.00", "-0" -> "0.00", "007.50" -> "7.50". Refuses "", "1,000.00", "$5", "1.234", "1e3" and more than
 * 12 integer digits. The result can go straight into a request body.
 */
export function parseMoneyInput(s: string): Money | null {
  const trimmed = s.trim()
  if (!MONEY_INPUT_PATTERN.test(trimmed)) return null
  const [whole = '', fraction = ''] = trimmed.split('.')
  return fromCents(toCents(`${whole}.${fraction.padEnd(2, '0')}` as Money))
}
