/**
 * Turns a flag's evidence dict (FlagOut.evidence, written by app/controls) into blocks the flag section renders:
 *   pairs       expected vs found, side by side (tax codes and amounts, invoice vs master, computed vs total ...)
 *   matches     duplicate matches: bills (links) or card transactions, with kind, score and reasons
 *   related     the other bills of a possible split, with their combined CAD total
 *   bankChange  old last 4 -> new last 4, with the date, channel and whether it was verified
 *   facts       every other key, as a small key-value list
 * Every key is used once. Values keep their server text; only known money keys are formatted as money, and only
 * when they parse as money. Pure functions, no React.
 */
import type { DuplicateMatch } from '../api/types'
import { parseDateOnly } from '../lib/dates'
import { isMoney, parseMoneyInput, type Money } from '../lib/money'

/** One displayable value. */
export type EvidenceValue =
  | { kind: 'money'; value: Money; currency: string }
  | { kind: 'date'; value: string }
  | { kind: 'id'; value: string }
  | { kind: 'text'; value: string }
  | { kind: 'list'; items: EvidenceValue[] }
  | { kind: 'empty' }

export interface PairRow {
  label: string
  expected: EvidenceValue
  found: EvidenceValue
}

export interface MatchRow {
  id: string
  /** True for a bill id (rendered as a link to that bill); false for a card transaction or anything else. */
  isBill: boolean
  kind: string | null
  /** 0..1 similarity, when known. */
  score: number | null
  reasons: string[]
}

export type EvidenceBlock =
  | { type: 'pairs'; expectedLabel: string; foundLabel: string; rows: PairRow[] }
  | { type: 'matches'; rows: MatchRow[] }
  | { type: 'related'; bills: string[]; combinedCad: EvidenceValue | null }
  | { type: 'bankChange'; oldLast4: string; newLast4: string; changedOn: EvidenceValue; channel: string | null;
    verified: boolean | null }
  | { type: 'facts'; rows: Array<{ key: string; label: string; value: EvidenceValue }> }

export interface EvidenceContext {
  /** The bill's currency, for amounts that aren't explicitly CAD. */
  currency: string
  /** The controls run's duplicate matches, for each match's own kind, score and reasons. */
  duplicates?: readonly DuplicateMatch[]
}

/**
 * Keys whose value is an amount. "*_cad" keys are in CAD; the rest are in the bill's currency. "rate" and "cap" are
 * left out on purpose: the same key holds an FX rate on some flags and a unit price on others.
 */
const MONEY_KEYS = new Set([
  'combined_cad', 'total_cad', 'po_remaining', 'overage', 'fee', 'one_off', 'month_total', 'nte', 'computed', 'total',
  'lines_sum', 'subtotal', 'expected_gst_hst', 'charged_gst_hst', 'expected_pst_qst', 'charged_pst_qst',
])

/** Expected-vs-found key pairs, grouped by their column labels (rows of one group share a table). */
const PAIR_GROUPS: Array<{ expectedLabel: string; foundLabel: string; pairs: Array<[string, string, string]> }> = [
  { expectedLabel: 'Expected', foundLabel: 'Found', pairs: [['expected', 'found', 'Value']] },
  {
    expectedLabel: 'Expected',
    foundLabel: 'Charged',
    pairs: [
      ['expected_codes', 'charged_codes', 'Tax codes'],
      ['expected_gst_hst', 'charged_gst_hst', 'GST/HST'],
      ['expected_pst_qst', 'charged_pst_qst', 'PST/QST'],
    ],
  },
  { expectedLabel: 'On file', foundLabel: 'On the invoice', pairs: [['master', 'invoice', 'Value']] },
  { expectedLabel: 'Computed', foundLabel: 'On the invoice', pairs: [['computed', 'total', 'Total']] },
  { expectedLabel: 'Sum of lines', foundLabel: 'On the invoice', pairs: [['lines_sum', 'subtotal', 'Subtotal']] },
  { expectedLabel: 'Actual', foundLabel: 'Stated', pairs: [['actual_pct', 'stated_pct', 'Percentage']] },
  { expectedLabel: 'Contract cap', foundLabel: 'Charged', pairs: [['cap', 'rate', 'Rate']] },
  { expectedLabel: 'Not to exceed', foundLabel: 'Month total', pairs: [['nte', 'month_total', 'Amount']] },
  { expectedLabel: 'Usual domain', foundLabel: 'Sent from', pairs: [['known_domain', 'sender_domain', 'Domain']] },
]

