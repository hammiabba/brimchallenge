/**
 * Reference data shared by many screens, one TanStack Query key per resource. Flag help, departments, GL accounts
 * and the people list change rarely, so they are fetched once per session (staleTime: Infinity).
 */
import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from './client'
import type { Department, GlAccount, PickerUser } from './types'

/** GET /reference/departments (signed-in users only), cached for the session. */
export function useDepartments() {
  return useQuery({
    queryKey: ['reference', 'departments'],
    queryFn: () => unwrap(api.GET('/reference/departments')),
    staleTime: Infinity,
  })
}

/** "Finance (D02)" when the department list is loaded, else just the id. */
export function departmentLabel(departmentId: string, departments: readonly Department[] | undefined): string {
  const department = departments?.find((d) => d.department_id === departmentId)
  return department ? `${department.name} (${department.department_id})` : departmentId
}

/** GET /reference/flag-help: title, one-sentence help and severity for every flag code, cached for the session. */
export function useFlagHelp() {
  return useQuery({
    queryKey: ['reference', 'flag-help'],
    queryFn: () => unwrap(api.GET('/reference/flag-help')),
    staleTime: Infinity,
  })
}

/** A flag code as words ("DUPLICATE_EXACT" -> "Duplicate exact"), for when flag help has no entry. */
export function codeAsWords(code: string): string {
  const words = code.toLowerCase().split('_').join(' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** GET /reference/gl-accounts, cached for the session. */
export function useGlAccounts() {
  return useQuery({
    queryKey: ['reference', 'gl-accounts'],
    queryFn: () => unwrap(api.GET('/reference/gl-accounts')),
    staleTime: Infinity,
  })
}

/** The GL account's name, or undefined while loading or when unknown. */
export function glAccountName(number: string, accounts: readonly GlAccount[] | undefined): string | undefined {
  return accounts?.find((a) => a.account_number === number)?.name
}

/**
 * The people directory, for showing names next to user ids (assignees, approvers, resolvers). It is the sign-in
 * picker list (GET /auth/users, same cache entry as the login page): every user who isn't terminated. A terminated
 * user's id is shown without a name.
 */
export function usePeople() {
  return useQuery({
    queryKey: ['auth', 'users'],
    queryFn: () => unwrap(api.GET('/auth/users')),
    staleTime: Infinity,
  })
}

/** The person with `userId`, if the directory has them. */
export function personFor(userId: string | null | undefined, people: readonly PickerUser[] | undefined) {
  return userId ? people?.find((p) => p.user_id === userId) : undefined
}

/** "Priya Raman" for a known user, the bare id otherwise, or "Unassigned" when there is no id. */
export function personName(userId: string | null | undefined, people: readonly PickerUser[] | undefined): string {
  if (!userId) return 'Unassigned'
  return personFor(userId, people)?.full_name ?? userId
}

/** GET /vendors (up to 200, enough for the vendor filter), cached for five minutes. */
export function useVendorList() {
  return useQuery({
    queryKey: ['vendors', 'list'],
    queryFn: () => unwrap(api.GET('/vendors', { params: { query: { limit: 200 } } })),
    staleTime: 5 * 60_000,
  })
}

/** GET /vendors/{vendor_id} (for the vendor's status on the bill header). Disabled without an id. */
export function useVendor(vendorId: string | null | undefined) {
  return useQuery({
    queryKey: ['vendors', 'detail', vendorId],
    queryFn: () => unwrap(api.GET('/vendors/{vendor_id}', { params: { path: { vendor_id: vendorId ?? '' } } })),
    enabled: Boolean(vendorId),
    staleTime: 60_000,
  })
}
