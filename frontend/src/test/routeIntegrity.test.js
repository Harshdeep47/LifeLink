/**
 * Every internal link must point at a route that exists.
 *
 * This exists because a dead link is invisible in every other check. The build
 * succeeds, the tests pass, nothing throws — the user simply clicks and lands
 * on the 404 page. A footer link to a `/requests` route that had been renamed
 * shipped exactly that way, and nothing in the suite noticed.
 *
 * The check reads the real files rather than importing the app, so it needs no
 * browser, no router and no mocking, and it cannot be satisfied by a component
 * that happens not to render during a test.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Locate `src/` from the working directory.
 *
 * `import.meta.url` is not usable here: under Vitest it is a dev-server URL
 * (`/@fs/D:/...` on Windows), which is not a filesystem path. Walking up from
 * the working directory works whether the suite is run from `frontend/` or
 * from the repository root.
 */
function findSrc() {
  let dir = process.cwd()
  for (let depth = 0; depth < 4; depth += 1) {
    for (const candidate of [join(dir, 'src'), join(dir, 'frontend', 'src')]) {
      if (existsSync(join(candidate, 'App.jsx'))) return candidate
    }
    dir = resolve(dir, '..')
  }
  throw new Error('could not locate the frontend src directory')
}

const SRC = findSrc()

function sourceFiles(dir = SRC, found = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      // The test directory describes links, it does not create them.
      if (entry !== 'test') sourceFiles(full, found)
    } else if (/\.jsx?$/.test(entry)) {
      found.push(full)
    }
  }
  return found
}

/** Declared routes, from the single file that declares them. */
function declaredRoutes() {
  const app = readFileSync(join(SRC, 'App.jsx'), 'utf8')
  const paths = [...app.matchAll(/path="([^"]+)"/g)].map((m) => m[1])
  return new Set(paths)
}

/**
 * Turn a route pattern into a matcher: `/camps/:campId` accepts `/camps/x`.
 * A wildcard route is excluded deliberately — `*` matches everything, so
 * counting it would make every dead link "valid".
 */
function routeMatchers(routes) {
  return [...routes]
    .filter((route) => route !== '*' && route.startsWith('/'))
    .map((route) => ({
      route,
      regex: new RegExp(`^${route.replace(/:[^/]+/g, '[^/]+')}$`),
    }))
}

/**
 * Literal internal link targets.
 *
 * Only string literals are collected. A computed target (`to={href}`) cannot
 * be checked without evaluating it, and guessing would produce false failures.
 * Those are covered by the helpers that build them having their own tests —
 * `requestBloodHref`, for instance.
 */
function literalLinkTargets(files) {
  const targets = new Map()
  for (const file of files) {
    const text = readFileSync(file, 'utf8')
    for (const match of text.matchAll(/\bto=(?:"([^"{}]+)"|'([^'{}]+)'|\{'([^'{}]+)'\}|\{"([^"{}]+)"\})/g)) {
      const value = match[1] ?? match[2] ?? match[3] ?? match[4]
      if (!value || !value.startsWith('/')) continue
      const bare = value.split(/[?#]/)[0]
      if (!targets.has(bare)) targets.set(bare, [])
      targets.get(bare).push(file.replace(SRC, ''))
    }
  }
  return targets
}

const routes = declaredRoutes()
const matchers = routeMatchers(routes)
const files = sourceFiles()
const targets = literalLinkTargets(files)

describe('route integrity', () => {
  it('finds the application source to scan', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it('declares the routes this check depends on', () => {
    for (const expected of ['/', '/find', '/camps', '/emergency', '/activity']) {
      expect(routes.has(expected)).toBe(true)
    }
  })

  it('collects link targets to check', () => {
    expect(targets.size).toBeGreaterThan(5)
  })

  it('has no link pointing at a route that does not exist', () => {
    const dead = []
    for (const [target, sources] of targets) {
      if (!matchers.some(({ regex }) => regex.test(target))) {
        dead.push(`${target} (linked from ${[...new Set(sources)].join(', ')})`)
      }
    }
    expect(dead).toEqual([])
  })

  it('routes every navigation label to a real page', () => {
    // The nav and footer are the links a user is most likely to click and the
    // least likely to be exercised by any other test.
    const layout = readFileSync(join(SRC, 'components', 'Layout.jsx'), 'utf8')
    const navTargets = [...layout.matchAll(/to: '([^']+)'/g)].map((m) => m[1])
    expect(navTargets.length).toBeGreaterThan(5)
    for (const target of navTargets) {
      expect(
        matchers.some(({ regex }) => regex.test(target)),
        `nav link ${target} has no route`,
      ).toBe(true)
    }
  })

  it('keeps a wildcard route so an unknown path renders the 404 page', () => {
    expect(routes.has('*')).toBe(true)
  })
})

describe('workflow separation in the interface', () => {
  /**
   * The ordinary need and the emergency workflow must not share a label.
   * Emergency coordination fans a request out to providers and carries a
   * clinical priority only a verified hospital may certify; an ordinary need
   * is served by searching and holding units. When the nav called the
   * emergency route "Request blood", everyone with an ordinary need was sent
   * down the escalated path.
   */
  it('does not label the emergency route as a generic blood request', () => {
    const layout = readFileSync(join(SRC, 'components', 'Layout.jsx'), 'utf8')
    expect(layout).not.toMatch(/\{\s*to:\s*'\/emergency',\s*label:\s*'Request blood'\s*\}/)
    expect(layout).toMatch(/to:\s*'\/emergency',\s*label:\s*'Emergency request'/)
  })

  it('labels the emergency entry button as an emergency request', () => {
    const button = readFileSync(
      join(SRC, 'components', 'RequestBloodButton.jsx'),
      'utf8',
    )
    expect(button).toMatch(/children = 'Emergency request'/)
  })
})
