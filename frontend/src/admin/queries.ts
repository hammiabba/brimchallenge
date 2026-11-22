/**
 * TanStack Query hooks for the admin screens. Keys: ['admin', 'users' | 'policies' | 'absences']. Reads are open to
 * the controller and auditors; writes to the controller only (the server decides and answers 403 otherwise).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { AbsenceInput, PolicyPatch, Role, UserPatch } from '../api/types'

/**
 * The roles that may change users, policies and absences, as the API's role gate decides it (the PATCH and POST
 * routes under /admin are controller only; tests/api/matrix.py). Screens show their edit actions only to these roles;
 * the server still refuses anyone else.
 */
export const ADMIN_WRITE_ROLES: readonly Role[] = ['controller_admin']

/** GET /admin/users: every user, including terminated ones. */
export function useAdminUsers() {
  return useQuery({ queryKey: ['admin', 'users'], queryFn: () => unwrap(api.GET('/admin/users')) })
}

/** GET /admin/policies: the approval, payment-release and match rules. */
export function usePolicies() {
  return useQuery({ queryKey: ['admin', 'policies'], queryFn: () => unwrap(api.GET('/admin/policies')) })
}

/** GET /admin/absences: recorded absences with their delegates. */
export function useAbsences() {
  return useQuery({ queryKey: ['admin', 'absences'], queryFn: () => unwrap(api.GET('/admin/absences')) })
}

/**
 * Refreshes the admin lists and the people directory after a write: a role, status or delegate change shows up in
 * names and approval routes elsewhere, and the signed-in user's own limits may have changed.
 */
function useInvalidateAdmin() {
  const queryClient = useQueryClient()
  return () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['admin'] }),
    queryClient.invalidateQueries({ queryKey: ['auth'] }),
  ])
}

/** PATCH /admin/users/{id} with only the fields that changed. */
export function useUpdateUser(userId: string) {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: (body: UserPatch) =>
      unwrap(api.PATCH('/admin/users/{user_id}', { params: { path: { user_id: userId } }, body })),
    onSuccess: invalidate,
  })
}

/** PATCH /admin/policies/{id} with only the fields that changed. */
export function useUpdatePolicy(ruleId: string) {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: (body: PolicyPatch) =>
      unwrap(api.PATCH('/admin/policies/{rule_id}', { params: { path: { rule_id: ruleId } }, body })),
    onSuccess: invalidate,
  })
}

/** POST /admin/absences: record someone's absence and who signs for them. */
export function useAddAbsence() {
  const invalidate = useInvalidateAdmin()
  return useMutation({
    mutationFn: (body: AbsenceInput) => unwrap(api.POST('/admin/absences', { body })),
    onSuccess: invalidate,
  })
}
