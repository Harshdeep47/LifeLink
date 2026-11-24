/**
 * Entry point into the emergency coordination workflow.
 *
 * Labelled "Emergency request", not "Request blood". The label used to be the
 * generic one, which sent anyone with an ordinary need down the escalated
 * path: emergency coordination fans a request out to matching providers and
 * carries a clinical priority that only a verified hospital may certify. An
 * ordinary need is served by searching and holding specific units instead.
 * Two workflows, two consequences, so two names.
 *
 * The workflow itself was already built and deployed: creation, hospital
 * certification, provider matching, provider responses, notifications and
 * tracking. What was missing was any way to *reach* it from the places where
 * a user realises they need it — a search result, a facility page, the
 * homepage. So this adds entry points and carries the context across; it does
 * not add a second request system.
 *
 * Context travels in the query string and is read by EmergencyRequestPage, so
 * a user who has already chosen O-negative PRBC, 4 units, near Patiala does
 * not re-enter all of it.
 *
 * What it carries is a *preference*, not a routing instruction: matching
 * remains the backend's job, and a request is never silently aimed at one
 * facility because the user happened to click from its page.
 */
import { Link } from 'react-router-dom'

export function requestBloodHref({
  bloodGroup,
  component,
  units,
  origin,
  facility,
} = {}) {
  const params = new URLSearchParams()
  if (bloodGroup) params.set('bloodGroup', bloodGroup)
  if (component) params.set('component', component)
  if (units) params.set('units', String(units))
  if (origin?.latitude != null) params.set('lat', String(origin.latitude))
  if (origin?.longitude != null) params.set('lon', String(origin.longitude))
  if (facility?.facilityId) params.set('facilityId', facility.facilityId)
  if (facility?.name) params.set('facilityName', facility.name)
  const query = params.toString()
  return query ? `/emergency?${query}` : '/emergency'
}

export function RequestBloodButton({
  bloodGroup,
  component,
  units,
  origin,
  facility,
  variant = 'secondary',
  size = 'sm',
  children = 'Emergency request',
}) {
  return (
    <Link
      className={`btn btn--${variant} btn--${size}`}
      to={requestBloodHref({ bloodGroup, component, units, origin, facility })}
    >
      {children}
    </Link>
  )
}
