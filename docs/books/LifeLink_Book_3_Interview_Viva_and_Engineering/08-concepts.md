<!-- pagebreak -->

# 46. Frontend Interview Concepts

Questions a frontend interviewer will ask about this project, with answers
grounded in what was actually built.

**F1. Why is there exactly one module that calls `fetch`?**

Because the things that must happen on every request — the bearer token, the
correlation id, the idempotency key, error normalisation, abort handling —
cannot be forgotten if there is only one place they can be written. Thirty
components each calling `fetch` would mean thirty opportunities to omit one.

**F2. How do you stop a slow response overwriting a fast one?**

An `AbortController` per request, cancelled when the hook's dependencies
change. Without it, a user typing in a search box generates overlapping
requests, and an earlier slow response can land after a later fast one and
replace fresher results with staler ones. The symptom is intermittent and
maddening to reproduce.

**F3. What is the difference between your route guards and your authorization?**

The guards are usability. They keep a donor from clicking into a hospital
dashboard that would fail anyway. The server enforces authorization
independently on every request, which is why the guard's refusal message says
so explicitly — a user who edits the URL learns that nothing is gained.

**F4. Why bundle freshness and verification into one component?**

Because the specification requires them shown together, and separate
components make it easy to render one. `DataQuality` takes both and renders
both. A developer reaching for the convenient option gets the correct one.

**F5. How do you handle a component that throws?**

An error boundary around each routed view, so one failing panel does not blank
the application. React requires a class component for this, which is the one
remaining reason to write one.

**F6. Describe a React bug you fixed.**

Setting state during render to adopt a browser-provided geolocation. React
re-renders, the condition still holds, it sets state again — an infinite loop.
The fix is an effect keyed on the geolocation status.

**F7. How is accessibility handled?**

Visible focus rings everywhere, a skip link, semantic headings, labelled form
fields with `aria-describedby` for hints and errors, `aria-live` on
asynchronous regions, and no status conveyed by colour alone — every badge
carries a text label and a glyph. What has *not* been done is an audit with
assistive technology, and that is in the limitations.

**F8. Why code-split the dashboards?**

They are the heaviest and least-visited screens. A public visitor searching for
blood should not download the administrator dashboard. The production build
confirms them as separate chunks.

**F9. Why is MapLibre dynamically imported?**

It is 802 KB. With no map style configured — the local default — it is never
downloaded at all, and the facility list renders instead.

**F10. How do you test a presentation rule?**

Assert it. `renders UNKNOWN as "Not reported", never as a zero count` is a test
name, and the body checks both that the correct text appears and that
`0 units` does not. A rule that matters is a rule worth pinning.

<!-- pagebreak -->

# 47. Backend, Python and Lambda

**P1. Why is there no web framework?**

API Gateway hands a Lambda a dictionary and expects one back. A route table
and path matching is the entire requirement. A framework would add a
dependency, cold-start cost and an adapter layer for no capability gained.

**P2. What makes the domain layer testable?**

It has no I/O and does not read the clock. Every function takes `now` as a
parameter. The tests pass a fixed instant and assert exact boundaries with no
patching, which is why {{fact:test_unit}} unit tests run in under a second.

**P3. How do you keep a Lambda cold start small?**

A small dependency set, one function serving the whole API so warm containers
are reused widely, and the service object graph built once per container and
cached with `functools.lru_cache` rather than rebuilt per invocation.

**P4. Why `arm64`?**

Roughly 20% cheaper per millisecond at equivalent performance, and every
dependency publishes `aarch64` wheels. There is no downside at this
dependency footprint.

**P5. Why Python 3.14 specifically?**

It matches the local interpreter exactly, which removes an entire class of
"works on my machine" failure. It is generally available with support to June
2029. Python 3.15 exists but is in public preview and explicitly outside the
Lambda SLA.

**P6. How does the same code run locally and in Lambda?**

The local server builds an API Gateway-shaped event and calls the same router
the Lambda handler calls. Only the transport differs. There is no second
application that could drift.

**P7. What Python features does this code lean on?**

`StrEnum` for domain enumerations that serialise directly. Frozen slotted
dataclasses for immutable domain values. `Protocol` for structural interfaces
so adapters need no base class. `functools.lru_cache` for the container.
Modern union syntax throughout.

**P8. Why frozen dataclasses?**

A domain value that cannot be mutated cannot be mutated accidentally by a
caller. `apply_stock_operation` returns a new batch rather than modifying the
one it was given, so the pre-image is still available for the audit record.

