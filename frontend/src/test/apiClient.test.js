/**
 * API client tests.
 *
 * The client is the single place that turns HTTP into application errors, so
 * these cover the translations every screen depends on: auth failures, network
 * failures, retryability, and the header contract.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, setTokenProvider } from '../api/client.js'

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

describe('ApiError', () => {
  it('treats 5xx as retryable', () => {
    expect(new ApiError('boom', { status: 500 }).isRetryable).toBe(true)
  })

  it('treats a network failure as retryable', () => {
    expect(new ApiError('offline', { code: 'NETWORK_ERROR', status: 0 }).isRetryable).toBe(true)
  })

  it('treats a concurrent modification as retryable', () => {
    const error = new ApiError('conflict', { code: 'CONCURRENT_MODIFICATION', status: 409 })
    expect(error.isRetryable).toBe(true)
  })

  it('does not treat a validation error as retryable', () => {
    expect(new ApiError('bad', { code: 'VALIDATION_ERROR', status: 400 }).isRetryable).toBe(false)
  })

  it('identifies auth failures so the session can be cleared', () => {
    expect(new ApiError('nope', { status: 401 }).isAuthError).toBe(true)
    expect(new ApiError('nope', { code: 'UNAUTHENTICATED' }).isAuthError).toBe(true)
    expect(new ApiError('nope', { status: 403 }).isAuthError).toBe(false)
  })
})

describe('api client', () => {
  beforeEach(() => {
    setTokenProvider(() => null)
    globalThis.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('unwraps the data envelope', async () => {
    globalThis.fetch.mockResolvedValue(jsonResponse({ data: { status: 'ok' } }))
    await expect(api.health()).resolves.toEqual({ status: 'ok' })
  })

  it('sends a correlation id on every request', async () => {
    globalThis.fetch.mockResolvedValue(jsonResponse({ data: {} }))
    await api.health()
    const [, init] = globalThis.fetch.mock.calls[0]
    expect(init.headers['X-Correlation-Id']).toMatch(/^web-/)
  })

  it('attaches a bearer token when one is available', async () => {
    setTokenProvider(() => 'test-token')
    globalThis.fetch.mockResolvedValue(jsonResponse({ data: {} }))
    await api.me()
    const [, init] = globalThis.fetch.mock.calls[0]
    expect(init.headers.Authorization).toBe('Bearer test-token')
  })

  it('omits the Authorization header when signed out', async () => {
    globalThis.fetch.mockResolvedValue(jsonResponse({ data: {} }))
    await api.health()
    const [, init] = globalThis.fetch.mock.calls[0]
    expect(init.headers.Authorization).toBeUndefined()
  })

  it('sends an idempotency key for request creation', async () => {
    globalThis.fetch.mockResolvedValue(jsonResponse({ data: {} }))
    await api.createEmergencyRequest({ bloodGroup: 'O-' }, 'key-123')
    const [, init] = globalThis.fetch.mock.calls[0]
    expect(init.headers['Idempotency-Key']).toBe('key-123')
  })

  it('omits empty query parameters instead of sending blanks', async () => {
    globalThis.fetch.mockResolvedValue(jsonResponse({ data: {} }))
    await api.searchFacilities({ lat: 30.3, lon: 76.4, bloodGroup: undefined, component: '' })
    const [url] = globalThis.fetch.mock.calls[0]
    expect(url).toContain('lat=30.3')
    expect(url).not.toContain('bloodGroup')
    expect(url).not.toContain('component')
  })

  it('translates a backend error envelope into ApiError', async () => {
    globalThis.fetch.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'CROSS_ORGANIZATION_DENIED',
            message: 'this resource belongs to another organization',
          },
          correlationId: 'corr-1',
        },
        { status: 403 },
      ),
    )

    await expect(api.getFacility('fac-1')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'CROSS_ORGANIZATION_DENIED',
      status: 403,
      correlationId: 'corr-1',
    })
  })

  it('preserves error details so forms can show the broken rule', async () => {
    globalThis.fetch.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'stale update rejected',
            details: { rule: 'STALE_UPDATE_REJECTED' },
          },
        },
        { status: 400 },
      ),
    )

    await expect(api.getFacility('fac-1')).rejects.toMatchObject({
      details: { rule: 'STALE_UPDATE_REJECTED' },
    })
  })

  it('turns a fetch rejection into a readable network error', async () => {
    globalThis.fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(api.health()).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      status: 0,
    })
    // The message must be for a user, not an echo of the fetch internal.
    await expect(api.health()).rejects.toThrow(/Could not reach LifeLink/)
  })

  it('rethrows an abort so a superseded request is silently dropped', async () => {
    const abort = new Error('aborted')
    abort.name = 'AbortError'
    globalThis.fetch.mockRejectedValue(abort)
    await expect(api.health()).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('returns null for 204 No Content', async () => {
    globalThis.fetch.mockResolvedValue({ ok: true, status: 204, text: () => Promise.resolve('') })
    await expect(api.cancelAlert('a-1')).resolves.toBeNull()
  })

  it('reports an unreadable body rather than crashing', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve('<html>not json</html>'),
    })
    await expect(api.health()).rejects.toMatchObject({ code: 'MALFORMED_RESPONSE' })
  })

  it('returns items and meta for paginated endpoints', async () => {
    globalThis.fetch.mockResolvedValue(
      jsonResponse({ data: [{ batchId: 'b1' }], meta: { count: 1, nextCursor: 'abc' } }),
    )
    await expect(api.listBatches('fac-1')).resolves.toEqual({
      items: [{ batchId: 'b1' }],
      meta: { count: 1, nextCursor: 'abc' },
    })
  })
})
