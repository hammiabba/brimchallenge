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

/** A badge in one of the theme's tones. Colours are set inline so they are exactly the pairs the contrast test checks. */
function ToneBadge({ tone, children }: { tone: BadgeTone; children: string }) {
  return (
    <Badge
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

/** A count of open flags of one severity ("2 block"), in that severity's colours; nothing for zero. */
export function SeverityCountBadge({ severity, count }: { severity: Severity; count: number }) {
  if (count <= 0) return null
  return <ToneBadge tone={SEVERITY_STYLES[severity]}>{`${count} ${severity}`}</ToneBadge>
}

/** The signed-in user's role, as in the header. */
export function RoleBadge({ role }: { role: Role }) {
  return <ToneBadge tone={ROLE_TONE}>{ROLE_LABELS[role]}</ToneBadge>
}
