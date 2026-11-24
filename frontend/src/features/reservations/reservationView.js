/**
 * Presentation logic for temporary reservations.
 *
 * Pure and separated from the screens so it can be tested without a browser,
 * the same split used for the map (`components/mapData.js`). What lives here
 * is every decision that could mislead someone if it were wrong: how long a
 * hold has left, whether it still holds units, what a facility may do to it
 * next, and what each state is called in plain words.
 *
 * Three rules this module exists to keep:
 *
 * 1. **A hold is not clinical approval.** CONFIRMED means the facility
 *    accepted the request, nothing more. No label here ever says approved,
 *    cleared, matched or safe.
 * 2. **An expired hold holds nothing**, even if no sweep has rewritten the
 *    row yet. The backend already distinguishes `status` (effective) from
 *    `storedStatus` (raw); this module surfaces that difference instead of
 *    hiding it, because a hold that looks live but is not would send someone
 *    to a facility for units that were released.
 * 3. **Time remaining is computed from the stored expiry**, never from a
 *    duration the client guessed, and never allowed to read as negative.
 */

import { ReservationStatus } from './reservationStatus.js'

export { ReservationStatus }

/** States in which units are genuinely still held. Mirrors the backend. */
export const HOLDING_STATES = Object.freeze([
  ReservationStatus.PENDING,
  ReservationStatus.CONFIRMED,
])

/**
 * Milliseconds until a hold expires, floored at zero.
 *
 * Returns null when there is no usable expiry, so a caller shows "unknown"
 * rather than a fabricated countdown.
 */
export function remainingMs(reservation, now = new Date()) {
  const raw = reservation?.expiresAt
  if (!raw) return null
  const expiry = new Date(raw).getTime()
  if (!Number.isFinite(expiry)) return null
  const current = now instanceof Date ? now.getTime() : new Date(now).getTime()
  if (!Number.isFinite(current)) return null
  return Math.max(0, expiry - current)
}

/**
 * Human countdown: "1 h 58 m left", "4 m left", "Expired".
 *
 * Deliberately coarse. A to-the-second countdown on a two-hour hold invites a
 * precision the system does not have — the facility's clock, the sweep and the
 * user's device are not synchronised — so the smallest unit shown is a minute.
 */
export function formatRemaining(ms) {
  if (ms === null || ms === undefined) return 'Expiry unknown'
  if (ms <= 0) return 'Expired'
  const totalMinutes = Math.floor(ms / 60000)
  if (totalMinutes < 1) return 'Under a minute left'
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours === 0) return `${minutes} m left`
  if (minutes === 0) return `${hours} h left`
  return `${hours} h ${minutes} m left`
}

/** Whether this reservation is still taking units out of other searches. */
export function holdsUnits(reservation, now = new Date()) {
  // Trust the backend's own computed flag when present: it applied the same
  // effective-status rule server-side. Fall back to recomputing only when the
  // field is absent, so an older response is still read correctly.
  if (typeof reservation?.holdsUnits === 'boolean') return reservation.holdsUnits
  if (!HOLDING_STATES.includes(reservation?.status)) return false
  const left = remainingMs(reservation, now)
  return left === null ? false : left > 0
}

/**
 * True when the row says it is holding but its time has already passed.
 *
 * Worth showing rather than smoothing over: it tells a facility that the
 * release sweep has not run yet, which is the difference between "someone
 * still holds these" and "these are free but the record is behind".
 */
export function isStaleHold(reservation) {
  const stored = reservation?.storedStatus
  if (!stored) return false
  return reservation?.status === ReservationStatus.EXPIRED && stored !== ReservationStatus.EXPIRED
}

/** Plain-language status, carefully not clinical. */
export function statusLabel(reservation) {
  switch (reservation?.status) {
    case ReservationStatus.PENDING:
      return 'Awaiting the facility'
    case ReservationStatus.CONFIRMED:
      // "Accepted", never "approved": the facility agreed to hold units, which
      // is an operational answer, not a clinical one.
      return 'Accepted — units held'
    case ReservationStatus.REJECTED:
      return 'Declined by the facility'
    case ReservationStatus.CANCELLED:
      return 'Cancelled'
    case ReservationStatus.EXPIRED:
      return 'Expired'
    case ReservationStatus.FULFILLED:
      return 'Units issued'
    default:
      return 'Unknown'
  }
}

