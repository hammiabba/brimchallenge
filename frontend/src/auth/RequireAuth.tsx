import { Center, Container, Loader } from '@mantine/core'
import { Navigate, Outlet, useLocation } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { useAuth } from './context'

/** Where the login page returns to after signing in (router location state). */
export interface LoginRedirectState {
  from?: string
}

/**
 * Route guard for everything behind sign-in. While /auth/me is loading it shows a spinner; when nobody is signed
 * in it redirects to /login, remembering the page that was asked for. This only decides what to render: the
 * server checks the session and the role on every request.
 */
export function RequireAuth() {
  const { user, isLoading, error, retry } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <Center h="100vh">
        <Loader size="sm" />
      </Center>
    )
  }
  if (user === null && error) {
    return (
      <Container size="xs" pt={80}>
        <ErrorAlert error={error} title="Can't check your session" onRetry={retry} />
      </Container>
    )
  }
  if (user === null) {
    const state: LoginRedirectState = { from: location.pathname + location.search + location.hash }
    return <Navigate to="/login" replace state={state} />
  }
  return <Outlet />
}
