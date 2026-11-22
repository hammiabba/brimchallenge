/**
 * Which roles may use each vendor and bank-change action, as the API's role gates decide them
 * (backend/app/api/routes_vendors.py, require_role). The vendor and bank-change answers carry no allowed_actions, so
 * the screens show a button only to these roles; the server still checks every request (status, own request, ...).
 */
import type { Role } from '../api/types'
import { useCurrentUser } from '../auth/context'

export const VENDOR_ACTION_ROLES = {
  onboard: ['ap_clerk'],
  approve: ['finance_manager', 'controller_admin'],
  hold: ['ap_clerk', 'finance_manager', 'controller_admin'],
  requestBankChange: ['ap_clerk'],
  decideBankChange: ['finance_manager', 'controller_admin'],
} as const satisfies Record<string, readonly Role[]>

export type VendorAction = keyof typeof VENDOR_ACTION_ROLES

/** True when the signed-in user's role may use `action` (display only; the server decides). */
export function useMayDo(action: VendorAction): boolean {
  const user = useCurrentUser()
  return (VENDOR_ACTION_ROLES[action] as readonly Role[]).includes(user.role)
}
