/** Test data for the intake pages, shaped like the generated API types. */
import type { IntakeItem } from './types'

/** An intake item (a submitted file), done and turned into bill AP-00431, unless overridden. */
export function intakeItem(overrides: Partial<IntakeItem> = {}): IntakeItem {
  return {
    item_id: 101,
    email_id: null,
    file_name: 'Invoice HA26-2766.pdf',
    file_hash: 'a'.repeat(64),
    status: 'ok',
    error: null,
    warnings: [],
    bill_id: 'AP-00431',
    created_at: '2026-11-02T15:00:00Z',
    created_by: 'U013',
    ...overrides,
  }
}

/** A File of `size` bytes (filled with "x"). */
export function fileOf(name: string, size = 1024, type = 'application/pdf'): File {
  return new File(['x'.repeat(size)], name, { type })
}
