import { MantineProvider, Title } from '@mantine/core'
import { IconLogout } from '@tabler/icons-react'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import { BILL_STATUS, PAYMENT_STATUS, VENDOR_STATUS, BANK_CHANGE_STATUS } from './statusStyles'
import { OverdueBadge, RoleBadge, SeverityBadge, SeverityCountBadge, StatusBadge } from './Badges'
import { DateText, Id, MoneyText } from './DataText'
import { ICON_STROKE, Icon } from './Icon'
import { FONT, SEVERITY_STYLES, STATUS_TONES, theme } from '../theme'

/** Renders inside Mantine with the app theme. */
function renderUi(ui: ReactNode) {
  return render(<MantineProvider theme={theme} env="test">{ui}</MantineProvider>)
}

/** jsdom reports inline colours as rgb(); convert a theme hex for comparison. */
function rgb(hex: string): string {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`
}

describe('MoneyText', () => {
  it('formats through lib/money in tabular figures', () => {
    renderUi(<MoneyText value="12345.60" />)
    const amount = screen.getByText('$12,345.60')
    expect(amount.style.fontVariantNumeric).toBe('tabular-nums')
  })

  it('shows USD with its prefix and right-aligns as a block for tables', () => {
    renderUi(<MoneyText value="-50.00" currency="USD" align="right" />)
    expect(screen.getByText('-US$50.00')).toBeInTheDocument()
  })
})

describe('DateText', () => {
  it('formats a date-only value without shifting the day', () => {
    renderUi(<DateText value="2026-11-02" />)
    const time = screen.getByText('Nov 2, 2026')
    expect(time.tagName).toBe('TIME')
    expect(time).toHaveAttribute('datetime', '2026-11-02')
  })

  it('formats a timestamp in the local time zone', () => {
    renderUi(<DateText value="2026-11-02T03:30:00Z" kind="timestamp" />)
    expect(screen.getByText('Nov 1, 2026, 10:30 PM EST')).toBeInTheDocument()
  })
})

describe('Id', () => {
  it('renders the id in the monospace font', () => {
    renderUi(<Id>AP-00427</Id>)
    expect(screen.getByText('AP-00427').style.fontFamily).toContain('monospace')
  })

  it('never breaks an id across lines', () => {
    renderUi(<Id>AP-00438</Id>)
    expect(screen.getByText('AP-00438').style.whiteSpace).toBe('nowrap')
  })
})

describe('badges', () => {
  it('gives every status a label and a tone, for each kind', () => {
    for (const table of [BILL_STATUS, PAYMENT_STATUS, VENDOR_STATUS, BANK_CHANGE_STATUS]) {
      for (const style of Object.values(table)) {
        expect(style.label).toMatch(/^[A-Z][a-z ]+$/)
        expect(STATUS_TONES[style.tone]).toBeDefined()
      }
    }
  })

  it('renders a status in its tone, in sentence case', () => {
    renderUi(<StatusBadge kind="bill" status="needs_review" />)
    const badge = screen.getByText('Needs review').closest('.mantine-Badge-root') as HTMLElement
    expect(badge.style.color).toBe(rgb(STATUS_TONES.attention.color))
    expect(badge.style.backgroundColor).toBe(rgb(STATUS_TONES.attention.background))
  })

  it('shows an open flag in the neutral tone, leaving urgency to the severity badge', () => {
    renderUi(<StatusBadge kind="flag" status="open" />)
    const badge = screen.getByText('Open').closest('.mantine-Badge-root') as HTMLElement
    expect(badge.style.color).toBe(rgb(STATUS_TONES.neutral.color))
    expect(badge.style.backgroundColor).toBe(rgb(STATUS_TONES.neutral.background))
  })

  it('renders block and warn severities solid, info as a tint', () => {
    renderUi(
      <>
        <SeverityBadge severity="block" />
        <SeverityBadge severity="warn" />
        <SeverityBadge severity="info" />
      </>,
    )
    for (const [label, severity] of [['Block', 'block'], ['Warn', 'warn'], ['Info', 'info']] as const) {
      const badge = screen.getByText(label).closest('.mantine-Badge-root') as HTMLElement
      expect(badge.style.backgroundColor).toBe(rgb(SEVERITY_STYLES[severity].background))
    }
  })

  it('labels the role', () => {
    renderUi(<RoleBadge role="controller_admin" />)
    expect(screen.getByText('Controller / admin')).toBeInTheDocument()
  })

  it('never cuts or shrinks a badge, so a table column is always as wide as its longest label', () => {
    renderUi(<StatusBadge kind="bankChange" status="pending_verification" />)
    const label = screen.getByText('Pending verification')
    const badge = label.closest('.mantine-Badge-root') as HTMLElement
    expect(badge.style.flexShrink).toBe('0')
    expect(badge.style.maxWidth).toBe('none')
    expect(label.style.overflow).toBe('visible')
  })

  it('counts open flags as "2 block", "1 warning", "2 warnings", and shows nothing for zero', () => {
    renderUi(
      <>
        <SeverityCountBadge severity="block" count={2} />
        <SeverityCountBadge severity="warn" count={1} />
        <SeverityCountBadge severity="warn" count={2} />
        <SeverityCountBadge severity="info" count={0} />
      </>,
    )
    expect(screen.getByText('2 block')).toBeInTheDocument()
    expect(screen.getByText('1 warning')).toBeInTheDocument()
    expect(screen.getByText('2 warnings')).toBeInTheDocument()
    expect(screen.queryByText(/info/)).not.toBeInTheDocument()
  })

  it('marks an overdue payment in the attention tone', () => {
    renderUi(<OverdueBadge />)
    const badge = screen.getByText('Overdue').closest('.mantine-Badge-root') as HTMLElement
    expect(badge.style.color).toBe(rgb(STATUS_TONES.attention.color))
  })
})

describe('Icon', () => {
  it('uses the one stroke weight and hides decorative icons from screen readers', () => {
    const { container } = renderUi(<Icon icon={IconLogout} />)
    const svg = container.querySelector('svg')!
    expect(svg).toHaveAttribute('stroke-width', String(ICON_STROKE))
    expect(svg).toHaveAttribute('aria-hidden', 'true')
  })

  it('names a standalone icon', () => {
    renderUi(<Icon icon={IconLogout} label="Sign out" />)
    expect(screen.getByRole('img', { name: 'Sign out' })).toBeInTheDocument()
  })
})

describe('theme', () => {
  it('sets page titles (h1) in the serif and section headings (h2 and below) in the sans', () => {
    renderUi(
      <>
        <Title order={1}>Bills</Title>
        <Title order={2}>Approval route</Title>
        <Title order={3}>Lines</Title>
      </>,
    )
    // jsdom drops the quotes around family names, so compare on the family itself.
    expect(screen.getByRole('heading', { level: 1 }).style.fontFamily).toContain('IBM Plex Serif')
    expect(screen.getByRole('heading', { level: 2 }).style.fontFamily).not.toContain('IBM Plex Serif')
    expect(screen.getByRole('heading', { level: 3 }).style.fontFamily).not.toContain('IBM Plex Serif')
    expect(FONT.serif).toContain('IBM Plex Serif')
  })

  it('keeps badge text in sentence case', () => {
    renderUi(<StatusBadge kind="payment" status="settled" />)
    expect(screen.getByText('Settled').style.textTransform).toBe('none')
  })
})
