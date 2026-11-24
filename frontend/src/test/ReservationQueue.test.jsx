/**
 * The facility-side reservation queue, rendered.
 *
 * This screen is the one that was missing: the API for deciding on a
 * reservation was deployed, authorized and tested, but nothing in the
 * interface called it, and `ReservationPanel` told requesters that "facility
 * staff manage incoming requests from the blood bank dashboard" — a screen
 * that did not exist.
 *
 * So these tests assert the thing a logic test cannot: that the buttons are
 * really wired to the real client methods, with the real request bodies.
 * "Do not create buttons that look functional but do nothing" is only
 * checkable by pressing them.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api/client.js', () => ({
  api: {
    facilityReservations: vi.fn(),
    decideReservation: vi.fn(),
    fulfilReservation: vi.fn(),
  },
}))

import { api } from '../api/client.js'
import { ReservationQueue } from '../features/reservations/ReservationQueue.jsx'

const FACILITY = 'fac-patiala-1'

/** Expiry far enough ahead that the hold is unambiguously live. */
function soon(minutes = 90) {
  return new Date(Date.now() + minutes * 60_000).toISOString()
}

function reservation(overrides = {}) {
  return {
    reservationId: 'res-1',
    facilityId: FACILITY,
    bloodGroup: 'O_NEG',
    component: 'PRBC',
    units: 2,
    status: 'PENDING',
    storedStatus: 'PENDING',
    holdsUnits: true,
    createdAt: new Date(Date.now() - 3_600_000).toISOString(),
    expiresAt: soon(),
    isReservation: true,
    isClinicalApproval: false,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.facilityReservations.mockResolvedValue([])
  api.decideReservation.mockResolvedValue({})
  api.fulfilReservation.mockResolvedValue({})
})

afterEach(() => {
  vi.clearAllMocks()
})

async function renderQueue(items) {
  api.facilityReservations.mockResolvedValue(items)
  render(<ReservationQueue facilityId={FACILITY} facilityName="Example Centre" />)
  await waitFor(() => expect(api.facilityReservations).toHaveBeenCalledWith(FACILITY))
  return screen
}

describe('loading and empty states', () => {
  it('asks the API for this facility’s reservations', async () => {
    await renderQueue([])
    expect(api.facilityReservations).toHaveBeenCalledWith(FACILITY)
  })

  it('says nothing is waiting rather than showing an empty list', async () => {
    await renderQueue([])
    expect(await screen.findByText('Nothing waiting')).toBeInTheDocument()
  })

  it('does not call the API at all without a facility', () => {
    render(<ReservationQueue facilityId="" />)
    expect(api.facilityReservations).not.toHaveBeenCalled()
    expect(screen.getByText(/Choose a facility/i)).toBeInTheDocument()
  })

  it('surfaces a load failure with a retry rather than an empty queue', async () => {
    api.facilityReservations.mockRejectedValue(new Error('network down'))
    render(<ReservationQueue facilityId={FACILITY} />)
    expect(await screen.findByText(/network down/i)).toBeInTheDocument()
  })
})

describe('what the queue tells staff', () => {
  it('shows the units, group and component of a request', async () => {
    await renderQueue([reservation()])
    expect(await screen.findByText('2 units')).toBeInTheDocument()
    expect(screen.getByText(/O-NEG PRBC/)).toBeInTheDocument()
  })

  it('reports how many units are actually held', async () => {
    await renderQueue([
      reservation({ reservationId: 'a', units: 2 }),
      reservation({ reservationId: 'b', units: 3, status: 'CONFIRMED', storedStatus: 'CONFIRMED' }),
      reservation({
        reservationId: 'c',
        units: 9,
        status: 'EXPIRED',
        storedStatus: 'EXPIRED',
        holdsUnits: false,
      }),
    ])
    // 2 + 3 held; the expired 9 must not be counted.
    const summary = await screen.findByText(/unit[s]? currently/i)
    expect(summary.textContent).toMatch(/\b5\b/)
    expect(summary.textContent).not.toMatch(/\b14\b/)
  })

  it('never calls an acceptance clinical approval', async () => {
    await renderQueue([reservation({ status: 'CONFIRMED', storedStatus: 'CONFIRMED' })])
    expect(await screen.findByText('Accepted — units held')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/clinically approved/i)
    // The standing notice must say the opposite, explicitly.
    expect(document.body.textContent).toMatch(/not.*clinical approval/i)
  })

  it('separates requests awaiting a decision from accepted holds', async () => {
    await renderQueue([
      reservation({ reservationId: 'pending-1' }),
      reservation({ reservationId: 'held-1', status: 'CONFIRMED', storedStatus: 'CONFIRMED' }),
    ])
    expect(await screen.findByText(/Awaiting your decision \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Accepted and holding \(1\)/)).toBeInTheDocument()
  })
})

