/**
 * The MapLibre worker must be a real, emitted asset.
 *
 * The bug: v6 derives its worker URL from `import.meta.url`, expecting
 * `maplibre-gl-worker.mjs` beside the library file. Vite bundles the library
 * into a hashed chunk, so that resolved to `/assets/maplibre-gl-worker.mjs`,
 * which nothing emitted — and the SPA fallback answered the 404 with
 * `index.html`, HTTP 200, `Content-Type: text/html`. The worker got an HTML
 * document and failed to start.
 *
 * It was non-fatal only because the basemap is raster: tiles decode on the
 * main thread, so the map drew with a permanent warning over it.
 *
 * These tests assert the two things that prevent a silent recurrence: the
 * worker resolves to a real URL, and the library still exposes the setter we
 * use to tell it where that is.
 */
import { describe, expect, it } from 'vitest'

describe('maplibre worker wiring', () => {
  it('resolves the worker to a real emitted asset', async () => {
    const { default: workerUrl } = await import(
      'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
    )
    expect(typeof workerUrl).toBe('string')
    expect(workerUrl.length).toBeGreaterThan(0)
    // Must not be the bare path the library would have guessed, which is the
    // one the SPA fallback swallowed.
    expect(workerUrl.endsWith('/assets/maplibre-gl-worker.mjs')).toBe(false)
  })

  it('still exposes setWorkerUrl, which the fix depends on', async () => {
    const module = await import('maplibre-gl')
    const maplibregl = module.default ?? module
    expect(typeof maplibregl.setWorkerUrl).toBe('function')
  })

  it('accepts a worker URL without throwing', async () => {
    const module = await import('maplibre-gl')
    const maplibregl = module.default ?? module
    expect(() => maplibregl.setWorkerUrl('/assets/test-worker.mjs')).not.toThrow()
  })
})
