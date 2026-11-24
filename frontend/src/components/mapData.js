/**
 * Pure helpers behind the map: GeoJSON construction, bounds, labels and
 * directions links.
 *
 * Separated from the component so they can be tested without a browser. The
 * map itself needs WebGL and cannot run in jsdom, but everything that decides
 * *what* the map shows is ordinary data transformation — and that is where the
 * mistakes with consequences live: a dropped coordinate, a fabricated
 * distance, an availability misread as zero.
 */

/** Blood banks and camps are different things and stay distinguishable. */
export const KIND_FACILITY = 'facility'
export const KIND_CAMP = 'camp'

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

/**
 * A coordinate pair, or null.
 *
 * Accepts strings because stored records sometimes carry them, but refuses
 * anything that is not a real finite number in range. A marker at a
 * nonsensical coordinate is worse than a missing marker: it looks like data.
 */
export function toCoordinate(latitude, longitude) {
  const lat = typeof latitude === 'string' ? Number(latitude) : latitude
  const lon = typeof longitude === 'string' ? Number(longitude) : longitude
  if (!isFiniteNumber(lat) || !isFiniteNumber(lon)) return null
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null
  // 0,0 is in the Gulf of Guinea and is almost always a missing value that
  // survived as a default.
  if (lat === 0 && lon === 0) return null
  return [lon, lat]
}

/** Short label for a marker. Long names are truncated, never wrapped. */
export function shortLabel(name, max = 22) {
  const text = String(name ?? '').trim()
  if (text.length <= max) return text
  return `${text.slice(0, max - 1).trimEnd()}…`
}

/**
 * One line summarising a blood bank's availability.
 *
 * `UNKNOWN` is reported as "Not reported" with no number. A facility that has
 * never reported is not a facility with zero units, and the two lead to
 * opposite actions.
 */
export function facilitySummary(facility) {
  const state = facility?.availability
  if (!state || state === 'UNKNOWN') return 'Not reported'
  if (state === 'NOT_STOCKED') return 'Not stocked'
  const units = facility?.eligibleUnits
  if (state === 'UNAVAILABLE' || units === 0) return 'None in stock'
  if (units === null || units === undefined) return state.toLowerCase()
  const plural = units === 1 ? 'unit' : 'units'
  return `${state === 'PARTIAL' ? 'Partial — ' : ''}${units} ${plural}`
}

/** One line summarising a camp. Registrations are never called attendance. */
export function campSummary(camp) {
  const bits = []
  if (camp?.status) bits.push(String(camp.status).toLowerCase())
  const capacity = Number(camp?.capacity)
  const registered = Number(camp?.registeredCount)
  if (Number.isFinite(capacity) && Number.isFinite(registered)) {
    const left = Math.max(0, capacity - registered)
    bits.push(`${registered}/${capacity} registered`)
    bits.push(left > 0 ? `${left} places left` : 'full')
  }
  return bits.join(' · ')
}

/**
 * Build the clustering source's data from the records on screen.
 *
 * Anything without a usable coordinate is dropped and counted, so the caller
 * can say "2 of 8 could not be placed" instead of silently showing fewer
 * markers than results.
 */
export function toFeatureCollection({ facilities = [], camps = [] } = {}) {
  const features = []
  let skipped = 0

  for (const facility of facilities) {
    const coordinates = toCoordinate(facility?.latitude, facility?.longitude)
    if (!coordinates) {
      skipped += 1
      continue
    }
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates },
      properties: {
        id: facility.facilityId,
        kind: KIND_FACILITY,
        name: facility.name ?? 'Blood bank',
        city: facility.city ?? '',
        km: isFiniteNumber(facility.straightLineKm) ? facility.straightLineKm : null,
        summary: facilitySummary(facility),
        availability: facility.availability ?? 'UNKNOWN',
        freshness: facility.freshness ?? 'UNKNOWN',
        verification: facility.verificationStatus ?? 'UNVERIFIED',
        lat: coordinates[1],
        lon: coordinates[0],
      },
    })
  }

  for (const camp of camps) {
    const coordinates = toCoordinate(camp?.latitude, camp?.longitude)
    if (!coordinates) {
      skipped += 1
      continue
    }
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates },
      properties: {
        id: camp.campId,
        kind: KIND_CAMP,
        name: camp.name ?? 'Donation camp',
        city: camp.city ?? '',
        km: isFiniteNumber(camp.straightLineKm) ? camp.straightLineKm : null,
        summary: campSummary(camp),
        status: camp.status ?? '',
        startsAt: camp.startsAt ?? '',
        lat: coordinates[1],
        lon: coordinates[0],
      },
    })
  }

  return { collection: { type: 'FeatureCollection', features }, skipped }
}

/**
 * Bounding box of a feature collection, padded slightly.
 *
 * Returns null for an empty set, and for a single point returns a small box
 * around it — fitting to a zero-area box makes MapLibre zoom to its maximum,
 * which lands the user in a featureless close-up.
 */
export function boundsOf(features, { padDegrees = 0.01 } = {}) {
  if (!features?.length) return null
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity
  for (const feature of features) {
    const [lon, lat] = feature.geometry.coordinates
    west = Math.min(west, lon)
    east = Math.max(east, lon)
    south = Math.min(south, lat)
    north = Math.max(north, lat)
  }
  if (west === east && south === north) {
    return [
      [west - padDegrees, south - padDegrees],
      [east + padDegrees, north + padDegrees],
    ]
  }
  return [[west, south], [east, north]]
}

/**
 * External navigation link to a destination's stored coordinates.
 *
 * Uses Google Maps directions with the real latitude and longitude. An origin
 * is included only when one is genuinely known — GPS, or a place the user
 * chose. With no origin, Google uses the device's own location, which is
 * better than asserting one we do not have.
 *
 * This opens an external route; LifeLink itself still reports straight-line
 * distance and never claims to have computed a road route.
 */
export function directionsUrl({ destination, origin } = {}) {
  const coordinates = toCoordinate(destination?.latitude, destination?.longitude)
  if (!coordinates) return null
  const [lon, lat] = coordinates
  const params = new URLSearchParams({
    api: '1',
    destination: `${lat},${lon}`,
  })
  const from = toCoordinate(origin?.latitude, origin?.longitude)
  if (from) params.set('origin', `${from[1]},${from[0]}`)
  return `https://www.google.com/maps/dir/?${params.toString()}`
}
