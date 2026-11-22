import { Badge } from '@mantine/core'

import type { IntakeItemStatus } from '../api/types'
import { STATUS_TONES } from '../theme'
import { INTAKE_STATUS } from './status'

/**
 * An intake item's status, drawn like StatusBadge (same tones and border). Kept here because StatusBadge has no
 * intake kind yet; it can move into src/ui/Badges.tsx if the shared badge gains one.
 */
export function IntakeStatusBadge({ status }: { status: IntakeItemStatus }) {
  const style = INTAKE_STATUS[status]
  const tone = STATUS_TONES[style.tone]
  return (
    <Badge style={{ color: tone.color, backgroundColor: tone.background, border: `1px solid ${tone.border}` }}>
      {style.label}
    </Badge>
  )
}
