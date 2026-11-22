/** Test data for the inbox pages, taken from a real run on the seeded database (EM-057, EM-058). */
import type { EmailDetail, EmailSummary, InboxJob } from '../common/types'

export function emailSummary(overrides: Partial<EmailSummary> = {}): EmailSummary {
  return {
    email_id: 'EM-001',
    from_name: 'Summit Packaging Supply Accounts Receivable',
    from_address: 'ar@summitpackaging.example',
    subject: 'Invoice 000804 attached',
    received_at: '2026-10-01T13:00:00Z',
    attachments: ['summitpackaging-inv-001.pdf'],
    email_class: 'invoice',
    triage_reason: 'Invoice attached from a known vendor',
    triaged_at: '2026-11-02T15:00:00Z',
    items: [],
    suggested_action: {
      kind: 'create_drafts', message: 'Review the draft bill made from the attachment.', language: 'en',
      reply_text: null, vendor_id: 'V011', invoice_status: null,
    },
    ...overrides,
  }
}

export function jobOf(overrides: Partial<InboxJob> = {}): InboxJob {
  return {
    job_id: 'b14d2229de36', status: 'running', started_by: 'U004', started_at: '2026-11-02T15:00:00Z',
    finished_at: null, total_emails: 59, processed_emails: 0, items: [], error: null,
    ...overrides,
  }
}

const EM057_REPLY = 'Hello,\n\nInvoice 1743 dated 2026-02-04 was paid on 2026-03-09 by EFT (369.75 CAD), reference ' +
  'BRIM-EFT-26388945.\n\nBest regards,\nAccounts Payable, Harborline Logistics'

export const EM_057: EmailDetail = {
  email_id: 'EM-057',
  from_name: 'Torque Industrial Maintenance',
  from_address: 'ar@torqueindustrial.example',
  to_address: 'ap@harborline-logistics.example',
  subject: 'Where is payment for invoice 1743?',
  received_at: '2026-10-30T14:36:00Z',
  body: 'Hi, we have not received payment for invoice 1743. Can you confirm?',
  attachments: [],
  email_class: 'payment_inquiry',
  triage_reason: 'Vendor asks about the status of a payment; no invoice attached',
  triaged_at: '2026-11-02T15:00:42Z',
  suggested_action: {
    kind: 'answer_status',
    message: 'Payment question from Torque Industrial Maintenance (V044). As of 2026-11-02: Invoice 1743 (AP-00049, ' +
      '369.75 CAD, dated 2026-02-04) was paid on 2026-03-09 by EFT, reference BRIM-EFT-26388945.',
    language: 'en',
    reply_text: EM057_REPLY,
    vendor_id: 'V044',
    invoice_status: {
      vendor_id: 'V044', vendor_name: 'Torque Industrial Maintenance', invoice_number: '1743', invoice_id: 'AP-00049',
      invoice_date: '2026-02-04', due_date: '2026-03-06', total: '369.75', currency: 'CAD', status: 'paid',
      payments: [{
        payment_id: 'PAY-00047', method: 'EFT', status: 'settled', scheduled_date: '2026-03-06', paid_date: '2026-03-09',
        amount: '369.75', currency: 'CAD', reference: 'BRIM-EFT-26388945',
      }],
      summary: 'Invoice 1743 (AP-00049, 369.75 CAD, dated 2026-02-04) was paid on 2026-03-09 by EFT, reference BRIM-EFT-26388945.',
    },
  },
  bill_ids: [],
  items: [],
}

export const EM058_REPLY = 'Hello,\n\nWe received your email "Invoice attached", but no invoice was attached. Could you ' +
  'please resend it as a PDF?\n\nBest regards,\nAccounts Payable, Harborline Logistics'

export const EM_058: EmailDetail = {
  ...EM_057,
  email_id: 'EM-058',
  from_name: 'Brightmore Consulting Group',
  from_address: 'ar@brightmoreconsulting.example',
  subject: 'Invoice attached',
  body: 'Please find our invoice attached.',
  email_class: 'missing_attachment',
  triage_reason: 'Says an invoice is attached but there is no attachment',
  suggested_action: {
    kind: 'request_resend',
    message: 'Email from Brightmore Consulting Group (V030) mentions an invoice but has no attachment. Send the reply ' +
      'asking for the file.',
    language: 'en',
    reply_text: EM058_REPLY,
    vendor_id: 'V030',
    invoice_status: null,
  },
}
