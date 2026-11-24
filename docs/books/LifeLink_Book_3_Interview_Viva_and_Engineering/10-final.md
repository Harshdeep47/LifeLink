<!-- pagebreak -->

# 55. Twenty More Scenario Questions

Additional scenarios covering the platform and security edge cases.

**S31. A token is valid but the user record has been deleted.**

Authentication fails with "authenticated subject has no LifeLink account". The
directory lookup returns nothing, and the authenticator refuses rather than
constructing a principal from claims.

**S32. A user's role is changed while they have the dashboard open.**

The next request uses the new role, because roles are read from the database
per request. The open page may show controls they can no longer use; clicking
one returns 403. The UI is a hint, the server is the authority.

**S33. Two administrators suspend the same organization simultaneously.**

Both succeed. The write is idempotent in effect — the status ends as
`SUSPENDED` either way — and both are audited, so the record shows two
actions rather than hiding one.

**S34. A correlation id is supplied by the client.**

It is honoured, so a client can correlate its own logs with the server's. It
is not trusted for anything else; it is a logging key, not an identity.

**S35. A request arrives with a malformed Authorization header.**

`UNAUTHENTICATED` with a message naming the expected format. A missing header
is treated as anonymous; a malformed one is an error, because the caller
clearly intended to authenticate.

**S36. A client sends the same idempotency key for two genuinely different
requests.**

The second returns the first request's stored result. That is the client's
error, and the contract is explicit: the key identifies the operation. This is
why the frontend generates one key per mounted form rather than reusing one.

**S37. The idempotency table's TTL removes a claim mid-request.**

The claim write fails its not-exists condition, the subsequent read finds
nothing, and the code treats it as a fresh claim rather than erroring. That
race is handled explicitly in the claim function.

**S38. A notification is queued for a user who then withdraws consent.**

The consumer re-checks consent at send time, not at queue time, and the
outcome records `NO_CONSENT`. A queued notification is not a committed one.

**S39. SES rejects an email because the recipient is not verified.**

The delivery result records `FAILED` with the provider's reason. Nothing
claims the message was delivered. In sandbox this is the expected outcome for
most addresses, and it is a documented limitation rather than a bug.

**S40. A log line would contain a patient reference.**

The redaction set covers key names at any depth. Patient reference is a
free-text field the user is explicitly asked not to put identifying
information in, and the form says so. That is weaker than redaction and is
worth stating: the mitigation there is interface guidance, not enforcement.

**S41. An outbox row has been pending for an hour.**

The domain data is correct — the write was transactional. Only publication is
behind. Check the publisher's logs and the stream iterator age; the event is
not lost.

**S42. An event type has no route in the publisher.**

It is logged as a warning and marked dispatched, so it does not sit pending
forever and trigger the reconciliation alarm indefinitely. The warning is the
signal that a route is missing.

**S43. A queue consumer is throttled by the concurrency ceiling.**

The message returns to the queue after its visibility timeout and is retried.
The consumer's `MaximumConcurrency` of two is what prevents a backlog from
consuming the whole pool and starving the API.

**S44. DynamoDB throttles a write.**

The SDK retries with adaptive backoff. If it still fails, the error surfaces
as `RATE_LIMITED`, which the API client classifies as retryable. An alarm
fires if throttles exceed the threshold.

**S45. The dispatcher and a manual action transition the same request.**

One wins. The transition is conditional on the current status, so the loser
fails its condition rather than overwriting.

**S46. A camp organizer tries to assign staff from another organization.**

Permitted, and deliberately: a camp may use staff from elsewhere. What is
checked is that the assigning user owns the camp and that the assigned user
exists. The assigned person then has camp-scoped permissions for that camp
only.

**S47. A camp's capacity is reduced below its current registrations.**

Existing registrations stand. New ones are refused with `CAMP_FULL`, because
the check is `registeredCount >= capacity` rather than an exact comparison.

**S48. A donor cancels their registration after checking in.**

The cancellation is conditional on the registration still being `REGISTERED`,
so it fails. Attendance has already been recorded and cannot be withdrawn by
the donor.

**S49. The frontend receives a 500 with no detail.**

By design. The error panel shows the correlation id, which is enough for an
operator to retrieve the full detail from logs. Returning the exception message
would risk disclosing internals.

