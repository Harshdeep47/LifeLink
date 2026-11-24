/**
 * Donor dashboard: impact, registrations, donation history, certificates,
 * notification preferences.
 *
 * The impact score is presented as recognition and never as medical status.
 * Interval advice comes from the backend already worded that way, and the
 * dashboard does not re-interpret it.
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
  DefinitionList,
  Notice,
} from '../../components/ui.jsx'
import { StatusPill } from '../../components/StatusBadges.jsx'
import './Dashboards.css'

function formatDate(iso) {
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

export default function DonorDashboard() {
  const { principal } = useAuth()
  const [certificate, setCertificate] = useState(null)

  const profile = useApiData(() => api.donorProfile(), [])
  const registrations = useApiData(() => api.myRegistrations(), [])
  const donations = useApiData(() => api.myDonations(), [])
  const preferences = useApiData(() => api.notificationPreferences(), [])

  const savePreferences = useMutation((body) => api.updateNotificationPreferences(body))
  const fetchCertificate = useMutation((donationId) => api.certificate(donationId))

  async function togglePreference(key, value) {
    try {
      const updated = await savePreferences.run({ ...preferences.data, [key]: value })
      preferences.setData(updated)
    } catch {
      /* rendered below */
    }
  }

  async function showCertificate(donationId) {
    try {
      const data = await fetchCertificate.run(donationId)
      setCertificate(data)
    } catch {
      /* rendered below */
    }
  }

  const prefs = preferences.data ?? {}

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Donor dashboard</h1>
        <p>{principal?.displayName ?? principal?.userId}</p>
      </header>

      <AsyncState
        loading={profile.loading}
        error={profile.error}
        onRetry={profile.reload}
        loadingMessage="Loading your profile…"
      >
        {profile.data && (
          <>
            <div className="metrics">
              <div className="metric">
                <span className="metric__value">{profile.data.impactScore}</span>
                <span className="metric__label">Impact score</span>
              </div>
              <div className="metric">
                <span className="metric__value">{profile.data.verifiedDonations}</span>
                <span className="metric__label">Verified donations</span>
              </div>
              <div className="metric">
                <span className="metric__value">{profile.data.milestones?.length ?? 0}</span>
                <span className="metric__label">Milestones earned</span>
              </div>
              <div className="metric">
                <span className="metric__value">
                  {profile.data.nextMilestone?.donationsRemaining ?? '—'}
                </span>
                <span className="metric__label">
                  {profile.data.nextMilestone
                    ? `More for ${profile.data.nextMilestone.name}`
                    : 'All milestones earned'}
                </span>
              </div>
            </div>

            <div className="grid grid--2">
              <Card title="Recognition">
                {profile.data.milestones?.length ? (
                  <ul className="home__chips" style={{ listStyle: 'none', padding: 0 }}>
                    {profile.data.milestones.map((milestone) => (
                      <li key={milestone} className="chip">{milestone}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm muted">
                    No milestones yet. The first is earned after one verified donation.
                  </p>
                )}
                <p className="text-xs muted">{profile.data.notice}</p>
              </Card>

              <Card title="Donation interval">
                <DefinitionList
                  items={[
                    {
                      label: 'Last verified donation',
                      value: formatDate(profile.data.lastVerifiedDonationAt),
                    },
                    {
                      label: 'Days since',
                      value: profile.data.intervalAdvice?.daysSinceLast ?? 'No record',
                    },
                  ]}
                />
                <Notice
                  tone={profile.data.intervalAdvice?.eligibleByInterval ? 'info' : 'warning'}
                >
                  {profile.data.intervalAdvice?.message}
                </Notice>
              </Card>
            </div>
          </>
        )}
      </AsyncState>

      <Card title="My camp registrations">
        <AsyncState
          loading={registrations.loading}
          error={registrations.error}
          onRetry={registrations.reload}
          isEmpty={!registrations.data?.length}
          emptyTitle="No registrations"
          emptyMessage="Find a camp near you and register to attend."
          emptyAction={<Link to="/camps" className="btn btn--primary btn--sm">Find camps</Link>}
        >
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Camp</th>
                  <th scope="col">Registration</th>
                  <th scope="col">Attendance</th>
                  <th scope="col">Registered</th>
                </tr>
              </thead>
              <tbody>
                {(registrations.data ?? []).map((registration) => (
                  <tr key={`${registration.campId}-${registration.userId}`}>
                    <td>
                      <Link to={`/camps/${registration.campId}`}>
                        {registration.campName ?? registration.campId}
                      </Link>
                    </td>
                    <td><StatusPill status={registration.status} tone="info" /></td>
                    <td>
                      <StatusPill
                        status={registration.attendanceStatus}
                        tone={
                          registration.attendanceStatus === 'CHECKED_IN' ? 'success' : 'neutral'
                        }
                      />
                    </td>
                    <td className="text-xs muted">{formatDate(registration.registeredAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AsyncState>
      </Card>

      <Card title="Donation history" subtitle="Recorded and verified are separate states">
        <AsyncState
          loading={donations.loading}
          error={donations.error}
          onRetry={donations.reload}
          isEmpty={!donations.data?.length}
          emptyTitle="No donations recorded"
        >
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Group</th>
                  <th scope="col">Component</th>
                  <th scope="col">Units</th>
                  <th scope="col">Status</th>
                  <th scope="col">Certificate</th>
                </tr>
              </thead>
              <tbody>
                {(donations.data ?? []).map((donation) => (
                  <tr key={donation.donationId}>
                    <td className="text-xs">{formatDate(donation.recordedAt)}</td>
                    <td>{donation.bloodGroup}</td>
                    <td className="text-xs">{donation.component?.replace(/_/g, ' ')}</td>
                    <td>{donation.units}</td>
                    <td>
                      <StatusPill
                        status={donation.status}
                        tone={donation.status === 'VERIFIED' ? 'success' : 'warning'}
                      />
                    </td>
                    <td>
                      {donation.status === 'VERIFIED' ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => showCertificate(donation.donationId)}
                        >
                          View
                        </Button>
                      ) : (
                        <span className="text-xs muted">After verification</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AsyncState>

        {certificate && (
          <div className="certificate">
            <h3 className="certificate__title">Certificate of recognition</h3>
            <p className="certificate__name">{certificate.donorName}</p>
            <DefinitionList
              items={[
                { label: 'Certificate', value: certificate.certificateId },
                { label: 'Camp', value: certificate.campName },
                { label: 'Donated', value: formatDate(certificate.donatedAt) },
                { label: 'Verified', value: formatDate(certificate.verifiedAt) },
                { label: 'Units', value: certificate.units },
              ]}
            />
            <p className="certificate__disclaimer text-xs">{certificate.disclaimer}</p>
            <Button variant="secondary" size="sm" onClick={() => setCertificate(null)}>
              Close
            </Button>
          </div>
        )}
      </Card>

      <Card title="Notification preferences">
        <AsyncState
          loading={preferences.loading}
          error={preferences.error}
          onRetry={preferences.reload}
        >
          <Notice tone={prefs.consentGiven ? 'success' : 'warning'}>
            {prefs.consentGiven
              ? 'You have consented to notifications. You can turn off any category below.'
              : 'You have not consented to notifications, so none will be sent to you.'}
          </Notice>

          <label className="pref">
            <input
              type="checkbox"
              checked={Boolean(prefs.consentGiven)}
              onChange={(event) => togglePreference('consentGiven', event.target.checked)}
            />
            <span>
              <strong>Consent to receive notifications</strong>
              <span className="text-xs muted"> — required before anything is sent</span>
            </span>
          </label>

          {[
            ['campNotifications', 'Camp announcements and reminders'],
            ['alertNotifications', 'Availability alert matches'],
            ['emergencyNotifications', 'Emergency request updates'],
          ].map(([key, label]) => (
            <label className="pref" key={key}>
              <input
                type="checkbox"
                disabled={!prefs.consentGiven}
                checked={Boolean(prefs[key])}
                onChange={(event) => togglePreference(key, event.target.checked)}
              />
              <span>{label}</span>
            </label>
          ))}

          <DefinitionList
            items={[
              {
                label: 'Notification radius',
                value: `${prefs.notificationRadiusKm ?? 10} km (camps beyond this are still searchable)`,
              },
              { label: 'Channels', value: (prefs.channels ?? []).join(', ') },
            ]}
          />

          <Notice tone="info" title="SMS is not available">
            This deployment supports email and in-app notifications only. SMS is not
            implemented, because the AWS account does not permit it.
          </Notice>

          {savePreferences.error && (
            <Notice tone="danger">{savePreferences.error.message}</Notice>
          )}
        </AsyncState>
      </Card>
    </div>
  )
}
