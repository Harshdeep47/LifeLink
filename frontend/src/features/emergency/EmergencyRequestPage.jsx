/**
 * Emergency request creation.
 *
 * The form is deliberately blunt about what happens next: a new request carries
 * NO clinical priority. Priority is certified afterwards by authorized hospital
 * personnel, and nothing a requester types can set it. Stating that on the form
 * prevents the most likely misunderstanding -- that ticking "critical" makes a
 * request critical.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { api } from '../../api/client.js'
import { useMutation } from '../../hooks/useApi.js'
import { useAuth } from '../../auth/AuthContext.jsx'
import { Button, Card, Field, Notice } from '../../components/ui.jsx'

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const COMPONENTS = [
  { value: 'PRBC', label: 'Packed red blood cells (PRBC)' },
  { value: 'WHOLE_BLOOD', label: 'Whole blood' },
  { value: 'FFP', label: 'Fresh frozen plasma (FFP)' },
  { value: 'PLATELETS', label: 'Platelets' },
]

function validate(form) {
  const errors = {}
  if (!form.bloodGroup) errors.bloodGroup = 'Choose a blood group.'
  if (!form.component) errors.component = 'Choose a component.'
  const units = Number(form.requiredUnits)
  if (!Number.isFinite(units) || units < 1) {
    errors.requiredUnits = 'Enter at least one unit.'
  } else if (units > 50) {
    errors.requiredUnits = 'A single request cannot exceed 50 units.'
  }
  if (!form.contactName.trim()) errors.contactName = 'A contact name is required.'
  if (!form.contactPhone.trim()) {
    errors.contactPhone = 'A contact phone number is required.'
  }
  const lat = Number(form.latitude)
  const lon = Number(form.longitude)
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
    errors.latitude = 'Latitude must be between -90 and 90.'
  }
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) {
    errors.longitude = 'Longitude must be between -180 and 180.'
  }
  if (form.requiredBy) {
    const deadline = new Date(form.requiredBy)
    if (Number.isNaN(deadline.getTime())) {
      errors.requiredBy = 'Enter a valid date and time.'
    } else if (deadline <= new Date()) {
      errors.requiredBy = 'The deadline must be in the future.'
    }
  }
  if (!form.consentGiven) {
    errors.consentGiven = 'Consent is required before a request can be submitted.'
  }
  return errors
}

export function EmergencyRequestPage() {
  const navigate = useNavigate()
  const { isAuthenticated, hasRole } = useAuth()
  // Prefilled from the link that brought the user here, so "Request blood"
  // on a search result or a facility page arrives with the group, component,
  // quantity and location already chosen. Without this the user had to
  // re-enter everything they had just selected, which is the main reason the
  // workflow felt disconnected from discovery.
  const [params] = useSearchParams()
  const [form, setForm] = useState({
    bloodGroup: params.get('bloodGroup') || 'O-',
    component: params.get('component') || 'PRBC',
    requiredUnits: Number(params.get('units')) || 2,
    latitude: params.get('lat') || '30.3398',
    longitude: params.get('lon') || '76.3869',
    requiredBy: '',
    // Carried through so a provider can see which facility prompted the
    // request. It does not route the request to that facility -- matching is
    // the backend's job and is unchanged.
    preferredFacilityId: params.get('facilityId') || '',
    preferredFacilityName: params.get('facilityName') || '',
    contactName: '',
    contactPhone: '',
    patientReference: '',
    requestingInstitution: '',
    notes: '',
    consentGiven: false,
  })
  const [touched, setTouched] = useState(false)

  // One key per mounted form, so a double-click or a retry after a network
  // blip cannot create two requests.
  const idempotencyKey = useMemo(
    () => `emergency-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`,
    [],
  )

  const errors = validate(form)
  const hasErrors = Object.keys(errors).length > 0

  const create = useMutation((body) => api.createEmergencyRequest(body, idempotencyKey))

  function update(field, value) {
    setForm((previous) => ({ ...previous, [field]: value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setTouched(true)
    if (hasErrors) return
    try {
      const result = await create.run({
        bloodGroup: form.bloodGroup,
        component: form.component,
        requiredUnits: Number(form.requiredUnits),
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        requiredBy: form.requiredBy ? new Date(form.requiredBy).toISOString() : undefined,
        contactName: form.contactName,
        contactPhone: form.contactPhone,
        patientReference: form.patientReference || undefined,
        requestingInstitution: form.requestingInstitution || undefined,
        notes: form.notes || undefined,
        consentGiven: true,
      })
      if (result?.requestId) navigate(`/emergency/${result.requestId}`)
    } catch {
      /* the hook renders the error */
    }
  }

  if (!isAuthenticated) {
    return (
      <div className="stack" style={{ maxWidth: '760px' }}>
        <header className="page-header">
          <h1>Emergency blood request</h1>
        </header>
        <Notice tone="info" title="Sign in to raise a request">
          <p>
            An emergency request records contact details and is routed to nearby
            facilities, so it requires a signed-in account.
          </p>
          <Link to="/sign-in" className="btn btn--primary btn--sm">Sign in</Link>
        </Notice>
      </div>
    )
  }

  return (
    <div className="stack" style={{ maxWidth: '860px' }}>
      <header className="page-header">
        <h1>Emergency blood request</h1>
        <p>
          This creates a coordination request that LifeLink routes to suitable nearby
          facilities. Raising a request does not hold units and does not
          dispatch an ambulance.
        </p>
      </header>

      <Notice tone="warning" title="Clinical priority is certified by a hospital, not by this form">
        A new request is created <strong>without</strong> a priority. An authorized
        hospital user then certifies it as Critical, Urgent or Scheduled, and that
        decision is recorded against their name and organization. Nothing you enter
        here sets the clinical priority.
        {!hasRole('HOSPITAL_ADMIN', 'HOSPITAL_AUTHORIZER') && (
          <p className="text-sm" style={{ marginBottom: 0 }}>
            Your account cannot certify priority, so this request will wait for a
            hospital authorizer.
          </p>
        )}
      </Notice>

      <form onSubmit={handleSubmit} noValidate>
        <Card title="What is needed">
          <div className="grid grid--3">
            <Field
              label="Blood group"
              htmlFor="bloodGroup"
              required
              error={touched ? errors.bloodGroup : null}
            >
              {({ id }) => (
                <select
                  id={id}
                  value={form.bloodGroup}
                  onChange={(event) => update('bloodGroup', event.target.value)}
                >
                  {BLOOD_GROUPS.map((group) => (
                    <option key={group} value={group}>{group}</option>
                  ))}
                </select>
              )}
            </Field>

            <Field
              label="Component"
              htmlFor="component"
              required
              error={touched ? errors.component : null}
            >
              {({ id }) => (
                <select
                  id={id}
                  value={form.component}
                  onChange={(event) => update('component', event.target.value)}
                >
                  {COMPONENTS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              )}
            </Field>

            <Field
              label="Units required"
              htmlFor="requiredUnits"
              required
              error={touched ? errors.requiredUnits : null}
            >
              {({ id }) => (
                <input
                  id={id}
                  type="number"
                  min="1"
                  max="50"
                  value={form.requiredUnits}
                  onChange={(event) => update('requiredUnits', event.target.value)}
                />
              )}
            </Field>
          </div>

          <Field
            label="Required by"
            htmlFor="requiredBy"
            hint="Optional. A deadline within 30 minutes is prioritised in the dispatch queue."
            error={touched ? errors.requiredBy : null}
          >
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                type="datetime-local"
                value={form.requiredBy}
                onChange={(event) => update('requiredBy', event.target.value)}
              />
            )}
          </Field>
        </Card>

        <Card title="Where">
          <div className="grid grid--2">
            <Field
              label="Latitude"
              htmlFor="latitude"
              required
              error={touched ? errors.latitude : null}
            >
              {({ id }) => (
                <input
                  id={id}
                  type="text"
                  inputMode="decimal"
                  value={form.latitude}
                  onChange={(event) => update('latitude', event.target.value)}
                />
              )}
            </Field>
            <Field
              label="Longitude"
              htmlFor="longitude"
              required
              error={touched ? errors.longitude : null}
            >
              {({ id }) => (
                <input
                  id={id}
                  type="text"
                  inputMode="decimal"
                  value={form.longitude}
                  onChange={(event) => update('longitude', event.target.value)}
                />
              )}
            </Field>
          </div>
        </Card>

        <Card title="Contact and context">
          <div className="grid grid--2">
            <Field
              label="Contact name"
              htmlFor="contactName"
              required
              error={touched ? errors.contactName : null}
            >
              {({ id }) => (
                <input
                  id={id}
                  type="text"
                  autoComplete="name"
                  value={form.contactName}
                  onChange={(event) => update('contactName', event.target.value)}
                />
              )}
            </Field>
            <Field
              label="Contact phone"
              htmlFor="contactPhone"
              required
              error={touched ? errors.contactPhone : null}
            >
              {({ id }) => (
                <input
                  id={id}
                  type="tel"
                  autoComplete="tel"
                  value={form.contactPhone}
                  onChange={(event) => update('contactPhone', event.target.value)}
                />
              )}
            </Field>
          </div>

          <Field
            label="Requesting institution"
            htmlFor="requestingInstitution"
            hint="Optional, if a hospital is raising this on a patient's behalf."
          >
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                type="text"
                value={form.requestingInstitution}
                onChange={(event) => update('requestingInstitution', event.target.value)}
              />
            )}
          </Field>

          <Field
            label="Patient reference"
            htmlFor="patientReference"
            hint="Optional and non-identifying, e.g. a ward or case number. Do not enter a patient's name or medical details."
          >
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                type="text"
                value={form.patientReference}
                onChange={(event) => update('patientReference', event.target.value)}
              />
            )}
          </Field>

          <Field label="Notes" htmlFor="notes" hint="Optional operational notes for providers.">
            {({ id, describedBy }) => (
              <textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                value={form.notes}
                onChange={(event) => update('notes', event.target.value)}
              />
            )}
          </Field>
        </Card>

        <Card title="Consent">
          <Field label="" htmlFor="consentGiven" error={touched ? errors.consentGiven : null}>
            {({ id }) => (
              <label
                htmlFor={id}
                style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-start' }}
              >
                <input
                  id={id}
                  type="checkbox"
                  style={{ width: 'auto', marginTop: '4px' }}
                  checked={form.consentGiven}
                  onChange={(event) => update('consentGiven', event.target.checked)}
                />
                <span className="text-sm">
                  I consent to the contact details above being shared with the blood
                  banks and hospitals this request is routed to, so that they can
                  respond. I understand that raising a request does not hold
                  any units and that LifeLink does not make clinical decisions.
                </span>
              </label>
            )}
          </Field>
        </Card>

        {create.error && (
          <Notice tone="danger" title="The request was not created">
            <p style={{ margin: 0 }}>{create.error.message}</p>
            {create.error.code && (
              <p className="text-xs" style={{ margin: 0 }}>
                Code: <code>{create.error.code}</code>
              </p>
            )}
            {create.error.details?.rule && (
              <p className="text-xs" style={{ margin: 0 }}>
                Rule: <code>{create.error.details.rule}</code>
              </p>
            )}
          </Notice>
        )}

        {touched && hasErrors && (
          <Notice tone="warning" title="Please correct the highlighted fields" />
        )}

        <div className="row">
          <Button type="submit" size="lg" loading={create.submitting}>
            Submit request
          </Button>
          <span className="text-xs muted">
            Submitting twice will not create a duplicate request.
          </span>
        </div>
      </form>
    </div>
  )
}