describe('accepting a request', () => {
  it('sends CONFIRM with the sort-key fields the endpoint requires', async () => {
    const user = userEvent.setup()
    await renderQueue([reservation()])

    await user.click(await screen.findByRole('button', { name: /^Accept$/ }))

    await waitFor(() =>
      expect(api.decideReservation).toHaveBeenCalledWith(FACILITY, 'res-1', {
        bloodGroup: 'O_NEG',
        component: 'PRBC',
        decision: 'CONFIRM',
        reason: undefined,
      }),
    )
  })

  it('reloads afterwards so the row moves to the right pile', async () => {
    const user = userEvent.setup()
    await renderQueue([reservation()])
    expect(api.facilityReservations).toHaveBeenCalledTimes(1)

    await user.click(await screen.findByRole('button', { name: /^Accept$/ }))

    await waitFor(() => expect(api.facilityReservations).toHaveBeenCalledTimes(2))
  })

  it('shows the refusal instead of pretending it worked', async () => {
    const user = userEvent.setup()
    api.decideReservation.mockRejectedValue(new Error('this reservation has expired'))
    await renderQueue([reservation()])

    await user.click(await screen.findByRole('button', { name: /^Accept$/ }))

    expect(await screen.findByText(/this reservation has expired/i)).toBeInTheDocument()
  })
})

describe('declining a request', () => {
  it('asks for a reason before it will send anything', async () => {
    const user = userEvent.setup()
    await renderQueue([reservation()])

    await user.click(await screen.findByRole('button', { name: /^Decline$/ }))

    const confirm = screen.getByRole('button', { name: /Confirm decline/i })
    expect(confirm).toBeDisabled()
    expect(api.decideReservation).not.toHaveBeenCalled()
  })

  it('sends REJECT with the typed reason, which the requester sees', async () => {
    const user = userEvent.setup()
    await renderQueue([reservation()])

    await user.click(await screen.findByRole('button', { name: /^Decline$/ }))
    await user.type(
      screen.getByLabelText(/Why is this being declined/i),
      'units quarantined pending re-test',
    )
    await user.click(screen.getByRole('button', { name: /Confirm decline/i }))

    await waitFor(() =>
      expect(api.decideReservation).toHaveBeenCalledWith(FACILITY, 'res-1', {
        bloodGroup: 'O_NEG',
        component: 'PRBC',
        decision: 'REJECT',
        reason: 'units quarantined pending re-test',
      }),
    )
  })

  it('can be abandoned without sending anything', async () => {
    const user = userEvent.setup()
    await renderQueue([reservation()])

    await user.click(await screen.findByRole('button', { name: /^Decline$/ }))
    await user.click(screen.getByRole('button', { name: /Keep it open/i }))

    expect(screen.queryByRole('button', { name: /Confirm decline/i })).toBeNull()
    expect(api.decideReservation).not.toHaveBeenCalled()
  })
})

describe('recording that units were issued', () => {
  it('offers fulfilment only on an accepted hold', async () => {
    await renderQueue([reservation()])
    expect(screen.queryByRole('button', { name: /Record units issued/i })).toBeNull()
  })

  it('sends the fulfilment with the sort-key fields', async () => {
    const user = userEvent.setup()
    await renderQueue([
      reservation({ status: 'CONFIRMED', storedStatus: 'CONFIRMED' }),
    ])

    await user.click(await screen.findByRole('button', { name: /Record units issued/i }))

    await waitFor(() =>
      expect(api.fulfilReservation).toHaveBeenCalledWith(FACILITY, 'res-1', {
        bloodGroup: 'O_NEG',
        component: 'PRBC',
      }),
    )
  })
})

describe('actions the backend would refuse are not offered', () => {
  it('will not offer to accept a request whose hold has already lapsed', async () => {
    await renderQueue([
      reservation({ expiresAt: new Date(Date.now() - 60_000).toISOString() }),
    ])
    // Declining is still meaningful: it records an answer.
    expect(await screen.findByRole('button', { name: /^Decline$/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Accept$/ })).toBeNull()
  })

  it.each(['REJECTED', 'CANCELLED', 'EXPIRED', 'FULFILLED'])(
    'offers no action on a closed request (%s)',
    async (status) => {
      await renderQueue([
        reservation({ status, storedStatus: status, holdsUnits: false }),
      ])
      const history = await screen.findByText(/Closed requests \(1\)/)
      const list = history.closest('details')
      expect(within(list).queryByRole('button', { name: /^Accept$/ })).toBeNull()
      expect(within(list).queryByRole('button', { name: /^Decline$/ })).toBeNull()
      expect(within(list).queryByRole('button', { name: /Record units issued/i })).toBeNull()
      expect(within(list).getByText('No action available')).toBeInTheDocument()
    },
  )

  it('tells staff when a hold has lapsed but the sweep has not caught up', async () => {
    await renderQueue([
      reservation({
        status: 'EXPIRED',
        storedStatus: 'PENDING',
        holdsUnits: false,
        expiresAt: new Date(Date.now() - 60_000).toISOString(),
      }),
    ])
    expect(
      await screen.findByText(/release sweep has not run yet/i),
    ).toBeInTheDocument()
  })
})
