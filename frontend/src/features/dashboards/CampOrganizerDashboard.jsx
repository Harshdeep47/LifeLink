/**
 * Camp organizer and camp staff dashboard.
 *
 * The check-in → record → verify sequence is laid out in that order and each
 * step is gated on the previous one, because the specification treats them as
 * genuinely distinct facts. A donor cannot have a donation recorded before
 * being checked in, and verification is refused if the verifier is the donor.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import { useAuth } from '../../auth/AuthContext.jsx'
import {
  AsyncState,
  Button,
  Card,
  Field,
  Notice,
} from '../../components/ui.jsx'
import { CampStatusPill, StatusPill } from '../../components/StatusBadges.jsx'
import './Dashboards.css'

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'Asia/Kolkata',
    })
  } catch {
    return iso
  }
}

export default function CampOrganizerDashboard() {
  const { can, principal } = useAuth()
  const [selectedCampId, setSelectedCampId] = useState('')
  const [donationForm, setDonationForm] = useState({
    donorId: '',
    bloodGroup: 'O+',
    units: 1,
  })

  const camps = useApiData(() => api.myOrganizerCamps(), [])
  const campDetail = useApiData(
    () => api.getCamp(selectedCampId),
    [selectedCampId],
    { enabled: Boolean(selectedCampId) },
  )

  const checkIn = useMutation((donorId) => api.checkInDonor(selectedCampId, { donorId }))
  const record = useMutation((body) => api.recordDonation(selectedCampId, body))
  const verify = useMutation((body) => api.verifyDonation(selectedCampId, body))
  const cancelCamp = useMutation((reason) => api.cancelCamp(selectedCampId, { reason }))

  async function handleCheckIn(donorId) {
    try {
      await checkIn.run(donorId)
      campDetail.reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleRecord(event) {
    event.preventDefault()
    try {
      await record.run({
        donorId: donationForm.donorId,
        bloodGroup: donationForm.bloodGroup,
        component: 'WHOLE_BLOOD',
        units: Number(donationForm.units),
      })
      campDetail.reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleVerify(donorId, donationId) {
    try {
      await verify.run({ donorId, donationId })
      campDetail.reload()
    } catch {
      /* rendered below */
    }
  }

  const campList = Array.isArray(camps.data) ? camps.data : []
  const camp = campDetail.data
  const registrations = camp?.registrations ?? []
  const checkedIn = registrations.filter((r) => r.attendanceStatus === 'CHECKED_IN')

  const lastError = checkIn.error ?? record.error ?? verify.error

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Camp dashboard</h1>
        <p>
          Registration, attendance, donation recording and verification are four
          separate records. Each is taken by an authorized person and audited.
        </p>
      </header>

      <Card title="My camps">
        <AsyncState
          loading={camps.loading}
          error={camps.error}
          onRetry={camps.reload}
          isEmpty={campList.length === 0}
          emptyTitle="No camps"
          emptyMessage="Your organization has no camps on record."
        >
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Camp</th>
                  <th scope="col">Status</th>
                  <th scope="col">Starts</th>
                  <th scope="col">Registered</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {campList.map((item) => (
                  <tr key={item.campId}>
                    <td>
                      <Link to={`/camps/${item.campId}`}>{item.name}</Link>
                      <span className="text-xs muted" style={{ display: 'block' }}>
                        {item.city}
                      </span>
                    </td>
                    <td><CampStatusPill status={item.status} /></td>
                    <td className="text-xs">{formatTime(item.startsAt)}</td>
                    <td>
                      {item.registeredCount ?? 0} / {item.capacity}
                    </td>
                    <td>
                      <Button
                        variant={selectedCampId === item.campId ? 'primary' : 'secondary'}
                        size="sm"
                        onClick={() => setSelectedCampId(item.campId)}
                      >
                        {selectedCampId === item.campId ? 'Managing' : 'Manage'}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AsyncState>
      </Card>

      {lastError && (
        <Notice
          tone="danger"
          title={
            lastError.details?.rule === 'SELF_VERIFICATION_FORBIDDEN'
              ? 'A donor cannot verify their own donation'
              : 'That action was refused'
          }
        >
          <p style={{ margin: 0 }}>{lastError.message}</p>
          {lastError.details?.rule && (
            <p className="text-xs" style={{ margin: 0 }}>
              Rule: <code>{lastError.details.rule}</code>
            </p>
          )}
        </Notice>
      )}

      {selectedCampId && (
        <AsyncState
          loading={campDetail.loading}
          error={campDetail.error}
          onRetry={campDetail.reload}
          loadingMessage="Loading camp…"
        >
          {camp && (
            <>
              <div className="metrics">
                <div className="metric">
                  <span className="metric__value">{registrations.length}</span>
                  <span className="metric__label">Registered</span>
                </div>
                <div className="metric metric--success">
                  <span className="metric__value">{checkedIn.length}</span>
                  <span className="metric__label">Checked in</span>
                </div>
                <div className="metric">
                  <span className="metric__value">{camp.capacity}</span>
                  <span className="metric__label">Capacity</span>
                </div>
                <div className="metric">
                  <span className="metric__value">
                    {camp.capacity - (camp.registrationCount ?? registrations.length)}
                  </span>
                  <span className="metric__label">Places left</span>
                </div>
              </div>

              <Card
                title={`Attendance — ${camp.name}`}
                subtitle="Check a donor in when they arrive. This records attendance only."
                actions={
                  can('camp:manage') && camp.status !== 'CANCELLED' ? (
                    <Button
                      variant="danger"
                      size="sm"
                      loading={cancelCamp.submitting}
                      onClick={() => cancelCamp.run('cancelled from dashboard').then(camps.reload)}
                    >
                      Cancel camp
                    </Button>
                  ) : null
                }
              >
                {registrations.length === 0 ? (
                  <p className="text-sm muted">No registrations yet.</p>
                ) : (
                  <div className="table-scroll">
                    <table className="table">
                      <thead>
                        <tr>
                          <th scope="col">Donor</th>
                          <th scope="col">Registration</th>
                          <th scope="col">Attendance</th>
                          <th scope="col">Checked in at</th>
                          <th scope="col" />
                        </tr>
                      </thead>
                      <tbody>
                        {registrations.map((registration) => (
                          <tr key={registration.userId}>
                            <td><code>{registration.userId}</code></td>
                            <td><StatusPill status={registration.status} tone="info" /></td>
                            <td>
                              <StatusPill
                                status={registration.attendanceStatus}
                                tone={
                                  registration.attendanceStatus === 'CHECKED_IN'
                                    ? 'success'
                                    : 'neutral'
                                }
                              />
                            </td>
                            <td className="text-xs muted">
                              {formatTime(registration.checkedInAt)}
                            </td>
                            <td>
                              {can('camp:checkin') &&
                                registration.attendanceStatus !== 'CHECKED_IN' && (
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    loading={checkIn.submitting}
                                    onClick={() => handleCheckIn(registration.userId)}
                                  >
                                    Check in
                                  </Button>
                                )}
                              {registration.attendanceStatus === 'CHECKED_IN' && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() =>
                                    setDonationForm((previous) => ({
                                      ...previous,
                                      donorId: registration.userId,
                                    }))
                                  }
                                >
                                  Record donation
                                </Button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              {can('donation:record') && (
                <Card
                  title="Record a donation"
                  subtitle="The donor must already be checked in. Recording is not verification."
                >
                  <form onSubmit={handleRecord}>
                    <div className="batch-form">
                      <Field label="Donor id" htmlFor="don-donor" required>
                        {({ id }) => (
                          <input
                            id={id}
                            type="text"
                            value={donationForm.donorId}
                            onChange={(event) =>
                              setDonationForm((p) => ({ ...p, donorId: event.target.value }))
                            }
                            placeholder="user-donor-1"
                          />
                        )}
                      </Field>
                      <Field label="Blood group" htmlFor="don-group" required>
                        {({ id }) => (
                          <select
                            id={id}
                            value={donationForm.bloodGroup}
                            onChange={(event) =>
                              setDonationForm((p) => ({ ...p, bloodGroup: event.target.value }))
                            }
                          >
                            {BLOOD_GROUPS.map((group) => (
                              <option key={group} value={group}>{group}</option>
                            ))}
                          </select>
                        )}
                      </Field>
                      <Field label="Units" htmlFor="don-units" required>
                        {({ id }) => (
                          <input
                            id={id}
                            type="number"
                            min="1"
                            max="4"
                            value={donationForm.units}
                            onChange={(event) =>
                              setDonationForm((p) => ({ ...p, units: event.target.value }))
                            }
                          />
                        )}
                      </Field>
                      <Button
                        type="submit"
                        loading={record.submitting}
                        disabled={!donationForm.donorId}
                      >
                        Record
                      </Button>
                    </div>
                  </form>

                  {record.result && (
                    <Notice tone="success" title="Donation recorded">
                      <p style={{ margin: 0 }}>{record.result.notice}</p>
                      <div className="row" style={{ marginTop: 'var(--space-2)' }}>
                        <Button
                          variant="primary"
                          size="sm"
                          loading={verify.submitting}
                          onClick={() =>
                            handleVerify(donationForm.donorId, record.result.donationId)
                          }
                        >
                          Verify this donation
                        </Button>
                        <span className="text-xs muted">
                          Verifying credits the donor&rsquo;s impact ledger exactly once.
                        </span>
                      </div>
                    </Notice>
                  )}

                  {verify.result && (
                    <Notice tone="success" title="Donation verified">
                      <p style={{ margin: 0 }}>
                        Impact score is now {verify.result.impactScore} across{' '}
                        {verify.result.verifiedDonations} verified donation(s).
                      </p>
                      {verify.result.newMilestones?.length > 0 && (
                        <p style={{ margin: 0 }}>
                          New milestone: <strong>{verify.result.newMilestones.join(', ')}</strong>
                        </p>
                      )}
                    </Notice>
                  )}

                  <Notice tone="info" title="Who may verify">
                    Only assigned camp staff or the organizer may verify a donation, and
                    nobody may verify their own. Your account is{' '}
                    <code>{principal?.userId}</code>.
                  </Notice>
                </Card>
              )}
            </>
          )}
        </AsyncState>
      )}
    </div>
  )
}
