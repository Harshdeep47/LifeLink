/**
 * Centralized API client.
 *
 * Every network call goes through here, so error shapes, correlation ids,
 * idempotency keys and auth headers are handled once rather than in each
 * component. The backend always returns `{ data, meta?, correlationId }` on
 * success and `{ error: { code, message, details? } }` on failure, so this
 * client can normalise both into a single thrown `ApiError`.
 */

const BASE_URL = import.meta.env.VITE_API_BASE ?? '/api'

/** A failed request, carrying the backend's stable error code. */
export class ApiError extends Error {
  constructor(message, { code, status, details, correlationId } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code ?? 'UNKNOWN_ERROR'
    this.status = status ?? 0
    this.details = details ?? {}
    this.correlationId = correlationId
  }

  /** True when retrying the same request might succeed. */
  get isRetryable() {
    return (
      this.status >= 500 ||
      this.status === 0 ||
      this.code === 'RATE_LIMITED' ||
      this.code === 'CONCURRENT_MODIFICATION'
    )
  }

  /** True when the user needs to sign in again. */
  get isAuthError() {
    return this.status === 401 || this.code === 'UNAUTHENTICATED'
  }
}

let tokenProvider = () => null

/** Registered once by the auth context so the client never stores tokens itself. */
export function setTokenProvider(provider) {
  tokenProvider = provider
}

