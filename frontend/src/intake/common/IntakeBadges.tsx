import { Badge } from '@mantine/core'

import { codeAsWords } from '../../api/reference'
import { STATUS_TONES, type BadgeTone } from '../../theme'
import { EMAIL_CLASS, INTAKE_STATUS } from './labels'
import type { IntakeItemStatus } from './types'

/** A badge in one of the theme's status tones, coloured exactly as the shared StatusBadge does. */
function ToneBadge({ tone, children }: { tone: BadgeTone; children: string }) {
  return (
    <Badge style={{ color: tone.color, backgroundColor: tone.background, border: `1px solid ${tone.border}` }}>
      {children}
    </Badge>
  )
}

/** An intake item's status: queued, processing, done, not read or failed. */
export function IntakeStatusBadge({ status }: { status: IntakeItemStatus }) {
  const style = INTAKE_STATUS[status]
  return <ToneBadge tone={STATUS_TONES[style.tone]}>{style.label}</ToneBadge>
}

/** An email's class; "Not triaged" until an inbox run has sorted it. */
export function EmailClassBadge({ emailClass }: { emailClass: string | null | undefined }) {
  if (!emailClass) return <ToneBadge tone={STATUS_TONES.neutral}>Not triaged</ToneBadge>
  const style = EMAIL_CLASS[emailClass] ?? { label: codeAsWords(emailClass), tone: 'neutral' as const }
  return <ToneBadge tone={STATUS_TONES[style.tone]}>{style.label}</ToneBadge>
}
