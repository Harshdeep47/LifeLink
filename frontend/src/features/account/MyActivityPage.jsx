/**
 * My activity — the things a user has asked for that had nowhere to live.
 *
 * Scope is deliberately narrow, and the narrowing is the design. Two of the
 * four things a user can personally hold already have a home:
 *
 * *   availability alerts are listed, created and cancelled on `/alerts`;
 * *   camp registrations are listed with attendance state on the donor
 *     dashboard.
 *
 * Repeating either here would have produced two screens showing the same rows
 * with different affordances — the kind of duplication that makes a dashboard
 * look busy while telling you less. So this page covers only what genuinely
 * had no screen, and links to the two that do.
 *
 * What had no screen:
 *
 * *   **Reservations.** `GET /me/reservations` had no caller anywhere in the
 *     frontend. A hold became unfindable the moment the page was left, while
 *     still holding units out of every other user's search results — the worst
 *     combination available: invisible to its owner, consequential for
 *     everyone else.
 * *   **Emergency requests raised by this user.** The hospital dashboard lists
 *     an organization's requests, but a donor or member of the public who
 *     raised one had no list of their own.
 *
 * No new endpoint is introduced. Both were already deployed and authorized.
 */
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { PriorityBadge, RequestStatusPill, StatusPill } from '../../components/StatusBadges.jsx'
import { AsyncState, Button, Card, Notice } from '../../components/ui.jsx'
import { useAuth } from '../../auth/AuthContext.jsx'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import {
  canRequesterCancel,
  formatRemaining,
  isStaleHold,
  mutationBody,
  partitionForRequester,
  remainingMs,
  statusLabel,
  statusTone,
} from '../reservations/reservationView.js'

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

function groupLabel(record) {
  return `${String(record?.bloodGroup ?? '').replace(/_/g, '-')} ${record?.component ?? ''}`.trim()
}

/* ------------------------------------------------------------------ */
/* Reservations — the gap this page exists to close                    */
/* ------------------------------------------------------------------ */