function newCorrelationId() {
  if (globalThis.crypto?.randomUUID) return `web-${globalThis.crypto.randomUUID()}`
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function buildQuery(params) {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

async function request(method, path, { body, params, idempotencyKey, signal } = {}) {
  const headers = {
    Accept: 'application/json',
    'X-Correlation-Id': newCorrelationId(),
  }

  const token = tokenProvider()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey

  let response
  try {
    response = await fetch(`${BASE_URL}${path}${buildQuery(params)}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    // A network failure is distinct from a server error and is worded for the
    // user rather than echoing a fetch internal.
    throw new ApiError(
      'Could not reach LifeLink. Check your connection and try again.',
      { code: 'NETWORK_ERROR', status: 0 },
    )
  }

  if (response.status === 204) return null

  let payload = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      throw new ApiError('The server returned an unreadable response.', {
        code: 'MALFORMED_RESPONSE',
        status: response.status,
      })
    }
  }

  if (!response.ok) {
    const error = payload?.error ?? {}
    throw new ApiError(error.message ?? `Request failed (${response.status})`, {
      code: error.code,
      status: response.status,
      details: error.details,
      correlationId: payload?.correlationId,
    })
  }

  return payload
}

/** Returns the `data` field, which is what callers almost always want. */
async function data(method, path, options) {
  const payload = await request(method, path, options)
  return payload?.data ?? null
}

/** Returns `{ data, meta }` for paginated endpoints. */
async function page(method, path, options) {
  const payload = await request(method, path, options)
  return { items: payload?.data ?? [], meta: payload?.meta ?? {} }
}

export const api = {
  // --- metadata ---
  health: () => data('GET', '/health'),
  reference: () => data('GET', '/reference'),
  me: () => data('GET', '/me'),

  // --- Feature 2: discovery ---
  searchFacilities: (params, signal) => data('GET', '/facilities', { params, signal }),
  getFacility: (id) => data('GET', `/facilities/${id}`),
  facilityAvailability: (id, params) =>
    data('GET', `/facilities/${id}/availability`, { params }),
  routeToFacility: (id, params) => data('GET', `/facilities/${id}/route`, { params }),
  geocode: (params, signal) => data('GET', '/geocode', { params, signal }),

  // --- Feature 1: inventory ---
  listBatches: (facilityId, params) =>
    page('GET', `/facilities/${facilityId}/batches`, { params }),
  createBatch: (facilityId, body) =>
    data('POST', `/facilities/${facilityId}/batches`, {
      body,
      idempotencyKey: `batch-${facilityId}-${Date.now()}`,
    }),
  getBatch: (facilityId, batchId) =>
    data('GET', `/facilities/${facilityId}/batches/${batchId}`),
  adjustBatch: (facilityId, batchId, body) =>
    data('POST', `/facilities/${facilityId}/batches/${batchId}/adjust`, { body }),
  verifyBatch: (facilityId, batchId, body) =>
    data('POST', `/facilities/${facilityId}/batches/${batchId}/verify`, { body }),
  batchAudit: (facilityId, batchId) =>
    data('GET', `/facilities/${facilityId}/batches/${batchId}/audit`),

  // --- Feature 1: alerts ---
  createAlert: (body) =>
    data('POST', '/alerts', { body, idempotencyKey: `alert-${Date.now()}` }),
  listAlerts: (params) => data('GET', '/alerts', { params }),
  getAlert: (id) => data('GET', `/alerts/${id}`),
  cancelAlert: (id) => data('DELETE', `/alerts/${id}`),

  // --- Account profile ---
  updateMyProfile: (body) => data('PATCH', '/me', { body }),
  requestOrganizationAccess: (body) =>
    data('POST', '/me/organization-request', { body }),

  // --- Feature 1: temporary reservations ---
  requestReservation: (facilityId, body) =>
    data('POST', `/facilities/${facilityId}/reservations`, { body }),
  myReservations: () => data('GET', '/me/reservations'),
  cancelReservation: (facilityId, reservationId, body) =>
    data('DELETE', `/facilities/${facilityId}/reservations/${reservationId}`, { body }),
  facilityReservations: (facilityId) =>
    data('GET', `/facilities/${facilityId}/reservations`),
  decideReservation: (facilityId, reservationId, body) =>
    data('POST', `/facilities/${facilityId}/reservations/${reservationId}/decision`, { body }),
  fulfilReservation: (facilityId, reservationId, body) =>
    data('POST', `/facilities/${facilityId}/reservations/${reservationId}/fulfil`, { body }),

  // --- Feature 3: camps ---
  searchCamps: (params, signal) => data('GET', '/camps', { params, signal }),
  getCamp: (id) => data('GET', `/camps/${id}`),
  createCamp: (body) => data('POST', '/camps', { body }),
  myOrganizerCamps: () => data('GET', '/camps/mine'),
  approveCamp: (id, body) => data('POST', `/camps/${id}/approve`, { body }),
  cancelCamp: (id, body) => data('POST', `/camps/${id}/cancel`, { body }),
  assignCampStaff: (id, body) => data('POST', `/camps/${id}/staff`, { body }),
  registerForCamp: (id) =>
    data('POST', `/camps/${id}/register`, { idempotencyKey: `reg-${id}` }),
  cancelRegistration: (id) => data('DELETE', `/camps/${id}/register`),
  checkInDonor: (id, body) => data('POST', `/camps/${id}/checkin`, { body }),
  recordDonation: (id, body) => data('POST', `/camps/${id}/donations`, { body }),
  verifyDonation: (id, body) => data('POST', `/camps/${id}/donations/verify`, { body }),

  // --- Feature 3: donor ---
  myRegistrations: () => data('GET', '/me/registrations'),
  donorProfile: () => data('GET', '/me/donor-profile'),
  myDonations: () => data('GET', '/me/donations'),
  certificate: (donationId) => data('GET', `/me/donations/${donationId}/certificate`),

  // --- Feature 4: emergency ---
  createEmergencyRequest: (body, idempotencyKey) =>
    data('POST', '/emergency-requests', { body, idempotencyKey }),
  listEmergencyRequests: () => data('GET', '/emergency-requests'),
  getEmergencyRequest: (id) => data('GET', `/emergency-requests/${id}`),
  providerQueue: () => data('GET', '/emergency-requests/provider-queue'),
  certifyPriority: (id, body) => data('POST', `/emergency-requests/${id}/certify`, { body }),
  respondToRequest: (id, body) => data('POST', `/emergency-requests/${id}/respond`, { body }),
  confirmAvailability: (id) => data('POST', `/emergency-requests/${id}/confirm`),
  cancelEmergencyRequest: (id, body) =>
    data('POST', `/emergency-requests/${id}/cancel`, { body }),

  // --- Feature 6: notifications and admin ---
  notificationPreferences: () => data('GET', '/me/notification-preferences'),
  updateNotificationPreferences: (body) =>
    data('PUT', '/me/notification-preferences', { body }),
  notifications: () => data('GET', '/me/notifications'),
  pendingOrganizations: () => data('GET', '/admin/organizations/pending'),
  setOrganizationStatus: (id, body) =>
    data('POST', `/admin/organizations/${id}/status`, { body }),
  setAccountStatus: (id, body) => data('POST', `/admin/users/${id}/status`, { body }),
  audit: (params) => data('GET', '/admin/audit', { params }),
}
