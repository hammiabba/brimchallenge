/**
 * Guards for the rules in frontend/DESIGN.md that a text search can check, run over every source file in src/
 * (this file and the generated API schema excepted). A later chunk that breaks one fails here with the file name.
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['./**/*.{ts,tsx,css}', '!./design.test.ts', '!./api/schema.d.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

// Built from parts so this file doesn't match its own rules.
const RULES: Array<{ rule: string; pattern: RegExp }> = [
  { rule: 'flat colour fills only', pattern: new RegExp(['grad', 'ient'].join(''), 'i') },
  { rule: 'no blur or glass effects', pattern: new RegExp(['backdrop-fil', 'ter|bl', 'ur\\('].join(''), 'i') },
  { rule: 'no CSS shadows (the one floating shadow lives in theme.shadows)', pattern: new RegExp(['box-sha', 'dow'].join(''), 'i') },
  { rule: 'colours stay inside the palette', pattern: new RegExp(['\\b(vio', 'let|gra', 'pe|ind', 'igo|pur', 'ple)\\b'].join(''), 'i') },
  { rule: 'Tabler is the only icon set', pattern: new RegExp(['luc', 'ide|hero', 'icons|react-ic', 'ons'].join(''), 'i') },
  { rule: 'IBM Plex is the only typeface', pattern: new RegExp(['\\bIn', 'ter\\b'].join('')) },
  { rule: 'no emojis', pattern: /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u },
  {
    rule: 'no buzzwords',
    pattern: new RegExp(['\\b(seam', 'less|next-', 'gen|reima', 'gine|effort', 'less|power', 'ful|ai-pow', 'ered)\\b'].join(''), 'i'),
  },
  // Server text (vendor names, messages, comments) is rendered as plain text, never as HTML.
  { rule: 'no raw HTML injection', pattern: new RegExp(['dangerously', 'SetInnerHTML|inner', 'HTML\\s*='].join('')) },
  { rule: 'no uppercase text transforms', pattern: new RegExp(['text-transform:\\s*upper', 'case|tt="upper', 'case"'].join(''), 'i') },
]

describe('design rules', () => {
  it('scans the sources', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(20)
  })

  it.each(RULES)('$rule', ({ pattern }) => {
    const offenders = Object.entries(SOURCES)
      .filter(([, text]) => pattern.test(text))
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })

  it('draws Tabler icons only through <Icon> (one stroke weight)', () => {
    const offenders = Object.entries(SOURCES)
      .filter(([path]) => !path.endsWith('.test.tsx') && path !== './ui/Icon.tsx')
      .filter(([, text]) => /<Icon[A-Z]\w*[\s/>]/.test(text))
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })
})
