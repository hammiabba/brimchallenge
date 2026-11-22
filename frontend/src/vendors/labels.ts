/** Words for the vendor and bank-change enums. */
import type { BankChangeChannel, PaymentMethod } from '../api/types'

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  EFT: 'EFT',
  CHEQUE: 'Cheque',
  CARD: 'Card',
}

export const CHANNEL_LABELS: Record<BankChangeChannel, string> = {
  phone_callback_verified: 'Phone, confirmed by callback',
  vendor_portal: 'Vendor portal',
  email_request: 'Email request',
}

/** "Net 30", or "Due on receipt" for zero days. */
export function termsLabel(days: number): string {
  return days === 0 ? 'Due on receipt' : `Net ${days}`
}