/** Short codes and ids shown in mono: AP-00394, CT-00017, V002, C025, PO-2026-0044, P13, U010, BC-009. */
const ID_PATTERN = /^(AP|CT|PAY|PO|BC|EM)-[\w-]+$|^(V|C|P|U|D)\d{2,}$/

const ACRONYMS: Record<string, string> = {
  po: 'PO', gst: 'GST', hst: 'HST', pst: 'PST', qst: 'QST', cad: 'CAD', usd: 'USD', id: 'ID', nte: 'NTE', fx: 'FX',
  gl: 'GL', pct: 'percent',
}

/** A code value the controls write (lower case with underscores), such as an evidence "kind" or a status. */
const CODE_VALUE = /^[a-z]+(_[a-z]+)+$/

/** Code values that read better than their words with spaces; anything else becomes "Words like this". */
const CODE_WORDS: Record<string, string> = {
  one_off: 'One-off charge',
  no_tax: 'No tax charged',
  tax_charged: 'Tax charged',
  account_before_change: 'Account dated after the invoice',
  due_before_invoice: 'Due before the invoice date',
  email_request: 'Email request',
  vendor_portal: 'Vendor portal',
  phone_callback_verified: 'Phone, confirmed by callback',
}

/** "one_off" -> "One-off charge", "pending_review" -> "Pending review". */
function codeValueWords(code: string): string {
  const known = CODE_WORDS[code]
  if (known) return known
  const words = code.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** "po_remaining" -> "PO remaining", "this_status" -> "This status". */
export function keyLabel(key: string): string {
  const words = key.split('_').map((w) => ACRONYMS[w] ?? w)
  const text = words.join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The currency an amount under `key` is in. */
function currencyFor(key: string, context: EvidenceContext): string {
  return key.endsWith('_cad') ? 'CAD' : context.currency
}

/** One evidence value for display, by its key and JSON type. Never converts money to a number. */
export function evidenceValue(key: string, raw: unknown, context: EvidenceContext): EvidenceValue {
  if (raw === null || raw === undefined || raw === '') return { kind: 'empty' }
  if (Array.isArray(raw)) return { kind: 'list', items: raw.map((item) => evidenceValue(key, item, context)) }
  if (typeof raw === 'boolean') return { kind: 'text', value: raw ? 'Yes' : 'No' }
  if (typeof raw === 'number') return { kind: 'text', value: String(raw) }
  if (typeof raw === 'object') {
    // Nested objects (e.g. bank fields) are shown as "key: value" text.
    const parts = Object.entries(raw as Record<string, unknown>)
      .map(([k, v]) => `${keyLabel(k)}: ${v === null || v === undefined ? 'none' : String(v)}`)
    return { kind: 'text', value: parts.join(', ') }
  }
  const text = String(raw)
  if (MONEY_KEYS.has(key)) {
    const money = isMoney(text) ? text : parseMoneyInput(text)
    if (money !== null) return { kind: 'money', value: money as Money, currency: currencyFor(key, context) }
  }
  if (parseDateOnly(text)) return { kind: 'date', value: text }
  if (ID_PATTERN.test(text)) return { kind: 'id', value: text }
  // A code ("one_off", "email_request") reads as words; free text is kept as the server wrote it.
  if (CODE_VALUE.test(text)) return { kind: 'text', value: codeValueWords(text) }
  return { kind: 'text', value: text }
}

/** True when the value under `key` holds anything. */
function present(evidence: Record<string, unknown>, key: string): boolean {
  return key in evidence && evidence[key] !== null && evidence[key] !== undefined
}

/** Expected-vs-found blocks; marks the keys it used. */
function pairBlocks(evidence: Record<string, unknown>, used: Set<string>, context: EvidenceContext): EvidenceBlock[] {
  const blocks: EvidenceBlock[] = []
  for (const group of PAIR_GROUPS) {
    const rows: PairRow[] = []
    for (const [expectedKey, foundKey, label] of group.pairs) {
      if (!present(evidence, expectedKey) || !present(evidence, foundKey)) continue
      const expected = evidence[expectedKey]
      const found = evidence[foundKey]
      used.add(expectedKey).add(foundKey)
      // Two objects (bank fields on file vs on the invoice): one row per field.
      if (expected && found && typeof expected === 'object' && typeof found === 'object'
        && !Array.isArray(expected) && !Array.isArray(found)) {
        const keys = [...new Set([...Object.keys(expected), ...Object.keys(found)])]
        for (const k of keys) {
          rows.push({
            label: keyLabel(k),
            expected: evidenceValue(k, (expected as Record<string, unknown>)[k], context),
            found: evidenceValue(k, (found as Record<string, unknown>)[k], context),
          })
        }
      } else {
        rows.push({
          label,
          expected: evidenceValue(expectedKey, expected, context),
          found: evidenceValue(foundKey, found, context),
        })
      }
    }
    if (rows.length > 0) blocks.push({ type: 'pairs', expectedLabel: group.expectedLabel, foundLabel: group.foundLabel, rows })
  }
  return blocks
}

/** Duplicate matches ("matches", "kinds", "best_score"), enriched with the run's per-match kind, score, reasons. */
function matchBlock(evidence: Record<string, unknown>, used: Set<string>, context: EvidenceContext): EvidenceBlock | null {
  const matches = evidence.matches
  if (!Array.isArray(matches)) return null
  used.add('matches')
  const kinds = Array.isArray(evidence.kinds) ? evidence.kinds : []
  if ('kinds' in evidence) used.add('kinds')
  const best = typeof evidence.best_score === 'number' ? evidence.best_score : null
  if ('best_score' in evidence) used.add('best_score')
  const rows = matches.map((raw, index): MatchRow => {
    const id = String(raw)
    const detail = context.duplicates?.find((d) => d.matched_invoice_id === id || d.matched_card_txn_id === id)
    const kind = detail?.kind ?? (typeof kinds[index] === 'string' ? (kinds[index] as string) : null)
    return {
      id,
      isBill: /^AP-\d+$/.test(id),
      kind,
      score: detail?.score ?? (matches.length === 1 ? best : null),
      reasons: detail?.reasons ?? [],
    }
  })
  return { type: 'matches', rows }
}

/** A possible split: the related bills and their combined CAD total. */
function relatedBlock(evidence: Record<string, unknown>, used: Set<string>, context: EvidenceContext): EvidenceBlock | null {
  if (!Array.isArray(evidence.related)) return null
  used.add('related')
  let combinedCad: EvidenceValue | null = null
  if (present(evidence, 'combined_cad')) {
    used.add('combined_cad')
    combinedCad = evidenceValue('combined_cad', evidence.combined_cad, context)
  }
  return { type: 'related', bills: evidence.related.map(String), combinedCad }
}

/** A bank change (a bank_change_history row): old and new last 4, date, channel, verified. */
function bankChangeBlock(evidence: Record<string, unknown>, used: Set<string>, context: EvidenceContext): EvidenceBlock | null {
  if (!present(evidence, 'old_account_last4') || !present(evidence, 'new_account_last4')) return null
  used.add('old_account_last4').add('new_account_last4')
  const take = (key: string): unknown => {
    if (!(key in evidence)) return undefined
    used.add(key)
    return evidence[key]
  }
  const changedAt = take('changed_at')
  const channel = take('request_channel')
  const verified = take('verified_by_callback')
  return {
    type: 'bankChange',
    oldLast4: String(evidence.old_account_last4),
    newLast4: String(evidence.new_account_last4),
    changedOn: evidenceValue('changed_at', changedAt, context),
    channel: typeof channel === 'string' && channel ? channel : null,
    verified: verified === undefined || verified === null || verified === ''
      ? null
      : verified === true || String(verified).toLowerCase() === 'yes',
  }
}

/** The blocks for one flag's evidence, in display order; empty evidence gives no blocks. */
export function classifyEvidence(evidence: Record<string, unknown> | null | undefined,
  context: EvidenceContext): EvidenceBlock[] {
  if (!evidence) return []
  const used = new Set<string>()
  const blocks: EvidenceBlock[] = []
  for (const block of [
    matchBlock(evidence, used, context),
    relatedBlock(evidence, used, context),
    bankChangeBlock(evidence, used, context),
  ]) {
    if (block) blocks.push(block)
  }
  blocks.push(...pairBlocks(evidence, used, context))
  const rest = Object.keys(evidence).filter((key) => !used.has(key))
  if (rest.length > 0) {
    blocks.push({
      type: 'facts',
      rows: rest.map((key) => ({ key, label: keyLabel(key), value: evidenceValue(key, evidence[key], context) })),
    })
  }
  return blocks
}