function ReservationsSection() {
  const { data, loading, error, reload } = useApiData(() => api.myReservations(), [])
  const cancel = useMutation((reservation) =>
    api.cancelReservation(
      reservation.facilityId,
      reservation.reservationId,
      mutationBody(reservation),
    ),
  )

  const list = Array.isArray(data) ? data : []
  const { active, past } = partitionForRequester(list)

  async function onCancel(reservation) {
    try {
      await cancel.run(reservation)
      reload()
    } catch {
      // useMutation owns the error; it is rendered below.
    }
  }

  return (
    <Card
      title="My reservations"
      subtitle="Temporary holds you have placed on units at a facility"
      actions={
        <Button variant="ghost" size="sm" onClick={reload} loading={loading}>
          Refresh
        </Button>
      }
    >
      <AsyncState
        loading={loading}
        error={error}
        onRetry={reload}
        isEmpty={list.length === 0}
        emptyTitle="No reservations"
        emptyMessage="When you hold units at a facility, they appear here with the time remaining and a way to release them."
        emptyAction={
          <Link className="btn btn--secondary btn--sm" to="/find">
            Find blood
          </Link>
        }
      >
        <>
          {cancel.error && (
            <Notice tone="warning" title="That did not go through">
              {cancel.error.message ??
                'The cancellation was refused. Reload and try again.'}
            </Notice>
          )}

          {active.length > 0 && (
            <>
              <Notice tone="info">
                A hold keeps units out of other people&apos;s searches until it
                expires. It is <strong>not</strong> clinical approval. If you no
                longer need one, cancel it so the units return to availability.
              </Notice>
              <ul className="activity">
                {active.map((reservation) => (
                  <li className="activity__row" key={reservation.reservationId}>
                    <div className="activity__main">
                      <p className="activity__headline">
                        <strong>
                          {reservation.units} unit
                          {reservation.units === 1 ? '' : 's'}
                        </strong>{' '}
                        {groupLabel(reservation)}
                      </p>
                      <p className="text-xs muted">
                        <Link to={`/facilities/${reservation.facilityId}`}>
                          View facility
                        </Link>{' '}
                        · placed {formatWhen(reservation.createdAt)}
                      </p>
                      {isStaleHold(reservation) && (
                        <p className="text-xs muted">
                          This hold&apos;s time has passed, so the units have been
                          released even though the record still shows the older
                          state.
                        </p>
                      )}
                    </div>
                    <div className="activity__status">
                      <StatusPill
                        status={statusLabel(reservation)}
                        tone={statusTone(reservation.status)}
                      />
                      <span className="text-xs muted">
                        {formatRemaining(remainingMs(reservation))}
                      </span>
                    </div>
                    <div className="activity__actions">
                      {canRequesterCancel(reservation) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={cancel.submitting}
                          onClick={() => onCancel(reservation)}
                        >
                          Cancel hold
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {active.length === 0 && past.length > 0 && (
            <p className="text-sm muted">
              You have no live holds. Earlier reservations are below.
            </p>
          )}

          {past.length > 0 && (
            <details className="activity__history">
              <summary>Earlier reservations ({past.length})</summary>
              <ul className="activity">
                {past.map((reservation) => (
                  <li className="activity__row" key={reservation.reservationId}>
                    <div className="activity__main">
                      <p className="activity__headline">
                        {reservation.units} × {groupLabel(reservation)}
                      </p>
                      <p className="text-xs muted">
                        {formatWhen(reservation.createdAt)}
                        {reservation.decisionReason
                          ? ` · ${reservation.decisionReason}`
                          : ''}
                      </p>
                    </div>
                    <div className="activity__status">
                      <StatusPill
                        status={statusLabel(reservation)}
                        tone={statusTone(reservation.status)}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      </AsyncState>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Emergency requests raised by this user                              */
/* ------------------------------------------------------------------ */

function EmergencySection() {
  const { data, loading, error, reload } = useApiData(
    () => api.listEmergencyRequests(),
    [],
  )
  const list = Array.isArray(data) ? data : (data?.items ?? [])

  return (
    <Card
      title="My emergency requests"
      subtitle="A different workflow from reservations: coordinated across providers, and clinically prioritised only by a verified hospital"
      actions={
        <Button variant="ghost" size="sm" onClick={reload} loading={loading}>
          Refresh
        </Button>
      }
    >
      <AsyncState
        loading={loading}
        error={error}
        onRetry={reload}
        isEmpty={list.length === 0}
        emptyTitle="No emergency requests"
        emptyMessage="Emergency requests you raise appear here with their coordination status."
        emptyAction={
          <Link className="btn btn--secondary btn--sm" to="/emergency">
            Open the emergency workflow
          </Link>
        }
      >
        <ul className="activity">
          {list.map((request) => (
            <li className="activity__row" key={request.requestId}>
              <div className="activity__main">
                <p className="activity__headline">
                  <Link to={`/emergency/${request.requestId}`}>
                    {request.unitsRequired ?? request.units} ×{' '}
                    {groupLabel(request)}
                  </Link>
                </p>
                <p className="text-xs muted">
                  Raised {formatWhen(request.createdAt)}
                  {request.requiredBy
                    ? ` · needed by ${formatWhen(request.requiredBy)}`
                    : ''}
                </p>
              </div>
              <div className="activity__status">
                {request.status && <RequestStatusPill status={request.status} />}
                {/* Priority appears only once a verified hospital has
                    certified it. An uncertified request carries no clinical
                    priority, and showing a default would manufacture one. */}
                {request.clinicalPriority ? (
                  <PriorityBadge priority={request.clinicalPriority} />
                ) : (
                  <span className="text-xs muted">Not clinically certified</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      </AsyncState>
    </Card>
  )
}

/* ------------------------------------------------------------------ */

export default function MyActivityPage() {
  const { can } = useAuth()
  const showReservations = can('reservation:manage:own')
  const showEmergency = can('emergency:read:own')

  return (
    <div className="stack">
      <header className="page-header">
        <h1>My activity</h1>
        <p className="page-header__lead">
          Holds you have placed and emergency requests you have raised.
        </p>
      </header>

      {showReservations && <ReservationsSection />}
      {showEmergency && <EmergencySection />}

      {!showReservations && !showEmergency && (
        <Card title="Nothing to show here">
          <p className="text-sm">
            Your account does not use reservations or emergency requests. If you
            manage a facility, incoming requests are on your{' '}
            <Link to="/dashboard/blood-bank">blood bank dashboard</Link>.
          </p>
        </Card>
      )}

      <Card title="Elsewhere in your account">
        <ul className="link-list">
          <li>
            <Link to="/alerts">Availability alerts</Link> — create, review and
            cancel the alerts watching for stock near you.
          </li>
          <li>
            <Link to="/dashboard/donor">Donor dashboard</Link> — camp
            registrations, donation history and notification preferences.
          </li>
          <li>
            <Link to="/profile">Profile</Link> — your details and organization
            access.
          </li>
        </ul>
      </Card>
    </div>
  )
}
