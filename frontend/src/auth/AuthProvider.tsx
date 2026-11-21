import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, type ReactNode } from 'react'

import { api, setUnauthorizedHandler, unwrap } from '../api/client'
import { ApiError } from '../api/errors'
import type { Me } from '../api/types'
import { AuthContext, ME_QUERY_KEY, type AuthState } from './context'

/** GET /auth/me: the user, or null when there is no valid session (401). Other errors are thrown. */
async function fetchMe(): Promise<Me | null> {
  try {
    return await unwrap(api.GET('/auth/me'))
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

/** Removes every cached query except the signed-in user, so one user's data never shows for the next. */
function dropUserData(queryClient: QueryClient): void {
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] })
}

/**
 * Holds who is signed in. The user comes from GET /auth/me (cached by TanStack Query); login and logout call the
 * auth endpoints and update that cache. It also registers the API client's 401 handler: any 401 marks the user as
 * signed out, and RequireAuth then sends them to the login page. The session itself is the server's httpOnly cookie.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ME_QUERY_KEY, queryFn: fetchMe, staleTime: 5 * 60_000 })

  useEffect(
    () =>
      setUnauthorizedHandler(() => {
        queryClient.setQueryData(ME_QUERY_KEY, null)
        dropUserData(queryClient)
      }),
    [queryClient],
  )

  const login = useCallback(
    async (userId: string): Promise<Me> => {
      const user = await unwrap(api.POST('/auth/login', { body: { user_id: userId } }))
      dropUserData(queryClient)
      queryClient.setQueryData(ME_QUERY_KEY, user)
      return user
    },
    [queryClient],
  )

  const logout = useCallback(async (): Promise<void> => {
    try {
      await unwrap(api.POST('/auth/logout'))
    } catch (error) {
      // Already signed out on the server (expired session): finish signing out here too.
      if (!(error instanceof ApiError && error.status === 401)) throw error
    }
    queryClient.setQueryData(ME_QUERY_KEY, null)
    dropUserData(queryClient)
  }, [queryClient])

  const { refetch } = me
  const retry = useCallback(() => {
    void refetch()
  }, [refetch])

  const value = useMemo<AuthState>(
    () => ({
      user: me.data ?? null,
      isLoading: me.isPending,
      error: me.data == null ? me.error : null,
      retry,
      login,
      logout,
    }),
    [me.data, me.isPending, me.error, retry, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
