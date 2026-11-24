/**
 * Explore → Donation camps.
 *
 * A directory view over the same `searchCamps` endpoint the camps page uses.
 * Filtering and sorting happen client-side over the records the API returned
 * for the chosen origin and radius, so the filters only ever narrow what the
 * API said.
 *
 * On "popular": popularity is registration count, and it is labelled as such.
 * Registrations are not attendance and not donations — the product keeps
 * those three apart everywhere else, and a "popular" badge that quietly
 * conflated them would undo that. A camp with no registrations is never
 * badged.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { FacilityMap } from '../../components/FacilityMap.jsx'
import { OriginIndicator } from '../../components/OriginIndicator.jsx'
import { PlaceSearch } from '../../components/PlaceSearch.jsx'
import { directionsUrl } from '../../components/mapData.js'
import { AsyncState, Button, Card, Field } from '../../components/ui.jsx'
import { useApiData, useGeolocation } from '../../hooks/useApi.js'

const DEFAULT_ORIGIN = { latitude: 30.3398, longitude: 76.3869 }
const RADII = [5, 10, 20]

function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
      {hint && <span className="stat__hint">{hint}</span>}
    </div>
  )
}

function formatWhen(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return value
  }
}

export function CampDashboardTab() {
  const geo = useGeolocation()
  const [origin, setOrigin] = useState(DEFAULT_ORIGIN)
  const [originSource, setOriginSource] = useState('default')
  const [originLabel, setOriginLabel] = useState('Default search location')
  const [radiusKm, setRadiusKm] = useState(20)

  const [nameQuery, setNameQuery] = useState('')
  const [status, setStatus] = useState('any')
  const [onlyWithPlaces, setOnlyWithPlaces] = useState(false)
  const [sortBy, setSortBy] = useState('distance')
  const [selectedId, setSelectedId] = useState(null)

  useEffect(() => {
    if (geo.status === 'granted' && geo.coords) {
      setOrigin(geo.coords)
      setOriginSource('gps')
      setOriginLabel('Your current location')
    }
  }, [geo.status, geo.coords])

  const { data, loading, error, reload } = useApiData(
    (signal) =>
      api.searchCamps(
        { lat: origin.latitude, lon: origin.longitude, radiusKm },
        signal,
      ),
    [origin.latitude, origin.longitude, radiusKm],
  )

  const all = data?.results ?? []

  const stats = useMemo(() => {
    if (all.length === 0) return null
    const capacity = all.reduce((sum, c) => sum + (Number(c.capacity) || 0), 0)
    const registered = all.reduce((sum, c) => sum + (Number(c.registeredCount) || 0), 0)
    return {
      total: all.length,
      upcoming: all.filter((c) => c.status === 'UPCOMING').length,
      ongoing: all.filter((c) => c.status === 'ONGOING').length,
      capacity,
      registered,
      remaining: Math.max(0, capacity - registered),
      // Only meaningful if there is capacity to divide by.
      utilisation: capacity > 0 ? Math.round((registered / capacity) * 100) : null,
    }
  }, [all])

  const camps = useMemo(() => {
    const needle = nameQuery.trim().toLowerCase()
    let list = all.filter((c) => {
      if (needle && !`${c.name} ${c.city ?? ''}`.toLowerCase().includes(needle)) return false
      if (status !== 'any' && c.status !== status) return false
      if (onlyWithPlaces) {
        const left = (Number(c.capacity) || 0) - (Number(c.registeredCount) || 0)
        if (left <= 0) return false
      }
      return true
    })
    list = [...list]
    if (sortBy === 'distance') {
      list.sort((a, b) => (a.straightLineKm ?? Infinity) - (b.straightLineKm ?? Infinity))
    } else if (sortBy === 'registrations') {
      list.sort((a, b) => (b.registeredCount ?? 0) - (a.registeredCount ?? 0))
    } else if (sortBy === 'date') {
      list.sort((a, b) => String(a.startsAt ?? '').localeCompare(String(b.startsAt ?? '')))
    } else if (sortBy === 'capacity') {
      const left = (c) => (Number(c.capacity) || 0) - (Number(c.registeredCount) || 0)
      list.sort((a, b) => left(b) - left(a))
    }
    return list
  }, [all, nameQuery, status, onlyWithPlaces, sortBy])

  // Nearest camp a donor could actually attend.
  const nearestId = useMemo(() => {
    const attendable = camps.filter(
      (c) =>
        typeof c.straightLineKm === 'number' &&
        ['UPCOMING', 'ONGOING'].includes(c.status),
    )
    if (attendable.length === 0) return null
    return attendable.reduce((best, c) => (c.straightLineKm < best.straightLineKm ? c : best))
      .campId
  }, [camps])

  // Most registrations, among camps that have any. Labelled "Most registered"
  // rather than "popular", because registrations are not attendance.
  const mostRegisteredId = useMemo(() => {
    const withAny = all.filter((c) => (Number(c.registeredCount) || 0) > 0)
    if (withAny.length === 0) return null
    return withAny.reduce((best, c) =>
      (Number(c.registeredCount) || 0) > (Number(best.registeredCount) || 0) ? c : best,
    ).campId
  }, [all])

  return (
    <div className="stack">
      {stats && (
        <div className="stat-row" aria-label="Donation camp overview">
          <Stat label="Camps listed" value={stats.total} hint={`within ${radiusKm} km`} />
          <Stat label="Running now" value={stats.ongoing} />
          <Stat label="Upcoming" value={stats.upcoming} />
          <Stat label="Total capacity" value={stats.capacity} hint="across these camps" />
          <Stat label="Registered" value={stats.registered} hint="registrations, not attendance" />
          <Stat label="Places left" value={stats.remaining} />
          {stats.utilisation !== null && (
            <Stat label="Capacity used" value={`${stats.utilisation}%`} />
          )}
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
          <Field label="Within" htmlFor="camp-radius">
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
        {data?.notice && <p className="text-xs muted">{data.notice}</p>}
      </Card>

      <AsyncState loading={loading} error={error} onRetry={reload}>
        <>
          <FacilityMap
            camps={camps}
            origin={origin}
            selectedId={selectedId}
            onSelectCamp={(c) => setSelectedId(c.campId)}
            height={340}
          />

          <Card title="Filter the directory">
            <div className="filter-bar">
              <Field label="Name or city" htmlFor="camp-name">
                {({ id }) => (
                  <input id={id} type="search" value={nameQuery} placeholder="e.g. Thapar"
                         onChange={(e) => setNameQuery(e.target.value)} />
                )}
              </Field>
              <Field label="Status" htmlFor="camp-status">
                {({ id }) => (
                  <select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
                    <option value="any">Any</option>
                    <option value="UPCOMING">Upcoming</option>
                    <option value="ONGOING">Ongoing</option>
                    <option value="COMPLETED">Completed</option>
                  </select>
                )}
              </Field>
              <Field label="Sort by" htmlFor="camp-sort">
                {({ id }) => (
                  <select id={id} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                    <option value="distance">Nearest</option>
                    <option value="registrations">Most registered</option>
                    <option value="date">Soonest</option>
                    <option value="capacity">Most places left</option>
                  </select>
                )}
              </Field>
              <label className="checkbox">
                <input type="checkbox" checked={onlyWithPlaces}
                       onChange={(e) => setOnlyWithPlaces(e.target.checked)} />
                <span className="text-sm">Only camps with places left</span>
              </label>
              <Button variant="ghost" size="sm" onClick={() => {
                setNameQuery(''); setStatus('any'); setOnlyWithPlaces(false)
              }}>
                Clear filters
              </Button>
            </div>
            <p className="text-xs muted">
              Showing {camps.length} of {all.length} camps within {radiusKm} km.
            </p>
          </Card>

          {camps.length === 0 ? (
            <Card>
              <p className="muted text-sm">
                No camps match these filters. Try widening the radius or
                clearing a filter.
              </p>
            </Card>
          ) : (
            <ul className="directory">
              {camps.map((c) => {
                const left = (Number(c.capacity) || 0) - (Number(c.registeredCount) || 0)
                return (
                  <li
                    key={c.campId}
                    onClick={() => setSelectedId(c.campId)}
                    className={`directory__row directory__row--selectable ${
                      c.campId === nearestId ? 'directory__row--nearest' : ''
                    } ${selectedId === c.campId ? 'directory__row--selected' : ''}`}
                  >
                    <div className="directory__main">
                      <h3 className="directory__name">
                        <Link to={`/camps/${c.campId}`}>{c.name}</Link>
                        {c.campId === nearestId && (
                          <span className="pill pill--nearest">Nearest</span>
                        )}
                        {c.campId === mostRegisteredId && (
                          <span className="pill pill--popular" title="Most registrations — not attendance">
                            Most registered
                          </span>
                        )}
                      </h3>
                      <p className="text-xs muted">
                        {c.city} · starts {formatWhen(c.startsAt)}
                      </p>
                      <p className="text-xs muted">
                        {c.registeredCount ?? 0} of {c.capacity} registered
                        {left > 0 ? ` · ${left} places left` : ' · full'}
                        {' · '}{c.status?.toLowerCase()}
                      </p>
                    </div>
                    <div className="directory__side">
                      {typeof c.straightLineKm === 'number' && (
                        <div className="facility__distance">
                          <strong>{c.straightLineKm.toFixed(1)} km</strong>
                          <span className="text-xs muted">straight-line</span>
                        </div>
                      )}
                      <Link to={`/camps/${c.campId}`} className="btn btn--secondary btn--sm">
                        View camp
                      </Link>
                      {directionsUrl({ destination: c, origin }) && (
                        <a className="btn btn--ghost btn--sm"
                           href={directionsUrl({ destination: c, origin })}
                           target="_blank" rel="noreferrer noopener">
                          Directions
                        </a>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      </AsyncState>
    </div>
  )
}
