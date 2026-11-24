/**
 * Camp discovery.
 *
 * Note the search radius here is independent of a user's notification radius.
 * The 10 km default governs which camps they are *told* about; it must never
 * restrict which camps they can *find*, which is why this page takes its own
 * radius control.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { FacilityMap } from '../../components/FacilityMap.jsx'
import { OriginIndicator } from '../../components/OriginIndicator.jsx'
import { PlaceSearch } from '../../components/PlaceSearch.jsx'
import { useApiData, useGeolocation } from '../../hooks/useApi.js'
import { AsyncState, Button, Card, Field, Notice } from '../../components/ui.jsx'
import { CampStatusPill } from '../../components/StatusBadges.jsx'

const RADII = [10, 20, 50, 100]
const DEFAULT_ORIGIN = { latitude: 30.3398, longitude: 76.3869 }

function formatDate(iso) {
  if (!iso) return 'Date not set'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'Asia/Kolkata',
    })
  } catch {
    return iso
  }
}

export function CampsPage() {
  const [origin, setOrigin] = useState(DEFAULT_ORIGIN)
  const [selectedCampId, setSelectedCampId] = useState(null)
  const [originSource, setOriginSource] = useState('default')
  const [originLabel, setOriginLabel] = useState('Default search location')
  const [radiusKm, setRadiusKm] = useState(50)
  const geo = useGeolocation()

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

  const rawCamps = data?.results ?? []

  /**
   * Sorted nearest-first, and the nearest *attendable* camp identified.
   *
   * Only UPCOMING and ONGOING camps can be attended, so a completed or
   * cancelled camp 200 m away is not the nearest useful one. Labelling it
   * "Nearest" would point a donor at a camp they cannot join.
   */
  const camps = useMemo(
    () =>
      [...rawCamps].sort(
        (a, b) => (a.straightLineKm ?? Infinity) - (b.straightLineKm ?? Infinity),
      ),
    [rawCamps],
  )

  const nearestCampId = useMemo(() => {
    const attendable = rawCamps.filter(
      (c) =>
        typeof c.straightLineKm === 'number' &&
        ['UPCOMING', 'ONGOING'].includes(c.status),
    )
    if (attendable.length === 0) return null
    return attendable.reduce((best, c) =>
      c.straightLineKm < best.straightLineKm ? c : best,
    ).campId
  }, [rawCamps])

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Blood donation camps</h1>
        <p>
          Find upcoming camps, register to attend, and build a verified
          donation history. Registering is not the same as attending, and
          attending is not the same as a completed donation — each is
          recorded separately.
        </p>
      </header>

      <Card title="Search area">
        <OriginIndicator
          source={originSource}
          label={originLabel}
          origin={origin}
          accuracy={geo.accuracy}
          status={geo.status}
          message={geo.message}
        />
        <div className="row">
          <Button variant="secondary" size="sm" onClick={geo.request} loading={geo.status === 'locating'}>
            Use my location
          </Button>
          <div style={{ minWidth: '160px' }}>
            <Field label="Within" htmlFor="camp-radius">
              {({ id }) => (
                <select
                  id={id}
                  value={radiusKm}
                  onChange={(event) => setRadiusKm(Number(event.target.value))}
                >
                  {RADII.map((r) => (
                    <option key={r} value={r}>{r} km</option>
                  ))}
                </select>
              )}
            </Field>
          </div>
        </div>
        {data?.notice && <p className="text-xs muted">{data.notice}</p>}
        <PlaceSearch onSelect={(place) => {
          setOrigin({ latitude: place.latitude, longitude: place.longitude })
          setOriginSource('manual')
          setOriginLabel(place.label)
        }} />
      </Card>

      {camps.length > 0 && (
        <Card title="Camps near you" subtitle={originLabel}>
          <FacilityMap
            camps={camps}
            origin={origin}
            selectedId={selectedCampId}
            // A marker click selects rather than navigating away: the user is
            // comparing camps, and losing the page to open one is hostile.
            onSelectCamp={(c) => setSelectedCampId(c.campId)}
            height={320}
          />
        </Card>
      )}

      <AsyncState
        loading={loading}
        error={error}
        onRetry={reload}
        isEmpty={camps.length === 0}
        loadingMessage="Finding camps near you…"
        emptyTitle="No camps found"
        emptyMessage={`No upcoming camps within ${radiusKm} km. Try a wider search area.`}
      >
        <div className="grid grid--2">
          {camps.map((camp) => (
            <Card
              key={camp.campId}
              className={camp.campId === nearestCampId ? 'card--nearest' : undefined}
              title={
                <>
                  {camp.name}
                  {camp.campId === nearestCampId && (
                    <span className="pill pill--nearest" title="Closest camp you can attend">
                      Nearest
                    </span>
                  )}
                </>
              }
              subtitle={`${camp.address ?? ''}${camp.city ? `, ${camp.city}` : ''}`}
              actions={<CampStatusPill status={camp.status} />}
            >
              <dl className="definition-list">
                {typeof camp.straightLineKm === 'number' && (
                  <div className="definition-list__row">
                    <dt>Distance</dt>
                    <dd>
                      <strong>{camp.straightLineKm.toFixed(1)} km</strong>{' '}
                      <span className="muted text-xs">straight-line</span>
                    </dd>
                  </div>
                )}
                <div className="definition-list__row">
                  <dt>Starts</dt>
                  <dd>{formatDate(camp.startsAt)}</dd>
                </div>
                <div className="definition-list__row">
                  <dt>Registration closes</dt>
                  <dd>{formatDate(camp.registrationDeadline)}</dd>
                </div>
                <div className="definition-list__row">
                  <dt>Capacity</dt>
                  <dd>
                    {camp.registeredCount ?? 0} of {camp.capacity} registered
                    {camp.registeredCount >= camp.capacity && (
                      <strong> — full</strong>
                    )}
                  </dd>
                </div>
                {typeof camp.straightLineKm === 'number' && (
                  <div className="definition-list__row">
                    <dt>Distance</dt>
                    <dd>{camp.straightLineKm.toFixed(1)} km straight-line</dd>
                  </div>
                )}
              </dl>
              <div className="row" style={{ marginTop: 'var(--space-3)' }}>
                <Link to={`/camps/${camp.campId}`} className="btn btn--primary btn--sm">
                  View and register
                </Link>
              </div>
            </Card>
          ))}
        </div>
      </AsyncState>

      <Notice tone="info" title="About notification radius">
        Your notification preferences use a 10 km radius by default, which you can
        change or extend to 20 km. That setting controls which camps you are
        <strong> told</strong> about. It never limits which camps you can search for
        here.
      </Notice>
    </div>
  )
}
