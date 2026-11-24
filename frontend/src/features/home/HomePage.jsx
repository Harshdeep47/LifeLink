/**
 * Home page.
 *
 * The hero leads with the three things someone arriving in a hurry needs:
 * find blood, find a camp, raise an emergency request. Everything explanatory
 * comes after those, because a person under pressure should not have to scroll
 * past marketing copy to reach the action they came for.
 */
import { Link } from 'react-router-dom'

import { api } from '../../api/client.js'
import { REFERENCE_FALLBACK } from '../../api/referenceFallback.js'
import { useApiData } from '../../hooks/useApi.js'
import { Card, Notice } from '../../components/ui.jsx'
import './HomePage.css'

const ACTIONS = [
  {
    to: '/find',
    title: 'Find blood now',
    description:
      'Search nearby blood banks by blood group and component, with how recently each one reported its stock.',
    glyph: '◎',
    tone: 'primary',
  },
  {
    to: '/emergency',
    title: 'Raise an emergency request',
    description:
      'Coordinate an urgent requirement with nearby facilities. Clinical priority is certified by hospital staff.',
    glyph: '▲',
    tone: 'critical',
  },
  {
    to: '/camps',
    title: 'Donate at a camp',
    description:
      'Find upcoming donation camps near you, register, and track your verified donation history.',
    glyph: '✚',
    tone: 'secondary',
  },
]

export function HomePage() {
  // `loading` and `error` are both used: rendering on `reference` alone left
  // a permanent "Loading reference data…" message when the request failed.
  const {
    data: liveReference,
    loading: referenceLoading,
    error: referenceError,
  } = useApiData(() => api.reference(), [])

  // Fall back to the static domain constants rather than showing nothing. The
  // eight groups and four components are fixed facts, not configuration.
  const reference = liveReference ?? (referenceError ? REFERENCE_FALLBACK : null)

  return (
    <div className="home">
      <section className="hero">
        <p className="hero__eyebrow">Blood availability and emergency coordination</p>
        <h1 className="hero__title">
          Every Drop Counts.<br />Every Connection Saves Lives.
        </h1>
        <p className="hero__lede">
          LifeLink connects people who need blood with blood banks, hospitals, donors
          and donation camps — using reliable data, location intelligence and
          coordinated workflows.
        </p>
      </section>

      <nav className="actions" aria-label="Main tasks">
        {ACTIONS.map((action) => (
          <Link key={action.to} to={action.to} className={`action action--${action.tone}`}>
            <span className="action__glyph" aria-hidden="true">{action.glyph}</span>
            <span className="action__title">{action.title}</span>
            <span className="action__description">{action.description}</span>
            <span className="action__cue" aria-hidden="true">→</span>
          </Link>
        ))}
      </nav>

      <Notice tone="warning" title="What this system does and does not do">
        <p>
          LifeLink is a <strong>coordination</strong> system. It shows what facilities
          have reported and helps you contact them. It does <strong>not</strong> reserve
          stock, does not decide clinical urgency, and does not determine whether any
          particular unit is suitable for a patient. Those decisions belong to
          qualified medical professionals.
        </p>
      </Notice>

      <div className="grid grid--2">
        <Card title="How availability is reported">
          <p className="text-sm">
            Facilities report stock at the level of individual batches, each with its
            own expiry. LifeLink shows two separate things about every figure:
          </p>
          <ul className="home__list text-sm">
            <li>
              <strong>How recently it was updated</strong> — fresh, aging, stale or
              outdated.
            </li>
            <li>
              <strong>Whether a person independently verified it</strong> — which is
              not the same thing. An automated feed can update a figure every minute
              without anyone having checked it.
            </li>
          </ul>
          <p className="text-sm">
            Where a facility has reported nothing, LifeLink says
            <strong> &ldquo;not reported&rdquo;</strong> rather than showing zero. Those
            mean different things and lead to different decisions.
          </p>
        </Card>

        <Card title="Supported blood groups and components">
          {reference ? (
            <>
              <h4 className="home__subhead">Blood groups</h4>
              <ul className="home__chips">
                {reference.bloodGroups.map((group) => (
                  <li key={group} className="chip">{group}</li>
                ))}
              </ul>
              <h4 className="home__subhead">Components</h4>
              <ul className="home__chips">
                {reference.components.map((component) => (
                  <li key={component} className="chip chip--muted">
                    {component.replace(/_/g, ' ')}
                  </li>
                ))}
              </ul>
              <p className="text-xs muted">
                Blood group and component are tracked separately. Not every facility
                stocks every component. Compatibility reference version{' '}
                <code>{reference.compatibility.rulesVersion}</code> (
                {reference.compatibility.reviewStatus.replace(/_/g, ' ').toLowerCase()}).
              </p>
            </>
          ) : referenceLoading ? (
            <p className="muted text-sm">Loading reference data…</p>
          ) : (
            <p className="muted text-sm">Reference data is unavailable.</p>
          )}
          {reference?.isFallback ? (
            <p className="text-xs muted">
              Showing the built-in reference list; the live reference service
              could not be reached.
            </p>
          ) : null}
        </Card>
      </div>

      <Card title="For institutions">
        <div className="grid grid--3">
          <div>
            <h4 className="home__subhead">Blood banks</h4>
            <p className="text-sm muted">
              Maintain batch-level stock, record corrections and quarantine, and mark
              independent verification separately from routine updates.
            </p>
          </div>
          <div>
            <h4 className="home__subhead">Hospitals</h4>
            <p className="text-sm muted">
              Raise emergency requests and have authorized clinical staff certify
              priority. Every certification records who, when and from which hospital.
            </p>
          </div>
          <div>
            <h4 className="home__subhead">Camp organizers</h4>
            <p className="text-sm muted">
              Run donation camps end to end: approval, registration, check-in,
              donation recording and independent verification by assigned staff.
            </p>
          </div>
        </div>
      </Card>
    </div>
  )
}
