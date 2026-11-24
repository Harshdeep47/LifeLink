/**
 * Cognito sign-in: OAuth 2.0 Authorization Code with PKCE.
 *
 * This is the flow an earlier comment claimed was implemented and was not. The
 * deployed sign-in page instead told visitors to run a local development
 * command and listed seeded account ids, including an administrator's. This
 * module replaces that.
 *
 * Why authorization code with PKCE, rather than the implicit flow: a browser
 * cannot keep a client secret, so the app client is public
 * (`GenerateSecret: false`). PKCE closes the gap that leaves — an intercepted
 * authorization code is useless without the `code_verifier`, which never
 * leaves this origin. The implicit flow would put an access token in the URL
 * fragment, where it lands in history and in any `Referer` the page emits.
 *
 * Token storage is `sessionStorage`, not `localStorage`. Both are readable by
 * script on this origin, so neither defends against XSS; the difference is
 * lifetime. A token in `localStorage` outlives the tab and sits on a shared or
 * lab machine until something clears it, which for a demonstration laptop is
 * the realistic risk. `sessionStorage` is scoped to the tab.
 *
 * What this module does NOT do, stated so nobody has to infer it:
 *
 * - It does not decide what the user may do. The backend re-reads roles and
 *   account status from the database on every request; everything here is
 *   usability.
 * - It does not refresh silently in the background. Expiry is detected on use
 *   and surfaced; see `isExpired`.
 *
 * Configuration comes from Vite environment variables written at deploy time by
 * `scripts/deploy_frontend.py` from the CloudFormation stack outputs, so the
 * bundle cannot point at the wrong user pool. All of them are public
 * identifiers; no secret belongs in a browser bundle.
 */

const VERIFIER_KEY = 'lifelink.pkce.verifier'
const STATE_KEY = 'lifelink.pkce.state'
const RETURN_KEY = 'lifelink.pkce.returnTo'
export const TOKEN_KEY = 'lifelink.session'

/** Whether Cognito is configured in this build. */
export function isCognitoConfigured() {
  return Boolean(config().domain && config().clientId)
}

export function config() {
  const env = import.meta.env
  return {
    domain: (env.VITE_COGNITO_DOMAIN ?? '').replace(/\/$/, ''),
    clientId: env.VITE_COGNITO_CLIENT_ID ?? '',
    redirectUri: env.VITE_COGNITO_REDIRECT_URI ?? `${window.location.origin}/auth/callback`,
    logoutUri: env.VITE_COGNITO_LOGOUT_URI ?? `${window.location.origin}/`,
    scopes: (env.VITE_COGNITO_SCOPES ?? 'openid email profile').split(/\s+/).join(' '),
    // Needed by cognitoSignUp.js to derive the regional endpoint. Public.
    poolId: env.VITE_COGNITO_USER_POOL_ID ?? '',
  }
}

// --- PKCE primitives --------------------------------------------------------

function base64UrlEncode(bytes) {
  let binary = ''
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte)
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomString(byteLength = 48) {
  const bytes = new Uint8Array(byteLength)
  window.crypto.getRandomValues(bytes)
  return base64UrlEncode(bytes)
}

async function challengeFor(verifier) {
  const digest = await window.crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(verifier),
  )
  return base64UrlEncode(digest)
}

// --- Session storage --------------------------------------------------------

function readStore(key) {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStore(key, value) {
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    /* Private mode or blocked storage: sign-in works for this page only. */
  }
}

