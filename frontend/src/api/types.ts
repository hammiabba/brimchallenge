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

// Vendors and bank changes
export type VendorsPage = Schemas['Page_VendorSummary_']
export type VendorInput = Schemas['VendorIn']
export type PaymentMethod = VendorSummary['preferred_payment_method']
export type BankAccount = Schemas['BankAccountOut']
export type BankChange = Schemas['BankChangeOut']
export type BankChangeInput = Schemas['BankChangeIn']
export type BankChangeChannel = BankChange['request_channel']

// Audit log
export type AuditPage = Schemas['AuditPage']

// Admin
export type AdminUser = Schemas['UserOut']
export type UserPatch = Schemas['UserPatch']
export type Policy = Schemas['PolicyOut']
export type PolicyPatch = Schemas['PolicyPatch']
export type Absence = Schemas['AbsenceOut']
export type AbsenceInput = Schemas['AbsenceIn']
export type DelegationInput = Schemas['DelegationIn']

// Spend
export type SpendReport = Schemas['SpendReport']
export type SpendRow = Schemas['SpendRow']
export type SpendGroupBy = SpendReport['group_by']

// Intake
export type IntakeItem = Schemas['IntakeItemOut']
export type IntakeItemStatus = IntakeItem['status']
export type IntakeItemsPage = Schemas['Page_IntakeItemOut_']
export type InboxJob = Schemas['JobOut']
export type InboxEmail = Schemas['EmailOut']
export type EmailsPage = Schemas['Page_EmailOut_']
