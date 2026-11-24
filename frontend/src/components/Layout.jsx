/**
 * Application shell: header, role-aware navigation, footer.
 *
 * On the synthetic-data disclosure. This shell used to open with a full-width
 * red striped banner reading "DEMO ENVIRONMENT - SYNTHETIC DATA - NOT REAL
 * BLOOD AVAILABILITY". The requirement behind it is sound and unchanged: a
 * reader must never mistake invented stock for real institutional data. The
 * execution was wrong, because a page that shouts a warning at full width
 * reads as broken rather than as careful, and a disclosure nobody takes
 * seriously protects nobody.
 *
 * The disclosure now works in three quieter places that are harder to ignore
 * than a banner people learn to skip:
 *
 *   - every facility and camp name carries a "(DEMO)" suffix, from the data
 *     itself rather than from the interface;
 *   - a persistent, low-key strip in the footer states it on every page;
 *   - the Help and About pages say it in full.
 *
 * Nothing claims these records are real, and nothing implies a synthetic
 * facility is a real institution.
 */
import { NavLink, Outlet, Link } from 'react-router-dom'
import { useState } from 'react'

import { useAuth } from '../auth/AuthContext.jsx'
import './Layout.css'

/**
 * Quiet, persistent disclosure. Kept in the footer rather than above the
 * header: present on every page, not competing with the content.
 */
export function SyntheticDataNotice() {
  return (
    <p className="synthetic-notice">
      Academic project prototype. Demonstration records are simulated.
    </p>
  )
}

/**
 * Primary navigation.
 *
 * "Emergency request" is labelled for what it is rather than as a generic
 * "Request blood". The two are different workflows with different
 * consequences: an emergency request is coordinated across providers and
 * carries a clinical priority that only a verified hospital may certify,
 * whereas an ordinary need is served by searching and placing a hold on
 * specific units. Labelling the emergency route "Request blood" sent everyone
 * with an ordinary need down the escalated path.
 */
const PUBLIC_LINKS = [
  { to: '/', label: 'Home', end: true },
  { to: '/explore', label: 'Explore' },
  { to: '/find', label: 'Find blood' },
  { to: '/camps', label: 'Donation camps' },
  { to: '/emergency', label: 'Emergency request' },
  { to: '/help', label: 'Help' },
]

/** Account links, shown only when signed in. */
const ACCOUNT_LINKS = [{ to: '/activity', label: 'My activity' }]

/** Dashboard links, each gated on a role the backend also enforces. */
const ROLE_LINKS = [
  { to: '/dashboard/donor', label: 'Donor', roles: ['DONOR'] },
  {
    to: '/dashboard/blood-bank',
    label: 'Blood bank',
    roles: ['BLOOD_BANK_ADMIN', 'BLOOD_BANK_STAFF'],
  },
  {
    to: '/dashboard/hospital',
    label: 'Hospital',
    roles: ['HOSPITAL_ADMIN', 'HOSPITAL_STAFF', 'HOSPITAL_AUTHORIZER'],
  },
  {
    to: '/dashboard/camps',
    label: 'Camp organizer',
    roles: ['CAMP_ORGANIZER', 'CAMP_STAFF'],
  },
  { to: '/dashboard/admin', label: 'Administrator', roles: ['PLATFORM_ADMIN'] },
]