**P9. How do you handle configuration?**

Environment variables set by the infrastructure template, read at module
import, with local defaults. No configuration is baked into code, and
`.env.example` documents every variable with placeholder values only.

**P10. What would you change about the Python?**

Add type checking in CI. The code is annotated throughout but nothing verifies
the annotations, so they are documentation rather than a guarantee.

<!-- pagebreak -->

# 48. REST API Design

**R1. What makes an API consistent?**

Predictability. Same resource naming, same status codes, same error shape,
same pagination mechanism, same idempotency mechanism everywhere. A client
developer should be able to guess the shape of an endpoint they have not read
about.

**R2. Why one response envelope?**

So a client writes one response handler. `{ data, meta?, correlationId }` on
success and `{ error: { code, message, details? } }` on failure. Every one of
the {{fact:openapi_operations}} operations uses it.

**R3. Why branch on a code rather than a message?**

The message is written for a human and may be reworded at any time. The code
is contract. A client matching on message text breaks the first time someone
improves the wording.

**R4. How do you decide between 400, 403, 404 and 409?**

400 means the request is malformed. 403 means it is well-formed and refused.
404 means the resource does not exist. 409 means the request conflicts with
current state — which is the interesting one, because it tells the client that
retrying *might* work, unlike the others.

**R5. Should a 403 ever be a 404?**

Sometimes. Returning 404 for a resource the caller may not see avoids
confirming it exists. LifeLink returns 403 with
`CROSS_ORGANIZATION_DENIED` but deliberately does not name the owning
organization, which gives a useful error without disclosure.

**R6. Why cursor pagination rather than offset?**

Offset requires the database to read and discard rows, which DynamoDB cannot
do efficiently and which produces inconsistent results when the underlying
data changes between pages. A cursor encodes position directly.

**R7. What is the fingerprint in the cursor for?**

So a cursor from one query presented against a different query is rejected
rather than silently returning results from the wrong set — a bug that is
nearly impossible to notice in testing.

**R8. How does idempotency work over HTTP?**

The client sends an `Idempotency-Key` header. The server claims it with a
conditional write before doing anything. A repeat with the same key returns the
stored result instead of repeating the effect.

**R9. Who generates the key?**

The client, because only the client knows that two requests are the same
logical operation. LifeLink's frontend generates one per mounted form, so a
double-click or a retry after a network blip cannot create two records.

**R10. How do you keep documentation accurate?**

Generate it. The OpenAPI document is produced from the live route table, so it
cannot describe an endpoint that does not exist, and a `--check` mode fails if
the committed file has drifted.

<!-- pagebreak -->

# 49. JWT, Cognito and Session Design

**J1. What is in a JWT?**

A header naming the algorithm and key id, a payload of claims, and a
signature. It is signed, not encrypted — anyone can read the claims, so
nothing secret belongs in them.

**J2. Why RS256 rather than HS256?**

Asymmetric signing means the verifier needs only the public key. With HS256 the
shared secret would have to exist everywhere a token is verified, and anyone
who can verify could also mint.

**J3. What do you verify?**

Signature against the key the `kid` names, issuer, expiry, the presence of a
subject, and that `token_use` is one you accept. Skipping any of them is a
vulnerability; skipping expiry is the classic one.

**J4. Why not verify audience?**

Cognito access tokens carry `client_id` rather than `aud`. Leaving `verify_aud`
enabled rejects every valid access token, and the common "fix" is to stop
checking the client at all. LifeLink disables the generic check and verifies
`client_id` explicitly.

**J5. What is the fundamental limitation of a JWT?**

It cannot be revoked. It is valid until it expires, by construction. Any
design that needs immediate revocation must check something else.

**J6. How does LifeLink handle that?**

By treating the token as proof of identity only. Roles and account status come
from the database on every request, so suspending an account takes effect on
the next request rather than at token expiry.

**J7. What does that cost, and how is it mitigated?**

One read per request, mitigated by a short in-process cache with a
thirty-second TTL. The staleness is bounded explicitly rather than
accidentally.

**J8. Where should a browser store a token?**

Neither option is perfect. `localStorage` is readable by any script, so a
cross-site scripting flaw exposes it. An httpOnly cookie resists that but
introduces cross-site request forgery, needing `SameSite` and a token. For a
development flow LifeLink uses `localStorage` and wraps every access in
try/catch for private-browsing contexts.

**J9. What is a refresh token for?**

