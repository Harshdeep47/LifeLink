/**
 * Tests for post-sign-in redirect validation.
 *
 * The attack these prevent: a victim is sent to `https://app.example//evil.com`,
 * is asked to sign in, and on success is redirected off-site to a page that
 * looks like the application and asks for their credentials again.
 *
 * Almost every case here is a rejection. The two acceptance tests exist so that
 * a future tightening of the rule cannot quietly break legitimate navigation.
 */
import { describe, expect, it } from 'vitest'

import { DEFAULT_REDIRECT, safeInternalPath } from '../auth/redirect.js'

describe('safeInternalPath', () => {
  describe('accepts genuine internal paths', () => {
    const allowed = [
      '/',
      '/find-blood',
      '/facilities/fac-patiala-1',
      '/camps/demo-camp-0001',
      '/emergency/01JD7Q2X',
      '/find-blood?bloodGroup=O-&radiusKm=30',
      '/facilities/fac-1#availability',
      '/me/donations',
    ]
    it.each(allowed)('keeps %s', (path) => {
      expect(safeInternalPath(path)).toBe(path)
    })
  })

  describe('rejects protocol-relative URLs', () => {
    // The specific variant our own sign-in flow was exposed to.
    const rejected = ['//evil.com', '//evil.com/path', '///evil.com', '//']
    it.each(rejected)('rejects %s', (path) => {
      expect(safeInternalPath(path)).toBe(DEFAULT_REDIRECT)
    })
  })

  describe('rejects backslash variants', () => {
    // Several browsers normalise backslashes to forward slashes, so these
    // become protocol-relative after the check a naive implementation makes.
    const rejected = ['/\\evil.com', '/\\/evil.com', '\\\\evil.com', '/path\\evil']
    it.each(rejected)('rejects %s', (path) => {
      expect(safeInternalPath(path)).toBe(DEFAULT_REDIRECT)
    })
  })

  describe('rejects absolute URLs and schemes', () => {
    const rejected = [
      'https://evil.com',
      'http://evil.com',
      'javascript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      '/javascript:alert(1)',
      '//javascript:alert(1)',
      'mailto:someone@example.com',
      'about:blank',
    ]
    it.each(rejected)('rejects %s', (path) => {
      expect(safeInternalPath(path)).toBe(DEFAULT_REDIRECT)
    })
  })

  describe('rejects control-character smuggling', () => {
    // Tab and newline inside a scheme are stripped by browsers, turning
    // `/\tjavascript:` into something executable.
    const rejected = ['/\tjavascript:alert(1)', '/\njavascript:alert(1)', '/\u0000', '/a\u007f']
    it.each(rejected)('rejects a control-character payload', (path) => {
      expect(safeInternalPath(path)).toBe(DEFAULT_REDIRECT)
    })
  })

  describe('rejects relative and unrooted paths', () => {
    const rejected = ['find-blood', '../admin', './x', 'evil.com']
    it.each(rejected)('rejects %s', (path) => {
      expect(safeInternalPath(path)).toBe(DEFAULT_REDIRECT)
    })
  })

  describe('rejects non-strings and empties', () => {
    const rejected = [undefined, null, '', '   ', 42, {}, [], true, (() => {})]
    it.each(rejected)('rejects %s', (value) => {
      expect(safeInternalPath(value)).toBe(DEFAULT_REDIRECT)
    })
  })

  it('does not throw on any input', () => {
    // A validator that throws on a hostile input is itself a denial of service
    // on the sign-in page.
    const nasty = [Symbol.iterator, new Map(), NaN, Infinity, -0]
    for (const value of nasty) {
      expect(() => safeInternalPath(value)).not.toThrow()
    }
  })

  it('trims surrounding whitespace rather than rejecting a valid path', () => {
    expect(safeInternalPath('  /find-blood  ')).toBe('/find-blood')
  })

  it('rejects whitespace-padded hostile input too', () => {
    expect(safeInternalPath('  //evil.com  ')).toBe(DEFAULT_REDIRECT)
  })
})
