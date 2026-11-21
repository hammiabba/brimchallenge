import { createContext, useContext } from 'react'

import type { Me } from '../api/types'

/** The TanStack Query key for the signed-in user (GET /auth/me). null in the cache means "signed out". */
export const ME_QUERY_KEY = ['auth', 'me'] as const

/** What AuthProvider exposes. */
export interface AuthState {
  /** The signed-in user, null when signed out (or not yet known: see isLoading). */
  user: Me | null
  /** True until the first GET /auth/me answers. */
  isLoading: boolean
  /** Set when GET /auth/me failed for a reason other than 401 (server down, 5xx). */
  error: unknown
  /** Asks /auth/me again (after `error`). */
  retry: () => void
  /** Signs in as `userId` (POST /auth/login); resolves to the new user, or throws ApiError. */
  login: (userId: string) => Promise<Me>
  /** Signs out (POST /auth/logout) and drops the signed-in user's cached data. Throws ApiError if refused. */
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

/** The auth state. Must be used inside AuthProvider. */
export function useAuth(): AuthState {
  const state = useContext(AuthContext)
  if (state === null) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return state
}

/** The signed-in user, for components rendered behind RequireAuth (where there always is one). */
export function useCurrentUser(): Me {
  const { user } = useAuth()
  if (user === null) {
    throw new Error('useCurrentUser must be used behind <RequireAuth>')
  }
  return user
}
