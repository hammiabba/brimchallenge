/**
 * Short names for the generated API types (src/api/schema.d.ts, from `npm run gen:api`). Import from here, not from
 * the generated file, so a renamed schema only needs fixing in one place.
 */
import type { components } from './schema'

type Schemas = components['schemas']

export type Me = Schemas['Me']
export type PickerUser = Schemas['PickerUser']
export type ActingFor = Schemas['ActingForOut']
export type Role = Me['role']
export type Department = Schemas['DepartmentOut']
export type ErrorEnvelope = Schemas['ErrorEnvelope']
export type Severity = Schemas['FlagOut']['severity']
export type BillStatus = Schemas['BillSummary']['status']
export type PaymentStatus = Schemas['PaymentSummary']['status']
export type VendorStatus = Schemas['VendorSummary']['status']
export type BankChangeStatus = Schemas['BankChangeOut']['status']
export type UserStatus = Me['status']
