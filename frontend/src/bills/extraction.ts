/**
 * Reading the frozen extraction snapshot (BillDetail.extracted: the DraftBill as intake read it, with bank numbers
 * already masked by the server for the caller's role) and comparing it with the bill's current values.
 */
import { parseMoneyInput } from '../lib/money'

export type Snapshot = Record<string, unknown>

/** Confidence below this gets the amber underline and a tooltip. */
export const LOW_CONFIDENCE = 0.8

/** The value at a dotted path ("vendor.bank.account") in the snapshot, or undefined if absent. */
export function snapshotValue(snapshot: Snapshot | null | undefined, path: string): unknown {
  let value: unknown = snapshot
  for (const part of path.split('.')) {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
    value = (value as Record<string, unknown>)[part]
  }
  return value
}

/** The snapshot value as display text, or null when it is missing or empty. */
export function snapshotText(snapshot: Snapshot | null | undefined, path: string): string | null {
  const value = snapshotValue(snapshot, path)
  if (value === null || value === undefined || value === '') return null
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** The extraction confidence (0..1) for a field, or null when none was recorded. */
export function confidenceFor(snapshot: Snapshot | null | undefined, field: string): number | null {
  const value = snapshotValue(snapshot, `field_confidence.${field}`)
  return typeof value === 'number' ? value : null
}

/** "62%" for 0.62: a confidence, not money, so plain rounding is fine. */
export function confidencePercent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

/**
 * Whether the extracted value differs from the current one. Money compares as normalised strings ("6452.3" equals
 * "6452.30"), never as numbers; everything else compares as trimmed text; missing and empty are the same.
 */
export function differs(extracted: string | null, current: string | null, kind: 'money' | 'text' = 'text'): boolean {
  const norm = (value: string | null): string => {
    const text = (value ?? '').trim()
    if (kind === 'money' && text) return parseMoneyInput(text) ?? text
    return text
  }
  return norm(extracted) !== norm(current)
}

/** The extraction warnings, as strings. */
export function extractionWarnings(snapshot: Snapshot | null | undefined): string[] {
  const value = snapshotValue(snapshot, 'extraction_warnings')
  return Array.isArray(value) ? value.map(String) : []
}
