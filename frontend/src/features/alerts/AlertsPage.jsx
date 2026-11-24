/**
 * Short-term availability alerts.
 *
 * The screen repeats, in several places, that an alert is informational. That
 * repetition is intentional: an alert that fires saying "4 units available
 * 2 km away" is exactly the moment a user is most likely to assume something
 * has been set aside for them.
 */
import { useState } from 'react'

import { api } from '../../api/client.js'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import {
  AsyncState,
  Button,
  Card,
  Field,
  NotAReservationNotice,
  Notice,
} from '../../components/ui.jsx'
import { AvailabilityBadge, StatusPill } from '../../components/StatusBadges.jsx'

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const COMPONENTS = [
  { value: 'PRBC', label: 'PRBC' },
  { value: 'WHOLE_BLOOD', label: 'Whole blood' },
  { value: 'FFP', label: 'FFP' },
  { value: 'PLATELETS', label: 'Platelets' },
]

const STATUS_TONES = {
  ACTIVE: 'success',
  MATCHED: 'info',
  CANCELLED: 'neutral',
  EXPIRED: 'neutral',
  DEADLINE_PASSED: 'warning',
}

export function AlertsPage() {
  const [form, setForm] = useState({
    bloodGroup: 'O-',
    component: 'PRBC',
    requiredUnits: 2,
    latitude: '30.3398',
    longitude: '76.3869',
    radiusKm: 15,
  })

  const { data: alerts, loading, error, reload } = useApiData(() => api.listAlerts(), [])

  const create = useMutation((body) => api.createAlert(body))
  const cancel = useMutation((alertId) => api.cancelAlert(alertId))

  async function handleCreate(event) {
    event.preventDefault()
    try {
      await create.run({
        bloodGroup: form.bloodGroup,
        component: form.component,
        requiredUnits: Number(form.requiredUnits),
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        radiusKm: Number(form.radiusKm),
      })
      reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleCancel(alertId) {
    try {
      await cancel.run(alertId)
      reload()
    } catch {
      /* rendered below */
    }
  }

  function update(field, value) {
    setForm((previous) => ({ ...previous, [field]: value }))
  }

  const list = Array.isArray(alerts) ? alerts : []

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Availability alerts</h1>
        <p>
          Tell LifeLink what you need and you will be notified if a nearby facility
          reports matching stock.
        </p>
      </header>

      <NotAReservationNotice />

      <div className="grid grid--2">
        <Card title="Create an alert">
          <form onSubmit={handleCreate}>
            <div className="grid grid--2">
              <Field label="Blood group" htmlFor="alert-group" required>
                {({ id }) => (
                  <select
                    id={id}
                    value={form.bloodGroup}
                    onChange={(event) => update('bloodGroup', event.target.value)}
                  >
                    {BLOOD_GROUPS.map((group) => (
                      <option key={group} value={group}>{group}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Component" htmlFor="alert-component" required>
                {({ id }) => (
                  <select
                    id={id}
                    value={form.component}
                    onChange={(event) => update('component', event.target.value)}
                  >
                    {COMPONENTS.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Units needed" htmlFor="alert-units" required>
                {({ id }) => (
                  <input
                    id={id}
                    type="number"
                    min="1"
                    max="50"
                    value={form.requiredUnits}
                    onChange={(event) => update('requiredUnits', event.target.value)}
                  />
                )}
              </Field>
              <Field label="Search radius (km)" htmlFor="alert-radius" required>
                {({ id }) => (
                  <input
                    id={id}
                    type="number"
                    min="1"
                    max="50"
                    value={form.radiusKm}
                    onChange={(event) => update('radiusKm', event.target.value)}
                  />
                )}
              </Field>
              <Field label="Latitude" htmlFor="alert-lat" required>
                {({ id }) => (
                  <input
                    id={id}
                    type="text"
                    inputMode="decimal"
                    value={form.latitude}
                    onChange={(event) => update('latitude', event.target.value)}
                  />
                )}
              </Field>
              <Field label="Longitude" htmlFor="alert-lon" required>
                {({ id }) => (
                  <input
                    id={id}
                    type="text"
                    inputMode="decimal"
                    value={form.longitude}
                    onChange={(event) => update('longitude', event.target.value)}
                  />
                )}
              </Field>
            </div>

            {create.error && (
              <Notice tone="danger" title="The alert was not created">
                <p style={{ margin: 0 }}>{create.error.message}</p>
              </Notice>
            )}

            <Button type="submit" loading={create.submitting}>Create alert</Button>
          </form>

          {create.result?.immediateMatches?.length > 0 && (
            <Notice tone="success" title="Matching stock found right now">
              <ul className="text-sm">
                {create.result.immediateMatches.map((match) => (
                  <li key={match.facilityId}>
                    {match.facilityName}: {match.eligibleUnits} unit(s),{' '}
                    {match.straightLineKm} km straight-line
                  </li>
                ))}
              </ul>
              <p className="text-xs" style={{ marginBottom: 0 }}>
                Telephone the facility to confirm. Nothing is held for you.
              </p>
            </Notice>
          )}
        </Card>

        <Card title="My alerts">
          <AsyncState
            loading={loading}
            error={error}
            onRetry={reload}
            isEmpty={list.length === 0}
            emptyTitle="No alerts yet"
            emptyMessage="Create one and you will be notified when matching stock is reported nearby."
          >
            <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {list.map((alert) => (
                <li key={alert.alertId} className="card" style={{ padding: 'var(--space-3)' }}>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <div>
                      <strong>
                        {alert.bloodGroup} {alert.component?.replace(/_/g, ' ')}
                      </strong>
                      <span className="text-sm muted"> · {alert.requiredUnits} unit(s)</span>
                    </div>
                    <StatusPill
                      status={alert.status}
                      tone={STATUS_TONES[alert.status] ?? 'neutral'}
                    />
                  </div>
                  <p className="text-xs muted" style={{ margin: 'var(--space-1) 0 0' }}>
                    Within {alert.radiusKm} km · expires {alert.expiresAt}
                  </p>
                  {alert.status === 'ACTIVE' && (
                    <div className="row" style={{ marginTop: 'var(--space-2)' }}>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleCancel(alert.alertId)}
                        loading={cancel.submitting}
                      >
                        Cancel
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </AsyncState>
        </Card>
      </div>

      <Card title="What an alert does and does not do">
        <div className="grid grid--2">
          <div>
            <h4 className="text-sm">It does</h4>
            <ul className="text-sm muted">
              <li>Watch for matching eligible stock near your chosen location.</li>
              <li>Notify you when stock appears, or materially changes.</li>
              <li>Tell you how fresh the facility&rsquo;s data is.</li>
              <li>Expire automatically at your deadline.</li>
            </ul>
          </div>
          <div>
            <h4 className="text-sm">It does not</h4>
            <ul className="text-sm muted">
              <li>Reserve, hold or allocate any units.</li>
              <li>Guarantee the stock will still be there when you arrive.</li>
              <li>Confirm the blood is clinically suitable for a patient.</li>
              <li>Replace telephoning the facility.</li>
            </ul>
          </div>
        </div>
        <div style={{ marginTop: 'var(--space-3)' }}>
          <AvailabilityBadge state="UNKNOWN" />
          <span className="text-xs muted" style={{ marginLeft: 'var(--space-2)' }}>
            Facilities that have reported nothing are never matched, because unreported
            is not the same as in stock.
          </span>
        </div>
      </Card>
    </div>
  )
}