**S50. Someone runs the seeder with `LIFELINK_ENV=prod`.**

It refuses and exits non-zero before touching anything, printing why.

<!-- pagebreak -->

# 56. What Makes This Project Different

A candid assessment, for use when an interviewer asks you to compare it to
other student work.

## 56.1 What is genuinely unusual

**The refusals are tested.** A large share of the test suite asserts what the
system declines to do. Most projects test the happy path.

**Unknown is a first-class state.** Nearly every system of this kind collapses
"no data" into zero at some layer. Keeping them distinct end to end required a
decision at the domain, service, API and presentation layers.

**Two priority fields.** The separation between a hospital's clinical
judgement and the scheduler's ordering is not a common pattern, and it exists
because aging a clinical priority would be a safety problem.

**The documentation is generated.** Code listings are extracted at build time;
metrics come from running the suites. A renamed function breaks the book build.

**Bugs are recorded rather than quietly fixed.** Five appear in these books
with their symptom, cause and fix, because the interesting part of a project
is usually what went wrong.

## 56.2 What is ordinary

The AWS services are the obvious ones, chosen for the obvious reasons. The
React application is conventional. The DynamoDB access patterns are textbook
once the questions are enumerated. None of that is a criticism — the right
answer is usually the ordinary one — but none of it is distinguishing either.

## 56.3 What is weaker than it looks

**Operational history is thin.** The stack is deployed, but the alarms have
never fired in anger, no restore has been rehearsed and nothing has been
load-tested. Most operational claims are still about what the template creates
rather than what has been observed.

**The compatibility reference is not reviewed.** The engineering around it is
careful; the data is not authoritative, and that is the gap that matters most.

**Load behaviour is unknown.** A concurrency ceiling of
{{fact:lambda_concurrency}} makes a load test measure the ceiling, so no
throughput figure exists.

**Accessibility is structural only.** Focus management, labels and
non-colour status indicators are in place. No audit with assistive technology
has been run.

## 56.4 How to present that honestly

Lead with what is unusual. Concede what is ordinary without apologising for
it. Volunteer what is weak before being asked.

The last of those is counter-intuitive and the most effective. An interviewer
who discovers a weakness you concealed discounts everything else you claimed.
An interviewer who hears it from you first tends to believe the rest.

<!-- pagebreak -->

# 57. Final Revision Sheet

## 57.1 If you remember nothing else

| Rule | Why it exists |
|---|---|
| Unknown is not zero | They lead a user to opposite actions |
| Updated is not verified | A feed proves recency, not accuracy |
| An offer is not a reservation | Nothing is held, so nothing can double-count |
| Clinical priority is not dispatch order | A scheduler must not overrule a clinician |
| Fail closed | Hiding usable stock costs a call; showing unusable stock costs a journey |

*Table 57.1. The five rules that explain most of the design.*

## 57.2 The numbers

{{fact:test_backend}} backend tests ({{fact:test_unit}} unit,
{{fact:test_integration}} integration), {{fact:test_frontend}} frontend tests,
{{fact:test_status}}. {{fact:route_count}} routes,
{{fact:openapi_operations}} documented operations.
{{fact:table_count}} tables, {{fact:gsi_count}} indexes.
{{fact:permission_count}} permissions, {{fact:role_count}} roles.
{{fact:cfn_resources}} infrastructure resources, {{fact:cfn_alarms}} alarms.
{{fact:backend_modules}} backend modules, {{fact:frontend_modules}} frontend
modules.

## 57.3 The five bugs

| Bug | Symptom | Found by |
|---|---|---|
| Geohash neighbour-only coverage | A facility 25.6 km away never appeared | Integration test with real distances |
| Unused expression placeholders | `ValidationException` naming nothing | Integration test |
| Version conflict as `DuplicateError` | Retry path never engaged | Integration test |
| `None` stripped from expression values | Any null-setting update failed | Integration test |
| Reminder index never populated | Reminders would never fire | Writing the limitations table |

*Table 57.2. Every bug worth discussing, and what found it.*

Four of five failed silently. All five were found by something other than
reading the code.

## 57.4 The sentence to end on

> The hard part was not the AWS. It was deciding, repeatedly, what the system
> should refuse to claim.
