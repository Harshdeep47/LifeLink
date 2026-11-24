/**
 * Help, privacy and terms.
 *
 * Privacy and terms are explicitly marked as placeholders requiring legal
 * review. The specification forbids claiming compliance or certification
 * without a proper assessment, so these pages describe what the system does
 * with data and say plainly that the text has not been reviewed by a lawyer.
 */
import { Card, Notice } from '../../components/ui.jsx'

export function HelpPage() {
  return (
    <div className="stack">
      <header className="page-header">
        <h1>Help</h1>
        <p>How to read what LifeLink shows you, and what it cannot tell you.</p>
      </header>

      <Card title="Availability, freshness and verification are three different things">
        <dl className="definition-list">
          <div className="definition-list__row">
            <dt>Available</dt>
            <dd>
              The facility has reported eligible, unexpired stock of the group and
              component you asked for.
            </dd>
          </div>
          <div className="definition-list__row">
            <dt>Partial</dt>
            <dd>There is some stock, but less than the number of units you asked for.</dd>
          </div>
          <div className="definition-list__row">
            <dt>None in stock</dt>
            <dd>
              The facility has reported its stock, and it currently has none of what
              you need.
            </dd>
          </div>
          <div className="definition-list__row">
            <dt>Not reported</dt>
            <dd>
              The facility has not reported inventory at all. This is <strong>not</strong>{' '}
              the same as having none. Telephone them and ask.
            </dd>
          </div>
        </dl>
      </Card>

      <Card title="How recent is the data?">
        <p className="text-sm">
          Freshness describes how long ago the facility last updated the figure:
        </p>
        <dl className="definition-list">
          <div className="definition-list__row"><dt>Fresh</dt><dd>Within the last 6 hours</dd></div>
          <div className="definition-list__row"><dt>Aging</dt><dd>6 to 24 hours ago</dd></div>
          <div className="definition-list__row"><dt>Stale</dt><dd>24 to 48 hours ago</dd></div>
          <div className="definition-list__row"><dt>Outdated</dt><dd>More than 48 hours ago</dd></div>
        </dl>
        <Notice tone="info" title="Updated is not the same as verified">
          A facility can have an automated system that updates a number every few
          minutes without anyone having physically checked the shelf. LifeLink
          therefore shows verification separately: &ldquo;Independently verified&rdquo;
          means a person confirmed the figures, and &ldquo;Not verified&rdquo; means
          nobody has.
        </Notice>
      </Card>

      <Card title="What LifeLink will not do">
        <ul className="text-sm">
          <li>
            <strong>Browsing does not hold anything.</strong> Figures on a
            results page are reports from each facility. You can request a{' '}
            <strong>temporary reservation</strong>, which holds specific units
            for a limited time and takes them out of everyone else&apos;s search
            results until it expires or is released.
          </li>
          <li>
            <strong>A reservation is not clinical approval.</strong> It is not a
            cross-match and not a guarantee of release. Compatibility and
            release remain decisions for qualified staff at the facility.
          </li>
          <li>
            <strong>It does not decide clinical urgency.</strong> Only authorized
            hospital staff certify the priority of an emergency request.
          </li>
          <li>
            <strong>It does not decide clinical suitability.</strong> Compatibility
            shown here narrows operational matching only; crossmatching and release
            are laboratory and clinical decisions.
          </li>
          <li>
            <strong>It does not confirm you can donate.</strong> Camp staff assess
            eligibility on the day.
          </li>
        </ul>
      </Card>

      <Card title="Distances">
        <p className="text-sm">
          Where LifeLink says <strong>straight-line</strong>, it means the direct
          distance between two points, not the distance you would drive. Road distance
          and estimated travel time are shown separately and only when a routing
          provider returns them. If routing is unavailable, LifeLink says so rather
          than showing a straight-line figure as if it were a driving distance.
        </p>
      </Card>
    </div>
  )
}

export function PrivacyPage() {
  return (
    <div className="stack">
      <header className="page-header">
        <h1>Privacy and data handling</h1>
      </header>

      <Notice tone="warning" title="Placeholder — requires legal review">
        This text describes what the system does with data. It is <strong>not</strong> a
        reviewed privacy notice, and nothing here should be read as a statement of
        legal compliance or certification. A qualified assessment against the Indian
        Digital Personal Data Protection framework and any applicable medical data
        rules is required before this system handles real personal data.
      </Notice>

      <Card title="What this demonstration collects">
        <ul className="text-sm">
          <li>Account identity and role, to decide what you may do.</li>
          <li>
            An approximate location when you search, to find facilities near you.
            Precise coordinates are not stored; only a coarse geographic cell derived
            from them is kept on records that need it.
          </li>
          <li>Contact details you type into an emergency request, so facilities can reach you.</li>
          <li>Camp registrations and verified donation records.</li>
          <li>
            An audit record of privileged actions: who did what, to which record, and
            when.
          </li>
        </ul>
      </Card>

      <Card title="Choices you have">
        <ul className="text-sm">
          <li>Location sharing is optional. Searching by place name works the same way.</li>
          <li>Notifications require consent, and each category can be turned off separately.</li>
          <li>
            Your donation history and certificates are visible only to you and to
            platform administrators.
          </li>
        </ul>
      </Card>

      <Card title="What is deliberately not done">
        <ul className="text-sm">
          <li>Sensitive values are redacted from logs rather than recorded.</li>
          <li>Precise coordinates are not retained once a search is complete.</li>
          <li>Donor identities are not exposed to other donors.</li>
          <li>No data in this demonstration is real, and no real institution is represented.</li>
        </ul>
      </Card>
    </div>
  )
}

export function TermsPage() {
  return (
    <div className="stack">
      <header className="page-header">
        <h1>Terms of use</h1>
      </header>

      <Notice tone="warning" title="Placeholder — requires legal review">
        This page is a placeholder for a reviewed terms-of-use document. It has not
        been drafted or checked by a lawyer.
      </Notice>

      <Card title="The essential points">
        <ul className="text-sm">
          <li>
            LifeLink is a demonstration system containing synthetic data. Do not rely
            on it for any real clinical or logistical decision.
          </li>
          <li>It is not a medical device and provides no medical advice.</li>
          <li>
            Availability information is reported by facilities and is not guaranteed,
            reserved or clinically approved.
          </li>
          <li>
            Named institutions in this demonstration are invented. None is a real
            partner.
          </li>
          <li>Recognition certificates are not medical or government documents.</li>
        </ul>
      </Card>
    </div>
  )
}
