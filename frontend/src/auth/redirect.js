/**
 * Validation for post-sign-in redirect targets.
 *
 * The sign-in page sends the user back to wherever they were headed before
 * being asked to authenticate. That target arrives as router state set from
 * `location.pathname`, which looks trustworthy and is not.
 *
 * Visiting `https://app.example//evil.com` produces a pathname of
 * `//evil.com`. Handing that to `<Navigate to=...>` makes the browser treat it
 * as a protocol-relative URL and leave the site — an open redirect, which is
 * worth more to an attacker than it first appears: the victim is mid-sign-in,
 * so a convincing credential-harvesting page is exactly what they expect to
 * see next.
 *
 * React Router has published advisories for several variants of this
 * (GHSA-2j2x-hqr9-3h42, GHSA-wrjc-x8rr-h8h6, GHSA-jjmj-jmhj-qwj2). The
 * dependency is patched, but this check stays regardless: the application
 * should not rely on a library version to avoid sending its own users to an
 * attacker's site, and the next variant of the bug is cheaper to survive than
 * to discover.
 *
 * Allow-list, not deny-list: a target is rejected unless it is recognisably a
 * single internal path.
 */

export const DEFAULT_REDIRECT = '/'

/**
 * Reduce an untrusted redirect target to a safe internal path.
 *
 * @param {unknown} candidate - the proposed target, from router state
 * @returns {string} the candidate if it is a safe internal path, else '/'
 */
export function safeInternalPath(candidate) {
  if (typeof candidate !== 'string') return DEFAULT_REDIRECT

  const value = candidate.trim()
  if (value === '') return DEFAULT_REDIRECT

  // Must be rooted. A relative path would resolve against whatever page is
  // current, which is not a target we can reason about.
  if (!value.startsWith('/')) return DEFAULT_REDIRECT

  // `//host` is protocol-relative and leaves the site. `/\host` and `/\/host`
  // are the same attack through backslashes, which several browsers normalise
  // to forward slashes.
  if (value.startsWith('//') || value.startsWith('/\\')) return DEFAULT_REDIRECT

  // A backslash anywhere invites browser-specific normalisation, and no
  // legitimate route in this application contains one.
  if (value.includes('\\')) return DEFAULT_REDIRECT

  // Control characters, including the tab/newline tricks used to smuggle a
  // scheme past naive checks (`/\tjavascript:...`).
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(value)) return DEFAULT_REDIRECT

  // A scheme cannot appear in a rooted path, so its presence means someone is
  // trying to build an absolute URL. Checked after the control-character test
  // so that obfuscated schemes are already gone.
  if (/^\/+[a-z][a-z0-9+.-]*:/i.test(value)) return DEFAULT_REDIRECT

  return value
}
