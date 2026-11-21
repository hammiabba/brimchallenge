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

// Bills (chunk 2)
export type BillSummary = Schemas['BillSummary']
export type BillsPage = Schemas['Page_BillSummary_']
export type BillDetail = Schemas['BillDetail']
export type BillLine = Schemas['BillLineOut']
export type BillTax = Schemas['BillTaxOut']
export type BillFlag = Schemas['FlagOut']
export type FlagResolution = BillFlag['resolution']
export type ControlsRun = Schemas['ControlsRunOut']
export type RouteStep = Schemas['RouteStepOut']
export type CurrentStep = Schemas['CurrentStepOut']
export type Decision = Schemas['DecisionOut']
export type DuplicateMatch = Schemas['DuplicateOut']
export type Payment = Schemas['PaymentSummary']
export type AuditEvent = Schemas['AuditEventOut']
export type DepartmentSource = NonNullable<BillDetail['department_source']>

// Reference data
export type FlagHelp = Schemas['FlagHelpOut']
export type GlAccount = Schemas['GlAccountOut']
export type VendorSummary = Schemas['VendorSummary']
export type VendorDetail = Schemas['VendorDetail']
