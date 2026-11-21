/**
 * Dates and timestamps from the API.
 *
 * - Date-only values ("2026-11-02": invoice, due and payment dates) are calendar dates with no time zone. They are
 *   formatted by splitting the string. Never parse them with `new Date("2026-11-02")`: that means midnight UTC,
 *   which is the evening of Nov 1 anywhere west of UTC (all of Canada), so the UI would show the previous day.
 * - Timestamps ("2026-11-02T15:00:00Z": audit events, decisions, releases) are instants. The API sends them in UTC
 *   with an explicit "Z"; they are shown in the browser's time zone with its abbreviation.
 *
 * Display is English: "Nov 2, 2026" and "Nov 2, 2026, 10:00 AM EST".
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/
// An explicit UTC marker or offset at the end: "Z", "+05:30", "-0500".
const HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/i

/** Days in `month` (1-12) of `year`, with the Gregorian leap-year rule. */
function daysInMonth(year: number, month: number): number {
  if (month === 2) {
    const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0
    return leap ? 29 : 28
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31
}

/** "2026-11-02" -> { year: 2026, month: 11, day: 2 }, or null when it isn't a real calendar date. */
export function parseDateOnly(value: string): { year: number; month: number; day: number } | null {
  const match = DATE_ONLY.exec(value)
  if (!match) return null
  // Small integers (a year, month and day), not money: parseInt is fine here.
  const year = Number.parseInt(match[1] ?? '', 10)
  const month = Number.parseInt(match[2] ?? '', 10)
  const day = Number.parseInt(match[3] ?? '', 10)
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null
  return { year, month, day }
}

/** Month abbreviation for 1-12. */
function monthName(month: number): string {
  return MONTHS[month - 1] ?? '?'
}

/**
 * A date-only string for display: "2026-11-02" -> "Nov 2, 2026". Pure string handling, so the result is the same in
 * every time zone. Throws a TypeError for anything that isn't a real YYYY-MM-DD date.
 */
export function formatDate(value: string): string {
  const parsed = parseDateOnly(value)
  if (!parsed) {
    throw new TypeError(`Not a YYYY-MM-DD date: ${JSON.stringify(value)}`)
  }
  return `${monthName(parsed.month)} ${parsed.day}, ${parsed.year}`
}

let warnedMissingOffset = false

/**
 * An ISO 8601 timestamp for display in the browser's time zone (or `options.timeZone`):
 * "2026-11-02T15:00:00Z" -> "Nov 2, 2026, 10:00 AM EST" in Toronto.
 *
 * The API is asked to send UTC with "Z". A value without "Z" or an offset is treated as UTC, and a console warning
 * is logged once per page load so the gap gets noticed; JavaScript would otherwise read it as local time.
 * Throws a TypeError for a value that isn't a timestamp.
 */
export function formatTimestamp(iso: string, options: { timeZone?: string } = {}): string {
  let value = iso.trim()
  if (DATE_ONLY.test(value)) {
    throw new TypeError(`A date-only value is not a timestamp; use formatDate: ${JSON.stringify(iso)}`)
  }
  if (!HAS_OFFSET.test(value)) {
    if (!warnedMissingOffset) {
      warnedMissingOffset = true
      console.warn(`Timestamp without a time zone, treated as UTC: ${JSON.stringify(iso)}. The API should send "Z".`)
    }
    value = `${value}Z`
  }
  // A full timestamp with an explicit zone is an instant, so parsing it with Date is safe (unlike a date-only value).
  const instant = new Date(value)
  if (Number.isNaN(instant.getTime())) {
    throw new TypeError(`Not an ISO 8601 timestamp: ${JSON.stringify(iso)}`)
  }

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: options.timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  }).formatToParts(instant)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''

  const month = Number.parseInt(part('month'), 10)
  return `${monthName(month)} ${part('day')}, ${part('year')}, ${part('hour')}:${part('minute')} ` +
    `${part('dayPeriod')} ${part('timeZoneName')}`
}
