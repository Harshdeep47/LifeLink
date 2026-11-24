/**
 * Platform administrator dashboard: organization verification, account
 * suspension, audit inspection.
 *
 * Suspension is the control behind one of the system's sharpest security
 * guarantees: a suspended account's existing JWT stops working on its very next
 * request, because authorization reads account status from the database rather
 * than from the token.
 */
import { useState } from 'react'

import { api } from '../../api/client.js'
import { useApiData, useMutation } from '../../hooks/useApi.js'
import {
  AsyncState,
  Button,
  Card,
  Field,
  Notice,
} from '../../components/ui.jsx'
import { StatusPill } from '../../components/StatusBadges.jsx'
import './Dashboards.css'

const ACCOUNT_STATUSES = ['ACTIVE', 'SUSPENDED']

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

export default function AdminDashboard() {
  const [userId, setUserId] = useState('')
  const [accountStatus, setAccountStatus] = useState('SUSPENDED')
  const [auditQuery, setAuditQuery] = useState({ mode: 'actor', actorId: '', resourceType: 'BATCH', resourceId: '' })
  const [auditRecords, setAuditRecords] = useState(null)

  const pending = useApiData(() => api.pendingOrganizations(), [])

  const setOrgStatus = useMutation(({ organizationId, status, reason }) =>
    api.setOrganizationStatus(organizationId, { status, reason }),
  )
  const setUserStatus = useMutation(({ id, status }) =>
    api.setAccountStatus(id, { status }),
  )
  const loadAudit = useMutation((params) => api.audit(params))

  async function handleOrgStatus(organizationId, status) {
    try {
      await setOrgStatus.run({
        organizationId,
        status,
        reason: `set to ${status} from admin dashboard`,
      })
      pending.reload()
    } catch {
      /* rendered below */
    }
  }

  async function handleUserStatus(event) {
    event.preventDefault()
    try {
      await setUserStatus.run({ id: userId, status: accountStatus })
    } catch {
      /* rendered below */
    }
  }

  async function handleAudit(event) {
    event.preventDefault()
    const params =
      auditQuery.mode === 'actor'
        ? { actorId: auditQuery.actorId }
        : { resourceType: auditQuery.resourceType, resourceId: auditQuery.resourceId }
    try {
      const records = await loadAudit.run(params)
      setAuditRecords(records ?? [])
    } catch {
      setAuditRecords(null)
    }
  }

  const organizations = Array.isArray(pending.data)
    ? pending.data.filter((item) => item.entityType === 'ORGANIZATION')
    : []

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Administrator dashboard</h1>
        <p>
          Organization verification, account status and the audit trail. Every action
          here is itself audited.
        </p>
      </header>

      <Card
        title="Organizations awaiting verification"
        subtitle="Only an administrator can mark an organization verified"
      >
        <AsyncState
          loading={pending.loading}
          error={pending.error}
          onRetry={pending.reload}
          isEmpty={organizations.length === 0}
          emptyTitle="Nothing pending"
          emptyMessage="No organizations are awaiting verification."
        >
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Organization</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {organizations.map((organization) => (
                  <tr key={organization.organizationId}>
                    <td>
                      {organization.name}
                      <span className="text-xs mono muted" style={{ display: 'block' }}>
                        {organization.organizationId}
                      </span>
                    </td>
                    <td className="text-xs">
                      {organization.organizationType?.replace(/_/g, ' ')}
                    </td>
                    <td><StatusPill status={organization.status} tone="warning" /></td>
                    <td>
                      <div className="inline-actions">
                        <Button
                          variant="success"
                          size="sm"
                          loading={setOrgStatus.submitting}
                          onClick={() => handleOrgStatus(organization.organizationId, 'VERIFIED')}
                        >
                          Verify
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleOrgStatus(organization.organizationId, 'REJECTED')}
                        >
                          Reject
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => handleOrgStatus(organization.organizationId, 'SUSPENDED')}
                        >
                          Suspend
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {setOrgStatus.error && (
            <Notice tone="danger">{setOrgStatus.error.message}</Notice>
          )}
          {setOrgStatus.result && (
            <Notice tone="success">
              {setOrgStatus.result.organizationId} is now{' '}
              <strong>{setOrgStatus.result.status}</strong>.
            </Notice>
          )}

          <Notice tone="info" title="Verification has teeth">
            A hospital that is suspended immediately loses the ability to certify
            clinical priority, even mid-workflow, because that check is re-run at the
            moment of certification rather than cached.
          </Notice>
        </AsyncState>
      </Card>

      <Card title="Account status">
        <form onSubmit={handleUserStatus}>
          <div className="batch-form">
            <Field label="User id" htmlFor="admin-user" required>
              {({ id }) => (
                <input
                  id={id}
                  type="text"
                  value={userId}
                  onChange={(event) => setUserId(event.target.value)}
                  placeholder="user-bb-admin-1"
                />
              )}
            </Field>
            <Field label="Status" htmlFor="admin-status" required>
              {({ id }) => (
                <select
                  id={id}
                  value={accountStatus}
                  onChange={(event) => setAccountStatus(event.target.value)}
                >
                  {ACCOUNT_STATUSES.map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              )}
            </Field>
            <Button type="submit" loading={setUserStatus.submitting} disabled={!userId}>
              Apply
            </Button>
          </div>
        </form>

        {setUserStatus.error && <Notice tone="danger">{setUserStatus.error.message}</Notice>}
        {setUserStatus.result && (
          <Notice tone="success">
            <code>{setUserStatus.result.userId}</code> is now{' '}
            <strong>{setUserStatus.result.accountStatus}</strong>. Their existing token
            stops working on the next request.
          </Notice>
        )}

        <Notice tone="warning" title="Why suspension is immediate">
          Authorization reads roles and account status from the database on every
          request, not from the token. A valid, unexpired JWT belonging to a suspended
          account is therefore rejected straight away. Try it with{' '}
          <code>user-suspended-1</code> in the seeded dataset.
        </Notice>
      </Card>

      <Card title="Audit trail" subtitle="Queried by actor or by resource — never scanned">
        <form onSubmit={handleAudit}>
          <Field label="Look up by" htmlFor="audit-mode">
            {({ id }) => (
              <select
                id={id}
                value={auditQuery.mode}
                onChange={(event) =>
                  setAuditQuery((previous) => ({ ...previous, mode: event.target.value }))
                }
              >
                <option value="actor">Actor</option>
                <option value="resource">Resource</option>
              </select>
            )}
          </Field>

          {auditQuery.mode === 'actor' ? (
            <Field label="Actor user id" htmlFor="audit-actor" required>
              {({ id }) => (
                <input
                  id={id}
                  type="text"
                  value={auditQuery.actorId}
                  onChange={(event) =>
                    setAuditQuery((previous) => ({ ...previous, actorId: event.target.value }))
                  }
                  placeholder="user-bb-admin-1"
                />
              )}
            </Field>
          ) : (
            <div className="batch-form">
              <Field label="Resource type" htmlFor="audit-type" required>
                {({ id }) => (
                  <select
                    id={id}
                    value={auditQuery.resourceType}
                    onChange={(event) =>
                      setAuditQuery((previous) => ({
                        ...previous,
                        resourceType: event.target.value,
                      }))
                    }
                  >
                    {['BATCH', 'CAMP', 'EMERGENCY_REQUEST', 'DONATION', 'ORGANIZATION', 'USER', 'ALERT'].map(
                      (type) => (
                        <option key={type} value={type}>{type}</option>
                      ),
                    )}
                  </select>
                )}
              </Field>
              <Field label="Resource id" htmlFor="audit-id" required>
                {({ id }) => (
                  <input
                    id={id}
                    type="text"
                    value={auditQuery.resourceId}
                    onChange={(event) =>
                      setAuditQuery((previous) => ({
                        ...previous,
                        resourceId: event.target.value,
                      }))
                    }
                  />
                )}
              </Field>
            </div>
          )}

          <Button type="submit" loading={loadAudit.submitting}>Search audit</Button>
        </form>

        {loadAudit.error && (
          <Notice tone="danger" title="Audit query refused">
            <p style={{ margin: 0 }}>{loadAudit.error.message}</p>
            {loadAudit.error.details?.reason && (
              <p className="text-xs" style={{ margin: 0 }}>
                {loadAudit.error.details.reason}
              </p>
            )}
          </Notice>
        )}

        {auditRecords && (
          auditRecords.length === 0 ? (
            <p className="text-sm muted">No audit records matched.</p>
          ) : (
            <div className="table-scroll" style={{ marginTop: 'var(--space-3)' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Action</th>
                    <th scope="col">Actor</th>
                    <th scope="col">Resource</th>
                    <th scope="col">Correlation</th>
                  </tr>
                </thead>
                <tbody>
                  {auditRecords.map((record) => (
                    <tr key={record.eventId}>
                      <td className="text-xs">{formatTime(record.occurredAt)}</td>
                      <td className="text-xs">
                        <strong>{record.action?.replace(/_/g, ' ')}</strong>
                      </td>
                      <td className="text-xs mono">{record.actorId}</td>
                      <td className="text-xs mono">
                        {record.resourceType}/{String(record.resourceId).slice(0, 14)}
                      </td>
                      <td className="text-xs mono muted">
                        {String(record.correlationId ?? '').slice(0, 14)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        <Notice tone="info" title="Audit records cannot be edited by the application">
          In AWS the execution role is granted write-only access to the audit table —
          no update, no delete — so the application physically cannot alter history.
          That is tamper <em>resistance</em> within the platform&rsquo;s means, not
          cryptographic immutability, and it is documented as such.
        </Notice>
      </Card>
    </div>
  )
}
