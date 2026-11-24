/**
 * Hospital dashboard: emergency requests, priority certification, provider
 * responses.
 *
 * Certification controls appear only for roles that actually hold the
 * permission. A hospital staff member sees the queue and an explanation of why
 * they cannot certify, rather than a button that fails.
 */
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import { useAuth } from '../../auth/AuthContext.jsx'
import { AsyncState, Button, Card, Notice } from '../../components/ui.jsx'
import { PriorityBadge, RequestStatusPill } from '../../components/StatusBadges.jsx'
import './Dashboards.css'

const PRIORITY_CHOICES = [
  { value: 'CRITICAL', label: 'Critical', variant: 'danger' },
  { value: 'URGENT', label: 'Urgent', variant: 'secondary' },
  { value: 'SCHEDULED', label: 'Scheduled', variant: 'secondary' },
]

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

export default function HospitalDashboard() {
  const { can, roles } = useAuth()
  const requests = useApiData(() => api.listEmergencyRequests(), [])
  const certify = useMutation(({ requestId, priority }) =>
    api.certifyPriority(requestId, { priority }),
  )

  const canCertify = can('emergency:certify:priority')

  async function handleCertify(requestId, priority) {
    try {
      await certify.run({ requestId, priority })
      requests.reload()
    } catch {
      /* rendered below */
    }
  }

  const rows = Array.isArray(requests.data) ? requests.data : []
  const awaitingCertification = rows.filter(
    (r) => r.status === 'VERIFICATION_PENDING' || !r.clinicalPriority,
  )
  const active = rows.filter(
    (r) => !['RESOLVED', 'CANCELLED', 'EXPIRED'].includes(r.status),
  )
  const critical = rows.filter((r) => r.clinicalPriority === 'P1')

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Hospital dashboard</h1>
        <p>
          Emergency requests raised by your organization, and the clinical priority
          certification queue.
        </p>
      </header>

      {!canCertify && (
        <Notice tone="info" title="Your role cannot certify clinical priority">
          You hold {roles.join(', ') || 'no roles'}. Certifying priority requires a
          hospital authorizer or hospital admin. The server enforces this, so the
          controls are hidden rather than shown and then refused.
        </Notice>
      )}

      <div className="metrics">
        <div className="metric">
          <span className="metric__value">{rows.length}</span>
          <span className="metric__label">Total requests</span>
        </div>
        <div className="metric metric--warning">
          <span className="metric__value">{awaitingCertification.length}</span>
          <span className="metric__label">Awaiting certification</span>
        </div>
        <div className="metric">
          <span className="metric__value">{active.length}</span>
          <span className="metric__label">Active</span>
        </div>
        <div className="metric metric--danger">
          <span className="metric__value">{critical.length}</span>
          <span className="metric__label">Critical (P1)</span>
        </div>
      </div>

      {certify.error && (
        <Notice tone="danger" title="Certification was refused">
          <p style={{ margin: 0 }}>{certify.error.message}</p>
          {certify.error.details?.organizationStatus && (
            <p className="text-xs" style={{ margin: 0 }}>
              Hospital status: <code>{certify.error.details.organizationStatus}</code>.
              A hospital that is not currently verified cannot certify priority.
            </p>
          )}
        </Notice>
      )}

      {canCertify && (
        <Card
          title="Certification queue"
          subtitle="Requests with no hospital-certified clinical priority"
        >
          <AsyncState
            loading={requests.loading}
            error={requests.error}
            onRetry={requests.reload}
            isEmpty={awaitingCertification.length === 0}
            emptyTitle="Nothing awaiting certification"
            emptyMessage="Every request raised by your organization has a certified priority."
          >
            <ul className="stack" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {awaitingCertification.map((request) => (
                <li key={request.requestId} className="queue-item queue-item--p3">
                  <div>
                    <strong>
                      {request.bloodGroup} {request.component?.replace(/_/g, ' ')} ·{' '}
                      {request.requiredUnits} unit(s)
                    </strong>
                    <p className="text-xs muted" style={{ margin: '2px 0 0' }}>
                      Created {formatTime(request.createdAt)} · required by{' '}
                      {formatTime(request.requiredBy)}
                    </p>
                    <p className="text-xs mono muted" style={{ margin: '2px 0 0' }}>
                      {request.requestId}
                    </p>
                  </div>
                  <div className="inline-actions">
                    {PRIORITY_CHOICES.map((choice) => (
                      <Button
                        key={choice.value}
                        variant={choice.variant}
                        size="sm"
                        loading={certify.submitting}
                        onClick={() => handleCertify(request.requestId, choice.value)}
                      >
                        {choice.label}
                      </Button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>

            <Notice tone="warning" title="Certification is recorded against you">
              Each decision stores your account, your role, your hospital and the
              timestamp in the audit trail. LifeLink never sets clinical priority
              itself, and the scheduler cannot change what you certify.
            </Notice>
          </AsyncState>
        </Card>
      )}

      <Card title="All requests from my organization">
        <AsyncState
          loading={requests.loading}
          error={requests.error}
          onRetry={requests.reload}
          isEmpty={rows.length === 0}
          emptyTitle="No requests"
          emptyMessage="Your organization has not raised any emergency requests."
          emptyAction={
            <Link to="/emergency" className="btn btn--primary btn--sm">
              Raise a request
            </Link>
          }
        >
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Need</th>
                  <th scope="col">Priority</th>
                  <th scope="col">Status</th>
                  <th scope="col">Required by</th>
                  <th scope="col">Created</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {rows.map((request) => (
                  <tr key={request.requestId}>
                    <td>
                      <strong>{request.bloodGroup}</strong>{' '}
                      <span className="text-xs muted">
                        {request.component?.replace(/_/g, ' ')} · {request.requiredUnits}u
                      </span>
                    </td>
                    <td><PriorityBadge priority={request.clinicalPriority} /></td>
                    <td><RequestStatusPill status={request.status} /></td>
                    <td className="text-xs">{formatTime(request.requiredBy)}</td>
                    <td className="text-xs muted">{formatTime(request.createdAt)}</td>
                    <td>
                      <Link
                        to={`/emergency/${request.requestId}`}
                        className="btn btn--ghost btn--sm"
                      >
                        Track
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AsyncState>
      </Card>
    </div>
  )
}
