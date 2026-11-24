<!-- pagebreak -->

# 7. Amazon Cognito and Identity

Each AWS service chapter answers the same ten questions: what it is, why
LifeLink uses it, how it works, where it sits, what configuration matters, what
secures it, what can fail, how failure is handled, what it costs, and what
simpler alternative was considered.

## 7.1 What Cognito is

A managed identity provider. It stores user accounts, handles sign-up, sign-in,
password recovery and multi-factor authentication, and issues signed JSON Web
Tokens that other services can verify without calling back to it.

## 7.2 Why LifeLink uses it

Because writing authentication is a way to introduce vulnerabilities, not a way
to demonstrate skill. Password hashing, reset-token expiry, enumeration
resistance, MFA enrolment and token rotation are all solved problems with
well-understood failure modes, and all of them are easy to get subtly wrong.

The specification also asks for OAuth 2.0 and OIDC flows including
Authorization Code with PKCE. Cognito provides those directly.

## 7.3 How it works here

```diagram
type: sequence
title: Authorization Code with PKCE
actor browser Browser
actor cognito Cognito managed login
actor api LifeLink API
actor db Organizations table
msg browser -> cognito redirect with code challenge
msg cognito -> browser authorization code
msg browser -> cognito exchange code and verifier
msg cognito -> browser access and id tokens
msg browser -> api request with bearer token
msg api -> cognito fetch JWKS once and cache
msg api -> db load roles and account status
msg db -> api authoritative principal
note The browser never holds a client secret, which is why PKCE exists.
```

*Figure 7.1. The sign-in flow. The code-plus-verifier exchange means an
intercepted authorization code is useless without the verifier.*

The step that matters most for LifeLink's security model is the last one. The
token proves *who* the caller is. It does **not** decide *what they may do*:

{{include:backend/src/appcore/auth.py:class Authenticator}}

*Listing 7.1. The authenticator, from `backend/src/appcore/auth.py`. Note the
final step: the principal is loaded from the database, not constructed from
token claims.*

## 7.4 Where it sits

Cognito is consulted at two moments: interactively, when a user signs in; and
programmatically, when the API fetches the JSON Web Key Set to verify a
signature. The JWKS is cached, so steady-state request handling makes no call
to Cognito at all.

## 7.5 Configuration that matters

| Setting | Value | Why |
|---|---|---|
| `GenerateSecret` | `false` | A browser cannot keep a secret; PKCE replaces it |
| `AllowedOAuthFlows` | `code` | Implicit flow puts tokens in the URL |
| Password minimum | 12 characters, mixed classes | Longer beats complex, so both |
| `AccessTokenValidity` | 1 hour | Short enough to limit a leaked token |
| `RefreshTokenValidity` | 30 days | Balances convenience against revocation lag |
| `PreventUserExistenceErrors` | `ENABLED` | Stops account enumeration via error text |
| `EnableTokenRevocation` | `true` | Allows immediate sign-out everywhere |
| MFA | `OPTIONAL`, TOTP | Required by policy for privileged roles |
| `AttributesRequireVerificationBeforeUpdate` | `[email]` | Stops silent account takeover by email change |

*Table 7.1. Cognito configuration and the reasoning behind each value.*

## 7.6 What secures it

Tokens are RS256-signed; LifeLink verifies the signature against the pool's
JWKS, checks the issuer, the expiry and the `token_use` claim, and rejects
anything that fails. The `kid` header selects the key, and an unknown `kid`
triggers exactly one JWKS refresh rather than a fetch per request.

## 7.7 What can fail

| Failure | Effect | Handling |
|---|---|---|
| Cognito unavailable | New sign-ins fail | Existing valid tokens continue to work until expiry |
| JWKS fetch fails | Token verification fails | Cached keys are used; failure returns 401, logged |
| Token expired | Request rejected | 401 with `UNAUTHENTICATED`; client refreshes |
| Token valid, account suspended | Request rejected | 403 `ACCOUNT_SUSPENDED` — the database decides |
| Role changed mid-session | Next request uses the new role | Roles read per request, not from the token |

*Table 7.2. Cognito failure modes.*

The third and fourth rows are the interesting pair. A system that trusts token
claims cannot distinguish them: both present a valid, unexpired, correctly
signed token. LifeLink can, because it treats the token as proof of identity
only.

