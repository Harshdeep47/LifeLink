/**
 * Where a facility record came from, and how precisely it is placed.
 *
 * ## Why this exists
 *
 * Every facility in LifeLink today is invented, and the interface says so with
 * a single "Synthetic record" pill. That is adequate while *everything* is
 * synthetic. It stops being adequate the moment any real institution is added,
 * because one pill cannot answer two separate questions that have different
 * answers:
 *
 * 1. **Is this a real place?** — the identity axis.
 * 2. **Is this stock real?** — the inventory axis.
 *
 * A real blood centre carrying demonstration stock is *more* dangerous than a
 * wholly invented one, not less: an invented name invites nobody to act, while
 * a real name beside "9 units O-negative" invites someone to drive there. So
 * the two axes are tracked and displayed separately, and a real identity never
 * silently upgrades the credibility of a synthetic figure.
 *
 * A third axis matters for the map:
 *
 * 3. **How precisely is it placed?** — a city centroid is not an address. The
 *    project already places synthetic facilities at real city centroids, and a
 *    centroid presented as a street location is a quiet falsehood that reads
 *    as precision.
 *
 * ## Fail closed
 *
 * Absent fields resolve to the *least* confident answer, never the most. A
 * record with no `dataSource` is reported as unverified provenance rather than
 * assumed real, for the same reason unreported stock is "Not reported" rather
 * than zero.
 */

/** Identity provenance: where the facility's name and address came from. */
export const IdentitySource = Object.freeze({
  SYNTHETIC: 'SYNTHETIC',
  PUBLIC_REGISTRY: 'PUBLIC_REGISTRY',
  UNKNOWN: 'UNKNOWN',
})

/** Stock provenance: where the quantities came from. */
export const InventorySource = Object.freeze({
  SYNTHETIC: 'SYNTHETIC',
  REPORTED_BY_FACILITY: 'REPORTED_BY_FACILITY',
  UNKNOWN: 'UNKNOWN',
})

/** Positional provenance: how the coordinates were obtained. */
export const CoordinateSource = Object.freeze({
  SURVEYED: 'SURVEYED',
  GEOCODED_ADDRESS: 'GEOCODED_ADDRESS',
  CITY_CENTROID: 'CITY_CENTROID',
  UNKNOWN: 'UNKNOWN',
})

function known(value, allowed) {
  return typeof value === 'string' && allowed.includes(value) ? value : null
}

/**
 * Identity provenance for a record.
 *
 * `demoData: true` is authoritative for synthetic, because it is the marker
 * the seeder already writes and it predates these fields. Without any signal
 * the answer is UNKNOWN, not PUBLIC_REGISTRY.
 */
export function identitySource(record) {
  const explicit = known(record?.dataSource, [
    IdentitySource.SYNTHETIC,
    IdentitySource.PUBLIC_REGISTRY,
  ])
  if (record?.demoData === true) return IdentitySource.SYNTHETIC
  if (explicit) return explicit
  return IdentitySource.UNKNOWN
}

/**
 * Stock provenance.
 *
 * Deliberately does **not** inherit from the identity axis. A record read from
 * a public registry tells us the place exists; it says nothing at all about
 * what is on its shelves today. Inheriting here is the exact mistake this
 * module exists to prevent, so a real identity with no inventory provenance
 * reports SYNTHETIC when the record is demonstration data and UNKNOWN
 * otherwise — never REPORTED_BY_FACILITY by default.
 */
export function inventorySource(record) {
  const explicit = known(record?.inventoryDataSource, [
    InventorySource.SYNTHETIC,
    InventorySource.REPORTED_BY_FACILITY,
  ])
  if (explicit) return explicit
  if (record?.demoData === true) return InventorySource.SYNTHETIC
  return InventorySource.UNKNOWN
}

export function coordinateSource(record) {
  return (
    known(record?.coordinateProvenance, [
      CoordinateSource.SURVEYED,
      CoordinateSource.GEOCODED_ADDRESS,
      CoordinateSource.CITY_CENTROID,
    ]) ?? CoordinateSource.UNKNOWN
  )
}