Obtaining a new short-lived access token without re-authenticating. It lets
access tokens be short — one hour here — which bounds the damage from a leak,
while keeping the user signed in for thirty days.

**J10. What is PKCE protecting against?**

Authorization code interception. A public client cannot keep a secret, so
without PKCE an attacker who intercepts the code could exchange it. With PKCE
the exchange requires the verifier, which never left the browser that
generated it.

<!-- pagebreak -->

# 50. Maps, Geocoding and Routing

**M1. What does MapLibre actually do?**

Renders vector tiles in a browser. It does not supply tiles, geocode an
address or calculate a route. Conflating the renderer with the data behind it
is the most common mistake in map integrations.

**M2. Why can you not use the public OpenStreetMap tile servers?**

They run on donated infrastructure for development and light use. Pointing an
application at them breaches their usage policy and makes an operational
dependency of someone else's goodwill.

**M3. How does the browser fetch tiles without a key?**

A Cognito identity pool issues temporary credentials scoped to four read-only
tile actions on one map resource. A browser holding them cannot geocode,
cannot route and cannot read any data.

**M4. Why not proxy tiles through the backend?**

Volume. Tiles are thousands of small requests per session; proxying them
through Lambda would be slow, expensive and pointless, since the tiles are not
sensitive.

**M5. Then why proxy geocoding?**

Low volume, cacheable, and exposing it client-side turns the deployment into a
free geocoding service for anyone who opens the page.

**M6. What is the difference between straight-line and road distance?**

Straight-line is the direct distance between two points. Road distance is how
far you would drive, typically 20–40% further and sometimes much more. Showing
one labelled as the other is misleading in a way that matters when someone is
deciding where to drive.

**M7. What happens when routing fails?**

The response carries `routingAvailable: false` with a reason, and the road
distance and duration stay null. The straight-line figure is shown and
explicitly labelled as not a driving distance. Substituting one for the other
would be the convenient and wrong choice.

**M8. How do you test a map?**

The rendering, barely — it is a canvas. What you test is the fallback: with no
style configured, the component renders a facility list. Because that is the
local default, the fallback is exercised constantly rather than kept as
untested emergency code.

**M9. What is attribution and why does it matter?**

Tile providers require their data sources to be credited. It is a licence
condition, not a nicety, and MapLibre's attribution control is enabled.

**M10. Would you add a second routing provider?**

Only with a reason. The specification permits one as optional. A second
provider that cannot be verified end to end adds a failure mode without adding
reliability. The interface leaves the seam open, which is the point of having
an abstraction.

<!-- pagebreak -->

# 51. Cost and Capacity Reasoning

**C1. What does this system cost to run?**

About $0.40 a month in fixed charges — a Secrets Manager
secret at $0.40 — with everything else inside free tiers at demonstration
volume. The application is not free to run, and the documentation says so.

**C2. What scales with usage?**

Map tile loads and CloudWatch Logs ingestion, in that order. Both are easy to
overlook because neither appears in a functional requirement.

**C3. How do you control log cost?**

Retention as a template parameter defaulting to 30 days, and access logs that
exclude request bodies and query strings — which also happens to be the right
privacy decision.

**C4. Why on-demand DynamoDB rather than provisioned?**

Provisioned capacity requires predicting throughput for a system with no
traffic history and charges for idle capacity. On-demand costs more per
request and nothing at rest, which is the right shape for bursty, mostly-idle
usage.

**C5. When would you switch to provisioned?**

When traffic becomes predictable enough that reserved capacity is cheaper —
typically a sustained baseline. The crossover is around 15–20% utilisation of
provisioned capacity.

**C6. What was the most expensive decision you avoided?**

An always-on compute tier. A single small container running continuously costs
more per month than this entire architecture at demonstration volume.

**C7. How does the concurrency limit affect cost?**

It caps it, incidentally. Ten concurrent executions is also a ceiling on how
much Lambda time can be consumed per second, which makes a runaway bill
difficult.

**C8. What would you measure before optimising?**

Which endpoints dominate request count, which DynamoDB indexes dominate read
capacity, and the ratio of map tile loads to searches. Optimising without those
three numbers is guessing.

**C9. Is the free tier a reasonable basis for an architecture?**

For a demonstration, yes, and the design says which figures depend on it. For
production it is not, and the cost chapter separates fixed charges from
free-tier-covered ones precisely so the distinction survives.

**C10. What is the hidden cost in this design?**

Transactions. Every event-producing write is a transaction at double the write
cost. It is a deliberate trade for durability, and naming it is better than
discovering it on a bill.
