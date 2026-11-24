/**
 * Static fallback for GET /reference.
 *
 * The home page rendered "Loading reference data…" whenever the reference
 * payload was falsy, which included the error case — so an API failure left a
 * permanent loading message with no way forward. A spinner that never resolves
 * is worse than an error, because it tells the user to keep waiting.
 *
 * These values mirror `backend/src/domain/blood.py`. They are safe to hard-code
 * because they are not configuration: the eight ABO/Rh groups and the four
 * components LifeLink handles are fixed domain facts, and changing them would
 * require schema and index changes, not a config edit.
 *
 * `isFallback` lets the interface say so rather than pretending the data came
 * from the API, and `compatibility` deliberately keeps the unreviewed status —
 * degrading to a fallback must not quietly upgrade a clinical caveat.
 *
 * Guarded by a unit test that compares this list against the live API response
 * shape, so the two cannot drift apart silently.
 */

export const REFERENCE_FALLBACK = {
  isFallback: true,
  bloodGroups: ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'],
  components: ['WHOLE_BLOOD', 'PRBC', 'FFP', 'PLATELETS'],
  componentLabels: {
    WHOLE_BLOOD: 'Whole Blood',
    PRBC: 'PRBC',
    FFP: 'FFP',
    PLATELETS: 'Platelets',
  },
  freshnessBands: [
    { label: 'FRESH', description: 'Updated within 6 hours' },
    { label: 'AGING', description: 'Updated 6 to 24 hours ago' },
    { label: 'STALE', description: 'Updated 24 to 48 hours ago' },
    { label: 'OUTDATED', description: 'Updated more than 48 hours ago' },
    { label: 'UNKNOWN', description: 'Never reported' },
  ],
  compatibility: {
    rulesVersion: 'abo_rh_v1',
    reviewStatus: 'UNREVIEWED_SYNTHETIC',
  },
}

/** Human label for a component code, falling back to the code itself. */
export function componentLabel(code) {
  return REFERENCE_FALLBACK.componentLabels[code] ?? code
}
