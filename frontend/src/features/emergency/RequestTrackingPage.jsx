/**
 * Emergency request tracking.
 *
 * Shows the lifecycle timeline and every provider response. Two presentation
 * rules the specification requires:
 *
 * - Offered units are labelled as offers, never summed into a "secured" total.
 *   Two providers may each offer the same units, and presenting a combined
 *   figure would imply supply that does not exist.
 * - An ACCEPTED response is described as willingness to proceed, not as a
 *   reservation.
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
import {
  PriorityBadge,
  RequestStatusPill,
  StatusPill,
} from '../../components/StatusBadges.jsx'
import './RequestTracking.css'

const PRIORITY_CHOICES = [
  { value: 'CRITICAL', label: 'Critical (P1)' },
  { value: 'URGENT', label: 'Urgent (P2)' },
  { value: 'SCHEDULED', label: 'Scheduled (P3)' },
]

const RESPONSE_LABELS = {
  ACCEPTED: 'Willing to proceed',
  REJECTED: 'Declined',
  INSUFFICIENT_STOCK: 'Partial stock only',
  NEEDS_CLARIFICATION: 'Needs clarification',
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'medium',
      timeZone: 'Asia/Kolkata',
    })
  } catch {
    return iso
  }
}

export function RequestTrackingPage() {
  const { requestId } = useParams()
  const { can, hasRole } = useAuth()

  const { data: request, loading, error, reload } = useApiData(
    () => api.getEmergencyRequest(requestId),
    [requestId],
  )

  const certify = useMutation((priority) =>
    api.certifyPriority(requestId, { priority }),
  )
  const cancel = useMutation(() =>
    api.cancelEmergencyRequest(requestId, { reason: 'cancelled by requester' }),
  )

  async function handleCertify(priority) {
    try {
      await certify.run(priority)
      reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleCancel() {
    try {
      await cancel.run()
      reload()
    } catch {
      /* rendered below */
    }
  }

  const canCertify =
    can('emergency:certify:priority') &&
    request &&
    request.status === 'VERIFICATION_PENDING'

  const isClosed =
    request && ['RESOLVED', 'CANCELLED', 'EXPIRED'].includes(request.status)

  return (
    <div className="stack">
      <AsyncState
        loading={loading}
        error={error}
        onRetry={reload}
        loadingMessage="Loading request…"
      >
        {request && (
          <>
            <header className="page-header">
              <h1>
                Request {request.bloodGroup} {request.component?.replace(/_/g, ' ')}
              </h1>
              <div className="row">
                <RequestStatusPill status={request.status} />
                <PriorityBadge priority={request.clinicalPriority} />
                {request.effectivePriority &&
                  request.effectivePriority !== request.clinicalPriority && (
                    <StatusPill
                      status={`dispatch order ${request.effectivePriority}`}
                      tone="info"
                    />
                  )}
              </div>
              <p className="text-xs muted mono">{request.requestId}</p>
            </header>

            {!request.clinicalPriority && (
              <Notice tone="warning" title="No clinical priority has been certified yet">
                Until an authorized hospital user certifies this request, it is queued
                at the lowest dispatch priority. LifeLink will not assign a priority on
                its own.
              </Notice>
            )}

            {request.effectivePriority &&
              request.clinicalPriority &&
              request.effectivePriority !== request.clinicalPriority && (
                <Notice tone="info" title="Dispatch order has been raised by waiting time">
                  The hospital-certified clinical priority is still{' '}
                  <strong>{request.clinicalPriority}</strong>. Only the scheduling order
                  has changed, so a long-waiting request is not starved. The clinical
                  priority itself is never altered by the scheduler.
                </Notice>
              )}

            <div className="grid grid--2">
              <Card title="Request">
                <DefinitionList
                  items={[
                    { label: 'Blood group', value: request.bloodGroup },
                    { label: 'Component', value: request.component?.replace(/_/g, ' ') },
                    { label: 'Units required', value: request.requiredUnits },
                    { label: 'Required by', value: formatTime(request.requiredBy) },
                    { label: 'Created', value: formatTime(request.createdAt) },
                    {
                      label: 'Hospital verification',
                      value: request.hospitalVerificationState?.replace(/_/g, ' '),
                    },
                    { label: 'Contact', value: request.contactName },
                    { label: 'Phone', value: request.contactPhone },
                  ]}
                />
              </Card>

              <Card title="Certification">
                {request.clinicalPriority ? (
                  <DefinitionList
                    items={[
                      { label: 'Priority', value: request.clinicalPriority },
                      { label: 'Certified by', value: request.certifiedBy },
                      { label: 'Certified at', value: formatTime(request.certifiedAt) },
                    ]}
                  />
                ) : (
                  <p className="text-sm muted">Not yet certified.</p>
                )}

                {canCertify && (
                  <>
                    <hr className="rule" />
                    <p className="text-sm">
                      <strong>Certify clinical priority.</strong> This records your
                      account, role and hospital against the decision.
                    </p>
                    <div className="row">
                      {PRIORITY_CHOICES.map((choice) => (
                        <Button
                          key={choice.value}
                          variant={choice.value === 'CRITICAL' ? 'danger' : 'secondary'}
                          size="sm"
                          loading={certify.submitting}
                          onClick={() => handleCertify(choice.value)}
                        >
                          {choice.label}
                        </Button>
                      ))}
                    </div>
                  </>
                )}

                {!canCertify && !request.clinicalPriority && hasRole('HOSPITAL_STAFF') && (
                  <Notice tone="info">
                    Your role cannot certify clinical priority. A hospital authorizer
                    must do it.
                  </Notice>
                )}

                {certify.error && (
                  <Notice tone="danger" title="Certification was refused">
                    <p style={{ margin: 0 }}>{certify.error.message}</p>
                    {certify.error.code && (
                      <p className="text-xs" style={{ margin: 0 }}>
                        Code: <code>{certify.error.code}</code>
                      </p>
                    )}
                  </Notice>
                )}
              </Card>
            </div>

            <Card
              title="Provider responses"
              subtitle={
                request.tally
                  ? `${request.tally.accepted} willing · ${request.tally.rejected} declined · ${request.tally.insufficient} partial`
                  : undefined
              }
            >
              {request.responses?.length ? (
                <>
                  <div className="table-scroll">
                    <table className="table">
                      <thead>
                        <tr>
                          <th scope="col">Provider</th>
                          <th scope="col">Facility</th>
                          <th scope="col">Response</th>
                          <th scope="col">Units offered</th>
                          <th scope="col">Responded</th>
                        </tr>
                      </thead>
                      <tbody>
                        {request.responses.map((response) => (
                          <tr key={response.providerOrganizationId}>
                            <td><code>{response.providerOrganizationId}</code></td>
                            <td><code>{response.facilityId}</code></td>
                            <td>
                              {response.responseType ? (
                                <StatusPill
                                  status={RESPONSE_LABELS[response.responseType] ?? response.responseType}
                                  tone={
                                    response.responseType === 'ACCEPTED'
                                      ? 'success'
                                      : response.responseType === 'REJECTED'
                                        ? 'danger'
                                        : 'warning'
                                  }
                                />
                              ) : (
                                <StatusPill status="Awaiting response" tone="neutral" />
                              )}
                            </td>
                            <td>
                              {response.unitsOffered
                                ? `${response.unitsOffered} offered`
                                : '—'}
                            </td>
                            <td className="text-xs muted">{formatTime(response.respondedAt)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <Notice tone="warning" title="Offers are not reserved stock">
                    Each figure above is what that provider said it is willing to
                    supply. Offers are <strong>not</strong> added together, because two
                    providers may be offering the same physical units. Nothing here is
                    held, allocated or clinically approved.
                  </Notice>
                </>
              ) : (
                <p className="text-sm muted">
                  No providers have been contacted yet. This happens once the request
                  is certified and matching runs.
                </p>
              )}
            </Card>

            <Card title="Timeline">
              {request.timeline?.length ? (
                <ol className="timeline">
                  {request.timeline.map((event, index) => (
                    <li key={`${event.occurredAt}-${index}`} className="timeline__item">
                      <span className="timeline__marker" aria-hidden="true" />
                      <div>
                        <strong className="timeline__event">
                          {event.eventType?.replace(/_/g, ' ')}
                        </strong>
                        <p className="timeline__meta text-xs muted">
                          {formatTime(event.occurredAt)}
                          {event.actorId ? ` · ${event.actorId}` : ''}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm muted">No lifecycle events recorded.</p>
              )}
            </Card>

            {!isClosed && (
              <div className="row">
                <Button variant="danger" onClick={handleCancel} loading={cancel.submitting}>
                  Cancel this request
                </Button>
                {cancel.error && (
                  <span className="text-sm" style={{ color: 'var(--crimson-700)' }}>
                    {cancel.error.message}
                  </span>
                )}
              </div>
            )}

            {request.notice && (
              <p className="text-xs muted" style={{ maxWidth: '80ch' }}>{request.notice}</p>
            )}
          </>
        )}
      </AsyncState>
    </div>
  )
}
