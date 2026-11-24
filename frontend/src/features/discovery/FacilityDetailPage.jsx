/**
 * Facility detail: the full availability matrix plus routing.
 *
 * The matrix shows every group and component combination the facility could
 * hold, including the ones it does not. A blank cell would be ambiguous, so
 * each cell says explicitly whether stock is available, absent, or simply not
 * reported.
 */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../api/client.js'
import { useApiData } from '../../hooks/useApi.js'
import {
  AsyncState,
  Button,
  Card,
  DefinitionList,
  NotAReservationNotice,
  Notice,
} from '../../components/ui.jsx'
import { RequestBloodButton } from '../../components/RequestBloodButton.jsx'
import { ReservationPanel } from './ReservationPanel.jsx'
import {
  AvailabilityBadge,
  DataQuality,
  StatusPill,
} from '../../components/StatusBadges.jsx'
import { DataProvenance, ProvenancePills } from '../../components/DataProvenance.jsx'
import './FacilityDetailPage.css'

const COMPONENT_LABELS = {
  WHOLE_BLOOD: 'Whole blood',
  PRBC: 'PRBC',
  FFP: 'FFP',
  PLATELETS: 'Platelets',
}

const GROUP_ORDER = ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+']

export function FacilityDetailPage() {
  const { facilityId } = useParams()
  const [route, setRoute] = useState(null)
  const [routeLoading, setRouteLoading] = useState(false)

  const facilityQuery = useApiData(() => api.getFacility(facilityId), [facilityId])
  const availabilityQuery = useApiData(
    () => api.facilityAvailability(facilityId, { units: 1 }),
    [facilityId],
  )

  const facility = facilityQuery.data
  const availability = availabilityQuery.data

  async function loadRoute() {
    if (!facility) return
    setRouteLoading(true)
    try {
      // Origin is Patiala in this demo; a real client would use the user's
      // chosen search origin.
      const result = await api.routeToFacility(facilityId, { lat: 30.3398, lon: 76.3869 })
      setRoute(result)
    } catch (cause) {
      setRoute({ routingAvailable: false, unavailableReason: cause.code })
    } finally {
      setRouteLoading(false)
    }
  }

  const matrix = availability?.availability ?? []
  const byGroup = GROUP_ORDER.map((group) => ({
    group,
    cells: matrix.filter((cell) => cell.bloodGroup === group),
  })).filter((row) => row.cells.length > 0)

  const components = [...new Set(matrix.map((cell) => cell.component))]

  return (
    <div className="stack">
      <AsyncState
        loading={facilityQuery.loading}
        error={facilityQuery.error}
        onRetry={facilityQuery.reload}
        loadingMessage="Loading facility…"
      >
        {facility && (
          <>
            <header className="page-header">
              <Link to="/find" className="text-sm">&larr; Back to search</Link>
              <h1>{facility.name}</h1>
              <div className="row">
                <StatusPill
                  status={facility.verificationStatus}
                  tone={facility.verificationStatus === 'VERIFIED' ? 'success' : 'warning'}
                />
                {/* Two axes, not one: whether the place is real and whether
                    the stock is real can differ. See components/provenance.js */}
                <ProvenancePills record={facility} />
              </div>
            </header>

            {facility.verificationStatus !== 'VERIFIED' && (
              <Notice tone="warning" title="This facility is not verified by LifeLink">
                LifeLink has not confirmed that this organization is an operating blood
                bank. Appearing on a map or in a business listing is not proof of that.
              </Notice>
            )}

            <div className="grid grid--2">
              <Card title="Facility details">
                <DefinitionList
                  items={[
                    { label: 'Type', value: facility.facilityType?.replace(/_/g, ' ') },
                    { label: 'Address', value: facility.address },
                    { label: 'City', value: facility.city },
                    { label: 'State', value: facility.state },
                    { label: 'Phone', value: facility.contactPhone },
                    { label: 'Hours', value: facility.operatingHours },
                    {
                      label: 'Coordinates',
                      value: `${facility.latitude?.toFixed(5)}, ${facility.longitude?.toFixed(5)}`,
                    },
                  ]}
                />
              </Card>

              <Card title="Data quality" subtitle="Two separate signals">
                <DefinitionList
                  items={[
                    {
                      label: 'Inventory reported',
                      value: facility.inventoryKnown ? 'Yes' : 'No — nothing on record',
                    },
                    {
                      label: 'Last updated',
                      value: facility.inventoryLastUpdatedAt ?? 'Never',
                    },
                    {
                      label: 'Last verified',
                      value: facility.inventoryLastVerifiedAt ?? 'Never independently verified',
                    },
                  ]}
                />
                <div style={{ marginTop: 'var(--space-3)' }}>
                  <DataQuality
                    freshness={facility.freshness}
                    verification={facility.verificationFreshness}
                  />
                </div>

                <hr className="rule" />

                <Button variant="secondary" size="sm" onClick={loadRoute} loading={routeLoading}>
                  Get directions from Patiala
                </Button>
                {route && (
                  <div className="route-result text-sm">
                    <p style={{ margin: 'var(--space-2) 0 0' }}>
                      <strong>{route.straightLineKm} km</strong> straight-line
                    </p>
                    {route.routingAvailable ? (
                      <p style={{ margin: 0 }}>
                        <strong>{route.roadKm} km</strong> by road, about{' '}
                        <strong>{route.etaMinutes} minutes</strong>
                      </p>
                    ) : (
                      <p className="muted" style={{ margin: 0 }}>
                        Road directions unavailable ({route.unavailableReason}). The
                        figure above is straight-line only and is not a driving distance.
                      </p>
                    )}
                  </div>
                )}
              </Card>
            </div>

            {/* Record provenance, stated on the page rather than only in the
                documentation. A reader needs to know which parts of what they
                are looking at are real before they act on any of it. */}
            <Card title="Where this record comes from" subtitle="Identity, stock and location are separate claims">
              <DataProvenance record={facility} />
            </Card>

            <NotAReservationNotice />

            <Card
              title="Availability"
              subtitle="Every blood group and component this facility could hold"
            >
              <AsyncState
                loading={availabilityQuery.loading}
                error={availabilityQuery.error}
                onRetry={availabilityQuery.reload}
                isEmpty={matrix.length === 0}
                emptyTitle="No availability information"
                emptyMessage="This facility has not reported any inventory."
              >
                {!availability?.inventoryKnown && (
                  <Notice tone="info" title="This facility has not reported inventory">
                    Every cell below reads &ldquo;not reported&rdquo;. That is different
                    from reporting zero stock.
                  </Notice>
                )}

                <div className="table-scroll">
                  <table className="table matrix">
                    <caption className="visually-hidden">
                      Availability by blood group and component
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Group</th>
                        {components.map((component) => (
                          <th scope="col" key={component}>
                            {COMPONENT_LABELS[component] ?? component}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {byGroup.map((row) => (
                        <tr key={row.group}>
                          <th scope="row" className="matrix__group">{row.group}</th>
                          {components.map((component) => {
                            const cell = row.cells.find((c) => c.component === component)
                            if (!cell) {
                              return (
                                <td key={component} className="muted text-xs">
                                  Not stocked
                                </td>
                              )
                            }
                            return (
                              <td key={component}>
                                <AvailabilityBadge
                                  state={cell.availability}
                                  units={
                                    cell.availability === 'UNKNOWN'
                                      ? undefined
                                      : cell.eligibleUnits
                                  }
                                />
                                {cell.nearExpiryUnits > 0 && (
                                  <span className="matrix__note text-xs">
                                    {cell.nearExpiryUnits} near expiry
                                  </span>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {availability?.disclaimer && (
                  <p className="text-xs muted" style={{ marginTop: 'var(--space-3)' }}>
                    {availability.disclaimer}
                  </p>
                )}
              </AsyncState>
            </Card>

            <Card title="Need blood from here?">
              <p className="inline-note">
                A blood request is routed to matching providers and, where a
                hospital certifies it, carries a clinical priority. It is
                separate from a temporary reservation, which holds specific
                units for you right now.
              </p>
              <RequestBloodButton
                origin={{
                  latitude: facility?.latitude,
                  longitude: facility?.longitude,
                }}
                facility={{ facilityId, name: facility?.name }}
                variant="primary"
                size="md"
              />
            </Card>

            <ReservationPanel
              facilityId={facilityId}
              facilityName={facility?.name ?? 'this facility'}
              matrix={matrix}
              // Reload the matrix after a hold so the reserved and unreserved
              // figures on screen reflect the hold that was just placed.
              onPlaced={() => availabilityQuery.reload()}
            />
          </>
        )}
      </AsyncState>
    </div>
  )
}
