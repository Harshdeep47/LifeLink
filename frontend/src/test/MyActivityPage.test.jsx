/**
 * The "My activity" page, rendered.
 *
 * `GET /me/reservations` had a client method and no caller anywhere in the
 * frontend, so a hold became unfindable the moment the page was left — while
 * still holding units out of every other user's search results. Invisible to
 * its owner, consequential for everyone else.
 *
 * These tests assert that the page reaches the real endpoints, that cancelling
 * sends the fields the endpoint needs, and that the sections a role cannot use
 * are absent rather than rendering a 403.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/client.js', () => ({
  api: {
    myReservations: vi.fn(),
    cancelReservation: vi.fn(),
    listEmergencyRequests: vi.fn(),
  },
}))

const authState = { can: () => true }
vi.mock('../auth/AuthContext.jsx', () => ({
  useAuth: () => authState,
}))

import { api } from '../api/client.js'
import MyActivityPage from '../features/account/MyActivityPage.jsx'

function soon(minutes = 118) {
  return new Date(Date.now() + minutes * 60_000).toISOString()
}

function reservation(overrides = {}) {
  return {
    reservationId: 'res-1',
    facilityId: 'fac-patiala-1',
    bloodGroup: 'O_NEG',
    component: 'PRBC',
    units: 2,
    status: 'PENDING',
    storedStatus: 'PENDING',
    holdsUnits: true,
    createdAt: new Date(Date.now() - 600_000).toISOString(),
    expiresAt: soon(),
    ...overrides,
  }
}

function emergency(overrides = {}) {
  return {
    requestId: 'req-1',
    bloodGroup: 'O_NEG',
    component: 'PRBC',
    unitsRequired: 4,
    status: 'VERIFICATION_PENDING',
    createdAt: new Date(Date.now() - 900_000).toISOString(),
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MyActivityPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  authState.can = () => true
  api.myReservations.mockResolvedValue([])
  api.listEmergencyRequests.mockResolvedValue([])
  api.cancelReservation.mockResolvedValue({})
})

describe('reaching the endpoints that had no caller', () => {
  it('loads the signed-in user’s reservations', async () => {
    renderPage()
    await waitFor(() => expect(api.myReservations).toHaveBeenCalled())
  })

  it('loads the user’s emergency requests', async () => {
    renderPage()
    await waitFor(() => expect(api.listEmergencyRequests).toHaveBeenCalled())
  })
})

describe('live holds', () => {
  it('shows the hold with a coarse countdown, not a false precision', async () => {
    api.myReservations.mockResolvedValue([reservation()])
    renderPage()
    expect(await screen.findByText('2 units')).toBeInTheDocument()
    // 118 minutes ahead -> "1 h 58 m left"; never seconds.
    expect(screen.getByText(/1 h 5[78] m left/)).toBeInTheDocument()
  })

  it('states that a hold is not clinical approval', async () => {
    api.myReservations.mockResolvedValue([reservation()])
    renderPage()
    await screen.findByText('2 units')
    expect(document.body.textContent).toMatch(/not.*clinical approval/i)
  })

  it('offers an empty state with a way forward when there are none', async () => {
    renderPage()
    expect(await screen.findByText('No reservations')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Find blood/i })).toBeInTheDocument()
  })
})

describe('cancelling a hold', () => {
  it('sends the facility, the id and the sort-key fields', async () => {
    const user = userEvent.setup()
    api.myReservations.mockResolvedValue([reservation()])
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Cancel hold/i }))

    await waitFor(() =>
      expect(api.cancelReservation).toHaveBeenCalledWith('fac-patiala-1', 'res-1', {
        bloodGroup: 'O_NEG',
        component: 'PRBC',
      }),
    )
  })

  it('reloads so the released hold leaves the live list', async () => {
    const user = userEvent.setup()
    api.myReservations.mockResolvedValue([reservation()])
    renderPage()
    await screen.findByText('2 units')
    expect(api.myReservations).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: /Cancel hold/i }))

    await waitFor(() => expect(api.myReservations).toHaveBeenCalledTimes(2))
  })

  it('shows a refusal rather than appearing to succeed', async () => {
    const user = userEvent.setup()
    api.cancelReservation.mockRejectedValue(new Error('this reservation changed'))
    api.myReservations.mockResolvedValue([reservation()])
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Cancel hold/i }))

    expect(await screen.findByText(/this reservation changed/i)).toBeInTheDocument()
  })

  it('does not offer cancellation once nothing is held', async () => {
    api.myReservations.mockResolvedValue([
      reservation({ status: 'FULFILLED', storedStatus: 'FULFILLED', holdsUnits: false }),
    ])
    renderPage()
    // The counted summary, not the prose sentence above it, which also
    // contains the words "Earlier reservations".
    await screen.findByText(/Earlier reservations \(1\)/)
    expect(screen.queryByRole('button', { name: /Cancel hold/i })).toBeNull()
  })
})

describe('history', () => {
  it('keeps finished holds out of the live list but still reachable', async () => {
    api.myReservations.mockResolvedValue([
      reservation({ reservationId: 'live' }),
      reservation({
        reservationId: 'done',
        status: 'CANCELLED',
        storedStatus: 'CANCELLED',
        holdsUnits: false,
      }),
    ])
    renderPage()
    expect(await screen.findByText(/Earlier reservations \(1\)/)).toBeInTheDocument()
  })
})

describe('emergency requests are kept distinct from holds', () => {
  it('says so in the section subtitle', async () => {
    renderPage()
    await screen.findByText(/My emergency requests/i)
    expect(document.body.textContent).toMatch(/different workflow from reservations/i)
  })

  it('does not invent a clinical priority for an uncertified request', async () => {
    api.listEmergencyRequests.mockResolvedValue([emergency()])
    renderPage()
    expect(await screen.findByText('Not clinically certified')).toBeInTheDocument()
  })

  it('shows a certified priority when a hospital has set one', async () => {
    api.listEmergencyRequests.mockResolvedValue([
      emergency({ clinicalPriority: 'P1' }),
    ])
    renderPage()
    await waitFor(() =>
      expect(screen.queryByText('Not clinically certified')).toBeNull(),
    )
  })
})

describe('sections a role cannot use are absent, not broken', () => {
  it('hides reservations when the permission is not held', async () => {
    authState.can = (permission) => permission !== 'reservation:manage:own'
    renderPage()
    await screen.findByText(/My emergency requests/i)
    expect(screen.queryByText('My reservations')).toBeNull()
    expect(api.myReservations).not.toHaveBeenCalled()
  })

  it('hides emergency requests when the permission is not held', async () => {
    authState.can = (permission) => permission !== 'emergency:read:own'
    renderPage()
    await screen.findByText('My reservations')
    expect(screen.queryByText('My emergency requests')).toBeNull()
    expect(api.listEmergencyRequests).not.toHaveBeenCalled()
  })

  it('explains itself to an account that uses neither, and points staff on', async () => {
    authState.can = () => false
    renderPage()
    expect(await screen.findByText('Nothing to show here')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /blood bank dashboard/i }),
    ).toBeInTheDocument()
  })

  it('always links on to the screens that own the other activity', async () => {
    renderPage()
    expect(
      await screen.findByRole('link', { name: /Availability alerts/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Donor dashboard/i })).toBeInTheDocument()
  })
})

describe('one section failing does not blank the others', () => {
  it('still renders emergency requests when reservations fail to load', async () => {
    api.myReservations.mockRejectedValue(new Error('reservations unavailable'))
    api.listEmergencyRequests.mockResolvedValue([emergency()])
    renderPage()

    expect(await screen.findByText(/reservations unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/My emergency requests/i)).toBeInTheDocument()
    expect(screen.getByText(/4 ×/)).toBeInTheDocument()
  })
})
