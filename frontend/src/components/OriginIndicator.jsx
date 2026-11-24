/**
 * Says where the search origin came from, and never overstates it.
 *
 * The problem this solves: the page opened showing "Patiala (default)" and
 * "Measured from 30.3398, 76.3869", and the nearest facility read 0.0 km. A
 * reader could reasonably conclude the browser had located them and they were
 * standing next to a blood bank. Neither was true — no permission had been
 * requested, and that facility had been seeded onto the city centroid.
 *
 * So the origin now carries its provenance, and the three cases look
 * different:
 *
 *   default — nobody has told us anything. Labelled a *default search
 *             location*, never "your location".
 *   manual  — the user picked a place by name. Named, with its own icon.
 *   gps     — the browser returned real coordinates. Only this one says
 *             "Using your current location", and only after coordinates
 *             actually arrived.
 *
 * Accuracy is shown for GPS because a 3 km fix and a 20 m fix mean very
 * different things for "nearest".
 */

const SOURCES = {
  default: {
    icon: '◇',
    title: 'Default search location',
    tone: 'origin--default',
  },
  manual: {
    icon: '⌖',
    title: 'Searching a place you chose',
    tone: 'origin--manual',
  },
  gps: {
    icon: '◉',
    title: 'Using your current location',
    tone: 'origin--gps',
  },
}

export function OriginIndicator({
  source = 'default',
  label,
  origin,
  accuracy = null,
  status = 'idle',
  message = null,
}) {
  const meta = SOURCES[source] ?? SOURCES.default

  return (
    <div className={`origin ${meta.tone}`}>
      <span className="origin__icon" aria-hidden="true">{meta.icon}</span>
      <div className="origin__text">
        <strong className="origin__title">
          {status === 'locating' ? 'Finding your location…' : meta.title}
        </strong>

        {source === 'default' ? (
          <span className="origin__detail">
            Showing results near Patiala because no location has been set.
            Use your location or search a place to change this.
          </span>
        ) : (
          <span className="origin__detail">{label}</span>
        )}

        {origin && (
          <span className="origin__coords">
            Distances measured from {origin.latitude.toFixed(4)},{' '}
            {origin.longitude.toFixed(4)}
            {source === 'gps' && typeof accuracy === 'number'
              ? ` · accurate to about ${Math.round(accuracy)} m`
              : ''}
          </span>
        )}

        {/* Geolocation problems are shown here rather than swallowed: a
            denied permission that silently leaves the default in place is
            exactly how a default gets mistaken for a real location. */}
        {message && (
          <span className="origin__message" role="status">{message}</span>
        )}
      </div>
    </div>
  )
}
