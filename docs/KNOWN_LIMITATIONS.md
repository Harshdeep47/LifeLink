# LifeLink — Known Limitations

Every limitation we are aware of, stated plainly. The specification requires
that implemented, simulated, configured-but-unverified and future functionality
be clearly distinguished, and this document is where that distinction lives.

---

## 1. Deployment: what is and is not verified

**LifeLink is deployed and live** at https://d324z37do52g8f.cloudfront.net.
This section previously said nothing was deployed; that was true until
15 November 2026. Full record: [DEPLOYMENT_RECORD.md](DEPLOYMENT_RECORD.md).

Verified against the running system: the API and all 50 routes registered at
that time (the repository now registers 58), radius and
ranking behaviour, Cognito token verification, role separation,
cross-organization refusal, DynamoDB persistence, CloudFront hosting with SPA
routing, and 24/24 data-coverage checks against the deployed database.

Still **not** verified, despite being deployed:

- **No alarm has ever fired.** All 8 are configured and mapped to runbook
  steps; none has been triggered, so none has been observed working.
- **Point-in-time restore has never been rehearsed.** Enabled on 8 tables;
  [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) §8 remains marked **UNTESTED**.
- **No load testing.** The Lambda concurrency ceiling on this account is 10 and
  the architecture is built for it, but no measurement exists. Latency and
  throughput figures remain design assumptions.
