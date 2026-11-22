import { describe, expect, it } from 'vitest'

import { accountEnding, lastFour } from './accounts'

describe('account numbers', () => {
  it('keeps only the last four digits, whatever form the number comes in', () => {
    expect(lastFour('953389679')).toBe('9679')
    expect(lastFour('****9679')).toBe('9679')
    expect(lastFour('9679')).toBe('9679')
    expect(lastFour(null)).toBeNull()
    expect(lastFour('')).toBeNull()
  })

  it('reads "Ending 9679" in a field and "ending 9679" in a sentence', () => {
    expect(accountEnding('953389679')).toBe('Ending 9679')
    expect(accountEnding('****9679', true)).toBe('ending 9679')
    expect(accountEnding(undefined)).toBe('None on file')
  })
})
