import { Text, type MantineFontSize, type StyleProp } from '@mantine/core'

import { formatDate, formatTimestamp } from '../lib/dates'
import { formatMoney } from '../lib/money'

/**
 * An identifier or code in IBM Plex Mono: AP-00427, V004, PAY-00012, GL 6310, HST13. Slightly smaller than the
 * surrounding text so the mono face doesn't look heavier. Use it wherever an ID stands on its own (a table cell, a
 * header, a link); inside a sentence of running text an ID may stay in the body font. An ID never breaks across lines
 * ("AP-" / "00438"): its column grows to fit it instead.
 */
export function Id({ children, size }: { children: string; size?: MantineFontSize }) {
  return (
    <Text component="span" inherit ff="monospace" fz={size ?? '0.93em'} style={{ whiteSpace: 'nowrap' }}>
      {children}
    </Text>
  )
}

interface MoneyTextProps {
  /** A money string from the API ("12345.60"). Anything else throws, as formatMoney does. */
  value: string
  /** ISO currency code; CAD by default (see lib/money for the display convention). */
  currency?: string
  /** "right" renders a block, right-aligned, for table cells and totals. */
  align?: 'left' | 'right'
  fw?: StyleProp<React.CSSProperties['fontWeight']>
}

/** A formatted amount ("$12,345.60", "US$1,000.00") in tabular figures, so columns of amounts line up. */
export function MoneyText({ value, currency = 'CAD', align, fw }: MoneyTextProps) {
  return (
    <Text
      component="span"
      inherit
      fw={fw}
      ta={align}
      display={align === 'right' ? 'block' : undefined}
      style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}
    >
      {formatMoney(value, currency)}
    </Text>
  )
}

/**
 * A date-only value ("Nov 2, 2026", kind "date", the default) or a timestamp in the browser's time zone
 * ("Nov 2, 2026, 10:00 AM EST", kind "timestamp"), as a <time> element with the original value.
 */
export function DateText({ value, kind = 'date' }: { value: string; kind?: 'date' | 'timestamp' }) {
  return (
    <time dateTime={value} style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
      {kind === 'date' ? formatDate(value) : formatTimestamp(value)}
    </time>
  )
}
