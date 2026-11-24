/**
 * The data layer behind the map.
 *
 * The map needs WebGL and cannot run in jsdom, but everything that decides
 * *what* it shows is ordinary data transformation — and that is where the
 * mistakes that matter live: a dropped coordinate, a fabricated distance, or
 * unknown availability rendered as zero.
 */
import { describe, expect, it } from 'vitest'

import {
  KIND_CAMP,
  KIND_FACILITY,
  boundsOf,
  campSummary,
  directionsUrl,
  facilitySummary,
  shortLabel,
  toCoordinate,
  toFeatureCollection,
} from '../components/mapData.js'

describe('toCoordinate', () => {
  it('accepts real coordinates as [lon, lat]', () => {
    expect(toCoordinate(30.3398, 76.3869)).toEqual([76.3869, 30.3398])
  })

  it('accepts numeric strings, which stored records sometimes carry', () => {
    expect(toCoordinate('30.3398', '76.3869')).toEqual([76.3869, 30.3398])
  })

  it.each([
    [undefined, undefined],
    [null, null],
    ['', ''],
    ['abc', 'def'],
    [NaN, 10],
    [Infinity, 10],
    [91, 10],
    [-91, 10],
    [10, 181],
    [10, -181],
  ])('rejects unusable input (%s, %s)', (lat, lon) => {
    expect(toCoordinate(lat, lon)).toBeNull()
  })

  it('rejects 0,0, which is nearly always a missing value', () => {
    expect(toCoordinate(0, 0)).toBeNull()
  })

  it('does not reject a genuine zero on one axis only', () => {
    expect(toCoordinate(0, 76.3869)).toEqual([76.3869, 0])
  })
})

describe('facilitySummary', () => {
  it('reports unknown as "Not reported" with no number', () => {
    const text = facilitySummary({ availability: 'UNKNOWN', eligibleUnits: null })
    expect(text).toBe('Not reported')
    expect(text).not.toMatch(/\d/)
  })

  it('treats a missing availability as not reported', () => {
    expect(facilitySummary({})).toBe('Not reported')
  })

  it('distinguishes none-in-stock from not-reported', () => {
    expect(facilitySummary({ availability: 'UNAVAILABLE', eligibleUnits: 0 }))
      .toBe('None in stock')
  })

  it('reports a count when units are known', () => {
    expect(facilitySummary({ availability: 'AVAILABLE', eligibleUnits: 9 }))
      .toBe('9 units')
  })

  it('uses the singular for one unit', () => {
    expect(facilitySummary({ availability: 'AVAILABLE', eligibleUnits: 1 }))
      .toBe('1 unit')
  })

  it('marks a partial match as partial', () => {
    expect(facilitySummary({ availability: 'PARTIAL', eligibleUnits: 2 }))
      .toBe('Partial — 2 units')
  })

  it('separates not-stocked from both zero and unknown', () => {
    expect(facilitySummary({ availability: 'NOT_STOCKED' })).toBe('Not stocked')
  })
})

describe('campSummary', () => {
  it('reports registrations without calling them attendance', () => {
    const text = campSummary({ status: 'UPCOMING', capacity: 150, registeredCount: 40 })
    expect(text).toContain('40/150 registered')
    expect(text).toContain('110 places left')
    expect(text.toLowerCase()).not.toContain('attend')
    expect(text.toLowerCase()).not.toContain('popular')
    expect(text.toLowerCase()).not.toContain('donat')
  })

  it('says full rather than showing negative places', () => {
    const text = campSummary({ status: 'ONGOING', capacity: 10, registeredCount: 12 })
    expect(text).toContain('full')
    expect(text).not.toContain('-2')
  })

  it('copes with a camp that has no capacity figures', () => {
    expect(campSummary({ status: 'UPCOMING' })).toBe('upcoming')
  })
})

