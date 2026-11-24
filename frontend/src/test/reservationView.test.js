/**
 * Reservation presentation logic.
 *
 * The screens need a browser; these decisions do not, and they are the ones
 * that could mislead a user: a countdown that reads as live when the hold has
 * lapsed, a button offering an action the backend will refuse, or a label that
 * turns an operational acceptance into a clinical one.
 */
import { describe, expect, it } from 'vitest'

import {
  ReservationStatus,
  canRequesterCancel,
  facilityActions,
  formatRemaining,
  holdsUnits,
  isStaleHold,
  mutationBody,
  partitionForFacility,
  partitionForRequester,
  remainingMs,
  statusLabel,
  statusTone,
  totalHeldUnits,
} from '../features/reservations/reservationView.js'
import { ALL_RESERVATION_STATUSES } from '../features/reservations/reservationStatus.js'

const NOW = new Date('2026-11-24T10:00:00Z')

/** A reservation as the API actually serialises one. */
function reservation(overrides = {}) {
  return {
    reservationId: 'res-1',
    facilityId: 'fac-patiala-1',
    bloodGroup: 'O_NEG',
    component: 'PRBC',
    units: 2,
    status: ReservationStatus.PENDING,
    storedStatus: ReservationStatus.PENDING,
    holdsUnits: true,
    createdAt: '2026-11-24T09:00:00Z',
    expiresAt: '2026-11-24T11:00:00Z',
    isReservation: true,
    isClinicalApproval: false,
    ...overrides,
  }
}

describe('remainingMs', () => {
  it('measures from the stored expiry', () => {
    expect(remainingMs(reservation(), NOW)).toBe(60 * 60 * 1000)
  })

  it('never returns a negative remainder', () => {
    const past = reservation({ expiresAt: '2026-11-24T09:30:00Z' })
    expect(remainingMs(past, NOW)).toBe(0)
  })

  it('returns null rather than a guess when expiry is missing', () => {
    expect(remainingMs(reservation({ expiresAt: null }), NOW)).toBeNull()
    expect(remainingMs(reservation({ expiresAt: undefined }), NOW)).toBeNull()
    expect(remainingMs({}, NOW)).toBeNull()
  })

  it('returns null for an unparseable expiry instead of NaN', () => {
    expect(remainingMs(reservation({ expiresAt: 'not a date' }), NOW)).toBeNull()
  })
})

describe('formatRemaining', () => {
  it('reports hours and minutes', () => {
    expect(formatRemaining(118 * 60 * 1000)).toBe('1 h 58 m left')
  })

  it('omits minutes on the hour', () => {
    expect(formatRemaining(2 * 60 * 60 * 1000)).toBe('2 h left')
  })

  it('reports minutes alone under an hour', () => {
    expect(formatRemaining(4 * 60 * 1000)).toBe('4 m left')
  })

  it('says Expired at or below zero', () => {
    expect(formatRemaining(0)).toBe('Expired')
    expect(formatRemaining(-5000)).toBe('Expired')
  })

  it('does not round a live hold down to "Expired"', () => {
    expect(formatRemaining(30 * 1000)).toBe('Under a minute left')
  })

  it('says expiry is unknown rather than inventing a figure', () => {
    expect(formatRemaining(null)).toBe('Expiry unknown')
    expect(formatRemaining(undefined)).toBe('Expiry unknown')
  })
})

describe('holdsUnits', () => {
  it('trusts the backend flag when present', () => {
    expect(holdsUnits(reservation({ holdsUnits: false }), NOW)).toBe(false)
    expect(holdsUnits(reservation({ holdsUnits: true }), NOW)).toBe(true)
  })

  it('recomputes when the flag is absent', () => {
    const r = reservation({ holdsUnits: undefined })
    expect(holdsUnits(r, NOW)).toBe(true)
  })

  it('treats a lapsed hold as holding nothing even if the row says PENDING', () => {
    const lapsed = reservation({
      holdsUnits: undefined,
      expiresAt: '2026-11-24T09:00:00Z',
    })
    expect(holdsUnits(lapsed, NOW)).toBe(false)
  })

  it.each([
    ReservationStatus.REJECTED,
    ReservationStatus.CANCELLED,
    ReservationStatus.EXPIRED,
    ReservationStatus.FULFILLED,
  ])('holds nothing in terminal state %s', (status) => {
    expect(holdsUnits(reservation({ status, holdsUnits: undefined }), NOW)).toBe(false)
  })
})

describe('isStaleHold', () => {
  it('flags a row the sweep has not caught up with', () => {
    const stale = reservation({
      status: ReservationStatus.EXPIRED,
      storedStatus: ReservationStatus.PENDING,
    })
    expect(isStaleHold(stale)).toBe(true)
  })

  it('does not flag a properly expired row', () => {
    const settled = reservation({
      status: ReservationStatus.EXPIRED,
      storedStatus: ReservationStatus.EXPIRED,
    })
    expect(isStaleHold(settled)).toBe(false)
  })

  it('does not flag a live hold', () => {
    expect(isStaleHold(reservation())).toBe(false)
  })
})

describe('statusLabel', () => {
  it('never describes an acceptance as clinical approval', () => {
    const label = statusLabel(reservation({ status: ReservationStatus.CONFIRMED }))
    expect(label).toBe('Accepted — units held')
    for (const word of ['approv', 'cleared', 'match', 'safe', 'compatible']) {
      expect(label.toLowerCase()).not.toContain(word)
    }
  })

  it('gives every backend state a human label, not a raw enum', () => {
    for (const status of ALL_RESERVATION_STATUSES) {
      const label = statusLabel({ status })
      expect(label).not.toBe('Unknown')
      expect(label).not.toBe(status)
    }
  })

  it('falls back to Unknown for an unrecognised state rather than throwing', () => {
    expect(statusLabel({ status: 'WAT' })).toBe('Unknown')
    expect(statusLabel(undefined)).toBe('Unknown')
  })
})

