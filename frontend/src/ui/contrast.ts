/**
 * WCAG 2.x contrast ratio between two "#RRGGBB" colours, from 1 (same colour) to 21 (black on white).
 * Used by the contrast test to check every colour pair in src/theme.ts.
 */

/** Relative luminance of a "#RRGGBB" colour (WCAG 2.x definition). */
export function relativeLuminance(hex: string): number {
  const match = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!match) throw new TypeError(`Not a #RRGGBB colour: ${hex}`)
  const value = Number.parseInt(match[1] ?? '', 16)
  const channels = [(value >> 16) & 255, (value >> 8) & 255, value & 255].map((c) => {
    const s = c / 255
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  })
  const [r = 0, g = 0, b = 0] = channels
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** The contrast ratio of two colours (order doesn't matter). */
export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x)
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05)
}
