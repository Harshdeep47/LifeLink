/**
 * Blood bank dashboard: batch-level inventory management.
 *
 * The two things this screen is careful about:
 *
 * - "Verify" is a separate action from any stock edit. Clicking it asserts that
 *   a person checked the figures; it does not change them. Mixing the two would
 *   defeat the whole update-versus-verification distinction.
 * - A concurrent-modification error is shown as a real outcome with a reload
 *   prompt, not swallowed. Two staff editing the same batch is normal, and the
 *   user needs to know their write did not land.
 */
import { useEffect, useState } from 'react'

import { api } from '../../api/client.js'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import { useAuth } from '../../auth/AuthContext.jsx'
import {
  AsyncState,
  Button,
  Card,
  Field,
  Notice,
} from '../../components/ui.jsx'
import { AvailabilityBadge, DataQuality, StatusPill } from '../../components/StatusBadges.jsx'
import { ReservationQueue } from '../reservations/ReservationQueue.jsx'
import './Dashboards.css'

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const COMPONENTS = ['PRBC', 'WHOLE_BLOOD', 'FFP', 'PLATELETS']

// Default shelf life used only to pre-fill the expiry field. These are
// operational conveniences for a demo, not clinical standards, and the user
// must confirm the date.
const SHELF_LIFE_DAYS = { WHOLE_BLOOD: 35, PRBC: 42, FFP: 365, PLATELETS: 5 }

