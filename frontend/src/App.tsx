import { Route, Routes } from 'react-router'

import { LoginPage } from './auth/LoginPage'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './shell/AppLayout'
import { HomeRedirect } from './shell/HomeRedirect'
import { ALL_NAV_ITEMS } from './shell/navigation'
import { NotFoundPage } from './shell/NotFoundPage'
import { PlaceholderPage } from './shell/PlaceholderPage'

/**
 * The routes. /login is public; everything else is behind RequireAuth inside the shell. Every screen in
 * navigation.ts has a route for every signed-in user (the server, not the router, decides access); "/" goes to the
 * role's home page and anything else is a 404.
 */
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<HomeRedirect />} />
          {ALL_NAV_ITEMS.map((item) => (
            <Route key={item.key} path={item.path} element={<PlaceholderPage item={item} />} />
          ))}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
