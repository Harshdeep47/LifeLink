/**
 * Request a temporary hold on units at one facility.
 *
 * Deliberately not a one-click "Reserve" button next to a number. A hold takes
 * units out of everyone else's search results, so the control asks for the
 * group, the component and the quantity explicitly, and states what the hold
 * does and does not mean before it is placed.
 *
 * Everything shown comes from the API. The panel holds no stock knowledge of
 * its own: it offers what `/facilities/{id}/availability` reported as
 * unreserved, and the backend re-validates and re-checks atomically, so a
 * stale panel cannot oversell.
 */
import { useState } from 'react'

import { api } from '../../api/client.js'
import { useAuth } from '../../auth/AuthContext.jsx'
import { Button, Card, Field, Notice } from '../../components/ui.jsx'

/** Cells a user could actually hold units from. */
function reservableCells(matrix) {
  return matrix.filter(
    (cell) =>
      cell.availability !== 'UNKNOWN' &&
      cell.availability !== 'NOT_STOCKED' &&
      (cell.unreservedUnits ?? cell.eligibleUnits ?? 0) > 0,
  )
}

export function ReservationPanel({ facilityId, facilityName, matrix, onPlaced }) {
  const { isAuthenticated, can } = useAuth()
  const options = reservableCells(matrix ?? [])
  const [selected, setSelected] = useState('')
  const [units, setUnits] = useState('1')
  const [holdMinutes, setHoldMinutes] = useState('120')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Rendered, not hidden: a user should be able to see the capability exists
  // and what it needs, rather than wonder why nothing is offered. The backend
  // is the authority either way.
  if (!isAuthenticated) {
    return (
      <Card title="Temporary reservation">
        <p className="text-sm">
          Sign in to hold units at {facilityName} for a limited time. A hold
          takes those units out of other searches until it expires or is
          released.
        </p>
      </Card>
    )
  }

  if (!can('reservation:create')) {
    return (
      <Card title="Temporary reservation">
        <p className="text-sm">
          Your account cannot request reservations. Facility staff manage
          incoming requests from the blood bank dashboard instead.
        </p>
      </Card>
    )
  }

  if (options.length === 0) {
    return (
      <Card title="Temporary reservation">
        <p className="text-sm">
          There are no unreserved units here to hold right now. Figures can
          change; try again after searching.
        </p>
      </Card>
    )
  }

  const chosen = options.find((c) => `${c.bloodGroup}|${c.component}` === selected)
  const maxUnits = Math.min(
    10,
    chosen ? (chosen.unreservedUnits ?? chosen.eligibleUnits ?? 1) : 10,
  )

  const submit = async (event) => {
    event.preventDefault()
    if (!chosen) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const reservation = await api.requestReservation(facilityId, {
        bloodGroup: chosen.bloodGroup,
        component: chosen.component,
        units: Number(units),
        holdMinutes: Number(holdMinutes),
      })
      setResult(reservation)
      onPlaced?.(reservation)
    } catch (cause) {
      // The backend's reason code is the useful part; its message is written
      // for a human and is shown as-is.
      setError(cause?.message ?? 'The reservation could not be placed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Temporary reservation"
      subtitle="Holds specific units for a limited time"
    >
      {result ? (
        <Notice tone="success" title="Units held">
          <p className="text-sm">
            {result.units} unit(s) of {result.bloodGroup} {result.component} are
            held until{' '}
            <strong>{new Date(result.expiresAt).toLocaleString()}</strong>.
            Status: {result.status}.
          </p>
          <p className="text-xs" style={{ margin: 0 }}>
            {result.notice}
          </p>
        </Notice>
      ) : null}

      <form onSubmit={submit}>
        <Field label="Blood group and component" htmlFor="res-pool">
          {({ id }) => (
            <select
              id={id}
              value={selected}
              onChange={(event) => {
                setSelected(event.target.value)
                setUnits('1')
              }}
            >
              <option value="">Choose…</option>
              {options.map((cell) => {
                const key = `${cell.bloodGroup}|${cell.component}`
                const free = cell.unreservedUnits ?? cell.eligibleUnits
                return (
                  <option key={key} value={key}>
                    {cell.bloodGroup} {cell.component.replace(/_/g, ' ')} —{' '}
                    {free} unreserved
                  </option>
                )
              })}
            </select>
          )}
        </Field>

        <Field
          label="Units"
          htmlFor="res-units"
          hint={chosen ? `Up to ${maxUnits} may be held in one request.` : null}
        >
          {({ id }) => (
            <input
              id={id}
              type="number"
              min="1"
              max={maxUnits}
              value={units}
              onChange={(event) => setUnits(event.target.value)}
            />
          )}
        </Field>

        <Field label="Hold for" htmlFor="res-minutes">
          {({ id }) => (
            <select
              id={id}
              value={holdMinutes}
              onChange={(event) => setHoldMinutes(event.target.value)}
            >
              <option value="30">30 minutes</option>
              <option value="60">1 hour</option>
              <option value="120">2 hours</option>
              <option value="240">4 hours</option>
              <option value="480">8 hours (maximum)</option>
            </select>
          )}
        </Field>

        <p className="inline-note">
          A reservation holds these units so nobody else is offered them. It is{' '}
          <strong>not clinical approval</strong>, not a cross-match, and not a
          guarantee of release — compatibility and release stay with qualified
          staff at the facility. The hold is released automatically when it
          expires.
        </p>

        {error ? (
          <p className="field__error" role="alert">{error}</p>
        ) : null}

        <Button type="submit" disabled={busy || !chosen || Number(units) < 1}>
          {busy ? 'Requesting…' : 'Request reservation'}
        </Button>
      </form>
    </Card>
  )
}
