import { afterEach, describe, expect, it, vi } from 'vitest'

import { formatDate, formatTimestamp, parseDateOnly } from './dates'

describe('test environment', () => {
  it('runs west of UTC, where the previous-day bug would show', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/Toronto')
  })
})

describe('formatDate', () => {
  it('formats a date-only string by splitting it', () => {
    expect(formatDate('2026-11-02')).toBe('Nov 2, 2026')
    expect(formatDate('2026-01-31')).toBe('Jan 31, 2026')
    expect(formatDate('2024-02-29')).toBe('Feb 29, 2024')
  })

  it('never shows the previous day west of UTC', () => {
    // The bug this guards against: new Date("2026-11-02") is midnight UTC, i.e. Nov 1 at 7 or 8 PM in Toronto.
    expect(new Date('2026-11-02').getDate()).toBe(1)
    expect(formatDate('2026-11-02')).toBe('Nov 2, 2026')
    expect(formatDate('2026-01-01')).toBe('Jan 1, 2026')
  })

  it('refuses values that are not real dates', () => {
    for (const s of ['', '2026-11-2', '2026/11/02', '2026-13-01', '2026-00-10', '2026-02-29', '2026-04-31',
      '2026-11-02T00:00:00Z', 'Nov 2, 2026']) {
      expect(() => formatDate(s), s).toThrow(TypeError)
    }
  })

  it('parses the parts', () => {
    expect(parseDateOnly('2026-11-02')).toEqual({ year: 2026, month: 11, day: 2 })
    expect(parseDateOnly('2026-02-30')).toBeNull()
  })
})

describe('formatTimestamp', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows an instant near midnight UTC on the right local day', () => {
    // 03:30 UTC on Nov 2 is still the evening of Nov 1 in Toronto (EST, UTC-5).
    expect(formatTimestamp('2026-11-02T03:30:00Z')).toBe('Nov 1, 2026, 10:30 PM EST')
    expect(formatTimestamp('2026-11-02T03:30:00Z', { timeZone: 'UTC' })).toBe('Nov 2, 2026, 3:30 AM UTC')
    expect(formatTimestamp('2026-11-02T05:00:00Z')).toBe('Nov 2, 2026, 12:00 AM EST')
  })

  it('respects an explicit offset', () => {
    expect(formatTimestamp('2026-11-02T10:00:00-05:00', { timeZone: 'UTC' })).toBe('Nov 2, 2026, 3:00 PM UTC')
    expect(formatTimestamp('2026-07-01T12:00:00+00:00')).toBe('Jul 1, 2026, 8:00 AM EDT')
  })

  it('treats a missing offset as UTC and warns once', async () => {
    vi.resetModules()
    const fresh = await import('./dates')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

    expect(fresh.formatTimestamp('2026-11-02T03:30:00', { timeZone: 'UTC' })).toBe('Nov 2, 2026, 3:30 AM UTC')
    expect(fresh.formatTimestamp('2026-11-02T03:30:00')).toBe('Nov 1, 2026, 10:30 PM EST')
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it('refuses values that are not timestamps', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(() => formatTimestamp('not a date')).toThrow(TypeError)
    expect(() => formatTimestamp('2026-11-02')).toThrow(TypeError)
  })
})
