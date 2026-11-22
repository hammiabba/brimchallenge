/**
 * Bank account numbers, shown one way on every page and for every role: "Ending 9679" (at the start of a field) or
 * "ending 9679" (inside a sentence). The full number is never shown, even when the server sends it to a role that may
 * see it; the institution and transit numbers may sit next to it.
 */

/** The last four digits of an account, from a full number ("953389679"), a masked one ("****9679") or the last four. */
export function lastFour(account: string | null | undefined): string | null {
  const digits = (account ?? '').replace(/\D/g, '')
  return digits.length > 0 ? digits.slice(-4) : null
}

/** "Ending 9679" for a field, or "ending 9679" with `inSentence`; "None on file" / "none on file" without digits. */
export function accountEnding(account: string | null | undefined, inSentence = false): string {
  const last = lastFour(account)
  const text = last ? `Ending ${last}` : 'None on file'
  return inSentence ? text.charAt(0).toLowerCase() + text.slice(1) : text
}