## 7.8 Cost

Cognito's free tier covers 50,000 monthly active users for user pools. For a
demonstration system the cost is effectively zero. Advanced security features
are chargeable and are not enabled.

## 7.9 The alternative considered

**Hand-rolled authentication with JWTs signed by the application.** Rejected.
It would require implementing password storage, reset flows, MFA and revocation,
each a well-known source of vulnerabilities, in exchange for no capability
LifeLink needs.

**An API Gateway JWT authorizer alone.** Partially adopted — it is a sensible
outer layer — but rejected as the only mechanism, because it cannot check
account status or resource ownership. It would happily admit a suspended user.

<!-- pagebreak -->

# 8. Amazon API Gateway

## 8.1 What it is

A managed front door for APIs: TLS termination, routing, throttling, access
logging and integration with Lambda, without running a load balancer or web
server.

## 8.2 Why LifeLink uses it, and which variant

API Gateway offers REST APIs and HTTP APIs. LifeLink uses the **HTTP API**.

| Consideration | REST API | HTTP API | LifeLink needs it? |
|---|---|---|---|
| Cost per million requests | Higher | ~70% lower | Yes, cost matters |
| Latency overhead | Higher | Lower | Yes |
| Request validators | Yes | No | No — validation is in the handler |
| Usage plans and API keys | Yes | No | No — no third-party API consumers |
| AWS WAF integration | Yes | No | Not at this tier |
| Private endpoints | Yes | No | No |

*Table 8.1. Why the HTTP API variant was chosen.*

Nothing LifeLink does needs a REST-only feature. Choosing the more expensive
variant anyway would be paying for capability that no part of the design uses.

## 8.3 How it works here

One proxy route sends everything to a single Lambda function, which does its own
routing. That is a deliberate choice over defining 50 separate API Gateway
routes and 50 functions.

| Approach | Cold starts | IAM granularity | Template size | Chosen |
|---|---|---|---|---|
| One function per route | ~50 cold-start surfaces | Per-route policies | Very large | No |
| One proxy function | One warm container serves all | One policy set | Compact | **Yes** |

*Table 8.2. Routing granularity.*

At a concurrency ceiling of {{fact:lambda_concurrency}}, fifty separate
functions would be actively harmful: each has its own cold-start cost and its
own share of a pool that cannot stretch. One function keeps containers warm
across the whole API surface.

The trade-off is coarser IAM. The single API function holds the union of
permissions its routes need. That is mitigated by authorization being enforced
in the application on every request, and by the audit table's write-only grant.

## 8.4 Configuration that matters

{{include:infrastructure/template.yaml:anchor:DefaultRouteSettings:5}}

*Listing 8.1. Throttling, set below the Lambda ceiling on purpose.*

The throttle is set to 10 requests per second with a burst of 20 — at or below
the account's concurrency ceiling. API Gateway therefore sheds load with a clean
429 before Lambda starts throttling, which produces a better client experience
and a clearer signal in metrics.

Access logging deliberately excludes request bodies and query strings, both of
which can carry personal data.

## 8.5 What can fail, and how it is handled

| Failure | Status | Handling |
|---|---|---|
| Throttle exceeded | 429 | Client backs off; `isRetryable` is true in the API client |
| Lambda timeout | 504 | Handler timeout is 29s, inside the gateway's limit |
| Handler raises | 500 | Error is logged with correlation id; no internals leak |
| Unknown path | 404 | Distinguished from 405 for a known path, wrong method |

*Table 8.3. API Gateway failure handling.*

## 8.6 Cost and alternatives

HTTP API costs roughly $1.00 per million requests in this region. A demo
workload sits inside the free tier.

**Application Load Balancer with Lambda targets** was considered. It costs a
fixed hourly charge whether or not traffic arrives, which is the wrong shape for
bursty, low-volume usage. **Lambda function URLs** were considered and rejected:
no throttling, no access logging, and no central place to apply CORS.

<!-- pagebreak -->

# 9. AWS Lambda

## 9.1 What it is

Managed compute that runs a function in response to an event, with no server to
provision, and billing by millisecond of execution.

## 9.2 Why LifeLink uses it

