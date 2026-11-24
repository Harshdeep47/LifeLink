/**
 * Reservation lifecycle states, mirroring `backend/src/domain/reservations.py`.
 *
 * Kept in one place and imported everywhere rather than written as string
 * literals in each screen. The states are a backend contract, and a typo in a
 * comparison against a literal fails silently — a reservation simply stops
 * matching any branch and renders as "Unknown" with no error anywhere.
 */
export const ReservationStatus = Object.freeze({
  PENDING: 'PENDING',
  CONFIRMED: 'CONFIRMED',
  REJECTED: 'REJECTED',
  CANCELLED: 'CANCELLED',
  EXPIRED: 'EXPIRED',
  FULFILLED: 'FULFILLED',
})

/** Every state, for exhaustiveness checks in tests. */
export const ALL_RESERVATION_STATUSES = Object.freeze(Object.values(ReservationStatus))
