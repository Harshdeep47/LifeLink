/**
 * My profile: name, account type, verification status, institutional request.
 *
 * Two things this page deliberately does not do:
 *
 * 1.  It never shows the Cognito subject as a name. If the display name is
 *     missing or still equals the subject uuid, it says so plainly and invites
 *     the user to set one, rather than presenting a uuid as their identity.
 * 2.  It offers no way to change a role. The edit form posts only a display
 *     name, and the organization request is a *request* — the backend records
 *     it as pending and an administrator verifies it. A profile page that
 *     could grant institutional access would be the shortest path to
 *     privilege escalation in the product.
 */
import { useEffect, useState } from 'react'

import { api } from '../../api/client.js'
import { useAuth } from '../../auth/AuthContext.jsx'
import { AsyncState, Button, Card, Field, Notice } from '../../components/ui.jsx'

const REQUESTABLE = [
  { value: 'BLOOD_BANK', label: 'Blood bank' },
  { value: 'HOSPITAL', label: 'Hospital' },
  { value: 'CAMP_ORGANIZER', label: 'Donation camp organizer' },
]

const ROLE_LABELS = {
  DONOR: 'Individual / Donor',
  BLOOD_BANK_ADMIN: 'Blood bank administrator',
  BLOOD_BANK_STAFF: 'Blood bank staff',
  HOSPITAL_AUTHORIZER: 'Hospital authorizer',
  HOSPITAL_STAFF: 'Hospital staff',
  CAMP_ORGANIZER: 'Camp organizer',
  CAMP_STAFF: 'Camp staff',
  PLATFORM_ADMIN: 'Platform administrator',
}

