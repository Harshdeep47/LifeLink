/**
 * Explore → Blood banks.
 *
 * A directory view, not a copy of the Find Blood search form. Find Blood is a
 * focused "I need O-negative PRBC, four units, now" query; this is "show me
 * the blood banks around here and let me narrow them down". Embedding the
 * full search form here made one page do both jobs badly.
 *
 * It calls the same `searchFacilities` endpoint and renders the same status
 * badges, so nothing about availability, freshness or verification is
 * reinterpreted. What differs is the framing: a compact filter bar, a map and
 * a sortable directory.
 *
 * Filtering is client-side over the records the API already returned for the
 * chosen origin and radius. That keeps one request per origin change instead
 * of one per keystroke, and the filters only ever *narrow* what the API said
 * — they never compute availability themselves.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { FacilityMap } from '../../components/FacilityMap.jsx'
import { OriginIndicator } from '../../components/OriginIndicator.jsx'
import { PlaceSearch } from '../../components/PlaceSearch.jsx'
import { directionsUrl } from '../../components/mapData.js'
import { RequestBloodButton } from '../../components/RequestBloodButton.jsx'
import { AvailabilityBadge, DataQuality } from '../../components/StatusBadges.jsx'
import { AsyncState, Button, Card, Field } from '../../components/ui.jsx'
import { useApiData, useGeolocation } from '../../hooks/useApi.js'

const DEFAULT_ORIGIN = { latitude: 30.3398, longitude: 76.3869 }
const RADII = [10, 20, 30, 50, 100]

function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
      {hint && <span className="stat__hint">{hint}</span>}
    </div>
  )
}

export function BloodBankDashboardTab() {
  const geo = useGeolocation()
  const [origin, setOrigin] = useState(DEFAULT_ORIGIN)
  const [originSource, setOriginSource] = useState('default')
  const [originLabel, setOriginLabel] = useState('Default search location')
  const [radiusKm, setRadiusKm] = useState(30)

  const [nameQuery, setNameQuery] = useState('')
  const [reporting, setReporting] = useState('any')
  const [verification, setVerification] = useState('any')
  const [freshness, setFreshness] = useState('any')
  const [sortBy, setSortBy] = useState('distance')
  const [selectedId, setSelectedId] = useState(null)

  // Only adopt coordinates that actually arrived; a denied or failed lookup
  // leaves the origin alone and the indicator still reading "default".
  //
  // In an effect, not during render: setting state while rendering triggers
  // React's "Cannot update a component while rendering a different
  // component" warning and re-renders in a loop. The same mistake was fixed
  // once already in FindBloodPage.
  useEffect(() => {
    if (geo.status === 'granted' && geo.coords) {
      setOrigin(geo.coords)
      setOriginSource('gps')
      setOriginLabel('Your current location')
    }
  }, [geo.status, geo.coords])

  const { data, loading, error, reload } = useApiData(
    (signal) =>
      api.searchFacilities(
        { lat: origin.latitude, lon: origin.longitude, radiusKm },
        signal,
      ),
    [origin.latitude, origin.longitude, radiusKm],
  )

  const all = data?.results ?? []

  const stats = useMemo(() => {
    if (all.length === 0) return null
    const reportingCount = all.filter((f) => f.inventoryKnown).length
    return {
      total: all.length,
      reporting: reportingCount,
      unknown: all.length - reportingCount,
      verified: all.filter((f) => f.verificationStatus === 'VERIFIED').length,
      fresh: all.filter((f) => f.freshness === 'FRESH').length,
      aging: all.filter((f) => f.freshness === 'AGING').length,
      stale: all.filter((f) => ['STALE', 'OUTDATED'].includes(f.freshness)).length,
    }
  }, [all])

  const facilities = useMemo(() => {
    const needle = nameQuery.trim().toLowerCase()
    let list = all.filter((f) => {
      if (needle && !`${f.name} ${f.city ?? ''}`.toLowerCase().includes(needle)) return false
      if (reporting === 'reporting' && !f.inventoryKnown) return false
      if (reporting === 'unknown' && f.inventoryKnown) return false
      if (verification === 'verified' && f.verificationStatus !== 'VERIFIED') return false
      if (verification === 'unverified' && f.verificationStatus === 'VERIFIED') return false
      if (freshness !== 'any' && f.freshness !== freshness) return false
      return true
    })
    list = [...list]
    if (sortBy === 'distance') {
      list.sort((a, b) => (a.straightLineKm ?? Infinity) - (b.straightLineKm ?? Infinity))
    } else if (sortBy === 'name') {
      list.sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
    } else if (sortBy === 'freshness') {
      const rank = { FRESH: 0, AGING: 1, STALE: 2, OUTDATED: 3, UNKNOWN: 4 }
      list.sort((a, b) => (rank[a.freshness] ?? 9) - (rank[b.freshness] ?? 9))
    }
    return list
  }, [all, nameQuery, reporting, verification, freshness, sortBy])

  // Nearest among facilities that could actually supply. A facility with
  // nothing in stock is not the nearest useful option; UNKNOWN stays eligible
  // because "not reported" is exactly the case worth a phone call.
  const nearestId = useMemo(() => {
    const usable = facilities.filter(
      (f) =>
        typeof f.straightLineKm === 'number' &&
        ['AVAILABLE', 'PARTIAL', 'UNKNOWN'].includes(f.availability),
    )
    if (usable.length === 0) return null
    return usable.reduce((best, f) => (f.straightLineKm < best.straightLineKm ? f : best))
      .facilityId
  }, [facilities])

  const clearFilters = () => {
    setNameQuery('')
    setReporting('any')
    setVerification('any')
    setFreshness('any')
  }

  return (
    <div className="stack">
      {stats && (
        <div className="stat-row" aria-label="Blood bank overview">
          <Stat label="Listed blood banks" value={stats.total} hint={`within ${radiusKm} km`} />
          <Stat label="Reporting inventory" value={stats.reporting} />
          <Stat label="Not reported" value={stats.unknown} hint="unknown, not zero" />
          <Stat label="Independently verified" value={stats.verified} />
          <Stat label="Fresh" value={stats.fresh} hint="within 6 hours" />
          <Stat label="Aging" value={stats.aging} hint="6 to 24 hours" />
          <Stat label="Stale" value={stats.stale} hint="over 24 hours" />
        </div>
      )}

      <Card title="Search area">
        <OriginIndicator
          source={originSource}
          label={originLabel}
          origin={origin}
          accuracy={geo.accuracy}
          status={geo.status}
          message={geo.message}
        />
        <div className="filter-bar">
          <Button variant="secondary" size="sm" onClick={geo.request}
                  loading={geo.status === 'locating'}>
            Use my location
          </Button>
          <Field label="Within" htmlFor="bb-radius">
            {({ id }) => (
              <select id={id} value={radiusKm}
                      onChange={(e) => setRadiusKm(Number(e.target.value))}>
                {RADII.map((r) => <option key={r} value={r}>{r} km</option>)}
              </select>
            )}
          </Field>
        </div>
        <PlaceSearch onSelect={(place) => {
          setOrigin({ latitude: place.latitude, longitude: place.longitude })
          setOriginSource('manual')
          setOriginLabel(place.label)
        }} />
      </Card>

      <AsyncState loading={loading} error={error} onRetry={reload}>
        <>
          <FacilityMap
            facilities={facilities}
            origin={origin}
            onSelect={(f) => setSelectedId(f.facilityId)}
            selectedId={selectedId}
            height={340}
          />

          <Card title="Filter the directory">
            <div className="filter-bar">
              <Field label="Name or city" htmlFor="bb-name">
                {({ id }) => (
                  <input id={id} type="search" value={nameQuery} placeholder="e.g. Rajindra"
                         onChange={(e) => setNameQuery(e.target.value)} />
                )}
              </Field>
              <Field label="Inventory" htmlFor="bb-reporting">
                {({ id }) => (
                  <select id={id} value={reporting} onChange={(e) => setReporting(e.target.value)}>
                    <option value="any">Any</option>
                    <option value="reporting">Reporting</option>
                    <option value="unknown">Not reported</option>
                  </select>
                )}
              </Field>
              <Field label="Verification" htmlFor="bb-verif">
                {({ id }) => (
                  <select id={id} value={verification}
                          onChange={(e) => setVerification(e.target.value)}>
                    <option value="any">Any</option>
                    <option value="verified">Verified</option>
                    <option value="unverified">Not verified</option>
                  </select>
                )}
              </Field>
              <Field label="Freshness" htmlFor="bb-fresh">
                {({ id }) => (
                  <select id={id} value={freshness} onChange={(e) => setFreshness(e.target.value)}>
                    <option value="any">Any</option>
                    <option value="FRESH">Fresh</option>
                    <option value="AGING">Aging</option>
                    <option value="STALE">Stale</option>
                    <option value="OUTDATED">Outdated</option>
                  </select>
                )}
              </Field>
              <Field label="Sort by" htmlFor="bb-sort">
                {({ id }) => (
                  <select id={id} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                    <option value="distance">Nearest</option>
                    <option value="freshness">Freshest data</option>
                    <option value="name">Name</option>
                  </select>
                )}
              </Field>
              <Button variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>
            </div>
            <p className="text-xs muted">
              Showing {facilities.length} of {all.length} blood banks within{' '}
              {radiusKm} km.
            </p>
          </Card>

          {facilities.length === 0 ? (
            <Card>
              <p className="muted text-sm">
                No blood banks match these filters. Try widening the radius or
                clearing a filter.
              </p>
            </Card>
          ) : (
            <ul className="directory">
              {facilities.map((f) => (
                <li
                  key={f.facilityId}
                  onClick={() => setSelectedId(f.facilityId)}
                  className={`directory__row directory__row--selectable ${
                    f.facilityId === nearestId ? 'directory__row--nearest' : ''
                  } ${selectedId === f.facilityId ? 'directory__row--selected' : ''}`}
                >
                  <div className="directory__main">
                    <h3 className="directory__name">
                      <Link to={`/facilities/${f.facilityId}`}>{f.name}</Link>
                      {f.facilityId === nearestId && (
                        <span className="pill pill--nearest">Nearest</span>
                      )}
                    </h3>
                    <p className="text-xs muted">{f.city}</p>
                    <div className="facility__badges">
                      <AvailabilityBadge state={f.availability} units={f.eligibleUnits} />
                      <DataQuality
                        freshness={f.freshness}
                        verification={f.verificationStatus}
                      />
                    </div>
                  </div>
                  <div className="directory__side">
                    {directionsUrl({ destination: f, origin }) && (
                      <a className="btn btn--ghost btn--sm"
                         href={directionsUrl({ destination: f, origin })}
                         target="_blank" rel="noreferrer noopener">
                        Directions
                      </a>
                    )}
                    <div className="facility__distance">
                      <strong>{f.straightLineKm?.toFixed(1)} km</strong>
                      <span className="text-xs muted">straight-line</span>
                    </div>
                    <Link to={`/facilities/${f.facilityId}`}
                          className="btn btn--secondary btn--sm">
                      Details
                    </Link>
                    <RequestBloodButton origin={origin} facility={f} variant="ghost" />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      </AsyncState>
    </div>
  )
}
