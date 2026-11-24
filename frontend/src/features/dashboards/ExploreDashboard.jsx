/**
 * Explore: one hub for blood banks and donation camps.
 *
 * Each tab is a dedicated directory view -- compact filters, a map and a
 * sortable list -- not the full Find Blood search form embedded twice. Find
 * Blood answers "I need four units of O-negative PRBC now"; Explore answers
 * "show me what is around here and let me narrow it down". One page doing
 * both did neither well.
 *
 * The standalone /find and /camps routes are unchanged and still work.
 *
 * The active tab lives in the URL (?tab=camps), so a tab is linkable,
 * survives a reload, and the back button moves between tabs as expected.
 */
import { useSearchParams } from 'react-router-dom'

import { BloodBankDashboardTab } from './BloodBankDashboardTab.jsx'
import { CampDashboardTab } from './CampDashboardTab.jsx'

const TABS = [
  { id: 'blood', label: 'Blood banks' },
  { id: 'camps', label: 'Donation camps' },
]

export function ExploreDashboard() {
  const [params, setParams] = useSearchParams()
  const active = TABS.some((t) => t.id === params.get('tab'))
    ? params.get('tab')
    : 'blood'

  const select = (id) => {
    const next = new URLSearchParams(params)
    next.set('tab', id)
    // replace: switching tabs should not stack history entries.
    setParams(next, { replace: true })
  }

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Explore</h1>
        <p className="page-header__lead">
          Blood banks and donation camps around a location you choose.
        </p>
      </header>

      <div className="tabs" role="tablist" aria-label="Explore">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={active === tab.id}
            aria-controls={`panel-${tab.id}`}
            className={`tabs__tab ${active === tab.id ? 'tabs__tab--active' : ''}`}
            onClick={() => select(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {active === 'blood' ? (
        <section role="tabpanel" id="panel-blood" aria-labelledby="tab-blood">
          <BloodBankDashboardTab />
        </section>
      ) : (
        <section role="tabpanel" id="panel-camps" aria-labelledby="tab-camps">
          <CampDashboardTab />
        </section>
      )}
    </div>
  )
}
