/**
 * Incoming reservation requests, for facility staff.
 *
 * This screen is the provider half of the request workflow. The backend has
 * had it since reservations were built — `GET /facilities/{id}/reservations`,
 * `.../decision` and `.../fulfil` are all live, authorized and tested — but
 * nothing in the interface reached them, so requests arrived at a facility
 * that had no way to answer. `ReservationPanel` even told requesters that
 * "facility staff manage incoming requests from the blood bank dashboard",
 * which was not true until this screen existed.
 *
 * Nothing new is added to the API here. This is a window onto endpoints that
 * were already deployed.
 *
 * Two deliberate choices:
 *
 * *   **Requests awaiting a decision come first**, ordered by how soon they
 *     lapse. Every row in that pile is holding units nobody has agreed to,
 *     so it is the only pile with a clock against it.
 * *   **Declining asks for a reason.** The requester sees it. A hold that
 *     vanishes with no explanation reads as a system fault, and the person
 *     on the other end may be about to travel.
 */
import { useState } from 'react'

import { api } from '../../api/client.js'
import { StatusPill } from '../../components/StatusBadges.jsx'
import { AsyncState, Button, Card, EmptyPanel, Field, Notice } from '../../components/ui.jsx'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import {
  facilityActions,
  formatRemaining,
  isStaleHold,
  mutationBody,
  partitionForFacility,
  remainingMs,
  statusLabel,
  statusTone,
  totalHeldUnits,
} from './reservationView.js'

function groupLabel(reservation) {
  return `${String(reservation.bloodGroup ?? '').replace(/_/g, '-')} ${reservation.component ?? ''}`
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

/**
 * One request, with whatever actions are genuinely available on it.
 *
 * The available actions come from `facilityActions`, which mirrors the
 * backend's permitted transitions. An expired request cannot be confirmed, so
 * that button is not rendered — offering it and then showing the refusal would
 * be a worse experience than not offering it.
 */
function ReservationRow({ reservation, onDecide, onFulfil, busy }) {
  const [reason, setReason] = useState('')
  const [showDecline, setShowDecline] = useState(false)
  const actions = facilityActions(reservation)
  const left = remainingMs(reservation)
  const stale = isStaleHold(reservation)

  return (
    <li className="queue__row">
      <div className="queue__main">
        <p className="queue__headline">
          <strong>
            {reservation.units} unit{reservation.units === 1 ? '' : 's'}
          </strong>{' '}
          {groupLabel(reservation)}
        </p>
        <p className="text-xs muted">
          Requested {formatWhen(reservation.createdAt)} · reference{' '}
          <code>{reservation.reservationId}</code>
        </p>
        {reservation.decisionReason && (
          <p className="text-xs muted">Reason on record: {reservation.decisionReason}</p>
        )}
      </div>

      <div className="queue__status">
        <StatusPill
          status={statusLabel(reservation)}
          tone={statusTone(reservation.status)}
        />
        <span className="text-xs muted">{formatRemaining(left)}</span>
        {stale && (
          <span className="text-xs muted">
            Its time has passed; the release sweep has not run yet.
          </span>
        )}
      </div>

      <div className="queue__actions">
        {actions.includes('CONFIRM') && (
          <Button
            size="sm"
            loading={busy}
            onClick={() => onDecide(reservation, 'CONFIRM', '')}
          >
            Accept
          </Button>
        )}
        {actions.includes('FULFIL') && (
          <Button size="sm" loading={busy} onClick={() => onFulfil(reservation)}>
            Record units issued
          </Button>
        )}
        {actions.includes('REJECT') && !showDecline && (
          <Button variant="ghost" size="sm" onClick={() => setShowDecline(true)}>
            Decline
          </Button>
        )}
        {actions.length === 0 && <span className="text-xs muted">No action available</span>}
      </div>

      {showDecline && (
        <form
          className="queue__decline"
          onSubmit={(event) => {
            event.preventDefault()
            onDecide(reservation, 'REJECT', reason.trim())
          }}
        >
          <Field
            label="Why is this being declined?"
            htmlFor={`decline-${reservation.reservationId}`}
            hint="The requester sees this. Say whether they should try elsewhere."
            required
          >
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                value={reason}
                maxLength={200}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. units quarantined pending re-test"
              />
            )}
          </Field>
          <div className="queue__decline-actions">
            <Button
              type="submit"
              variant="danger"
              size="sm"
              loading={busy}
              disabled={reason.trim().length < 3}
            >
              Confirm decline
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setShowDecline(false)
                setReason('')
              }}
            >
              Keep it open
            </Button>
          </div>
        </form>
      )}
    </li>
  )
}