export function ProfilePage() {
  const { principal, refresh, status } = useAuth()
  const [name, setName] = useState('')
  const [savedName, setSavedName] = useState(null)
  const [nameError, setNameError] = useState(null)
  const [savingName, setSavingName] = useState(false)

  const [request, setRequest] = useState({ requestedType: 'BLOOD_BANK', organizationName: '', note: '' })
  const [requestResult, setRequestResult] = useState(null)
  const [requestError, setRequestError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const pending = principal?.pendingOrganizationRequest ?? null
  // A display name equal to the user id means provisioning could not read a
  // name from Cognito. Showing the uuid would be worse than admitting it.
  const nameLooksUnset =
    !principal?.displayName || principal.displayName === principal.userId

  useEffect(() => {
    if (principal && !nameLooksUnset) setName(principal.displayName)
  }, [principal?.displayName])

  // A request chosen during sign-up is submitted on the first visit here,
  // because registration happens before a LifeLink profile exists.
  useEffect(() => {
    if (!principal || pending) return
    let stored = null
    try {
      stored = window.sessionStorage.getItem('lifelink.pendingOrgRequest')
    } catch { return }
    if (!stored) return
    try {
      const parsed = JSON.parse(stored)
      if (parsed?.requestedType && parsed?.organizationName) {
        api
          .requestOrganizationAccess(parsed)
          .then(() => {
            window.sessionStorage.removeItem('lifelink.pendingOrgRequest')
            refresh()
          })
          .catch(() => {
            // Left in place so the form below can be used instead.
          })
      }
    } catch { /* malformed; ignore */ }
  }, [principal?.userId, pending])

  const saveName = async (event) => {
    event.preventDefault()
    setNameError(null)
    setSavedName(null)
    if (!name.trim()) return setNameError('Enter a display name.')
    setSavingName(true)
    try {
      const result = await api.updateMyProfile({ displayName: name.trim() })
      setSavedName(result.displayName)
      await refresh()
    } catch (cause) {
      setNameError(cause?.message ?? 'Could not save your name.')
    } finally {
      setSavingName(false)
    }
  }

  const submitRequest = async (event) => {
    event.preventDefault()
    setRequestError(null)
    if (!request.organizationName.trim()) {
      return setRequestError('Enter your organization name.')
    }
    setSubmitting(true)
    try {
      const result = await api.requestOrganizationAccess({
        requestedType: request.requestedType,
        organizationName: request.organizationName.trim(),
        note: request.note.trim() || undefined,
      })
      setRequestResult(result)
      await refresh()
    } catch (cause) {
      setRequestError(cause?.message ?? 'Could not submit your request.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="stack stack--narrow">
      <header className="page-header">
        <h1>My profile</h1>
      </header>

      <AsyncState loading={status === 'loading'} isEmpty={!principal}
        emptyTitle="Not signed in"
        emptyMessage="Sign in to view your profile.">
        <>
          <Card title="Account">
            <dl className="definition-list">
              <div className="definition-list__row">
                <dt>Name</dt>
                <dd>
                  {nameLooksUnset ? (
                    <span className="muted">Not set yet — add one below.</span>
                  ) : (
                    principal.displayName
                  )}
                </dd>
              </div>
              <div className="definition-list__row">
                <dt>Email</dt>
                <dd>{principal.email ?? <span className="muted">Not available</span>}</dd>
              </div>
              <div className="definition-list__row">
                <dt>Account type</dt>
                <dd>
                  {(principal.roles ?? [])
                    .map((role) => ROLE_LABELS[role] ?? role)
                    .join(', ') || 'Individual / Donor'}
                </dd>
              </div>
              <div className="definition-list__row">
                <dt>Status</dt>
                <dd>{principal.accountStatus === 'ACTIVE' ? 'Active' : principal.accountStatus}</dd>
              </div>
            </dl>
            {/* The Cognito subject is deliberately not displayed: it is an
                internal identifier and means nothing to the person. */}
          </Card>

          <Card title="Display name" subtitle="How your name appears on records you create">
            <form onSubmit={saveName}>
              <Field label="Display name" htmlFor="display-name">
                {({ id }) => (
                  <input
                    id={id}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    maxLength={80}
                    autoComplete="name"
                  />
                )}
              </Field>
              {nameError && <p className="field__error" role="alert">{nameError}</p>}
              {savedName && (
                <p className="text-xs muted" role="status">Saved as “{savedName}”.</p>
              )}
              <Button type="submit" disabled={savingName}>
                {savingName ? 'Saving…' : 'Save name'}
              </Button>
            </form>
          </Card>

          <Card title="Institutional access">
            {pending ? (
              <Notice
                tone={pending.status === 'PENDING' ? 'info' : 'success'}
                title={`Request ${pending.status.toLowerCase()}`}
              >
                <p className="text-sm" style={{ margin: 0 }}>
                  You asked to be recognised as{' '}
                  <strong>
                    {REQUESTABLE.find((r) => r.value === pending.requestedType)?.label
                      ?? pending.requestedType}
                  </strong>{' '}
                  for <strong>{pending.organizationName}</strong>.
                  {pending.status === 'PENDING' && (
                    <> An administrator must verify the organization before any
                    institutional access is granted. Your account keeps its
                    current access until then.</>
                  )}
                </p>
              </Notice>
            ) : requestResult ? (
              <Notice tone="info" title="Request submitted">
                <p className="text-sm" style={{ margin: 0 }}>{requestResult.notice}</p>
              </Notice>
            ) : (
              <>
                <p className="inline-note">
                  If you work for a blood bank, hospital or camp organizer, you
                  can request that access here. Requests are{' '}
                  <strong>verified by an administrator</strong> before anything
                  changes — submitting one does not grant access.
                </p>
                <form onSubmit={submitRequest}>
                  <Field label="Requesting access as" htmlFor="requested-type">
                    {({ id }) => (
                      <select
                        id={id}
                        value={request.requestedType}
                        onChange={(e) =>
                          setRequest((p) => ({ ...p, requestedType: e.target.value }))}
                      >
                        {REQUESTABLE.map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                    )}
                  </Field>
                  <Field label="Organization name" htmlFor="org-name">
                    {({ id }) => (
                      <input
                        id={id}
                        value={request.organizationName}
                        onChange={(e) =>
                          setRequest((p) => ({ ...p, organizationName: e.target.value }))}
                      />
                    )}
                  </Field>
                  <Field label="Anything else we should know?" htmlFor="org-note">
                    {({ id }) => (
                      <textarea
                        id={id}
                        rows={3}
                        value={request.note}
                        onChange={(e) => setRequest((p) => ({ ...p, note: e.target.value }))}
                      />
                    )}
                  </Field>
                  {requestError && <p className="field__error" role="alert">{requestError}</p>}
                  <Button type="submit" disabled={submitting}>
                    {submitting ? 'Submitting…' : 'Submit request'}
                  </Button>
                </form>
              </>
            )}
          </Card>
        </>
      </AsyncState>
    </div>
  )
}