export function Layout() {
  const { isAuthenticated, principal, roles, hasRole, signOut } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmSignOut, setConfirmSignOut] = useState(false)

  const visibleRoleLinks = ROLE_LINKS.filter((link) => hasRole(...link.roles))

  return (
    <div className="shell">

      <a className="skip-link" href="#main">Skip to main content</a>

      <header className="header">
        <div className="header__inner">
          <Link to="/" className="brand" aria-label="LifeLink home">
            <span className="brand__mark" aria-hidden="true">◆</span>
            <span className="brand__name">LifeLink</span>
          </Link>

          <button
            type="button"
            className="header__toggle"
            aria-expanded={menuOpen}
            aria-controls="primary-navigation"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="visually-hidden">
              {menuOpen ? 'Close navigation' : 'Open navigation'}
            </span>
            <span aria-hidden="true">{menuOpen ? '✕' : '☰'}</span>
          </button>

          <nav
            id="primary-navigation"
            className={`nav ${menuOpen ? 'nav--open' : ''}`}
            aria-label="Primary"
          >
            {PUBLIC_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) => `nav__link ${isActive ? 'nav__link--active' : ''}`}
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </NavLink>
            ))}

            {isAuthenticated &&
              ACCOUNT_LINKS.map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  className={({ isActive }) =>
                    `nav__link ${isActive ? 'nav__link--active' : ''}`
                  }
                  onClick={() => setMenuOpen(false)}
                >
                  {link.label}
                </NavLink>
              ))}

            {visibleRoleLinks.length > 0 && (
              <span className="nav__divider" aria-hidden="true" />
            )}
            {visibleRoleLinks.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `nav__link nav__link--role ${isActive ? 'nav__link--active' : ''}`
                }
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </NavLink>
            ))}
          </nav>

          <div className="header__account">
            {isAuthenticated ? (
              <>
                <Link to="/profile" className="header__user">
                  <span className="header__user-name">
                    {/* Never the Cognito subject: a uuid is not a name. */}
                    {principal?.displayName && principal.displayName !== principal.userId
                      ? principal.displayName
                      : 'My profile'}
                  </span>
                  <span className="header__user-roles">{roles.join(', ') || 'No roles'}</span>
                </Link>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => setConfirmSignOut(true)}
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <Link to="/sign-in" className="btn btn--ghost btn--sm">Sign in</Link>
                <Link to="/sign-up" className="btn btn--primary btn--sm">Create account</Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="main">
        <Outlet />
      </main>

      {/* Sign-out confirmation. Signing out is destructive in the small
          sense that it discards a session and, with Cognito, redirects away
          from the app -- so an accidental click should be recoverable. */}
      {confirmSignOut && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setConfirmSignOut(false)}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="signout-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="signout-title" className="modal__title">
              Are you sure you want to sign out?
            </h2>
            <p className="modal__body text-sm">
              You will need to sign in again to reserve units, register for
              camps or see your dashboards. Browsing blood availability does
              not require an account.
            </p>
            <div className="modal__actions">
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => setConfirmSignOut(false)}
                autoFocus
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => {
                  setConfirmSignOut(false)
                  signOut()
                }}
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Every link below points at a route that exists. A footer full of
          dead links is worse than a short footer. */}
      <footer className="footer">
        <div className="footer__inner">
          <div className="footer__grid">
            <div className="footer__brand">
              <span className="brand brand--footer">LifeLink</span>
              <p className="footer__tagline">
                Connecting donors, blood banks and communities.
              </p>
              <p className="footer__disclaimer">
                Not a medical device, and no clinical advice. A temporary
                reservation holds units for a limited time; it is not a
                cross-match and not a guarantee of release. Compatibility and
                release remain decisions for qualified staff at the facility.
              </p>
            </div>

            <nav className="footer__col" aria-label="Explore">
              <h2 className="footer__heading">Explore</h2>
              <Link to="/explore">Explore dashboard</Link>
              <Link to="/find">Find blood</Link>
              <Link to="/camps">Donation camps</Link>
              <Link to="/emergency">Emergency request</Link>
            </nav>

            <nav className="footer__col" aria-label="Platform">
              <h2 className="footer__heading">Platform</h2>
              <Link to="/help">How LifeLink works</Link>
              <Link to="/privacy">Privacy</Link>
              <Link to="/terms">Terms</Link>
            </nav>

            <nav className="footer__col" aria-label="Account">
              <h2 className="footer__heading">Account</h2>
              {isAuthenticated ? (
                <>
                  <Link to="/profile">My profile</Link>
                  <Link to="/activity">My activity</Link>
                  <Link to="/alerts">My alerts</Link>
                </>
              ) : (
                <>
                  <Link to="/sign-in">Sign in</Link>
                  <Link to="/sign-up">Create account</Link>
                </>
              )}
            </nav>
          </div>

          <div className="footer__bottom">
            <span>
              © 2026 LifeLink. Academic project prototype. Demonstration
              records are simulated.
            </span>
          </div>
        </div>
      </footer>
    </div>
  )
}
