import type { TablerIcon } from '@tabler/icons-react'

/** The one stroke weight for every icon. */
export const ICON_STROKE = 1.75

interface IconProps {
  /** A Tabler icon component, e.g. IconLogout from '@tabler/icons-react'. */
  icon: TablerIcon
  size?: number
  /**
   * Leave unset for an icon next to a visible label (it is hidden from screen readers). Set it only when the icon
   * stands alone; an icon-only button gets its aria-label on the button instead.
   */
  label?: string
}

/** A Tabler icon at the app's stroke weight. Always use this rather than rendering Tabler icons directly. */
export function Icon({ icon: Glyph, size = 16, label }: IconProps) {
  if (label) {
    return <Glyph size={size} stroke={ICON_STROKE} role="img" aria-label={label} />
  }
  return <Glyph size={size} stroke={ICON_STROKE} aria-hidden focusable={false} />
}
