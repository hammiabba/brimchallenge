/**
 * Flag-to-invoice highlighting. A flag's `field` ("taxes", "lines", "vendor.bank", "po_number" ...) names the part
 * of the invoice it is about; hovering a flag, focusing its button or clicking "Show on invoice" highlights that
 * part. The invoice marks its parts with <FieldRegion name=...>.
 */
import { createContext, useContext } from 'react'

/** The parts of the invoice a flag can point at, by flag field name. */
export const INVOICE_REGIONS = [
  'vendor', 'vendor.gst_number', 'vendor.bank', 'invoice_number', 'invoice_date', 'due_date', 'currency',
  'ship_to_province', 'po_number', 'contract_id', 'requester_user_id', 'department_id', 'lines', 'taxes', 'subtotal',
  'total',
] as const

export type InvoiceRegion = (typeof INVOICE_REGIONS)[number]

/** The region a flag field points at: the field itself, or its nearest parent ("vendor.address" -> "vendor"). */
export function regionFor(field: string | null | undefined): InvoiceRegion | null {
  let candidate = field ?? ''
  while (candidate) {
    if ((INVOICE_REGIONS as readonly string[]).includes(candidate)) return candidate as InvoiceRegion
    const dot = candidate.lastIndexOf('.')
    candidate = dot > 0 ? candidate.slice(0, dot) : ''
  }
  return null
}

/** The DOM id of a region, for scrolling to it. */
export function regionDomId(region: InvoiceRegion): string {
  return `invoice-${region.replace('.', '-')}`
}

export interface HighlightState {
  /** The highlighted region: the hovered flag's, else the one last pinned with "Show on invoice". */
  active: InvoiceRegion | null
  /** Highlight while a flag is hovered or focused (null when it leaves). */
  hover: (region: InvoiceRegion | null) => void
  /** Pin a region and scroll it into view. */
  pin: (region: InvoiceRegion) => void
}

export const HighlightContext = createContext<HighlightState>({ active: null, hover: () => {}, pin: () => {} })

/** The highlight state of the bill on screen. */
export function useHighlight(): HighlightState {
  return useContext(HighlightContext)
}