export function ReservationQueue({ facilityId, facilityName }) {
  const { data, loading, error, reload } = useApiData(
    () => api.facilityReservations(facilityId),
    [facilityId],
    { enabled: Boolean(facilityId) },
  )

  const decide = useMutation(({ reservation, decision, reason }) =>
    api.decideReservation(facilityId, reservation.reservationId, {
      ...mutationBody(reservation),
      decision,
      reason: reason || undefined,
    }),
  )
  const fulfil = useMutation((reservation) =>
    api.fulfilReservation(facilityId, reservation.reservationId, mutationBody(reservation)),
  )

  if (!facilityId) {
    return (
      <Card title="Reservation requests">
        <p className="text-sm muted">Choose a facility to see its requests.</p>
      </Card>
    )
  }

  const reservations = data?.items ?? data ?? []
  const list = Array.isArray(reservations) ? reservations : []
  const { needsDecision, held, closed } = partitionForFacility(list)
  const heldUnits = totalHeldUnits(list)
  const busy = decide.submitting || fulfil.submitting

  async function onDecide(reservation, decision, reason) {
    try {
      await decide.run({ reservation, decision, reason })
      reload()
    } catch {
      // useMutation holds the error; it is rendered below.
    }
  }

  async function onFulfil(reservation) {
    try {
      await fulfil.run(reservation)
      reload()
    } catch {
      // as above
    }
  }

  return (
    <Card
      title="Reservation requests"
      subtitle={
        facilityName
          ? `Temporary holds against ${facilityName}`
          : 'Temporary holds against this facility'
      }
      actions={
        <Button variant="ghost" size="sm" onClick={reload} loading={loading}>
          Refresh
        </Button>
      }
    >
      <Notice tone="info">
        Accepting a request means your facility agrees to hold these units until
        the hold expires. It is <strong>not</strong> a cross-match and not
        clinical approval — compatibility and release stay with your qualified
        staff.
      </Notice>

      <AsyncState loading={loading} error={error} onRetry={reload}>
        <>
          <p className="text-sm">
            <strong>{heldUnits}</strong> unit{heldUnits === 1 ? '' : 's'} currently
            held across <strong>{needsDecision.length + held.length}</strong> live
            reservation{needsDecision.length + held.length === 1 ? '' : 's'}. Held
            units do not appear as available in other users&apos; searches.
          </p>

          {(decide.error || fulfil.error) && (
            <Notice tone="warning" title="That did not go through">
              {(decide.error || fulfil.error)?.message ??
                'The request was refused. Reload and try again.'}
            </Notice>
          )}

          <h4 className="queue__heading">
            Awaiting your decision ({needsDecision.length})
          </h4>
          {needsDecision.length === 0 ? (
            <EmptyPanel
              title="Nothing waiting"
              message="New requests appear here, soonest to lapse first."
            />
          ) : (
            <ul className="queue">
              {needsDecision.map((reservation) => (
                <ReservationRow
                  key={reservation.reservationId}
                  reservation={reservation}
                  onDecide={onDecide}
                  onFulfil={onFulfil}
                  busy={busy}
                />
              ))}
            </ul>
          )}

          <h4 className="queue__heading">Accepted and holding ({held.length})</h4>
          {held.length === 0 ? (
            <p className="text-sm muted">No accepted holds right now.</p>
          ) : (
            <ul className="queue">
              {held.map((reservation) => (
                <ReservationRow
                  key={reservation.reservationId}
                  reservation={reservation}
                  onDecide={onDecide}
                  onFulfil={onFulfil}
                  busy={busy}
                />
              ))}
            </ul>
          )}

          {closed.length > 0 && (
            <details className="queue__history">
              <summary>Closed requests ({closed.length})</summary>
              <ul className="queue">
                {closed.map((reservation) => (
                  <ReservationRow
                    key={reservation.reservationId}
                    reservation={reservation}
                    onDecide={onDecide}
                    onFulfil={onFulfil}
                    busy={busy}
                  />
                ))}
              </ul>
            </details>
          )}
        </>
      </AsyncState>
    </Card>
  )
}
