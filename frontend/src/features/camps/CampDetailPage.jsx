/**
 * Camp detail and registration.
 *
 * Registration deliberately shows the donation-interval advice returned by the
 * backend, which is phrased as information rather than clearance. LifeLink
 * cannot assess fitness to donate, so the copy consistently points the user at
 * camp staff instead of implying approval.
 */
import { useParams } from 'react-router-dom'

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
import { CampStatusPill, StatusPill } from '../../components/StatusBadges.jsx'

function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      dateStyle: 'full',
      timeStyle: 'short',
      timeZone: 'Asia/Kolkata',
    })
  } catch {
    return iso
  }
}

export function CampDetailPage() {
  const { campId } = useParams()
  const { isAuthenticated, hasRole } = useAuth()

  const { data: camp, loading, error, reload } = useApiData(
    () => api.getCamp(campId),
    [campId],
  )

  const register = useMutation(() => api.registerForCamp(campId))
  const cancel = useMutation(() => api.cancelRegistration(campId))

  async function handleRegister() {
    try {
      await register.run()
      reload()
    } catch {
      /* error is rendered from the hook */
    }
  }

  async function handleCancel() {
    try {
      await cancel.run()
      reload()
    } catch {
      /* error is rendered from the hook */
    }
  }

  const canRegister =
    isAuthenticated &&
    hasRole('DONOR') &&
    camp &&
    ['UPCOMING', 'ONGOING'].includes(camp.status) &&
    (camp.registeredCount ?? 0) < camp.capacity

  const isFull = camp && (camp.registeredCount ?? 0) >= camp.capacity

  return (
    <div className="stack">
      <AsyncState
        loading={loading}
        error={error}
        onRetry={reload}
        loadingMessage="Loading camp…"
      >
        {camp && (
          <>
            <header className="page-header">
              <h1>{camp.name}</h1>
              <div className="row">
                <CampStatusPill status={camp.status} />
                {camp.derivedStatus && camp.derivedStatus !== camp.status && (
                  <StatusPill status={`now ${camp.derivedStatus}`} tone="info" />
                )}
                {camp.demoData && <StatusPill status="Synthetic record" tone="danger" />}
              </div>
            </header>

            {camp.status === 'CANCELLED' && (
              <Notice tone="danger" title="This camp has been cancelled">
                Registered donors have been notified. Please do not attend.
              </Notice>
            )}
            {camp.status === 'PENDING_APPROVAL' && (
              <Notice tone="warning" title="Awaiting approval">
                This camp has not yet been approved, so registration is closed.
              </Notice>
            )}

            <div className="grid grid--2">
              <Card title="Details">
                <DefinitionList
                  items={[
                    { label: 'Description', value: camp.description },
                    { label: 'Address', value: camp.address },
                    { label: 'City', value: camp.city },
                    { label: 'Starts', value: formatDate(camp.startsAt) },
                    { label: 'Ends', value: formatDate(camp.endsAt) },
                    {
                      label: 'Registration closes',
                      value: formatDate(camp.registrationDeadline),
                    },
                    {
                      label: 'Capacity',
                      value: `${camp.registrationCount ?? camp.registeredCount ?? 0} of ${camp.capacity} registered`,
                    },
                    {
                      label: 'Checked in',
                      value:
                        camp.checkedInCount !== undefined
                          ? String(camp.checkedInCount)
                          : undefined,
                    },
                  ]}
                />
              </Card>

              <Card title="Register to attend">
                {!isAuthenticated && (
                  <Notice tone="info">
                    Sign in as a donor to register for this camp.
                  </Notice>
                )}

                {isAuthenticated && !hasRole('DONOR') && (
                  <Notice tone="info">
                    Only donor accounts can register to attend a camp.
                  </Notice>
                )}

                {isFull && camp.status !== 'CANCELLED' && (
                  <Notice tone="warning" title="This camp is full">
                    All {camp.capacity} places have been taken.
                  </Notice>
                )}

                {register.error && (
                  <Notice tone="danger" title="Registration was not completed">
                    <p style={{ margin: 0 }}>{register.error.message}</p>
                    {register.error.code && (
                      <p className="text-xs" style={{ margin: 0 }}>
                        Code: <code>{register.error.code}</code>
                      </p>
                    )}
                  </Notice>
                )}

                {register.result && (
                  <Notice tone="success" title="You are registered">
                    <p>{register.result.notice}</p>
                    {register.result.intervalAdvice && (
                      <p className="text-sm" style={{ marginBottom: 0 }}>
                        {register.result.intervalAdvice.message}
                      </p>
                    )}
                  </Notice>
                )}

                <div className="row">
                  <Button
                    onClick={handleRegister}
                    loading={register.submitting}
                    disabled={!canRegister || Boolean(register.result)}
                  >
                    Register
                  </Button>
                  {register.result && (
                    <Button
                      variant="secondary"
                      onClick={handleCancel}
                      loading={cancel.submitting}
                    >
                      Cancel my registration
                    </Button>
                  )}
                </div>

                <p className="text-xs muted" style={{ marginTop: 'var(--space-3)' }}>
                  Registering reserves a place at the camp. It does not record a
                  donation and does not confirm that you are medically eligible to
                  donate — camp staff assess that on the day.
                </p>
              </Card>
            </div>

            {camp.registrations && (
              <Card
                title="Registered donors"
                subtitle="Visible to camp staff and the organizer only"
              >
                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">Donor</th>
                        <th scope="col">Registration</th>
                        <th scope="col">Attendance</th>
                        <th scope="col">Registered at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {camp.registrations.map((registration) => (
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
                          <td className="text-xs muted">{registration.registeredAt}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </>
        )}
      </AsyncState>
    </div>
  )
}