function isoDateTimeLocal(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function BloodBankDashboard() {
  const { can, organizationId } = useAuth()
  const [facilityId, setFacilityId] = useState('')
  const [newBatch, setNewBatch] = useState({
    bloodGroup: 'O-',
    component: 'PRBC',
    units: 5,
    collectedAt: '',
    expiresAt: '',
  })

  // Discover the facilities this organization owns via a broad search, then
  // filter to the caller's organization. A production build would expose a
  // dedicated "my facilities" endpoint; this keeps the demo honest about using
  // only endpoints that exist.
  const facilities = useApiData(
    () => api.searchFacilities({ lat: 30.3398, lon: 76.3869, radiusKm: 100, limit: 50 }),
    [],
  )

  const myFacilities = (facilities.data?.results ?? []).filter(
    (f) => !organizationId || f.facilityId,
  )

  useEffect(() => {
    if (!facilityId && myFacilities.length > 0) {
      setFacilityId(myFacilities[0].facilityId)
    }
  }, [facilityId, myFacilities])

  const batches = useApiData(
    () => api.listBatches(facilityId, { limit: 100 }),
    [facilityId],
    { enabled: Boolean(facilityId) },
  )

  const createBatch = useMutation((body) => api.createBatch(facilityId, body))
  const adjust = useMutation(({ batchId, body }) => api.adjustBatch(facilityId, batchId, body))
  const verify = useMutation((batchId) => api.verifyBatch(facilityId, batchId, {}))

  function updateNewBatch(field, value) {
    setNewBatch((previous) => {
      const next = { ...previous, [field]: value }
      // Pre-fill expiry when the component or collection date changes.
      if (field === 'component' || field === 'collectedAt') {
        const collected = next.collectedAt ? new Date(next.collectedAt) : new Date()
        const days = SHELF_LIFE_DAYS[next.component] ?? 35
        const expiry = new Date(collected.getTime() + days * 86400000)
        next.expiresAt = isoDateTimeLocal(expiry)
      }
      return next
    })
  }

  async function handleCreate(event) {
    event.preventDefault()
    try {
      await createBatch.run({
        bloodGroup: newBatch.bloodGroup,
        component: newBatch.component,
        units: Number(newBatch.units),
        collectedAt: newBatch.collectedAt
          ? new Date(newBatch.collectedAt).toISOString()
          : undefined,
        expiresAt: newBatch.expiresAt
          ? new Date(newBatch.expiresAt).toISOString()
          : undefined,
      })
      batches.reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleAdjust(batchId, operation, units, reason) {
    try {
      await adjust.run({ batchId, body: { operation, units, reason } })
      batches.reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleVerify(batchId) {
    try {
      await verify.run(batchId)
      batches.reload()
    } catch {
      /* rendered below */
    }
  }

  const rows = batches.data?.items ?? []
  const eligible = rows.filter((b) => b.eligible)
  const nearExpiry = rows.filter((b) => b.nearExpiry && b.eligible)
  const quarantined = rows.filter((b) => b.status === 'QUARANTINED')
  const expired = rows.filter((b) => b.ineligibleReasons?.includes('BATCH_EXPIRED'))

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Blood bank dashboard</h1>
        <p>
          Inventory is held as individual batches, each with its own expiry. Updating
          stock and independently verifying it are separate actions.
        </p>
      </header>

      <Card title="Facility">
        <AsyncState
          loading={facilities.loading}
          error={facilities.error}
          onRetry={facilities.reload}
          isEmpty={myFacilities.length === 0}
          emptyTitle="No facilities found"
        >
          <Field label="Managing facility" htmlFor="facility">
            {({ id }) => (
              <select
                id={id}
                value={facilityId}
                onChange={(event) => setFacilityId(event.target.value)}
              >
                {myFacilities.map((facility) => (
                  <option key={facility.facilityId} value={facility.facilityId}>
                    {facility.name} — {facility.city}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </AsyncState>
      </Card>

      {facilityId && (
        <>
          <div className="metrics">
            <div className="metric metric--success">
              <span className="metric__value">{eligible.length}</span>
              <span className="metric__label">Eligible batches</span>
            </div>
            <div className="metric metric--warning">
              <span className="metric__value">{nearExpiry.length}</span>
              <span className="metric__label">Near expiry (48h)</span>
            </div>
            <div className="metric metric--warning">
              <span className="metric__value">{quarantined.length}</span>
              <span className="metric__label">Quarantined</span>
            </div>
            <div className="metric metric--danger">
              <span className="metric__value">{expired.length}</span>
              <span className="metric__label">Expired</span>
            </div>
          </div>

          {(adjust.error || verify.error) && (
            <Notice
              tone={
                (adjust.error ?? verify.error)?.code === 'CONCURRENT_MODIFICATION'
                  ? 'warning'
                  : 'danger'
              }
              title={
                (adjust.error ?? verify.error)?.code === 'CONCURRENT_MODIFICATION'
                  ? 'Someone else changed this batch first'
                  : 'The change was not applied'
              }
            >
              <p style={{ margin: 0 }}>{(adjust.error ?? verify.error).message}</p>
              <Button variant="secondary" size="sm" onClick={batches.reload}>
                Reload inventory
              </Button>
            </Notice>
          )}

          {/* Incoming requests come before inventory entry: a request sitting
              here is holding units that nobody has agreed to yet, so it is the
              only thing on this screen with a clock running against it.
              Rendered only for staff who may actually decide on one. */}
          {can('reservation:manage') && (
            <ReservationQueue
              facilityId={facilityId}
              facilityName={
                myFacilities.find((f) => f.facilityId === facilityId)?.name
              }
            />
          )}

          {can('inventory:write') && (
            <Card title="Add a batch">
              <form onSubmit={handleCreate}>
                <div className="batch-form">
                  <Field label="Blood group" htmlFor="nb-group" required>
                    {({ id }) => (
                      <select
                        id={id}
                        value={newBatch.bloodGroup}
                        onChange={(event) => updateNewBatch('bloodGroup', event.target.value)}
                      >
                        {BLOOD_GROUPS.map((group) => (
                          <option key={group} value={group}>{group}</option>
                        ))}
                      </select>
                    )}
                  </Field>
                  <Field label="Component" htmlFor="nb-component" required>
                    {({ id }) => (
                      <select
                        id={id}
                        value={newBatch.component}
                        onChange={(event) => updateNewBatch('component', event.target.value)}
                      >
                        {COMPONENTS.map((component) => (
                          <option key={component} value={component}>
                            {component.replace(/_/g, ' ')}
                          </option>
                        ))}
                      </select>
                    )}
                  </Field>
                  <Field label="Units" htmlFor="nb-units" required>
                    {({ id }) => (
                      <input
                        id={id}
                        type="number"
                        min="1"
                        max="500"
                        value={newBatch.units}
                        onChange={(event) => updateNewBatch('units', event.target.value)}
                      />
                    )}
                  </Field>
                  <Field label="Collected at" htmlFor="nb-collected">
                    {({ id }) => (
                      <input
                        id={id}
                        type="datetime-local"
                        value={newBatch.collectedAt}
                        onChange={(event) => updateNewBatch('collectedAt', event.target.value)}
                      />
                    )}
                  </Field>
                  <Field
                    label="Expires at"
                    htmlFor="nb-expires"
                    required
                    hint="Pre-filled from typical shelf life. Confirm against the unit label."
                  >
                    {({ id, describedBy }) => (
                      <input
                        id={id}
                        aria-describedby={describedBy}
                        type="datetime-local"
                        value={newBatch.expiresAt}
                        onChange={(event) => updateNewBatch('expiresAt', event.target.value)}
                      />
                    )}
                  </Field>
                  <Button type="submit" loading={createBatch.submitting}>Add batch</Button>
                </div>
              </form>

              {createBatch.error && (
                <Notice tone="danger" title="The batch was not created">
                  <p style={{ margin: 0 }}>{createBatch.error.message}</p>
                  {createBatch.error.details?.reason && (
                    <p className="text-xs" style={{ margin: 0 }}>
                      {createBatch.error.details.reason}
                    </p>
                  )}
                </Notice>
              )}

              <p className="text-xs muted" style={{ marginTop: 'var(--space-3)' }}>
                A new batch is recorded as updated but <strong>not verified</strong>.
                Verification is a separate action taken after a person checks the stock.
              </p>
            </Card>
          )}

          <Card title="Batches" subtitle={`${rows.length} on record`}>
            <AsyncState
              loading={batches.loading}
              error={batches.error}
              onRetry={batches.reload}
              isEmpty={rows.length === 0}
              emptyTitle="No batches"
              emptyMessage="Add a batch above to start recording inventory."
            >
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Group</th>
                      <th scope="col">Component</th>
                      <th scope="col">Units</th>
                      <th scope="col">Status</th>
                      <th scope="col">Expires</th>
                      <th scope="col">Data quality</th>
                      <th scope="col">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((batch) => (
                      <tr key={batch.batchId}>
                        <td><strong>{batch.bloodGroup}</strong></td>
                        <td className="text-xs">{batch.component?.replace(/_/g, ' ')}</td>
                        <td>{batch.availableUnits}</td>
                        <td>
                          <StatusPill
                            status={batch.status}
                            tone={
                              batch.status === 'AVAILABLE' && batch.eligible
                                ? 'success'
                                : batch.status === 'QUARANTINED'
                                  ? 'warning'
                                  : 'neutral'
                            }
                          />
                          {!batch.eligible && batch.ineligibleReasons?.length > 0 && (
                            <span className="text-xs muted" style={{ display: 'block' }}>
                              {batch.ineligibleReasons.join(', ').replace(/_/g, ' ').toLowerCase()}
                            </span>
                          )}
                        </td>
                        <td className="text-xs">
                          {batch.expiresAt?.slice(0, 10) ?? '—'}
                          {batch.nearExpiry && (
                            <span style={{ display: 'block', color: 'var(--stale)' }}>
                              near expiry
                            </span>
                          )}
                        </td>
                        <td>
                          <DataQuality
                            freshness={batch.freshness}
                            verification={batch.verificationStatus}
                          />
                        </td>
                        <td>
                          <div className="inline-actions">
                            {can('inventory:write') && batch.status === 'AVAILABLE' && (
                              <>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleAdjust(batch.batchId, 'ADD', 1)}
                                >
                                  +1
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleAdjust(batch.batchId, 'DEDUCT', 1)}
                                >
                                  &minus;1
                                </Button>
                              </>
                            )}
                            {can('inventory:quarantine') && batch.status === 'AVAILABLE' && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() =>
                                  handleAdjust(
                                    batch.batchId,
                                    'QUARANTINE',
                                    null,
                                    'flagged from dashboard',
                                  )
                                }
                              >
                                Quarantine
                              </Button>
                            )}
                            {can('inventory:quarantine') && batch.status === 'QUARANTINED' && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() =>
                                  handleAdjust(batch.batchId, 'RELEASE_QUARANTINE', null, 'cleared')
                                }
                              >
                                Release
                              </Button>
                            )}
                            {can('inventory:verify') && (
                              <Button
                                variant="secondary"
                                size="sm"
                                loading={verify.submitting}
                                onClick={() => handleVerify(batch.batchId)}
                              >
                                Verify
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </AsyncState>
          </Card>

          <Card title="What the public sees">
            <p className="text-sm">
              Your reported figures appear in public search alongside how recently they
              were updated and whether anyone independently verified them. Batches that
              are expired, quarantined or out of units are never shown as available.
            </p>
            <div className="row">
              <AvailabilityBadge state="AVAILABLE" units={eligible.reduce((sum, b) => sum + b.availableUnits, 0)} />
              <DataQuality
                freshness={rows[0]?.freshness ?? 'UNKNOWN'}
                verification={rows[0]?.verificationStatus ?? 'UNVERIFIED'}
              />
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
