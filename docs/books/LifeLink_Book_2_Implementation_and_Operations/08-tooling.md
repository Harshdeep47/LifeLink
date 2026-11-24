<!-- pagebreak -->

# 44. The Seed Data Generator

## 44.1 Why the seeder is production code

A demonstration dataset that is wrong is worse than none: every screenshot,
every walkthrough and every test built on it inherits the error. The seeder is
therefore written with the same care as the application, and validated.

## 44.2 Determinism

```python
SEED = 20261115
self.rng = random.Random(SEED)
```

*Listing 44.1. A fixed seed and a dedicated generator instance.*

A dedicated `Random` instance rather than the module-level functions, so
unrelated code calling `random` cannot perturb the dataset. Identifiers are
fixed strings (`demo-batch-0001`), not generated, so a screenshot taken today
matches a database rebuilt next month.

## 44.3 Deliberate coverage

The dataset is not random data within plausible ranges. Every case the
specification names is placed on purpose:

{{include:scripts/seed_demo.py:anchor:freshness_plan = [:6}}

*Listing 44.2. The freshness spread from `scripts/seed_demo.py`.*

Fifty batches in each freshness band, so the four labels are all visible on
screen rather than theoretically reachable. Similar deliberate placement
covers quarantined stock, expired stock, near-expiry stock, zero-unit batches,
and a facility that has reported nothing at all.

## 44.4 The production guard

{{include:scripts/seed_demo.py:def guard_environment}}

*Listing 44.3. Three independent refusals.*

Three checks rather than one, because a single condition is one typo away from
being bypassed. The environment name must be local, dev or test; a local
endpoint must be configured; and the endpoint must not point at real AWS.

## 44.5 Validation as a first-class command

{{include:scripts/seed_demo.py:anchor:checks.append(("all 8 blood groups present":4}}

*Listing 44.4. One of twenty-four coverage checks.*

`--validate` reports each check individually and exits non-zero if any fails.
The alternative — a seeder that prints "done" — gives no evidence the dataset
covers what the demonstration needs.

## 44.6 Resetting

`--reset` deletes every item marked `demoData` before seeding. That requires a
scan, which is otherwise forbidden, so the function logs that it performed one:

```
OFFLINE MAINTENANCE SCAN: removed 312 demo items
```

*Listing 44.5. A scan that announces itself.*

Making the exception visible in the output is deliberate. A rule with silent
exceptions stops being a rule.

<!-- pagebreak -->

# 45. The OpenAPI Generator

## 45.1 The problem it solves

The specification says to generate an OpenAPI document matching the actual
endpoints, and not to document endpoints that do not exist. A hand-maintained
document satisfies neither requirement for long.

## 45.2 Reading the router

{{include:scripts/generate_openapi.py:def build_document}}

*Listing 45.1. Document construction from `scripts/generate_openapi.py`.*

The generator imports the live route table. An endpoint that does not exist
cannot appear, and one that exists cannot be forgotten.

## 45.3 Error responses are derived, not assumed

Only statuses a route can actually produce are documented. A route marked
anonymous omits 401; a route with no declared permission omits 403. Listing
every status on every operation would be noise that trains readers to ignore
the section.

## 45.4 Permissions in the document

Each operation carries an `x-lifelink-permission` extension naming the
permission required, so the document doubles as an authorization reference.
That is information a hand-written document would never stay accurate about.

## 45.5 Drift detection

```bash
python scripts/generate_openapi.py --check
# OpenAPI document matches the route table.
```

*Listing 45.2. Failing on drift.*

A `--check` mode that exits non-zero when the committed file differs from what
the router would produce. Suitable for a pre-commit hook or CI.

## 45.6 A lesson about hand-rolled formats

The first version emitted YAML with a bespoke serialiser to avoid a
dependency. It produced invalid YAML for multi-line description blocks — the
block-scalar indentation was wrong — and the file looked plausible while being
unparseable.

It now uses PyYAML and **parses the output back**, comparing it to the JSON
document before writing. A machine-readable artifact that cannot be read by a
machine is worse than one that does not exist, because its existence implies
it works.

<!-- pagebreak -->

# 46. The Local Server

## 46.1 Translating HTTP into a Lambda event

{{include:scripts/local_server.py:anchor:event = {:12}}

*Listing 46.1. Event construction from `scripts/local_server.py`.*

The shape matches what API Gateway delivers, so the router and every handler
behave identically. The specification warns against a mock application that
behaves differently from the real architecture; the way to avoid that is to
have only one application.

## 46.2 CORS in development

{{include:scripts/local_server.py:def _cors_headers}}

*Listing 46.2. CORS handling.*

The Vite dev server also proxies `/api` to the local server, which makes the
browser same-origin and avoids CORS entirely. The headers exist for direct
calls — `curl`, Postman — during development.

## 46.3 Staying up

A last-resort try/except around dispatch returns a 500 rather than killing the
server. A development server that dies on an unhandled exception interrupts
work for no benefit; the exception is still logged in full.

## 46.4 What it prints on startup

```
LifeLink local API on http://127.0.0.1:8080
  DynamoDB endpoint : http://localhost:8000
  Routes registered : 50
  CORS origins      : http://localhost:5173
  DEMO ENVIRONMENT - SYNTHETIC DATA - NOT REAL BLOOD AVAILABILITY
```

*Listing 46.3. Startup output.*

The route count is a cheap sanity check: if it is not what you expect, a
module failed to import.

<!-- pagebreak -->

# 47. Error Handling Patterns

## 47.1 The taxonomy as code

{{include:backend/src/domain/errors.py:class LifeLinkError}}

*Listing 47.1. The base error from `backend/src/domain/errors.py`.*

Three properties on every error: a stable `code` for clients, an `http_status`
so the router needs no mapping table, and a `details` dictionary for
machine-readable context.

## 47.2 Specific errors for specific conditions

Fifteen error classes rather than one with a message. The difference matters
at the call site:

```python
except ConcurrentModificationError:
    # Retry: the next attempt may well succeed.
except InsufficientStockError:
    # Do not retry: it will fail identically.
```

*Listing 47.2. Why error type matters more than error message.*

A single exception type would force string matching to make that distinction,
and string matching on error messages breaks the first time someone improves
the wording.

## 47.3 Details carry the rule

```python
raise ForbiddenError(
    "a donor cannot verify their own donation",
    details={"rule": "SELF_VERIFICATION_FORBIDDEN"},
)
```

*Listing 47.3. A named rule in the details.*

The message is for a human; the rule name is for a client developer, who can
branch on it or display a specific explanation.

## 47.4 Translating infrastructure errors

{{include:backend/src/repositories/dynamo.py:def translate_client_error}}

*Listing 47.4. DynamoDB errors mapped onto the domain taxonomy.*

Nothing above the repository layer sees a `ClientError`. Transaction
cancellations are unpacked so a conditional-check failure becomes a
concurrency error rather than an opaque "transaction cancelled".

## 47.5 The boundary

{{include:backend/src/handlers/router.py:anchor:except LifeLinkError as exc::14}}

*Listing 47.5. The edge of the system.*

Domain errors keep their code and status. Anything else becomes a generic 500
with a correlation id — the detail goes to the log, never to the client,
because an exception message can disclose internals.

<!-- pagebreak -->

# 48. The Design Token System

## 48.1 Why tokens rather than values

Every colour, space, radius and font size is a custom property on `:root`.
Changing the brand crimson is one edit. More importantly, a component cannot
invent a colour that is almost but not quite the right one, which is how
interfaces drift.

## 48.2 Status colours are chosen for contrast, not decoration

{{include:frontend/src/styles/tokens.css:anchor:/* Status: data freshness */:10}}

*Listing 48.1. Freshness tokens from `frontend/src/styles/tokens.css`.*

Each status has a foreground and a background chosen together to meet contrast
requirements, rather than a single colour applied to text on white.

## 48.3 No status relies on colour alone

Every badge carries a text label and a distinct glyph. The interface works in
greyscale, in print, and for a colour-blind user. For a service used under
pressure that is a requirement rather than a nicety.

## 48.4 Focus is always visible

```css
:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: var(--radius-sm);
}
```

*Listing 48.2. A visible focus ring everywhere.*

`:focus-visible` rather than `:focus` so a mouse click does not leave a ring,
while keyboard navigation always shows one.

## 48.5 Reduced motion is respected

A `prefers-reduced-motion` block reduces every animation and transition to
effectively zero. The only animation in the application is a loading spinner,
but honouring the preference costs four lines.

## 48.6 The demo banner cannot be dismissed

```css
.demo-banner {
  position: sticky;
  top: 0;
  z-index: 60;
```

*Listing 48.3. A banner that stays.*

There is no close button, and the sticky positioning keeps it visible while
scrolling. A banner a user can close is one they will close, after which a
screenshot of invented blood stock is indistinguishable from real institutional
data.