The workload is bursty and mostly idle. A demonstration system that nobody is
using should cost nothing, and a facility search arriving at 3am should still be
served. That is precisely the shape Lambda suits.

## 9.3 The functions

| Function | Trigger | Purpose | Timeout |
|---|---|---|---|
| `api` | API Gateway | All {{fact:route_count}} routes | 29s |
| `notification-worker` | SQS | Deliver queued notifications | 29s |
| `work-worker` | SQS | Alert matching on stock change | 29s |
| `outbox-publisher` | DynamoDB stream | Publish outbox rows to SQS | 29s |
| `dispatcher` | EventBridge, 1 minute | Priority scheduling for emergencies | 29s |
| `maintenance` | EventBridge, 10 minutes | Expiry sweep, reminders | 300s |

*Table 9.1. The six Lambda functions.*

## 9.4 Runtime and architecture

Runtime `{{fact:lambda_runtime}}` on `arm64`. Two reasons for each.

The runtime matches the local interpreter exactly ({{fact:python_version}}),
which removes an entire category of "works on my machine" failure: a dependency
that imports locally imports in Lambda. Python 3.14 is generally available with
support to June 2029; Python 3.15 exists but is in public preview and is
explicitly outside the Lambda SLA, so it is not used.

Graviton (`arm64`) is roughly 20% cheaper per millisecond at equivalent
performance for this kind of workload, and every dependency LifeLink uses
publishes `aarch64` wheels.

## 9.5 The concurrency ceiling, and designing within it

:::warning This is the single most consequential constraint in the project
The account permits {{fact:lambda_concurrency}} concurrent executions in total,
across every function. The AWS default is
{{fact:lambda_concurrency_default}}.
:::

Four design decisions follow directly:

**No function reserves concurrency.** Reserved concurrency is subtracted from
the shared pool. Reserving two for the dispatcher would leave eight for
everything else, including the synchronous API tier that a user is waiting on.

**Queue consumers cap their own parallelism.** Each SQS event source sets
`MaximumConcurrency: 2` and a batch size of 5. Without that, a backlog of
messages would consume the entire pool and the API would start returning 429s
while a background job drained.

**The dispatcher is one scheduled invocation, not a pool of consumers.** This
reinforces the conclusion Chapter 18 reaches on other grounds.

**Throttling is an expected condition, not an exception.** The DynamoDB client
uses adaptive retries, SQS consumers report partial batch failures so only the
failed messages return, and a CloudWatch alarm fires on the first throttle.

{{include:backend/src/repositories/dynamo.py:anchor:def _resource:16}}

*Listing 9.1. Adaptive retries configured in `backend/src/repositories/dynamo.py`,
with the reasoning recorded where a future reader will see it.*

## 9.6 Cold starts

A Python Lambda with boto3 and a handful of pure-Python dependencies typically
cold-starts in a few hundred milliseconds. LifeLink reduces the frequency and
cost of that:

- One function serves the whole API, so warm containers are reused widely.
- The service object graph is built once per container and cached with
  `functools.lru_cache`, not rebuilt per invocation.
- MapLibre and other heavy frontend assets are, of course, not in the Lambda
  package at all.
- SnapStart is not used: it is not available for Python runtimes.

## 9.7 What can fail

| Failure | Handling |
|---|---|
| Throttled | 429 to client; alarm fires; consumers retry with backoff |
| Timeout | 504; the 29s limit sits inside API Gateway's |
| Unhandled exception | Generic 500 to the client, full detail to logs |
| Crash mid-transaction | DynamoDB transaction either committed or did not |
| Crash after commit, before publish | Impossible: the outbox row is in the transaction |

*Table 9.2. Lambda failure modes.*

The last two rows are the payoff from the transactional outbox, and Chapter 22
explains the mechanism.

## 9.8 Cost

The free tier covers 1 million requests and 400,000 GB-seconds monthly. At 512 MB
and an assumed 200 ms average duration, that is roughly 4 million invocations of
headroom. A demonstration workload costs nothing.

## 9.9 Alternatives considered

**Fargate or ECS.** Rejected: a container running continuously costs money while
idle, and there is no long-running process to host.

**EC2.** Rejected for the same reason, with added patching and capacity
management.

**Lambda@Edge.** Unavailable on this account, and not needed — there is no
request-time logic that must run at the edge.
