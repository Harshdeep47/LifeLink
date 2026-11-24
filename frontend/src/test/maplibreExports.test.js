/**
 * maplibre-gl must expose the constructors the map component uses.
 *
 * This is the regression that produced "The map library could not be loaded,
 * so results are listed instead." The component destructured
 * `{ default: maplibregl }` from a dynamic import, but maplibre-gl v6 removed
 * the default export — so `maplibregl` was undefined and
 * `new maplibregl.Map(...)` threw. The code was written for v4 and broke when
 * the package was upgraded to fix a critical XSS advisory.
 *
 * A browser was not needed to catch this, only a test that imports the real
 * package the same way the component does. That is why one exists now.
 */
import { describe, expect, it } from 'vitest'

describe('maplibre-gl module shape', () => {
  it('resolves a Map constructor the way FacilityMap does', async () => {
    const module = await import('maplibre-gl')
    const maplibregl = module.default ?? module
    expect(typeof maplibregl.Map).toBe('function')
  })

  it('exposes every constructor the map component uses', async () => {
    const module = await import('maplibre-gl')
    const maplibregl = module.default ?? module
    for (const name of ['Map', 'Marker', 'Popup', 'NavigationControl']) {
      expect(typeof maplibregl[name], `${name} must be constructible`).toBe('function')
    }
  })

  it('documents that v6 has no default export', async () => {
    // Pinning the fact that caused the outage. If a future upgrade restores a
    // default export this will fail, and `module.default ?? module` already
    // handles that case — the failure is a prompt to re-read, not a bug.
    const module = await import('maplibre-gl')
    expect(module.default).toBeUndefined()
  })

  it('the old destructuring would have failed', async () => {
    const { default: legacy } = await import('maplibre-gl')
    expect(legacy).toBeUndefined()
    expect(() => new legacy.Map({})).toThrow(TypeError)
  })
})