- **The Amazon Location tile path has never served a browser.** The map,
  identity pool and `MapReaderRole` exist and are configured, but the shipped
  frontend renders OpenStreetMap raster tiles instead, because the account's
  SCP denies a Location API key ([ADR-0019](ARCHITECTURE_DECISIONS.md#adr-0019),
  and §1.6 below). The map itself does render; what is unexercised is this
  credential path.
- **The background workers have not been observed processing real volume.** The
  outbox publisher, queue consumers, dispatcher and maintenance function are
  deployed and wired; only the API path has been exercised end to end.
- **No cost has yet appeared on a bill.** The $0.40/month fixed charge is from
  AWS list pricing, not from an invoice.
- **SES is in sandbox** — `ProductionAccessEnabled: false`, 200 messages/day,
  1/second, verified recipients only.

### 1.1 The Cognito browser redirect is not implemented

The sign-in page accepts a **pasted** bearer token. Deployed, that token is a
**real Cognito access token** verified by the API against the user pool's JWKS,
so the production verification path is genuinely exercised. What does not exist
is the browser-side redirect to Cognito managed login and the
authorization-code-with-PKCE exchange.

An earlier version of the `SignInPage` docstring claimed that flow was
implemented. It was not. The claim has been removed from the source, and it is
recorded here because a false statement in a comment is worse than a missing
feature.

A presenter obtains a token with
`python scripts/provision_demo_logins.py --stack lifelink-dev --token <user-id>`.

### 1.2 ADMIN_USER_PASSWORD_AUTH is enabled outside production

So that a script can mint a real token. It is an admin API guarded by IAM, not
a browser flow, and the template omits it when `Environment` is `prod`. In a
real deployment it would be a standing risk with no demonstration benefit.

### 1.3 The three PDF books are rebuilt, but describe the repository

**Status changed on 24 November 2026.** This previously read "the three PDF
books predate deployment", which was correct when written.

All three were rebuilt on 24 November 2026 — 328 pages, 24 validation checks
passing. Counts, versions and sizes are re-measured from the repository at
build time, so the figures are current: **657 backend tests, 294 frontend
tests, 951 in all**, 19 ADRs, 12 tables, 39 permissions. Four viva answers that
had become false were corrected — they asserted there was no reservation model.

The final rebuild ran **after** that day's deployment, so the books describe
the **deployed** system. The repository and the running application are in
sync, evidenced in
[REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) by a matching frontend
bundle hash and Lambda code SHA. An earlier version of this entry warned that
the books described a repository ahead of the live site; that is no longer the
case.

One caution remains:

* Prose written before the first deployment may still say "not deployed" in a
  place no fact directive covers. The known instances were corrected at source;
  if you find another, read [DEPLOYMENT_RECORD](DEPLOYMENT_RECORD.md).

### 1.4 Camp discovery searches up to 20 km

Camps carry a single precision-5 geohash index, while facilities carry three.
`search_cells` coarsens to precision 4 beyond 20 km, and a precision-4 cell can
never match a precision-5 key — so a wider camp search returned nothing at all,
including the camp at the search origin. Covering 100 km at precision 5 would
need roughly 1,600 queries.

The radius is therefore capped, but **reported** as `effectiveRadiusKm` with a
notice, rather than applied silently as it was before (a 100 km search quietly
returned only the camps within 20 km). The proper fix is a second, coarser camp
geo index plus a backfill.

### 1.5 Temporary reservations: both screens are now deployed

**Status changed on 24 November 2026.** This previously read "facility-side UI
is missing", which was correct when written.

The reservation API was always complete, authorized and tested. What was
missing was any **screen**: `GET /me/reservations` had no caller anywhere in
the frontend, and `decideReservation` / `fulfilReservation` had no screen at
all, so requests arrived at a facility with no way to answer them.

Both screens now exist in this repository — `ReservationQueue` on the blood
bank dashboard and `MyActivityPage` at `/activity` — covered by 40 component
tests and 43 logic tests.

**Both were deployed on 24 November 2026** and the underlying workflow is
live-verified end to end: create, provider confirm, provider fulfil, requester
cancel from both PENDING and CONFIRMED, and refusal of a second requester for
held units. 37 live checks, counters read straight from DynamoDB.

What remains: **neither screen has been seen working in a real browser by
anyone**, because no browser automation was available. See
[REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) §6.

That verification found a real defect in the workflow — confirming a hold
released its units, permitting overselling. Fixed and deployed the same day:
[RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md).

### 1.6 Amazon Location tiles cannot be used — blocked by the account's SCP

MapLibre cannot sign an AWS request itself, so Amazon Location tiles need
either an API key or SigV4 signing in the browser. An
`AWS::Location::APIKey` scoped to map reads was attempted and refused:

    Access denied for operation 'AWS::Location::APIKey'

The managed service control policy on this account type does not permit
Location API keys. The resource was removed and the stack redeployed. **It has
not been retried**, and should not be: bypassing an account-level control is
out of scope.

**The map does render.** An earlier version of this entry said the map "renders
its facility-list fallback until a tile credential exists" — that was true at
the time and is no longer. The basemap is now OpenStreetMap raster
([ADR-0019](ARCHITECTURE_DECISIONS.md#adr-0019), and §1.8 below), with
clustering, named markers, popups, selection sync and directions all working.
What remains blocked is the **tile source**, not the map, and drawing a route
line on the map; the routing API itself works.

### 1.7 No LifeLink-designed sign-up form

Sign-in uses Authorization Code with PKCE against Cognito. Registration uses
Cognito's own hosted pages rather than a LifeLink form, and there are no
separate Sign In / Sign Up tabs. A new account works end to end — it is
provisioned a `DONOR` profile on first request — but institutional
registration (hospital, blood bank, camp organizer) has no self-service
request flow. Those roles are granted by an administrator after verification,
which is the correct default and is deliberately not bypassed.

### 1.8 The basemap is OpenStreetMap, not Amazon Location

Amazon Location tiles need a credential the account will not permit
(`AWS::Location::APIKey` is denied by the SCP). The demonstration basemap is
OpenStreetMap standard raster tiles, which require no credential.

That choice carries obligations under the OSM tile usage policy, and they are
met: attribution is displayed, zoom is capped, and nothing prefetches or bulk
downloads. **This is not a production tile solution** and is not presented as
one. If a signed Amazon Location style URL becomes available,
`VITE_MAP_STYLE_URL` takes precedence automatically.

Drawing a route on the map is not implemented. Road distance and ETA are shown
only when a routing provider genuinely returns them; otherwise distances are
labelled straight-line and nothing is fabricated.

### 1.9 Retained resources keep costing after teardown

The audit table carries `DeletionPolicy: Retain` and survives `sam delete`. It
must be removed by hand or it continues to incur storage charges.

### 1.10 Repository and deployment are in sync (resolved)

**Status changed on 24 November 2026.** This previously recorded that the
polishing pass had never been deployed.

Everything was deployed that day — one frontend publish and two backend
changesets — and the sync is evidenced rather than asserted: the live bundle
hash matches the local build, and all six Lambdas share the CloudFormation SHA
of the package built from the current source.

[REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) carries the proof and the
commands to re-check it after any future deployment.

### 1.11 Expired sessions now clear (resolved)

**Status changed on 24 November 2026.** Fixed and deployed.

The previous build referenced an undefined `STORAGE_KEY` against
`localStorage`, in a module that keeps sessions in `sessionStorage`; the
`ReferenceError` was swallowed by a bare `catch {}`, so an expired token was
never cleared and the error reappeared on every page load. `clearSession()`
now removes the right key from the right storage.

**Not browser-verified** — the fix is covered by tests and is in the live
bundle, but nobody has watched a session expire in a browser.

### 1.12 No real facility data

Facility identity is still entirely synthetic. Both candidate public sources
were unreachable on 24 November 2026 — the Punjab SACS licensed-centre PDF
returned HTTP 404, and the e-RaktKosh mirror failed DNS resolution — and
recording institution names from search-result summaries that nobody read
would have been fabrication.

The mechanism to add sourced records safely is built and tested (three
provenance axes, a validator that refuses any unsourced record, 61 tests), so
this is blocked on sources rather than code. See
[REAL_FACILITY_DATA](REAL_FACILITY_DATA.md).

### 1.13 Fifteen ESLint warnings remain

All pre-existing, all the same pattern: a `||`-defaulted array feeding a
`useMemo`, which ESLint cannot prove is stable. `npm run lint` passes with 0
errors; `npm run lint:strict` still fails on these by design, so they stay
visible rather than silenced. Fixing them means `useMemo` surgery across five
working files — judged a poor trade immediately before an evaluation.

### 1.14 The CloudFront SPA fallback masks missing assets

Any missing path returns `index.html` with HTTP 200 rather than a 404. This
already disguised one real defect: a MapLibre worker that failed to load looked
like a successful fetch of HTML. Restricting the error response so `/assets/*`
returns a true 404 is an infrastructure change and needs approval; it has not
been made.

### 1.15 One reservation row has a stale stored status

`01M86AA2WV2KDXR0B0ZKR80F18` — 1 unit O-/PRBC at `fac-patiala-1` — is stored
as `CONFIRMED` while its effective status is `EXPIRED`. It holds nothing and
every pool counter is zero, so it has no user-visible effect: every read path
uses the effective status.

It is residue from the investigation that found the reservation counter
defect, and the expiry sweep cannot settle it because settling would decrement
a counter already at zero. Left in place deliberately rather than hand-editing
a production row. The only such row; the other eight are terminal.
[RESERVATION_COUNTER_DEFECT](RESERVATION_COUNTER_DEFECT.md) §8.

### 1.16 No counter-versus-rows invariant check

The pool counter and the reservation rows are updated in the same transaction,
so they cannot normally diverge — but nothing *checks* that they agree. An
invariant sweep comparing each counter with the sum of units held by its rows
would have caught the counter defect immediately and cheaply.

Not added in this session because it belongs in the maintenance sweep and
would have required a third deployment. Recommended as the next piece of work.

### 1.17 Fulfilment does not decrement inventory

Recording a reservation as `FULFILLED` releases the **hold** but does not
reduce `eligibleUnits`. Confirmed live: `eligible` stayed at 12 across a
fulfilment. Stock is adjusted by an explicit batch operation, so a facility
that issues units must also adjust the batch. Deliberate — fulfilment records
an operational fact, and inventory movement is a separate audited action — but
easy to misread as a bug.

### 1.18 Browser workflows have never been verified by anyone

No browser automation was available in any session. Every UI claim in this
library rests on component tests under jsdom plus string checks against the
live bundle. Twelve manual checks are listed in
[REPOSITORY_VS_DEPLOYED](REPOSITORY_VS_DEPLOYED.md) §6.

### 1.19 Re-seeding duplicated request timeline events — RESOLVED

**Fixed and applied on 24 November 2026.** Kept here because the mechanism is
instructive and because §1.20 below is its residue.

**What went wrong.** The seeder wrote request events with the sort key
`EVENT#<iso-now>#seed0001`. The `seed0001` suffix was fixed but the timestamp
came from the run clock, so each seed run created a *new* sort key for the same
logical event rather than overwriting it. `seed_cloud.py` promises in its own
docstring that "a second run rewrites the same items rather than adding more";
that held for every record type except this one, and nothing tested it.

Five runs left each of the ten demo requests carrying five `REQUEST_CREATED`
events. It was user-visible: `emergency_repo.load_full_request` sorts events by
**sort key** and `RequestTrackingPage` renders every entry, so the emergency
tracking page showed "REQUEST CREATED" five times.

**The fix.** `seed_demo.seed_event_sk()` returns a deterministic
`EVENT#0000#seed0001`. Three properties, each load-bearing:

* **Deterministic** — the same request always yields the same key, so a
  re-seed overwrites.
* **Still ordered first** — sorting is lexicographic on the whole sort key, and
  `"0"` precedes the first character of any ISO year, so a seeded creation
  event stays ahead of genuine events appended later. That is the correct
  order: the seeded event *is* the request's creation.
* **Displayed time unaffected** — `occurredAt` keeps its realistic,
  now-relative value, and that attribute is what the API returns and the
  interface shows. Only the key is synthetic.

**Deliberately not changed.** `emergency_repo.append_event`, the application's
own writer, still uses `EVENT#<iso-now>#<uuid8>`. Real history is append-only:
two genuine events at the same instant must both survive, and making that
writer deterministic would have been a far worse defect than the duplication
it replaced. Four tests pin it, and the live dispatcher demonstrated it by
appending two genuine events during the cleanup itself.

**Applied to the deployed stack**, in this order, which converges in one pass:

1. Re-ran the fixed seeder — emergency rows 97 → 107, writing one canonical
   `EVENT#0000#seed0001` per request.
2. Ran `scripts/dedupe_request_events.py --apply` — removed **50** duplicate
   rows, keeping the canonical one for each of the ten requests.

Cleanup-first would have been wrong: it keeps the earliest old-format row, which
the next seed would then duplicate again.

Result, verified against the deployed table and through the API:

| | Before | After |
|---|---|---|
| `REQUEST_EVENT` rows | 83 | **35** |
| — seeded | 60 | **10** (one per request, all `EVENT#0000#seed0001`) |
| — genuine | 23 | 25 (grew: the live dispatcher appended two) |
| `REQUEST_CREATED` per request | 5 | **1** |
| Request records / provider responses | 11 / 13 | 11 / 13 — untouched |

Reservations were untouched throughout: 9 rows, every pool counter `0`.

**Tests.** 47, of which five fail against the pre-fix key — verified by
reverting it. `backend/tests/integration/test_seed_idempotency.py` (17) and
`backend/tests/unit/test_dedupe_request_events.py` (30).

**Still not browser-verified.** The API now returns one creation entry per
request; nobody has watched the page render it.

### 1.20 Demo requests accumulate genuine lifecycle events across seed cycles

Discovered while verifying §1.19, and distinct from it. This is **not** a code
defect and the rows involved **must not** be deleted.

Demo emergency requests are seeded with now-relative deadlines in dispatchable
states. The live scheduled workers then do exactly what they should: the
dispatcher (every minute) transitions them, and the maintenance sweep (every
ten minutes) expires them, each appending a **genuine** `TRANSITION_*` event.
Re-seeding revives the request into a dispatchable state again, so the next
cycle appends more. Two such events were written within minutes of the
24 November re-seed.

`demo-req-p2-1` now carries nine genuine events dated between 15 and
24 November.

Two visible consequences:

1. **Repeated transition types.** Four `TRANSITION_MATCHING_INITIATED` entries
   on one request, because it was revived and re-dispatched four times.
2. **Timestamps that read out of order.** The seeded `REQUEST_CREATED` is
   now-relative and refreshes on every seed, while genuine events keep their
   real historical stamps. So a timeline can read "created 24 November, expired
   16 November".

Why it is not fixed:

* The events are **real history** written by the application. Deleting them is
  explicitly out of scope, and the cleanup script refuses them by design
  (they carry a uuid suffix and no `demoData` marker).
* Sorting the timeline by `occurredAt` instead of sort key would be **worse** —
  it would place the creation event after the transitions, so a request would
  appear to have been created after it expired.
* The honest alternative is not to re-seed, which costs the freshness the
  refresh exists to provide.

**For a demonstration:** pick a request with a short timeline, or explain that
the demo data is periodically refreshed while real worker history accumulates
against it. `demo-req-p1-1` currently has two entries; `demo-req-p2-1` has ten.

A proper fix would seed emergency requests in terminal states, or give them
deadlines far enough out that the workers leave them alone. Both change the
dataset's demonstration value — several scenarios exist precisely to show
dispatch and expiry — so it is a dataset design decision rather than a bug fix.

## 2. Clinical

### 2.1 The compatibility reference is not clinically reviewed

`backend/src/reference/compatibility/abo_rh_v1.json` carries
`reviewStatus: "UNREVIEWED_SYNTHETIC"` and `reviewedBy: null`.

It reflects standard ABO/Rh relationships as described in transfusion-medicine
teaching material. **No qualified professional has reviewed it for this
deployment.** The loader refuses to start if the review status is absent, every
API response derived from it carries the version and status, and the interface
repeats the disclaimer.

This is the most significant limitation in the project, and it is a process gap
rather than an engineering one.

### 2.2 The system makes no clinical decisions, by design

Not a defect, but worth stating as a boundary: LifeLink does not determine
clinical urgency, does not certify suitability, and does not assess fitness to
donate. Where it appears to approach such a judgement — donation interval
advice, compatibility narrowing, availability filtering — the output is
explicitly informational and points at qualified personnel.

## 3. Notifications

### 3.1 SMS is not implemented

AWS End User Messaging SMS is a Paid-Plan service, and this account's service
control policy (`p-2cb1m8xd`) denies `sms-voice:*` outright. Verified in
Phase 0 by calling `sns:GetSMSAttributes` and receiving an explicit deny.

`UnavailableSmsChannel` raises `CHANNEL_UNAVAILABLE` with the reason. It is
**not** stubbed to appear functional, and it does not log a pretend send.

### 3.2 SES is in sandbox

200 messages per day, one per second, verified recipients only. Adequate for a
demonstration. Production access is a separate AWS request.

## 4. Testing

| Not tested | Why | What would be needed |
|---|---|---|
| Load and throughput | At a Lambda concurrency ceiling of 10, a load test measures the ceiling | A quota increase, then a deployment |
| Backup restoration | Never rehearsed, though PITR is enabled on the deployed tables | A rehearsal against a restored table |
| Cognito itself, in the automated suite | Local development uses a different token issuer, so the suite exercises an equivalent verifier | — now covered by 19 live checks against the deployed pool, outside the suite |
| Accessibility beyond structure | No audit tool or assistive technology was used | An audit with a screen reader |
| Deployment rollback | Never exercised; no deployment has failed in a way that rolled back since the stack went live | A deliberately failing changeset |

Structural accessibility work *is* in place: visible focus rings, a skip link,
semantic headings, labelled fields with `aria-describedby`, `aria-live` on
async regions, and no status conveyed by colour alone.

## 5. Architecture

### 5.1 Dashboard aggregates are computed per request

Works at demonstration scale; would not at real scale. The correct answer is a
materialised read model updated from the event stream. Recorded as future work.

### 5.2 Table schema is declared twice

Once in `backend/src/repositories/schema.py` (driving the local bootstrap and
integration tests) and once in `infrastructure/template.yaml`. They can drift.
A generator emitting the template resources from the Python definitions would
fix it.

### 5.3 Single region

Cross-region replication, multi-region KMS keys and latency-based routing are
unavailable on this account. A regional outage means LifeLink is unavailable.

### 5.4 No reservation model

Deliberate — see ADR-0017. A user may travel to a facility and find the stock
gone. The interface states this at every point where a user might assume
otherwise. It is a design decision, not a missing feature, but it is a real
constraint on what the system can promise.

## 6. Local development

### 6.1 Local authentication is not Cognito

Cognito has no local emulator. The local stack issues RS256 tokens signed with
a development keypair, with the same claim shape. The *verification* path is the
same code; only the issuer differs. This is stated on the application's sign-in
page as well as here.

### 6.2 moto rather than DynamoDB Local

The specification suggests DynamoDB Local. Its archive could not be downloaded
in the environment this project was built in, so the default local backend is
moto in server mode, which speaks the same DynamoDB API over HTTP. The
application code and boto3 client are unchanged. `scripts/dev.py dynamo-start`
still launches the Java version.

Condition expressions, transactions and GSI range queries all behave correctly
under moto — four real bugs were caught by integration tests because of that
fidelity.

### 6.3 No `make`

`make` is not installed on the development machine. Commands are Python and npm
scripts, which §11.3 of the specification permits.

## 7. File uploads

The infrastructure provisions a private uploads bucket with versioning and
lifecycle rules, but **no upload flow exists in the application**. The
protections described for file validation, size limits, content-type checking
and presigned URLs are designed but not built. Two edge cases in the register
(S-09, S-10) are marked NOT HANDLED for this reason.

## 8. Operational

### 8.1 No CI pipeline

Tests, lint and the book build run manually. Not requested, and the commands
are documented.

### 8.2 Alarms are defined, not firing

Eight CloudWatch alarms are deployed. None has ever fired, because no
condition has arisen to trigger one, so none has been observed working.

### 8.3 No cost measurement

The cost estimate is built from published AWS pricing, not from a bill.

## 9. Defects found and fixed during the build

Recorded because the history is informative, not because they remain.

| Defect | Symptom | Status |
|---|---|---|
| Geohash neighbour-only coverage | A facility 25.6 km away never appeared in a 30 km search | **Fixed**, property-tested |
| Unused DynamoDB expression placeholders (4 sites) | `ValidationException` naming nothing useful | **Fixed**, detector script written |
| Version conflict reported as `DuplicateError` | Retry path never engaged | **Fixed** |
| `None` stripped from expression values | Any update setting an optional field to null failed | **Fixed** |
| Camp reminder index never populated | Reminders would never have fired | **Fixed**, regression-tested |
| Book build: blank pages | Double page breaks inflated page counts | **Fixed**, validator added |
| Book build: dropped code listings | A zero-height wrapper flowable was never drawn | **Fixed**, validator added |
| Book build: wrong code under a caption | A line-number include drifted after an edit | **Fixed**, anchors replace line numbers |
| Book build: test count recorded as zero | `-q` suppressed pytest's summary line | **Fixed**, unmeasurable now reported as such |

Four of the first five failed silently. All were found by testing or by
validation rather than by reading the code.
