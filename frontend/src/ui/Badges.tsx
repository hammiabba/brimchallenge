import { Badge } from '@mantine/core'

import type {
  BankChangeStatus,
  BillStatus,
  FlagResolution,
  PaymentStatus,
  Role,
  Severity,
  UserStatus,
  VendorStatus,
} from '../api/types'
import { ROLE_LABELS } from '../auth/roles'
import { ROLE_TONE, SEVERITY_STYLES, STATUS_TONES, type BadgeTone } from '../theme'
import { SEVERITY_LABELS, STATUS_STYLES } from './statusStyles'

/**
 * Mantine's badge cuts its label with an ellipsis and may shrink to fit (`max-width: 100%`, label `overflow: hidden`).
 * In an auto-layout table cell that lets the browser squeeze a status down to "Sc…". A badge here never shrinks and
 * never cuts its label, so its column is always at least as wide as its longest label.
 */
const NO_TRUNCATION = {
  root: { flexShrink: 0, maxWidth: 'none', overflow: 'visible' },
  label: { overflow: 'visible', textOverflow: 'clip' },
} as const

/** A badge in one of the theme's tones. Colours are set inline so they are exactly the pairs the contrast test checks. */
function ToneBadge({ tone, children }: { tone: BadgeTone; children: string }) {
  return (
    <Badge
      styles={NO_TRUNCATION}
      style={{ color: tone.color, backgroundColor: tone.background, border: `1px solid ${tone.border}` }}
    >
      {children}
    </Badge>
  )
}

type StatusBadgeProps =
  | { kind: 'bill'; status: BillStatus }
  | { kind: 'payment'; status: PaymentStatus }
  | { kind: 'vendor'; status: VendorStatus }
  | { kind: 'bankChange'; status: BankChangeStatus }
  | { kind: 'user'; status: UserStatus }
  | { kind: 'flag'; status: FlagResolution }

/** The status of a bill, payment, vendor, bank change, user or flag resolution, with its label and tone from src/ui/statusStyles.ts. */
export function StatusBadge(props: StatusBadgeProps) {
  const table = STATUS_STYLES[props.kind] as Record<string, { label: string; tone: keyof typeof STATUS_TONES }>
  const style = table[props.status]
  if (!style) return null
  return <ToneBadge tone={STATUS_TONES[style.tone]}>{style.label}</ToneBadge>
}

/** A flag's severity: solid red for block, solid amber for warn, a slate tint for info. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return <ToneBadge tone={SEVERITY_STYLES[severity]}>{SEVERITY_LABELS[severity]}</ToneBadge>
}

/**
 * The count in full words: "1 blocking" / "2 blocking", "1 warning" / "2 warnings", "1 info" / "2 info" (only
 * "warning" takes a plural; "blocking" and "info" read the same for any count).
 */
function severityCountLabel(severity: Severity, count: number): string {
  if (severity === 'block') return `${count} blocking`
  if (severity === 'warn') return `${count} warning${count === 1 ? '' : 's'}`
  return `${count} info`
}

/** A count of open flags of one severity ("2 blocking", "1 warning"), in that severity's colours; nothing for zero. */
export function SeverityCountBadge({ severity, count }: { severity: Severity; count: number }) {
  if (count <= 0) return null
  return <ToneBadge tone={SEVERITY_STYLES[severity]}>{severityCountLabel(severity, count)}</ToneBadge>
}

/** "Overdue", in the attention tone: a scheduled payment dated before the business date. */
export function OverdueBadge() {
  return <ToneBadge tone={STATUS_TONES.attention}>Overdue</ToneBadge>
}

/**
 * "Possible duplicate of V002", in the attention tone: a vendor record the VENDOR_LOOKALIKE control treats as a
 * suspicious copy of an existing vendor (VendorSummary.lookalike_of).
 */
export function LookalikeBadge({ vendorId }: { vendorId: string }) {
  return <ToneBadge tone={STATUS_TONES.attention}>{`Possible duplicate of ${vendorId}`}</ToneBadge>
}

/** The signed-in user's role, as in the header. */
export function RoleBadge({ role }: { role: Role }) {
  return <ToneBadge tone={ROLE_TONE}>{ROLE_LABELS[role]}</ToneBadge>
}
