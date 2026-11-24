/**
 * Manual location search, shared by blood-bank and camp discovery.
 *
 * Extracted from FindBloodPage so both discovery pages determine their origin
 * the same way. Previously only the blood search offered a manual alternative,
 * so a user who denied location permission could search for blood by city but
 * had no way to move the camp search off its default coordinates — and nothing
 * on screen said that was what had happened.
 *
 * Geocoding is served by the API, not called from the browser, so a user's
 * search text never reaches a third-party provider with an identity attached.
 *
 * Debounced to avoid a request per keystroke: geocoding is charged per
 * request, and an unthrottled autocomplete would multiply that by the length
 * of every place name anyone types.
 */
import { useEffect, useState } from 'react'

import { api } from '../api/client.js'
import { useApiData } from '../hooks/useApi.js'
import { Field } from './ui.jsx'

export function PlaceSearch({
  onSelect,
  label = 'Or search a place',
  hint = 'You never have to share your precise location.',
  id = 'place-search',
}) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query), 350)
    return () => window.clearTimeout(timer)
  }, [query])

  const { data: places, loading } = useApiData(
    (signal) => api.geocode({ q: debounced, limit: 5 }, signal),
    [debounced],
    { enabled: debounced.trim().length >= 2 },
  )

  const results = places?.results ?? []
  // The provider can be configured but unreachable. Saying so is better than
  // an empty list that looks like "no such place".
  const providerDown = places && places.providerAvailable === false

  return (
    <>
      <Field label={label} htmlFor={id} hint={hint}>
        {({ id: fieldId, describedBy }) => (
          <input
            id={fieldId}
            aria-describedby={describedBy}
            type="search"
            placeholder="e.g. Patiala, Chandigarh, Amritsar"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />
        )}
      </Field>

      {loading && debounced.trim().length >= 2 ? (
        <p className="text-xs muted" role="status">Searching places…</p>
      ) : null}

      {providerDown ? (
        <p className="text-xs muted">
          Place search is unavailable right now. You can still use your
          location, or browse the results below.
        </p>
      ) : null}

      {results.length > 0 ? (
        <ul className="find__places">
          {results.map((place) => (
            <li key={`${place.latitude},${place.longitude}`}>
              <button
                type="button"
                onClick={() => {
                  onSelect?.(place)
                  setQuery('')
                  setDebounced('')
                }}
              >
                {place.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {!loading && !providerDown && debounced.trim().length >= 2 && results.length === 0 ? (
        <p className="text-xs muted">No places matched that search.</p>
      ) : null}
    </>
  )
}
