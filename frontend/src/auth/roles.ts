import type { Role } from '../api/types'

/** The six roles in the order they are listed (sign-in picker groups, docs). Matches backend/app/auth/roles.py. */
export const ROLES = [
  'employee',
  'ap_clerk',
  'approver',
  'finance_manager',
  'controller_admin',
  'auditor',
] as const satisfies readonly Role[]

/** How a role is shown in the UI. */
export const ROLE_LABELS: Record<Role, string> = {
  employee: 'Employee',
  ap_clerk: 'AP clerk',
  approver: 'Approver',
  finance_manager: 'Finance manager',
  controller_admin: 'Controller / admin',
  auditor: 'Auditor',
}
