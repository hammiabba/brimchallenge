import { describe, expect, it } from 'vitest'

import { BRAND, CONTRAST_PAIRS, SURFACE, TEXT } from '../theme'
import { contrastRatio } from './contrast'

describe('contrastRatio', () => {
  it('matches the WCAG reference values', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5)
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5)
    expect(contrastRatio('#767676', '#FFFFFF')).toBeCloseTo(4.54, 2)
  })
})

describe('theme colour pairs', () => {
  it.each(CONTRAST_PAIRS)('$name meets its minimum', ({ fg, bg, min }) => {
    expect(contrastRatio(fg, bg)).toBeGreaterThanOrEqual(min)
  })

  it('keeps Robin\'s Egg decorative: it is too light for text on white', () => {
    expect(contrastRatio(BRAND.robinsEgg, SURFACE.white)).toBeLessThan(3)
    for (const pair of CONTRAST_PAIRS) {
      expect(pair.fg, pair.name).not.toBe(BRAND.robinsEgg)
      expect(pair.bg, pair.name).not.toBe(BRAND.robinsEgg)
    }
  })

  it('pairs Sand only with ink text', () => {
    const onSand = CONTRAST_PAIRS.filter((pair) => pair.bg === BRAND.sand)
    expect(onSand.map((pair) => pair.fg)).toEqual([TEXT.ink])
  })
})
