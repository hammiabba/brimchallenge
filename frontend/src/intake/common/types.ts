/**
 * Short names for the generated intake types (src/api/schema.d.ts, from `npm run gen:api`). Kept here rather than in
 * src/api/types.ts, which is shared; they can move there once the intake pages settle.
 */
import type { components } from '../../api/schema'

type Schemas = components['schemas']

export type IntakeItem = Schemas['IntakeItemOut']
export type IntakeItemStatus = IntakeItem['status']
export type InboxJob = Schemas['JobOut']
export type EmailSummary = Schemas['EmailOut']
export type EmailDetail = Schemas['EmailDetail']
export type EmailItem = Schemas['EmailItem']
export type SuggestedAction = Schemas['SuggestedAction']
export type ActionKind = Schemas['ActionKind']
export type InvoiceStatus = Schemas['InvoiceStatus']
export type PaymentRecord = Schemas['PaymentRecord']
