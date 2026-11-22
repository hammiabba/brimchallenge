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

/** The lower-case words of a label or title ("Controller / admin" -> ["controller", "admin"]). */
function words(text: string): string[] {
  return text.toLowerCase().split(/[^a-z]+/).filter(Boolean)
}

/**
 * True when a job title already says the role, so the header shows the role once (the badge) and leaves the title
 * out: "Finance Manager" for finance_manager, "AP Clerk" for ap_clerk, "Internal Auditor" for auditor, "Controller"
 * for controller_admin. Every word of the role's label (the part before " / ") must appear in the title; "Operations
 * Manager" for an approver keeps its title.
 */
export function titleRepeatsRole(title: string, role: Role): boolean {
  const titleWords = new Set(words(title))
  const roleWords = words(ROLE_LABELS[role].split(' / ')[0] ?? '')
  return roleWords.length > 0 && roleWords.every((word) => titleWords.has(word))
}