describe('toFeatureCollection', () => {
  const facility = {
    facilityId: 'fac-1',
    name: 'Rajindra Civil Blood Centre (DEMO)',
    city: 'Patiala',
    latitude: 30.3556,
    longitude: 76.3535,
    straightLineKm: 3.65,
    availability: 'PARTIAL',
    eligibleUnits: 1,
    freshness: 'FRESH',
    verificationStatus: 'VERIFIED',
  }
  const camp = {
    campId: 'camp-1',
    name: 'Thapar Campus Drive (DEMO)',
    city: 'Patiala',
    latitude: 30.3389,
    longitude: 76.38,
    straightLineKm: 0.67,
    status: 'UPCOMING',
    capacity: 180,
    registeredCount: 12,
  }

  it('builds one feature per record', () => {
    const { collection } = toFeatureCollection({ facilities: [facility], camps: [camp] })
    expect(collection.type).toBe('FeatureCollection')
    expect(collection.features).toHaveLength(2)
  })

  it('keeps blood banks and camps distinguishable', () => {
    const { collection } = toFeatureCollection({ facilities: [facility], camps: [camp] })
    const kinds = collection.features.map((f) => f.properties.kind)
    expect(kinds).toContain(KIND_FACILITY)
    expect(kinds).toContain(KIND_CAMP)
  })

  it('uses the stored coordinates unchanged', () => {
    const { collection } = toFeatureCollection({ facilities: [facility] })
    expect(collection.features[0].geometry.coordinates).toEqual([76.3535, 30.3556])
  })

  it('drops records without usable coordinates and counts them', () => {
    const { collection, skipped } = toFeatureCollection({
      facilities: [facility, { facilityId: 'bad', name: 'No coords' }],
      camps: [{ campId: 'bad-camp', name: 'Nowhere', latitude: 0, longitude: 0 }],
    })
    expect(collection.features).toHaveLength(1)
    expect(skipped).toBe(2)
  })

  it('never invents a distance', () => {
    const { collection } = toFeatureCollection({
      facilities: [{ ...facility, straightLineKm: undefined }],
    })
    expect(collection.features[0].properties.km).toBeNull()
  })

  it('handles empty input', () => {
    const { collection, skipped } = toFeatureCollection({})
    expect(collection.features).toEqual([])
    expect(skipped).toBe(0)
  })
})

describe('boundsOf', () => {
  const at = (lon, lat) => ({ geometry: { coordinates: [lon, lat] } })

  it('returns null for nothing', () => {
    expect(boundsOf([])).toBeNull()
    expect(boundsOf(undefined)).toBeNull()
  })

  it('encloses every point', () => {
    const bounds = boundsOf([at(76.3, 30.3), at(76.8, 30.7)])
    expect(bounds).toEqual([[76.3, 30.3], [76.8, 30.7]])
  })

  it('pads a single point so the map does not zoom to maximum', () => {
    const [[west, south], [east, north]] = boundsOf([at(76.3869, 30.3398)])
    expect(east).toBeGreaterThan(west)
    expect(north).toBeGreaterThan(south)
  })
})

describe('directionsUrl', () => {
  const destination = { latitude: 30.3556, longitude: 76.3535 }

  it('uses the stored coordinates of the destination', () => {
    const url = directionsUrl({ destination })
    expect(url).toContain('destination=30.3556%2C76.3535')
  })

  it('includes an origin when one is genuinely known', () => {
    const url = directionsUrl({
      destination,
      origin: { latitude: 30.33, longitude: 76.38 },
    })
    expect(url).toContain('origin=30.33%2C76.38')
  })

  it('omits the origin rather than inventing one', () => {
    expect(directionsUrl({ destination })).not.toContain('origin=')
  })

  it('returns null for an unusable destination', () => {
    expect(directionsUrl({ destination: {} })).toBeNull()
    expect(directionsUrl({})).toBeNull()
  })
})

describe('shortLabel', () => {
  it('leaves a short name alone', () => {
    expect(shortLabel('Mohali Centre')).toBe('Mohali Centre')
  })

  it('truncates a long name instead of wrapping it', () => {
    const label = shortLabel('Rajindra Civil Blood Centre (DEMO)')
    expect(label.length).toBeLessThanOrEqual(22)
    expect(label.endsWith('…')).toBe(true)
  })

  it('copes with a missing name', () => {
    expect(shortLabel(undefined)).toBe('')
  })
})