function clearStore(key) {
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

export function loadSession() {
  const raw = readStore(TOKEN_KEY)
  if (!raw) return null
  try {
    const session = JSON.parse(raw)
    return session?.accessToken ? session : null
  } catch {
    clearStore(TOKEN_KEY)
    return null
  }
}

export function saveSession(session) {
  writeStore(TOKEN_KEY, JSON.stringify(session))
}

export function clearSession() {
  clearStore(TOKEN_KEY)
  clearStore(VERIFIER_KEY)
  clearStore(STATE_KEY)
}

/**
 * Whether a session is past its expiry.
 *
 * A 30-second margin avoids sending a token that expires mid-flight, which
 * would surface as an unexplained 401 rather than as "your session ended".
 */
export function isExpired(session, now = Date.now()) {
  if (!session?.expiresAt) return false
  return now >= session.expiresAt - 30_000
}

// --- The flow ---------------------------------------------------------------

/**
 * Begin sign-in by redirecting to Cognito managed login.
 *
 * `state` is random and checked on return: without it, a third party could
 * feed this origin an authorization code of their choosing (login CSRF).
 */
export async function beginSignIn({ returnTo = '/' } = {}) {
  const { domain, clientId, redirectUri, scopes } = config()
  if (!domain || !clientId) {
    throw new Error('Cognito is not configured in this build')
  }

  const verifier = randomString()
  const state = randomString(16)
  writeStore(VERIFIER_KEY, verifier)
  writeStore(STATE_KEY, state)
  writeStore(RETURN_KEY, returnTo)

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: scopes,
    state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: 'S256',
  })
  window.location.assign(`${domain}/oauth2/authorize?${params.toString()}`)
}

/**
 * Complete sign-in from the callback URL.
 *
 * Returns `{ session, returnTo }`. Throws with a message fit to show a user.
 */
export async function completeSignIn(search = window.location.search) {
  const { domain, clientId, redirectUri } = config()
  const params = new URLSearchParams(search)

  const error = params.get('error')
  if (error) {
    const description = params.get('error_description')
    throw new Error(description ? `${error}: ${description}` : error)
  }

  const code = params.get('code')
  if (!code) throw new Error('No authorization code was returned.')

  const expectedState = readStore(STATE_KEY)
  const actualState = params.get('state')
  if (!expectedState || expectedState !== actualState) {
    // Either a stale tab or a code this origin did not ask for. Refuse both.
    throw new Error('Sign-in state did not match. Please start again.')
  }

  const verifier = readStore(VERIFIER_KEY)
  if (!verifier) throw new Error('Sign-in could not be completed in this tab. Please start again.')

  const response = await fetch(`${domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: clientId,
      code,
      redirect_uri: redirectUri,
      code_verifier: verifier,
    }),
  })

  clearStore(VERIFIER_KEY)
  clearStore(STATE_KEY)

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = body.error_description || body.error || ''
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `Token exchange failed (${response.status}).`)
  }

  const payload = await response.json()
  const session = {
    // The API authorizes with the access token; the id token is not sent.
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token ?? null,
    expiresAt: Date.now() + (payload.expires_in ?? 3600) * 1000,
    tokenType: payload.token_type ?? 'Bearer',
  }
  saveSession(session)

  const returnTo = readStore(RETURN_KEY) || '/'
  clearStore(RETURN_KEY)
  return { session, returnTo }
}

/**
 * Exchange a refresh token for a new access token.
 *
 * Returns the new session, or null if the refresh token is gone or rejected —
 * in which case the caller should sign the user out rather than retry.
 */
export async function refreshSession(session) {
  const { domain, clientId } = config()
  if (!session?.refreshToken || !domain || !clientId) return null

  const response = await fetch(`${domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: clientId,
      refresh_token: session.refreshToken,
    }),
  })
  if (!response.ok) return null

  const payload = await response.json()
  if (!payload.access_token) return null

  const next = {
    accessToken: payload.access_token,
    // A refresh response usually omits the refresh token; keep the existing one.
    refreshToken: payload.refresh_token ?? session.refreshToken,
    expiresAt: Date.now() + (payload.expires_in ?? 3600) * 1000,
    tokenType: payload.token_type ?? 'Bearer',
  }
  saveSession(next)
  return next
}

/**
 * Sign out of Cognito as well as locally.
 *
 * Clearing local storage alone would leave the Cognito session cookie intact,
 * so the next sign-in would skip the login form and look like it never signed
 * out at all.
 */
export function signOutRedirect() {
  const { domain, clientId, logoutUri } = config()
  clearSession()
  if (!domain || !clientId) {
    window.location.assign('/')
    return
  }
  const params = new URLSearchParams({ client_id: clientId, logout_uri: logoutUri })
  window.location.assign(`${domain}/logout?${params.toString()}`)
}
