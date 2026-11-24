/**
 * Find blood: the application's primary screen.
 *
 * Design decisions that matter here:
 *
 * - Location is never forced. Browser geolocation is offered, but typing a
 *   place name works just as well, and declining permission is a first-class
 *   path rather than a dead end.
 * - Availability, freshness and verification are shown as three separate
 *   signals on every row. A user deciding whether to drive somewhere needs all
 *   three, and collapsing them into one "score" badge would hide the thing
 *   that matters most.
 * - A facility that has reported nothing shows "Not reported", visually
 *   distinct from "None in stock".
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../../api/client.js'
import { useApiData, useDebounced, useGeolocation } from '../../hooks/useApi.js'
import {
  AsyncState,
  Button,
  Card,
  Field,
  NotAReservationNotice,
  Notice,
} from '../../components/ui.jsx'
import { AvailabilityBadge, DataQuality } from '../../components/StatusBadges.jsx'
import { FacilityMap } from '../../components/FacilityMap.jsx'
import { OriginIndicator } from '../../components/OriginIndicator.jsx'
import { directionsUrl } from '../../components/mapData.js'
import { RequestBloodButton } from '../../components/RequestBloodButton.jsx'
import './FindBloodPage.css'

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const COMPONENTS = [
  { value: 'PRBC', label: 'Packed red blood cells (PRBC)' },
  { value: 'WHOLE_BLOOD', label: 'Whole blood' },
  { value: 'FFP', label: 'Fresh frozen plasma (FFP)' },
  { value: 'PLATELETS', label: 'Platelets' },
]
const RADII = [5, 10, 20, 30, 50, 100]

// Patiala, the centre of the demo geography.
const DEFAULT_ORIGIN = { latitude: 30.3398, longitude: 76.3869 }

export function FindBloodPage() {
  const [origin, setOrigin] = useState(DEFAULT_ORIGIN)
  // Provenance, not decoration: 'default' must never be presented as the
  // user's location. See components/OriginIndicator.jsx.
  const [originSource, setOriginSource] = useState('default')
  const [originLabel, setOriginLabel] = useState('Default search location')
  const [placeQuery, setPlaceQuery] = useState('')
  const [bloodGroup, setBloodGroup] = useState('O-')
  const [component, setComponent] = useState('PRBC')
  const [units, setUnits] = useState(2)
  const [radiusKm, setRadiusKm] = useState(20)
  const [onlyAvailable, setOnlyAvailable] = useState(false)
  const [verifiedOnly, setVerifiedOnly] = useState(false)
  const [selectedId, setSelectedId] = useState(null)

  const geo = useGeolocation()
  const navigate = useNavigate()
  const [sortBy, setSortBy] = useState('recommended')

  // Camps for the same origin, so the map answers "where can I give blood?"
  // alongside "where can I get it?". Failure here must not affect the blood
  // search, so the result is read defensively and never surfaced as an error.
  const { data: campData } = useApiData(
    (signal) =>
      api.searchCamps(
        { lat: origin.latitude, lon: origin.longitude, radiusKm: Math.min(radiusKm, 20) },
        signal,
      ),
    [origin.latitude, origin.longitude, radiusKm],
  )
  const nearbyCamps = campData?.results ?? []
  const debouncedPlace = useDebounced(placeQuery, 400)

  // Adopt a browser-provided position when one arrives. This runs in an effect
  // rather than during render: setting state while rendering would re-enter the
  // component on every pass and loop.
  useEffect(() => {
    // Only adopt coordinates that actually arrived. A denied or failed
    // lookup leaves the origin exactly as it was, and the indicator keeps
    // saying 'default' rather than implying a fix was obtained.
    if (geo.status === 'granted' && geo.coords) {
      setOrigin(geo.coords)
      setOriginSource('gps')
      setOriginLabel('Your current location')
    }
  }, [geo.status, geo.coords])

  const { data: places } = useApiData(
    (signal) => api.geocode({ q: debouncedPlace, limit: 5 }, signal),
    [debouncedPlace],
    { enabled: debouncedPlace.trim().length >= 2 },
  )

  const { data: results, loading, error, reload } = useApiData(
    (signal) =>
      api.searchFacilities(
        {
          lat: origin.latitude,
          lon: origin.longitude,
          radiusKm,
          bloodGroup,
          component,
          units,
          onlyAvailable: onlyAvailable ? 'true' : undefined,
          verifiedOnly: verifiedOnly ? 'true' : undefined,
          limit: 50,
        },
        signal,
      ),
    [origin.latitude, origin.longitude, radiusKm, bloodGroup, component, units, onlyAvailable, verifiedOnly],
  )

  const choosePlace = useCallback((place) => {
    setOrigin({ latitude: place.latitude, longitude: place.longitude })
    setOriginSource('manual')
    setOriginLabel(place.label)
    setPlaceQuery('')
  }, [])

  const rawFacilities = results?.results ?? []

  /**
   * Which result is nearest, and in what order to show them.
   *
   * "Nearest" is computed from the distance the API returned for each
   * facility, never from the order rows arrived in — and only among results
   * that could actually supply blood. A facility 200 m away with nothing in
   * stock is not the nearest *useful* option, and labelling it "Nearest"
   * would send someone to the wrong place.
   *
   * UNKNOWN is deliberately eligible for the badge: a facility that has never
   * reported may well have stock, and the whole point of showing UNKNOWN
   * rather than zero is that it is worth a phone call. It is ranked below a
   * confirmed match, but it is not excluded.
   */
  const facilities = useMemo(() => {
    const list = [...rawFacilities]
    if (sortBy === 'distance') {
      list.sort((a, b) => (a.straightLineKm ?? Infinity) - (b.straightLineKm ?? Infinity))
    } else if (sortBy === 'availability') {
      const rank = { AVAILABLE: 0, PARTIAL: 1, UNKNOWN: 2, UNAVAILABLE: 3, NOT_STOCKED: 4 }
      list.sort((a, b) => {
        const byState = (rank[a.availability] ?? 9) - (rank[b.availability] ?? 9)
        // Ties broken by distance, so equal availability still reads nearest
        // first rather than in arbitrary order.
        return byState !== 0
          ? byState
          : (a.straightLineKm ?? Infinity) - (b.straightLineKm ?? Infinity)
      })
    }
    // 'recommended' keeps the backend's ranking, which weighs availability,
    // quantity, freshness, verification and distance together.
    return list
  }, [rawFacilities, sortBy])

  const nearestUsefulId = useMemo(() => {
    const usable = rawFacilities.filter(
      (f) =>
        typeof f.straightLineKm === 'number' &&
        ['AVAILABLE', 'PARTIAL', 'UNKNOWN'].includes(f.availability),
    )
    if (usable.length === 0) return null
    return usable.reduce((best, f) =>
      f.straightLineKm < best.straightLineKm ? f : best,
    ).facilityId
  }, [rawFacilities])

  return (
    <div className="find">
      <header className="page-header">
        <h1>Find blood</h1>
        <p>
          Search nearby facilities by blood group and component. Every result
          shows how recently the facility updated its stock and whether anyone
          has independently verified it.
        </p>
      </header>

      <NotAReservationNotice />

      <div className="find__layout">
        <aside className="find__filters">
          <Card title="Search">
            <Field label="Blood group" htmlFor="bloodGroup" required>
              {({ id }) => (
                <select id={id} value={bloodGroup} onChange={(e) => setBloodGroup(e.target.value)}>
                  {BLOOD_GROUPS.map((group) => (
                    <option key={group} value={group}>{group}</option>
                  ))}
                </select>
              )}
            </Field>

            <Field label="Component" htmlFor="component" required>
              {({ id }) => (
                <select id={id} value={component} onChange={(e) => setComponent(e.target.value)}>
                  {COMPONENTS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              )}
            </Field>

            <Field
              label="Units needed"
              htmlFor="units"
              hint="Used to decide whether a facility shows as fully or partially available."
            >
              {({ id, describedBy }) => (
                <input
                  id={id}
                  aria-describedby={describedBy}
                  type="number"
                  min="1"
                  max="50"
                  value={units}
                  onChange={(e) => setUnits(Math.max(1, Number(e.target.value) || 1))}
                />
              )}
            </Field>

            <Field label="Search radius" htmlFor="radius">
              {({ id }) => (
                <select id={id} value={radiusKm} onChange={(e) => setRadiusKm(Number(e.target.value))}>
                  {RADII.map((r) => (
                    <option key={r} value={r}>{r} km</option>
                  ))}
                </select>
              )}
            </Field>

            <fieldset className="find__checks">
              <legend className="field__label">Filters</legend>
              <label className="find__check">
                <input
                  type="checkbox"
                  checked={onlyAvailable}
                  onChange={(e) => setOnlyAvailable(e.target.checked)}
                />
                <span>Only facilities reporting stock</span>
              </label>
              <label className="find__check">
                <input
                  type="checkbox"
                  checked={verifiedOnly}
                  onChange={(e) => setVerifiedOnly(e.target.checked)}
                />
                <span>Only independently verified</span>
              </label>
            </fieldset>
          </Card>

          <Card title="Where to search">
            <OriginIndicator
              source={originSource}
              label={originLabel}
              origin={origin}
              accuracy={geo.accuracy}
              status={geo.status}
              message={geo.message}
            />
            <Button
              variant="secondary"
              size="sm"
              onClick={geo.request}
              loading={geo.status === 'locating'}
            >
              Use my location
            </Button>

            <Field
              label="Or search a place"
              htmlFor="place"
              hint="You never have to share your precise location."
            >
              {({ id, describedBy }) => (
                <input
                  id={id}
                  aria-describedby={describedBy}
                  type="search"
                  placeholder="e.g. Patiala, Chandigarh"
                  value={placeQuery}
                  onChange={(e) => setPlaceQuery(e.target.value)}
                  autoComplete="off"
                />
              )}
            </Field>

            {places?.results?.length > 0 && (
              <ul className="find__places">
                {places.results.map((place) => (
                  <li key={`${place.latitude},${place.longitude}`}>
                    <button type="button" onClick={() => choosePlace(place)}>
                      {place.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {places && places.providerAvailable === false && (
              <p className="text-xs muted">{places.notice}</p>
            )}

          </Card>
        </aside>

        <section className="find__results" aria-live="polite">
          <AsyncState
            loading={loading}
            error={error}
            isEmpty={facilities.length === 0}
            onRetry={reload}
            loadingMessage="Searching nearby facilities…"
            emptyTitle="No facilities found"
            emptyMessage={`Nothing within ${radiusKm} km matched. Try a larger radius, a different component, or turn off the filters.`}
          >
            <div className="find__summary row">
              <strong>{facilities.length}</strong>
              <span className="muted text-sm">
                of {results?.totalCandidates ?? 0} facilities within {radiusKm} km
                {onlyAvailable || verifiedOnly ? ' matching your filters' : ''}
              </span>
            </div>

            <div className="find__sort">
              <label htmlFor="sort-by" className="text-xs muted">Sort by</label>
              <select
                id="sort-by"
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value)}
              >
                <option value="recommended">Recommended</option>
                <option value="distance">Distance</option>
                <option value="availability">Availability</option>
              </select>
            </div>

            <FacilityMap
              facilities={facilities}
              camps={nearbyCamps}
              origin={origin}
              onSelect={(f) => setSelectedId(f.facilityId)}
              onSelectCamp={(c) => navigate(`/camps/${c.campId}`)}
              selectedId={selectedId}
              height={320}
            />

            <ul className="find__list">
              {facilities.map((facility) => (
                <li
                  key={facility.facilityId}
                  onClick={() => setSelectedId(facility.facilityId)}
                  className={`facility facility--selectable ${
                    selectedId === facility.facilityId ? 'facility--selected' : ''
                  } ${facility.facilityId === nearestUsefulId ? 'facility--nearest' : ''}`}
                >
                  <div className="facility__main">
                    <h3 className="facility__name">
                      <Link to={`/facilities/${facility.facilityId}`}>{facility.name}</Link>
                      {facility.facilityId === nearestUsefulId && (
                        <span className="pill pill--nearest" title="Closest facility that may be able to supply">
                          Nearest
                        </span>
                      )}
                    </h3>
                    <p className="facility__location text-sm muted">
                      {facility.address}
                      {facility.city ? `, ${facility.city}` : ''}
                    </p>
                    <div className="facility__badges">
                      <AvailabilityBadge
                        state={facility.availability}
                        units={facility.eligibleUnits}
                      />
                      <DataQuality
                        freshness={facility.freshness}
                        verification={facility.verificationStatus}
                      />
                    </div>
                    {facility.rankExplanation?.length > 0 && (
                      <ul className="facility__why">
                        {facility.rankExplanation.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="facility__side">
                    <div className="facility__distance">
                      <strong>{facility.straightLineKm?.toFixed(1)} km</strong>
                      <span className="text-xs muted">straight-line</span>
                    </div>
                    {facility.roadKm == null && (
                      <span className="text-xs muted">Road distance unavailable</span>
                    )}
                    <Link
                      to={`/facilities/${facility.facilityId}`}
                      className="btn btn--secondary btn--sm"
                    >
                      Details
                    </Link>
                    {/* Straight to an external navigator using this
                        facility's stored coordinates. LifeLink still reports
                        straight-line distance and claims no road route. */}
                    {directionsUrl({ destination: facility, origin }) && (
                      <a
                        className="btn btn--ghost btn--sm"
                        href={directionsUrl({ destination: facility, origin })}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        Directions
                      </a>
                    )}
                    <RequestBloodButton
                      bloodGroup={bloodGroup}
                      component={component}
                      units={units}
                      origin={origin}
                      facility={facility}
                      variant="ghost"
                    />
                  </div>
                </li>
              ))}
            </ul>

            {facilities.some((f) => f.availability === 'UNKNOWN') && (
              <Notice tone="info" title="Some facilities have not reported stock">
                Rows marked <strong>Not reported</strong> have no inventory on record.
                That is not the same as having none — telephone them to ask.
              </Notice>
            )}

            {results?.notice && <p className="find__footnote text-xs muted">{results.notice}</p>}
          </AsyncState>
        </section>
      </div>
    </div>
  )
}
