/**
 * OAuth callback: completes the PKCE exchange and returns the user where they
 * were going.
 *
 * Two details that matter:
 *
 * 1.  The exchange runs exactly once. React 18 StrictMode double-invokes
 *     effects in development, and an authorization code is single-use — a
 *     second exchange fails with `invalid_grant` and would show the user an
 *     error after a successful sign-in. A ref guard, not state, because state
 *     updates do not land before the second invocation.
 * 2.  The code is removed from the URL on success, so it is not left in the
 *     address bar, in history, or in any `Referer` the next navigation emits.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../auth/AuthContext.jsx'
import { completeSignIn } from '../../auth/cognito.js'
import { safeInternalPath } from '../../auth/redirect.js'
import { Button, Card, Notice } from '../../components/ui.jsx'

export function AuthCallbackPage() {
  const { adoptSession } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    let cancelled = false
    completeSignIn()
      .then(({ session, returnTo }) => {
        if (cancelled) return
        adoptSession(session)
        // replace: the callback URL must not stay in history.
        navigate(safeInternalPath(returnTo), { replace: true })
      })
      .catch((cause) => {
        if (!cancelled) setError(cause?.message ?? 'Sign-in could not be completed.')
      })

    return () => {
      cancelled = true
    }
  }, [adoptSession, navigate])

  if (error) {
    return (
      <div className="stack stack--narrow">
        <header className="page-header">
          <h1>Sign-in did not complete</h1>
        </header>
        <Card>
          <Notice tone="warning" title="We could not finish signing you in">
            <p className="text-sm">{error}</p>
          </Notice>
          <Button type="button" onClick={() => navigate('/sign-in', { replace: true })}>
            Try again
          </Button>
        </Card>
      </div>
    )
  }

  return (
    <div className="stack stack--narrow">
      <Card>
        <p className="muted" role="status">Completing sign-in…</p>
      </Card>
    </div>
  )
}
