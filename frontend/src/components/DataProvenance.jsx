/**
 * Where this record came from — shown to the user, not just recorded.
 *
 * Replaces a single "Synthetic record" pill with the two statements that
 * actually matter and can differ: whether the *place* is real, and whether the
 * *stock* is real. See `provenance.js` for why conflating them is the hazard.
 *
 * Degrades quietly. Records seeded before these fields existed carry only
 * `demoData`, and for those this renders exactly what the old pill did.
 */
import { describeProvenance } from './provenance.js'
import { StatusPill } from './StatusBadges.jsx'

/** Compact form: two pills, for a results row or a card header. */
export function ProvenancePills({ record }) {
  const { identity, inventory } = describeProvenance(record)
  return (
    <>
      <StatusPill status={identity.label} tone={identity.tone} />
      <StatusPill status={inventory.label} tone={inventory.tone} />
    </>
  )
}

/** Full form: the pills plus the sentences, for a detail page. */
export function DataProvenance({ record, showLocation = true }) {
  const described = describeProvenance(record)
  const { identity, inventory, coordinates, citation, realNameWithDemoStock } =
    described

  return (
    <div className="provenance">
      <div className="provenance__pills">
        <StatusPill status={identity.label} tone={identity.tone} />
        <StatusPill status={inventory.label} tone={inventory.tone} />
      </div>

      <dl className="provenance__list">
        <div className="provenance__row">
          <dt>This institution</dt>
          <dd>{identity.detail}</dd>
        </div>
        <div className="provenance__row">
          <dt>These quantities</dt>
          <dd>{inventory.detail}</dd>
        </div>
        {showLocation && (
          <div className="provenance__row">
            <dt>This location</dt>
            <dd>{coordinates.detail}</dd>
          </div>
        )}
        {citation && (
          <div className="provenance__row">
            <dt>Source</dt>
            <dd>
              {citation.url ? (
                <a href={citation.url} target="_blank" rel="noreferrer noopener">
                  {citation.name}
                </a>
              ) : (
                citation.name
              )}
              {citation.retrievedOn && (
                <span className="text-xs muted"> · retrieved {citation.retrievedOn}</span>
              )}
            </dd>
          </div>
        )}
      </dl>

      {/* The one combination that needs saying twice, because a real name
          beside a demonstration figure is the case most likely to be acted
          on by mistake. */}
      {realNameWithDemoStock && (
        <p className="provenance__warning" role="note">
          <strong>This is a real institution with demonstration stock.</strong>{' '}
          The name and address are from a public listing; the quantities are
          generated. Do not travel here on the strength of these figures, and
          do not contact this institution about them.
        </p>
      )}
    </div>
  )
}