const IDENTITY_TEXT = {
  [IdentitySource.SYNTHETIC]: {
    label: 'Synthetic record',
    tone: 'danger',
    detail: 'This institution is invented for demonstration. No real organisation is represented.',
  },
  [IdentitySource.PUBLIC_REGISTRY]: {
    label: 'Listed in a public registry',
    tone: 'info',
    detail:
      'The name and address come from a published public listing. LifeLink has no relationship with this institution and does not act on its behalf.',
  },
  [IdentitySource.UNKNOWN]: {
    label: 'Unverified provenance',
    tone: 'neutral',
    detail: 'This record does not say where its details came from. Treat it as unverified.',
  },
}

const INVENTORY_TEXT = {
  [InventorySource.SYNTHETIC]: {
    label: 'Demonstration stock',
    tone: 'danger',
    detail:
      'Quantities, expiry dates and availability here are generated for demonstration. They are not this facility’s real stock.',
  },
  [InventorySource.REPORTED_BY_FACILITY]: {
    label: 'Reported by the facility',
    tone: 'info',
    detail:
      'Quantities were submitted by the facility. They are a report at a point in time, not a live count, and nothing is held for you.',
  },
  [InventorySource.UNKNOWN]: {
    label: 'Stock provenance unknown',
    tone: 'neutral',
    detail: 'This record does not say where its quantities came from. Do not rely on them.',
  },
}

const COORDINATE_TEXT = {
  [CoordinateSource.SURVEYED]: 'Location is the facility’s own recorded position.',
  [CoordinateSource.GEOCODED_ADDRESS]:
    'Location was derived from the published address and may be off by some distance.',
  [CoordinateSource.CITY_CENTROID]:
    'Location is the centre of the town, not the facility’s address. Distances are indicative only.',
  [CoordinateSource.UNKNOWN]: 'How this location was obtained is not recorded.',
}

/**
 * Everything the interface needs to describe a record honestly.
 *
 * Returns both axes always, so a caller cannot accidentally render one and
 * omit the other — which would reproduce the problem of a real name standing
 * beside an unlabelled figure.
 */
export function describeProvenance(record) {
  const identity = identitySource(record)
  const inventory = inventorySource(record)
  const coordinates = coordinateSource(record)
  return {
    identity: { source: identity, ...IDENTITY_TEXT[identity] },
    inventory: { source: inventory, ...INVENTORY_TEXT[inventory] },
    coordinates: { source: coordinates, detail: COORDINATE_TEXT[coordinates] },
    /** True when the location should not be read as a street address. */
    locationIsApproximate:
      coordinates === CoordinateSource.CITY_CENTROID ||
      coordinates === CoordinateSource.GEOCODED_ADDRESS ||
      coordinates === CoordinateSource.UNKNOWN,
    /** True when a real-world name sits beside demonstration figures. */
    realNameWithDemoStock:
      identity === IdentitySource.PUBLIC_REGISTRY &&
      inventory === InventorySource.SYNTHETIC,
    citation: citation(record),
  }
}

/**
 * A displayable citation, or null.
 *
 * Returns null unless there is a source *name* to show. A bare URL is not a
 * citation a reader can judge, and showing one would imply more verification
 * than a link provides.
 */
export function citation(record) {
  const name = typeof record?.sourceName === 'string' ? record.sourceName.trim() : ''
  if (!name) return null
  const url = typeof record?.sourceUrl === 'string' ? record.sourceUrl.trim() : ''
  const retrieved =
    typeof record?.sourceRetrievedOn === 'string' ? record.sourceRetrievedOn.trim() : ''
  return {
    name,
    // Only http(s) links are offered, so a record cannot inject a
    // javascript: or data: URL into an anchor.
    url: /^https?:\/\//i.test(url) ? url : null,
    retrievedOn: retrieved || null,
  }
}
