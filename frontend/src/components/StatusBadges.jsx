/**
 * Status badges for availability, freshness, verification and priority.
 *
 * These carry the specification's honesty rules into the interface:
 *
 * - UNKNOWN availability is rendered as "Not reported", never as "0 units" or
 *   "Unavailable". The two mean different things and lead a user to different
 *   actions, so they must look different.
 * - Freshness and verification are always two separate badges. A recently
 *   updated batch that nobody has independently checked shows "Fresh" AND
 *   "Not verified" side by side.
 * - No status relies on colour alone: each has a text label and a distinct
 *   glyph, so the interface still works for a colour-blind user and in
 *   greyscale print.
 */
import './StatusBadges.css'

const AVAILABILITY = {
  AVAILABLE: { label: 'Available', glyph: '●', className: 'available' },
  PARTIAL: { label: 'Partial', glyph: '◐', className: 'partial' },
  UNAVAILABLE: { label: 'None in stock', glyph: '○', className: 'unavailable' },
  UNKNOWN: { label: 'Not reported', glyph: '?', className: 'unknown' },
}

const FRESHNESS = {
  FRESH: { label: 'Fresh', glyph: '✓', hint: 'Updated within 6 hours' },
  AGING: { label: 'Aging', glyph: '◷', hint: 'Updated 6–24 hours ago' },
  STALE: { label: 'Stale', glyph: '◷', hint: 'Updated 24–48 hours ago' },
  OUTDATED: { label: 'Outdated', glyph: '!', hint: 'Updated more than 48 hours ago' },
  UNKNOWN: { label: 'No update time', glyph: '?', hint: 'No update timestamp recorded' },
}

const VERIFICATION = {
  VERIFIED: {
    label: 'Independently verified',
    glyph: '✓',
    hint: 'A person confirmed these figures',
  },
  VERIFICATION_EXPIRED: {
    label: 'Verification expired',
    glyph: '◷',
    hint: 'Last independent check is more than 72 hours old',
  },
  UNVERIFIED: {
    label: 'Not verified',
    glyph: '—',
    hint: 'No independent human verification on record',
  },
}

const PRIORITY = {
  P1: { label: 'Critical', className: 'p1' },
  P2: { label: 'Urgent', className: 'p2' },
  P3: { label: 'Scheduled', className: 'p3' },
}

export function AvailabilityBadge({ state, units }) {
  const entry = AVAILABILITY[state] ?? AVAILABILITY.UNKNOWN
  const isUnknown = state === 'UNKNOWN' || state == null

  return (
    <span className={`badge badge--${entry.className}`}>
      <span aria-hidden="true" className="badge__glyph">{entry.glyph}</span>
      <span>{entry.label}</span>
      {/* A unit count is shown only when it is a real measurement. */}
      {!isUnknown && typeof units === 'number' && (
        <span className="badge__count">{units} unit{units === 1 ? '' : 's'}</span>
      )}
    </span>
  )
}

export function FreshnessBadge({ level }) {
  const entry = FRESHNESS[level] ?? FRESHNESS.UNKNOWN
  const className = (level ?? 'UNKNOWN').toLowerCase()
  return (
    <span className={`badge badge--fresh-${className}`} title={entry.hint}>
      <span aria-hidden="true" className="badge__glyph">{entry.glyph}</span>
      <span>{entry.label}</span>
    </span>
  )
}

export function VerificationBadge({ status }) {
  const entry = VERIFICATION[status] ?? VERIFICATION.UNVERIFIED
  const className = (status ?? 'UNVERIFIED').toLowerCase().replace(/_/g, '-')
  return (
    <span className={`badge badge--verify-${className}`} title={entry.hint}>
      <span aria-hidden="true" className="badge__glyph">{entry.glyph}</span>
      <span>{entry.label}</span>
    </span>
  )
}

/**
 * Freshness and verification together, which is how they must always appear.
 * Bundling them in one component makes it hard to render one without the other.
 */
export function DataQuality({ freshness, verification }) {
  return (
    <span className="data-quality">
      <FreshnessBadge level={freshness} />
      <VerificationBadge status={verification} />
    </span>
  )
}

export function PriorityBadge({ priority }) {
  if (!priority) {
    return (
      <span className="badge badge--uncertified" title="No hospital has certified a priority">
        <span aria-hidden="true" className="badge__glyph">—</span>
        <span>Not certified</span>
      </span>
    )
  }
  const entry = PRIORITY[priority] ?? { label: priority, className: 'p3' }
  return (
    <span className={`badge badge--${entry.className}`}>
      <span aria-hidden="true" className="badge__glyph">▲</span>
      <span>{entry.label}</span>
      <span className="badge__count">{priority}</span>
    </span>
  )
}

export function StatusPill({ status, tone = 'neutral' }) {
  return <span className={`pill pill--${tone}`}>{String(status ?? '').replace(/_/g, ' ')}</span>
}

const CAMP_TONES = {
  UPCOMING: 'info',
  ONGOING: 'success',
  COMPLETED: 'neutral',
  CANCELLED: 'danger',
  REJECTED: 'danger',
  PENDING_APPROVAL: 'warning',
}

export function CampStatusPill({ status }) {
  return <StatusPill status={status} tone={CAMP_TONES[status] ?? 'neutral'} />
}

const REQUEST_TONES = {
  REQUEST_CREATED: 'neutral',
  VERIFICATION_PENDING: 'warning',
  HOSPITAL_CERTIFIED: 'info',
  MATCHING_INITIATED: 'info',
  PROVIDERS_NOTIFIED: 'info',
  RESPONSES_RECEIVED: 'info',
  AVAILABILITY_CONFIRMED: 'success',
  RESOLVED: 'success',
  CANCELLED: 'neutral',
  EXPIRED: 'danger',
}

export function RequestStatusPill({ status }) {
  return <StatusPill status={status} tone={REQUEST_TONES[status] ?? 'neutral'} />
}