describe('facilityActions', () => {
  it('offers confirm and decline on a live request', () => {
    expect(facilityActions(reservation(), NOW)).toEqual(['CONFIRM', 'REJECT'])
  })

  it('will not offer to confirm a request that has already lapsed', () => {
    const lapsed = reservation({ expiresAt: '2026-11-24T09:00:00Z' })
    expect(facilityActions(lapsed, NOW)).toEqual(['REJECT'])
  })

  it('offers fulfilment only on a live accepted hold', () => {
    const confirmed = reservation({ status: ReservationStatus.CONFIRMED })
    expect(facilityActions(confirmed, NOW)).toEqual(['FULFIL'])
  })

  it('offers nothing on a lapsed accepted hold', () => {
    const confirmed = reservation({
      status: ReservationStatus.CONFIRMED,
      expiresAt: '2026-11-24T09:00:00Z',
    })
    expect(facilityActions(confirmed, NOW)).toEqual([])
  })

  it.each([
    ReservationStatus.REJECTED,
    ReservationStatus.CANCELLED,
    ReservationStatus.EXPIRED,
    ReservationStatus.FULFILLED,
  ])('offers nothing in terminal state %s', (status) => {
    expect(facilityActions(reservation({ status }), NOW)).toEqual([])
  })
})

describe('canRequesterCancel', () => {
  it('allows withdrawal while units are held', () => {
    expect(canRequesterCancel(reservation(), NOW)).toBe(true)
  })

  it('does not offer cancellation once nothing is held', () => {
    const done = reservation({ status: ReservationStatus.FULFILLED, holdsUnits: false })
    expect(canRequesterCancel(done, NOW)).toBe(false)
  })
})

describe('mutationBody', () => {
  it('carries the sort-key fields every mutating call needs', () => {
    expect(mutationBody(reservation())).toEqual({
      bloodGroup: 'O_NEG',
      component: 'PRBC',
    })
  })
})

describe('partitionForFacility', () => {
  const pending = reservation({ reservationId: 'a' })
  const pendingSooner = reservation({
    reservationId: 'b',
    expiresAt: '2026-11-24T10:20:00Z',
  })
  const confirmed = reservation({ reservationId: 'c', status: ReservationStatus.CONFIRMED })
  const done = reservation({
    reservationId: 'd',
    status: ReservationStatus.FULFILLED,
    holdsUnits: false,
  })

  it('separates the three piles staff work in', () => {
    const { needsDecision, held, closed } = partitionForFacility(
      [pending, confirmed, done, pendingSooner],
      NOW,
    )
    expect(needsDecision.map((r) => r.reservationId)).toEqual(['b', 'a'])
    expect(held.map((r) => r.reservationId)).toEqual(['c'])
    expect(closed.map((r) => r.reservationId)).toEqual(['d'])
  })

  it('puts the request that lapses soonest first', () => {
    const { needsDecision } = partitionForFacility([pending, pendingSooner], NOW)
    expect(needsDecision[0].reservationId).toBe('b')
  })

  it('handles no reservations', () => {
    expect(partitionForFacility([], NOW)).toEqual({
      needsDecision: [],
      held: [],
      closed: [],
    })
    expect(partitionForFacility(undefined, NOW).needsDecision).toEqual([])
  })
})

describe('partitionForRequester', () => {
  it('separates live holds from history', () => {
    const live = reservation({ reservationId: 'live' })
    const over = reservation({
      reservationId: 'over',
      status: ReservationStatus.EXPIRED,
      holdsUnits: false,
    })
    const { active, past } = partitionForRequester([over, live], NOW)
    expect(active.map((r) => r.reservationId)).toEqual(['live'])
    expect(past.map((r) => r.reservationId)).toEqual(['over'])
  })

  it('orders history newest first', () => {
    const older = reservation({
      reservationId: 'older',
      status: ReservationStatus.CANCELLED,
      holdsUnits: false,
      createdAt: '2026-11-20T09:00:00Z',
    })
    const newer = reservation({
      reservationId: 'newer',
      status: ReservationStatus.CANCELLED,
      holdsUnits: false,
      createdAt: '2026-11-23T09:00:00Z',
    })
    const { past } = partitionForRequester([older, newer], NOW)
    expect(past.map((r) => r.reservationId)).toEqual(['newer', 'older'])
  })
})

describe('totalHeldUnits', () => {
  it('counts only units actually held', () => {
    const list = [
      reservation({ units: 2 }),
      reservation({ units: 3, status: ReservationStatus.CONFIRMED }),
      reservation({ units: 9, status: ReservationStatus.EXPIRED, holdsUnits: false }),
    ]
    expect(totalHeldUnits(list, NOW)).toBe(5)
  })

  it('is zero, not NaN, when units are missing', () => {
    expect(totalHeldUnits([reservation({ units: undefined })], NOW)).toBe(0)
  })
})

describe('statusTone', () => {
  it('gives every state a tone', () => {
    for (const status of ALL_RESERVATION_STATUSES) {
      expect(typeof statusTone(status)).toBe('string')
    }
  })

  it('falls back to neutral', () => {
    expect(statusTone('WAT')).toBe('neutral')
  })
})
