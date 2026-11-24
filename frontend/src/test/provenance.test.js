/**
 * Record provenance.
 *
 * The property under test throughout: a real-world *name* must never make a
 * synthetic *quantity* look credible. The two axes are independent, and the
 * tests below try to make them leak into one another.
 */
import { describe, expect, it } from 'vitest'

import {
  CoordinateSource,
  IdentitySource,
  InventorySource,
  citation,
  coordinateSource,
  describeProvenance,
  identitySource,
  inventorySource,
} from '../components/provenance.js'

describe('identitySource', () => {
  it('reads the seeder’s existing marker as synthetic', () => {
    expect(identitySource({ demoData: true })).toBe(IdentitySource.SYNTHETIC)
  })

  it('honours an explicit public-registry identity', () => {
    expect(identitySource({ dataSource: 'PUBLIC_REGISTRY' })).toBe(
      IdentitySource.PUBLIC_REGISTRY,
    )
  })

  it('lets demoData override a conflicting dataSource rather than trusting the weaker claim', () => {
    // If a record says both things, the demonstration marker wins. Treating a
    // demo record as real is the damaging direction of the two.
    expect(
      identitySource({ demoData: true, dataSource: 'PUBLIC_REGISTRY' }),
    ).toBe(IdentitySource.SYNTHETIC)
  })

  it('is UNKNOWN, never PUBLIC_REGISTRY, with no signal at all', () => {
    expect(identitySource({})).toBe(IdentitySource.UNKNOWN)
    expect(identitySource(undefined)).toBe(IdentitySource.UNKNOWN)
  })

  it('ignores an unrecognised dataSource rather than passing it through', () => {
    expect(identitySource({ dataSource: 'TOTALLY_LEGIT' })).toBe(
      IdentitySource.UNKNOWN,
    )
  })
})

describe('inventorySource', () => {
  it('does not inherit credibility from a real identity', () => {
    // The whole point: a genuine registry listing says the place exists. It
    // says nothing about what is on its shelves.
    const record = { dataSource: 'PUBLIC_REGISTRY' }
    expect(inventorySource(record)).not.toBe(InventorySource.REPORTED_BY_FACILITY)
    expect(inventorySource(record)).toBe(InventorySource.UNKNOWN)
  })

  it('reports synthetic stock for a demonstration record', () => {
    expect(inventorySource({ demoData: true })).toBe(InventorySource.SYNTHETIC)
  })

  it('reports synthetic stock even when the identity is real', () => {
    expect(
      inventorySource({ dataSource: 'PUBLIC_REGISTRY', inventoryDataSource: 'SYNTHETIC' }),
    ).toBe(InventorySource.SYNTHETIC)
  })

  it('honours a genuine facility report', () => {
    expect(inventorySource({ inventoryDataSource: 'REPORTED_BY_FACILITY' })).toBe(
      InventorySource.REPORTED_BY_FACILITY,
    )
  })

  it('is UNKNOWN with no signal', () => {
    expect(inventorySource({})).toBe(InventorySource.UNKNOWN)
  })
})

describe('coordinateSource', () => {
  it.each([
    ['SURVEYED', CoordinateSource.SURVEYED],
    ['GEOCODED_ADDRESS', CoordinateSource.GEOCODED_ADDRESS],
    ['CITY_CENTROID', CoordinateSource.CITY_CENTROID],
  ])('reads %s', (value, expected) => {
    expect(coordinateSource({ coordinateProvenance: value })).toBe(expected)
  })

  it('is UNKNOWN for an absent or unrecognised value', () => {
    expect(coordinateSource({})).toBe(CoordinateSource.UNKNOWN)
    expect(coordinateSource({ coordinateProvenance: 'VIBES' })).toBe(
      CoordinateSource.UNKNOWN,
    )
  })
})

describe('describeProvenance', () => {
  it('always returns both axes, so neither can be rendered alone', () => {
    const described = describeProvenance({ demoData: true })
    expect(described.identity.source).toBe(IdentitySource.SYNTHETIC)
    expect(described.inventory.source).toBe(InventorySource.SYNTHETIC)
    expect(described.identity.label).toBeTruthy()
    expect(described.inventory.label).toBeTruthy()
  })

  it('flags the dangerous combination explicitly', () => {
    const described = describeProvenance({
      dataSource: 'PUBLIC_REGISTRY',
      inventoryDataSource: 'SYNTHETIC',
    })
    expect(described.realNameWithDemoStock).toBe(true)
  })

  it('does not flag a wholly synthetic record as the dangerous combination', () => {
    expect(describeProvenance({ demoData: true }).realNameWithDemoStock).toBe(false)
  })

  it('treats a centroid and an unknown position as approximate', () => {
    expect(
      describeProvenance({ coordinateProvenance: 'CITY_CENTROID' })
        .locationIsApproximate,
    ).toBe(true)
    expect(describeProvenance({}).locationIsApproximate).toBe(true)
  })

  it('treats only a surveyed position as exact', () => {
    expect(
      describeProvenance({ coordinateProvenance: 'SURVEYED' }).locationIsApproximate,
    ).toBe(false)
  })

  it('never describes demonstration stock as real availability', () => {
    const text = describeProvenance({ demoData: true }).inventory.detail.toLowerCase()
    expect(text).toContain('demonstration')
    expect(text).not.toMatch(/\bis available\b/)
  })

  it('states that a registry listing is not an endorsement or a relationship', () => {
    const text = describeProvenance({ dataSource: 'PUBLIC_REGISTRY' }).identity.detail
    expect(text.toLowerCase()).toContain('no relationship')
  })

  it('copes with a record that is entirely empty', () => {
    const described = describeProvenance({})
    expect(described.identity.source).toBe(IdentitySource.UNKNOWN)
    expect(described.inventory.source).toBe(InventorySource.UNKNOWN)
    expect(described.citation).toBeNull()
  })
})

describe('citation', () => {
  it('needs a source name, not just a link', () => {
    expect(citation({ sourceUrl: 'https://example.gov/list.pdf' })).toBeNull()
    expect(citation({})).toBeNull()
  })

  it('returns the name, link and retrieval date', () => {
    expect(
      citation({
        sourceName: 'Punjab State AIDS Control Society — licensed blood centres',
        sourceUrl: 'https://punjabsacs.punjab.gov.in/example.pdf',
        sourceRetrievedOn: '2026-11-24',
      }),
    ).toEqual({
      name: 'Punjab State AIDS Control Society — licensed blood centres',
      url: 'https://punjabsacs.punjab.gov.in/example.pdf',
      retrievedOn: '2026-11-24',
    })
  })

  it('refuses a non-http scheme so a record cannot inject a script URL', () => {
    const result = citation({
      sourceName: 'Somewhere',
      // eslint-disable-next-line no-script-url
      sourceUrl: 'javascript:alert(1)',
    })
    expect(result.url).toBeNull()
    expect(result.name).toBe('Somewhere')
  })

  it('refuses a data URL as well', () => {
    expect(
      citation({ sourceName: 'Somewhere', sourceUrl: 'data:text/html,<script>' }).url,
    ).toBeNull()
  })

  it('treats blank fields as absent rather than empty strings', () => {
    expect(citation({ sourceName: '   ' })).toBeNull()
    expect(
      citation({ sourceName: 'Somewhere', sourceUrl: '  ', sourceRetrievedOn: '  ' }),
    ).toEqual({ name: 'Somewhere', url: null, retrievedOn: null })
  })
})
