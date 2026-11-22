import { Center, Loader } from '@mantine/core'
import { Suspense, lazy, type ComponentType, type LazyExoticComponent } from 'react'
import { Route, Routes } from 'react-router'

import { LoginPage } from './auth/LoginPage'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './shell/AppLayout'
import { HomeRedirect } from './shell/HomeRedirect'
import { ALL_NAV_ITEMS, type NavKey } from './shell/navigation'
import { NotFoundPage } from './shell/NotFoundPage'
import { PlaceholderPage } from './shell/PlaceholderPage'

// Screens load on first visit (their own bundle chunks), so the sign-in page and the shell stay small.
const BillsPage = lazy(() => import('./bills/BillsPage'))
const ReviewQueuePage = lazy(() => import('./bills/ReviewQueuePage'))
const BillDetailPage = lazy(() => import('./bills/BillDetailPage'))
const VendorsPage = lazy(() => import('./vendors/VendorsPage'))
const VendorDetailPage = lazy(() => import('./vendors/VendorDetailPage'))
const BankChangesPage = lazy(() => import('./bankChanges/BankChangesPage'))
const AuditPage = lazy(() => import('./audit/AuditPage'))
const UsersPage = lazy(() => import('./admin/UsersPage'))
const PoliciesPage = lazy(() => import('./admin/PoliciesPage'))
const AbsencesPage = lazy(() => import('./admin/AbsencesPage'))

/** The screens built so far, by navigation item. Every other item still shows its placeholder. */
const SCREENS: Partial<Record<NavKey, LazyExoticComponent<ComponentType>>> = {
  bills: BillsPage,
  review: ReviewQueuePage,
  vendors: VendorsPage,
  bankChanges: BankChangesPage,
  audit: AuditPage,
  users: UsersPage,
  policies: PoliciesPage,
  absences: AbsencesPage,
}

/** Shown while a screen's code loads. */
function ScreenLoading() {
  return (
    <Center py="xl">
      <Loader size="sm" aria-label="Loading" />
    </Center>
  )
}

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
          {ALL_NAV_ITEMS.map((item) => {
            const Screen = SCREENS[item.key]
            return (
              <Route
                key={item.key}
                path={item.path}
                element={Screen ? <Suspense fallback={<ScreenLoading />}><Screen /></Suspense> : <PlaceholderPage item={item} />}
              />
            )
          })}
          <Route
            path="/bills/:billId"
            element={<Suspense fallback={<ScreenLoading />}><BillDetailPage /></Suspense>}
          />
          <Route
            path="/vendors/:vendorId"
            element={<Suspense fallback={<ScreenLoading />}><VendorDetailPage /></Suspense>}
          />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
