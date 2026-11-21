import { Navigate } from 'react-router'

import { useCurrentUser } from '../auth/context'
import { homePathFor } from './navigation'

/** "/" sends the signed-in user to their role's first sidebar item. */
export function HomeRedirect() {
  const user = useCurrentUser()
  return <Navigate to={homePathFor(user.role)} replace />
}
