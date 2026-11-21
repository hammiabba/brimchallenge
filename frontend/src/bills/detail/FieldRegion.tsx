import { Box } from '@mantine/core'
import type { ReactNode } from 'react'

import { regionDomId, useHighlight, type InvoiceRegion } from './highlight'

/**
 * A part of the invoice that a flag can point at. It is highlighted (primary tint with a Blumine outline, see
 * global.css) while a flag about it is hovered, focused or pinned.
 */
export function FieldRegion({ name, children }: { name: InvoiceRegion; children: ReactNode }) {
  const { active } = useHighlight()
  return (
    <Box id={regionDomId(name)} className="app-flag-target" data-region={name} data-highlighted={active === name || undefined}>
      {children}
    </Box>
  )
}
