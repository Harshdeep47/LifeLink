/**
 * Routing and route guards.
 *
 * A `RequireRole` guard keeps privileged dashboards out of the public
 * navigation and gives a clear message instead of a broken screen. It is a
 * usability control, not a security one -- the backend independently rejects
 * every unauthorized request, which is why a user who edits their way past a
 * guard still cannot do anything.
 */
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Suspense, lazy } from 'react'

import { Layout } from './components/Layout.jsx'
import { ErrorBoundary, LoadingPanel, Notice } from './components/ui.jsx'
import { useAuth } from './auth/AuthContext.jsx'

import { HomePage } from './features/home/HomePage.jsx'
import { FindBloodPage } from './features/discovery/FindBloodPage.jsx'
import { FacilityDetailPage } from './features/discovery/FacilityDetailPage.jsx'
import { CampsPage } from './features/camps/CampsPage.jsx'
import { CampDetailPage } from './features/camps/CampDetailPage.jsx'
import { EmergencyRequestPage } from './features/emergency/EmergencyRequestPage.jsx'
import { RequestTrackingPage } from './features/emergency/RequestTrackingPage.jsx'
import { AlertsPage } from './features/alerts/AlertsPage.jsx'
import { AuthCallbackPage } from './features/account/AuthCallbackPage.jsx'
import { ExploreDashboard } from './features/dashboards/ExploreDashboard.jsx'
import { ProfilePage } from './features/account/ProfilePage.jsx'
import { SignInPage } from './features/account/SignInPage.jsx'
import { SignUpPage } from './features/account/SignUpPage.jsx'
import { HelpPage, PrivacyPage, TermsPage } from './features/home/InfoPages.jsx'
import { NotFoundPage } from './features/home/NotFoundPage.jsx'

// Dashboards are the least-visited, heaviest screens, so they load on demand.
const DonorDashboard = lazy(() => import('./features/dashboards/DonorDashboard.jsx'))
const BloodBankDashboard = lazy(() => import('./features/dashboards/BloodBankDashboard.jsx'))
const HospitalDashboard = lazy(() => import('./features/dashboards/HospitalDashboard.jsx'))
const CampOrganizerDashboard = lazy(() =>
  import('./features/dashboards/CampOrganizerDashboard.jsx'),
)
const AdminDashboard = lazy(() => import('./features/dashboards/AdminDashboard.jsx'))
const MyActivityPage = lazy(() => import('./features/account/MyActivityPage.jsx'))

function RequireAuth({ children }) {
  const { isAuthenticated, status } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <LoadingPanel message="Checking your account…" />
  if (!isAuthenticated) {
    return <Navigate to="/sign-in" state={{ from: location.pathname }} replace />
  }
  return children
}

function RequireRole({ roles, children }) {
  const { isAuthenticated, status, hasRole, roles: userRoles } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <LoadingPanel message="Checking your account…" />
  if (!isAuthenticated) {
    return <Navigate to="/sign-in" state={{ from: location.pathname }} replace />
  }
  if (!hasRole(...roles)) {
    return (
      <div className="stack">
        <Notice tone="danger" title="This dashboard is not available to your account">
          <p>
            It requires one of: <strong>{roles.join(', ')}</strong>.
          </p>
          <p className="text-sm">
            Your account holds: {userRoles.length ? userRoles.join(', ') : 'no roles'}.
          </p>
          <p className="text-sm">
            The server enforces this independently, so changing the address bar will
            not grant access.
          </p>
        </Notice>
      </div>
    )
  }
  return children
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route
          path="/"
          element={
            <ErrorBoundary>
              <HomePage />
            </ErrorBoundary>
          }
        />
        <Route
          path="/find"
          element={
            <ErrorBoundary>
              <FindBloodPage />
            </ErrorBoundary>
          }
        />
        <Route path="/facilities/:facilityId" element={<ErrorBoundary><FacilityDetailPage /></ErrorBoundary>} />
        <Route path="/explore" element={<ErrorBoundary><ExploreDashboard /></ErrorBoundary>} />
        <Route path="/camps" element={<ErrorBoundary><CampsPage /></ErrorBoundary>} />
        <Route path="/camps/:campId" element={<ErrorBoundary><CampDetailPage /></ErrorBoundary>} />
        <Route path="/emergency" element={<ErrorBoundary><EmergencyRequestPage /></ErrorBoundary>} />
        <Route
          path="/emergency/:requestId"
          element={
            <RequireAuth>
              <ErrorBoundary><RequestTrackingPage /></ErrorBoundary>
            </RequireAuth>
          }
        />
        <Route
          path="/alerts"
          element={
            <RequireAuth>
              <ErrorBoundary><AlertsPage /></ErrorBoundary>
            </RequireAuth>
          }
        />

        <Route path="/sign-in" element={<SignInPage />} />
        <Route path="/sign-up" element={<ErrorBoundary><SignUpPage /></ErrorBoundary>} />
        <Route
          path="/profile"
          element={<RequireAuth><ErrorBoundary><ProfilePage /></ErrorBoundary></RequireAuth>}
        />
        {/* Holds the user has placed and emergency requests they raised. Both
            were reachable only through the API before this route existed. */}
        <Route
          path="/activity"
          element={
            <RequireAuth>
              <ErrorBoundary>
                <Suspense fallback={<LoadingPanel />}>
                  <MyActivityPage />
                </Suspense>
              </ErrorBoundary>
            </RequireAuth>
          }
        />
        {/* Cognito returns here with ?code=...&state=... */}
        <Route path="/auth/callback" element={<ErrorBoundary><AuthCallbackPage /></ErrorBoundary>} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/terms" element={<TermsPage />} />

        <Route
          path="/dashboard/donor"
          element={
            <RequireRole roles={['DONOR']}>
              <Suspense fallback={<LoadingPanel />}>
                <ErrorBoundary><DonorDashboard /></ErrorBoundary>
              </Suspense>
            </RequireRole>
          }
        />
        <Route
          path="/dashboard/blood-bank"
          element={
            <RequireRole roles={['BLOOD_BANK_ADMIN', 'BLOOD_BANK_STAFF']}>
              <Suspense fallback={<LoadingPanel />}>
                <ErrorBoundary><BloodBankDashboard /></ErrorBoundary>
              </Suspense>
            </RequireRole>
          }
        />
        <Route
          path="/dashboard/hospital"
          element={
            <RequireRole roles={['HOSPITAL_ADMIN', 'HOSPITAL_STAFF', 'HOSPITAL_AUTHORIZER']}>
              <Suspense fallback={<LoadingPanel />}>
                <ErrorBoundary><HospitalDashboard /></ErrorBoundary>
              </Suspense>
            </RequireRole>
          }
        />
        <Route
          path="/dashboard/camps"
          element={
            <RequireRole roles={['CAMP_ORGANIZER', 'CAMP_STAFF']}>
              <Suspense fallback={<LoadingPanel />}>
                <ErrorBoundary><CampOrganizerDashboard /></ErrorBoundary>
              </Suspense>
            </RequireRole>
          }
        />
        <Route
          path="/dashboard/admin"
          element={
            <RequireRole roles={['PLATFORM_ADMIN']}>
              <Suspense fallback={<LoadingPanel />}>
                <ErrorBoundary><AdminDashboard /></ErrorBoundary>
              </Suspense>
            </RequireRole>
          }
        />

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