const TONES = {
  [ReservationStatus.PENDING]: 'warning',
  [ReservationStatus.CONFIRMED]: 'success',
  [ReservationStatus.REJECTED]: 'danger',
  [ReservationStatus.CANCELLED]: 'neutral',
  [ReservationStatus.EXPIRED]: 'neutral',
  [ReservationStatus.FULFILLED]: 'info',
}

export function statusTone(status) {
  return TONES[status] ?? 'neutral'
}

/**
 * What facility staff may do to this reservation right now.
 *
 * Mirrors the backend's VALID_TRANSITIONS rather than guessing, so the UI does
 * not offer a button whose request would be refused. The backend remains the
 * authority; this only avoids presenting impossible actions.
 */
export function facilityActions(reservation, now = new Date()) {
  const status = reservation?.status
  const live = remainingMs(reservation, now)
  const expired = live !== null && live <= 0
  if (status === ReservationStatus.PENDING) {
    // An expired request cannot be confirmed, but declining it is still
    // meaningful: it records an answer rather than letting it lapse silently.
    return expired ? ['REJECT'] : ['CONFIRM', 'REJECT']
  }
  if (status === ReservationStatus.CONFIRMED) {
    return expired ? [] : ['FULFIL']
  }
  return []
}

/** Whether the requester may still withdraw. Only the requester can cancel. */
export function canRequesterCancel(reservation, now = new Date()) {
  return holdsUnits(reservation, now)
}

/**
 * The body that cancel, decide and fulfil all require.
 *
 * Blood group and component are part of the reservation's sort key, so every
 * mutating call must carry them. Centralised because omitting one produces a
 * confusing "no such reservation" rather than a validation error.
 */
export function mutationBody(reservation) {
  return {
    bloodGroup: reservation?.bloodGroup,
    component: reservation?.component,
  }
}

/**
 * Split a facility's reservations into the three piles staff actually work in.
 *
 * `needsDecision` first because it is the only pile with a deadline attached:
 * every request sitting there is holding units that nobody has agreed to.
 */
export function partitionForFacility(reservations, now = new Date()) {
  const needsDecision = []
  const held = []
  const closed = []
  for (const reservation of reservations ?? []) {
    if (reservation?.status === ReservationStatus.PENDING) needsDecision.push(reservation)
    else if (reservation?.status === ReservationStatus.CONFIRMED) held.push(reservation)
    else closed.push(reservation)
  }
  const byExpiry = (a, b) => (remainingMs(a, now) ?? 0) - (remainingMs(b, now) ?? 0)
  needsDecision.sort(byExpiry)
  held.sort(byExpiry)
  return { needsDecision, held, closed }
}

/**
 * Split a user's own reservations into live and finished.
 *
 * A hold whose time has passed belongs in history even if its stored row still
 * says PENDING, so this uses the same effective reading as everything else.
 */
export function partitionForRequester(reservations, now = new Date()) {
  const active = []
  const past = []
  for (const reservation of reservations ?? []) {
    if (holdsUnits(reservation, now)) active.push(reservation)
    else past.push(reservation)
  }
  active.sort((a, b) => (remainingMs(a, now) ?? 0) - (remainingMs(b, now) ?? 0))
  past.sort((a, b) => String(b?.createdAt ?? '').localeCompare(String(a?.createdAt ?? '')))
  return { active, past }
}

/** Units a facility currently has spoken for, for a staff-facing summary. */
export function totalHeldUnits(reservations, now = new Date()) {
  return (reservations ?? []).reduce(
    (sum, reservation) =>
      holdsUnits(reservation, now) ? sum + (Number(reservation.units) || 0) : sum,
    0,
  )
}
