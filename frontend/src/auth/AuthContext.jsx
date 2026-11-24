/**
 * Authentication state for the browser.
 *
 * Two things this deliberately does NOT do:
 *
 * 1. It does not decide what the user may do. Roles held here drive navigation
 *    and which controls are rendered; the backend decides every actual
 *    permission. A route guard is a usability feature, not a security control.
 * 2. It does not hold any secret. Deployed, the token comes from Cognito via
 *    Authorization Code with PKCE (see cognito.js) against a public app client
 *    with no secret. In a development build only, a hand-pasted development
 *    JWT is also accepted; that path is compiled out of production.
 *
 * Sessions live in sessionStorage rather than localStorage: both are readable
 * by script on this origin, so the difference is lifetime, not secrecy, and a
 * token that outlives the tab on a shared machine is the realistic risk.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { ApiError, api, setTokenProvider } from '../api/client.js'
import {
  clearSession,
  isCognitoConfigured,
  isExpired,
  loadSession,
  refreshSession,
  saveSession,
  signOutRedirect,
} from './cognito.js'

/** Dev-token sign-in exists only in a development build. */
const DEV_SIGN_IN_ENABLED = Boolean(import.meta.env.DEV)

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => loadSession())
  const token = session?.accessToken ?? null
  const [principal, setPrincipal] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | authenticated | error
  const [error, setError] = useState(null)

  // The client asks for the token rather than being handed one, so there is a
  // single source of truth and no stale copy in a closure.
  useEffect(() => {
    setTokenProvider(() => token)
  }, [token])

  const loadPrincipal = useCallback(async () => {
    if (!token) {
      setPrincipal(null)
      setStatus('idle')
      return
    }
    setStatus('loading')
    setError(null)
    try {
      const me = await api.me()
      setPrincipal(me)
      setStatus('authenticated')
    } catch (cause) {
      setPrincipal(null)
      setStatus('error')
      if (cause instanceof ApiError) {
        setError(
          cause.isAuthError
            ? 'That sign-in token is not valid or has expired.'
            : cause.message,
        )
        if (cause.isAuthError) {
          // Purge the dead session instead of retrying it on every load.
          //
          // This line previously read
          // `window.localStorage.removeItem(STORAGE_KEY)`, which was wrong
          // twice over: `STORAGE_KEY` was never defined anywhere, and
          // sessions are kept in `sessionStorage`, not `localStorage`. The
          // resulting ReferenceError was swallowed by the surrounding
          // `catch {}`, so nothing was ever cleared and an expired token kept
          // producing this same error on every page load until the user
          // signed out by hand.
          //
          // `clearSession()` removes the right key from the right storage.
          // Dropping it from state as well stops the token provider handing
          // out a token that is known to be dead; `loadPrincipal` is guarded
          // on `!token`, so the next run settles to `idle` rather than
          // retrying.
          clearSession()
          setSession(null)
        }
      } else {
        setError('Could not load your account.')
      }
    }
  }, [token])

  useEffect(() => {
    loadPrincipal()
  }, [loadPrincipal])

  /** Adopt a session obtained from the Cognito callback. */
  const adoptSession = useCallback((next) => {
    saveSession(next)
    setSession(next)
  }, [])

  /**
   * Development-only sign-in with a pasted JWT.
   *
   * Refuses outright in a production build rather than quietly doing nothing,
   * so a stray caller is a visible error instead of a silent no-op.
   */
  const signInWithToken = useCallback((nextToken) => {
    if (!DEV_SIGN_IN_ENABLED) {
      setError('Token sign-in is not available in this build.')
      setStatus('error')
      return
    }
    const trimmed = (nextToken ?? '').trim()
    if (!trimmed) return
    adoptSession({ accessToken: trimmed, refreshToken: null, expiresAt: null })
  }, [adoptSession])

  const signOut = useCallback(() => {
    clearSession()
    setSession(null)
    setPrincipal(null)
    setStatus('idle')
    setError(null)
    // Clearing locally is not signing out: the Cognito session cookie would
    // remain and the next sign-in would skip the login form entirely.
    if (isCognitoConfigured()) signOutRedirect()
  }, [])

  /**
   * Expiry handling. Checked when the session changes and on an interval,
   * because a user who leaves a tab open should be told their session ended
   * rather than meeting an unexplained 401 on their next click.
   */
  useEffect(() => {
    if (!session || !session.expiresAt) return undefined

    let cancelled = false
    const check = async () => {
      if (cancelled || !isExpired(session)) return
      const refreshed = await refreshSession(session)
      if (cancelled) return
      if (refreshed) {
        setSession(refreshed)
      } else {
        clearSession()
        setSession(null)
        setPrincipal(null)
        setStatus('idle')
        setError('Your session expired. Please sign in again.')
      }
    }
    check()
    const timer = window.setInterval(check, 60_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [session])

  const value = useMemo(() => {
    const roles = principal?.roles ?? []
    const permissions = new Set(principal?.permissions ?? [])
    return {
      token,
      principal,
      status,
      error,
      isAuthenticated: status === 'authenticated' && Boolean(principal),
      roles,
      organizationId: principal?.organizationId ?? null,
      /** Mirrors a backend permission for UI purposes only. */
      can: (permission) => permissions.has(permission),
      hasRole: (...wanted) => wanted.some((r) => roles.includes(r)),
      signIn: signInWithToken,
      signInWithToken,
      adoptSession,
      signOut,
      refresh: loadPrincipal,
      devSignInEnabled: DEV_SIGN_IN_ENABLED,
      cognitoConfigured: isCognitoConfigured(),
    }
  }, [token, principal, status, error, signInWithToken, adoptSession, signOut, loadPrincipal])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
