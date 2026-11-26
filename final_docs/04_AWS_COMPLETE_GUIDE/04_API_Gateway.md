# API Gateway

The front door to the backend. **An HTTP API, not a REST API** — and that
distinction matters.

---

## 1. What API Gateway is

**Simple version.** A managed front door for your API: it receives HTTP
requests from the internet and forwards them to something that handles them —
in our case, a Lambda function.

**The analogy.** A receptionist for your backend. It accepts callers, applies
rules about who may come in and how often, and routes them to the right place.

**Mechanism.** You define **routes** (method plus path) and an **integration**
for each. API Gateway terminates TLS, applies CORS and throttling, converts the
HTTP request into a JSON event, and invokes the integration.

**Why LifeLink uses it.** A Lambda function is not reachable from the internet
on its own. Something must give it a public HTTPS endpoint, handle CORS,
and throttle abuse. The alternative — a Lambda Function URL — has no
throttling, no access logging and no usage plans.

---

## 2. HTTP API versus REST API — get this right

**LifeLink uses an HTTP API: `AWS::ApiGatewayV2::Api`, id `uk6itz2a5b`.**

These are two different AWS products behind one Console, with different pages
and different features.

| | **HTTP API** (ours) | REST API |
|---|---|---|
| CloudFormation type | `AWS::ApiGatewayV2::Api` | `AWS::ApiGateway::RestApi` |
| Cost | **~70% cheaper** | higher |
| Latency | lower | higher |
| Built-in JWT authorizer | yes | no (Cognito authorizer or Lambda) |
| Request validation | **no** | yes |
| Request/response transformation | **no** | yes (mapping templates) |
| Usage plans + API keys | **no** | yes |
| WAF integration | **no** | yes |
| Caching | **no** | yes |
| Private endpoints | no | yes |
| Payload format | **2.0** | 1.0 |

### Why HTTP API was the right choice here

> "We use an HTTP API rather than a REST API. It's about seventy percent
> cheaper and has lower latency, and we don't need the features REST API adds.
> Request validation happens in our handlers because our validation is
> business-level, not just schema-level. We don't transform requests — we use a
> straight proxy integration. We have no API keys because our clients
> authenticate with Cognito tokens. And we don't need response caching, because
> almost every response is user-specific.
>
> The one thing I'd miss at larger scale is WAF integration, which HTTP APIs
> don't support directly. You'd put CloudFront in front of the API to get it."

**That last point is a genuinely good detail** — it shows you know the
limitation and the workaround.

---

## 3. The deployed configuration

| Setting | Value |
|---|---|
| API id | `uk6itz2a5b` |
| Protocol | HTTP |
| Endpoint | `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com` |
| Route selection | `$request.method $request.path` |
| Created | 2026-11-15 15:13 UTC |
| `DisableExecuteApiEndpoint` | false |
| Stage | `dev`, `AutoDeploy: true` |
| Full base URL | `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev` |

### Routes — only two

| Route | Authorization | Target |
|---|---|---|
| `ANY /{proxy+}` | **NONE** | `lifelink-dev-api` |
| `ANY /` | **NONE** | `lifelink-dev-api` |

**Two routes serve all 58 application endpoints.** `{proxy+}` is a greedy path
variable matching everything, and `ANY` matches every HTTP method. Routing
happens inside the Lambda, in `backend/src/handlers/router.py`.

**Why a proxy route instead of 58 declared routes?** Because then the route
table exists in **two** places — the gateway and the code — and they can drift.
With a proxy route there is one route table, in code, and the same table drives
the local development server. The cost is that the gateway cannot reject an
unknown path for free; a 404 costs a Lambda invocation.

### Authorizers — none

```
Authorizers: []
```

**Expect to be asked why.** Full reasoning in
[../02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md](../02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md)
§Layer 4. Summary:

A JWT authorizer validates the token signature. Our authorization needs **five**
things: the signature, the user's role from DynamoDB, their account status,
the permission, and an organization scoping check. An authorizer solves the
first; the Lambda would still do the other four. Splitting it would mean
authorization logic in two places and no single reviewable location.

**The honest cost:** an unauthenticated request still invokes a Lambda and
costs money. The stage throttle is what bounds that exposure.

**Say this:**
> "There's deliberately no authorizer on the gateway. A JWT authorizer would
> check the signature, but our authorization also needs the user's role, which
> lives in DynamoDB and has to be revocable immediately, plus their account
> status and an organization scoping check. So we'd still need the Lambda to do
> four of the five checks, and the logic would be split across two places.
> Keeping all five in one decorator means one reviewable place and a test that
> enumerates every route to prove none is unprotected. The trade-off is that an
> invalid request still costs us a Lambda invocation, which is why the stage
> throttles at ten requests a second."

---

## 4. Throttling — derived, not guessed

| Setting | Value |
|---|---|
| `ThrottlingRateLimit` | **10 requests/second** |
| `ThrottlingBurstLimit` | **20** |
| Per-route overrides | none |
| `DetailedMetricsEnabled` | **true** |

**Why exactly 10?** Because the account's **Lambda concurrent execution limit
is 10**. Throttling at the gateway rejects excess load with a cheap **429**
instead of exhausting the Lambda pool and breaking requests already in flight.

**Rate versus burst:** the rate is the sustained limit; the burst is a token
bucket allowing a short spike. 20 burst lets a page that fires several parallel
requests on load succeed, while 10/s caps sustained traffic.

**This is the best "we understood our constraints" answer in the project**,
because the number is derived from a measured limit rather than chosen.

---

## 5. CORS

```json
{"AllowOrigins": ["https://d324z37do52g8f.cloudfront.net",
                  "http://localhost:5173", "http://127.0.0.1:5173"],
 "AllowMethods": ["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
 "AllowHeaders": ["content-type","authorization","idempotency-key","x-correlation-id"],
 "ExposeHeaders": ["x-correlation-id"], "MaxAge": 600}
```

| Field | Why |
|---|---|
| 3 exact origins, not `*` | `*` cannot be combined with credentials, and exact origins stop a random site making authenticated calls from a signed-in user's browser |
| both `localhost` and `127.0.0.1` | a browser treats them as **different origins** |
| 4 allowed headers | the four the client actually sends |
| `ExposeHeaders: x-correlation-id` | without this, JavaScript **cannot read** a custom response header |
| `MaxAge: 600` | caches the preflight for 10 minutes, so not every call is preceded by an `OPTIONS` |

**The `ExposeHeaders` detail is a good one** — by default CORS hides all but a
handful of response headers from JavaScript, even when the response arrives
successfully.

**The deployment hazard:** `CorsAllowOrigins` is a stack parameter. Omit it on
a deployment and the template default takes over, dropping the CloudFront
origin — the live site then fails every API call with a CORS error while the
API itself is perfectly healthy.

---

## 6. The integration

| Setting | Value |
|---|---|
| Type | **`AWS_PROXY`** |
| Target | `lifelink-dev-api` |
| Payload format | **2.0** |
| Timeout | **30000 ms** |

**`AWS_PROXY`** means the whole request is passed through as a JSON event and
whatever the function returns becomes the HTTP response. No mapping templates,
no transformation.

**Payload format 2.0** is the HTTP API shape. It differs from 1.0 in ways that
bite:

| | 1.0 | 2.0 |
|---|---|---|
| Path | `event["path"]` | **`event["rawPath"]`** |
| Method | `event["httpMethod"]` | **`event["requestContext"]["http"]["method"]`** |
| Query string | `queryStringParameters` | `rawQueryString` + `queryStringParameters` |
| Cookies | in headers | **`event["cookies"]`** |

`backend/src/handlers/router.py` reads **both** shapes:

```python
method = (
    event.get("httpMethod")
    or (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")
)
```

That is what lets the same router serve both the deployed HTTP API and the
local development server.

### Why 30 s integration timeout but a 29 s function timeout

So the **function fails first**. If the Lambda could run to or past 30 s, the
gateway would give up and return a bare **504** with no correlation id and no
application error code. At 29 s the function returns *our* error envelope with
a traceable id.

**30 seconds is also a hard ceiling** on HTTP APIs — you cannot raise it. Any
operation that might take longer must be made asynchronous, which is part of
why deferrable work goes to SQS.

---

## 7. The stage, and the prefix bug it caused

| Setting | Value |
|---|---|
| Stage name | `dev` |
| `AutoDeploy` | **true** |

A **stage** is a deployed snapshot of the API with its own URL and settings.
Ours serves at `/dev/...`, which is why `VITE_API_BASE` ends in `/dev`.

> **A real bug worth telling.** Every route worked locally and **404'd in
> AWS**. API Gateway reports `rawPath` as `/dev/health`, while the route table
> is written as `/health`. The fix is `strip_stage_prefix` in
> `backend/src/handlers/router.py`, which removes a leading segment that
> **exactly equals** `requestContext.stage`.
>
> Two details that make the fix good rather than merely working: the stage is
> read **from the event**, not from a constant, so renaming the stage cannot
> silently reintroduce the bug; and only an exact segment match is stripped, so
> a route like `/dev-tools` is left alone. `$default` is ignored because that
> stage adds no prefix. `backend/tests/unit/test_stage_prefix.py` covers the
> edge cases.

**`AutoDeploy: true`** means changes take effect without an explicit deployment
step — convenient, and the reason there is no "deploy API" action to forget.

---

## 8. Access logging

| Setting | Value |
|---|---|
| Destination | `/aws/apigateway/lifelink-dev` |
| Retention | 30 days |
| Format | JSON |

```json
{"requestId":"$context.requestId","ip":"$context.identity.sourceIp",
 "requestTime":"$context.requestTime","method":"$context.httpMethod",
 "routeKey":"$context.routeKey","status":"$context.status",
 "latency":"$context.responseLatency","integrationError":"$context.integrationErrorMessage"}
```

**Why JSON rather than the default text format?** Because CloudWatch Logs
Insights parses JSON fields automatically:

```
fields @timestamp, status, latency, routeKey
| filter status >= 400
| sort @timestamp desc
| limit 20
```

With the default text format you would be writing regular expressions.

**`integrationError` is the field that earns its place** — when the Lambda
fails to be invoked at all (a permission problem, a throttle), the reason
appears here and nowhere else.

---

## 9. Failure scenarios

| Failure | Response | Where to look |
|---|---|---|
| Throttled | **429** | alarm `lifelink-dev-lambda-throttles`; access log `status` |
| Lambda errors | 500 with our envelope | `/aws/lambda/lifelink-dev-api` by correlation id |
| Lambda unreachable | **502** | access log `integrationError` |
| Over 30 s | **504** | shouldn't happen — function times out at 29 s |
| Path not in the route table | 404 from **our code** | still costs an invocation |
| Path exists, wrong method | **405** from our code | the router tracks this deliberately |
| CORS origin not allowed | browser blocks it; the request may still have run | the request reaches Lambda; only the *response* is withheld from JavaScript |

**That last row is worth knowing:** a CORS failure is enforced by the
**browser**, not the server. The request may have executed and had an effect.
That is why `AllowOrigins` is a security boundary for *reading responses*, not
for preventing requests.

---

## 10. Console demonstration

```
API Gateway -> APIs -> the HTTP API (uk6itz2a5b)
  Routes           -> ANY /{proxy+}  and  ANY /
  Authorization    -> empty    <- "all authentication is in the Lambda"
  Integrations     -> AWS_PROXY to lifelink-dev-api, payload 2.0
  CORS             -> three origins, four headers
  Stages -> dev    -> throttle 10/20, detailed metrics, access logging
  Metrics          -> request count, latency, 4xx and 5xx
```

**The best moment:** open the **Monitor/Metrics** view, then make a request to
the live site in another window, and watch the count rise. Then open
CloudWatch Logs on `/aws/apigateway/lifelink-dev` and show the JSON line for
that exact request, including its latency.

Combine it with the browser: copy the `correlationId` from the response in the
Network tab, then find it in `/aws/lambda/lifelink-dev-api`. Click to log line
in about thirty seconds.

---

## 11. Spoken answers

### 20–30 seconds
> "We use an API Gateway HTTP API — not a REST API; it's about seventy percent
> cheaper and we don't need the extra features. It has only two routes, a root
> and a greedy proxy, and both forward every request to one Lambda function,
> which does the real routing. There's no authorizer on the gateway: all
> authentication happens inside the Lambda. The stage throttles at ten requests
> a second, which is derived from our Lambda concurrency limit of ten."

### 1–2 minutes
> "API Gateway gives our Lambda a public HTTPS endpoint, handles CORS and
> throttles abuse. We chose an HTTP API over a REST API on cost and latency; the
> features we gave up — request validation, mapping templates, API keys,
> response caching — we don't use, because validation is business-level in our
> handlers and our clients authenticate with Cognito tokens.
>
> There are only two routes, a greedy `{proxy+}` and a root, and both proxy to
> one Lambda. That's deliberate: declaring all 58 routes at the gateway would
> mean the route table exists in two places and could drift. With a proxy route
> there's one table, in code, and the same table drives our local server.
>
> The number worth explaining is the throttle: ten requests a second with a
> burst of twenty. That comes from our account's Lambda concurrency limit, which
> is ten rather than the usual thousand. Shedding excess load with a cheap 429
> at the gateway is better than exhausting the Lambda pool and failing requests
> that are already running. And the function timeout is twenty-nine seconds
> against the gateway's thirty, so the function fails first and the error is ours
> with a correlation id rather than a bare gateway 504."

---

## 12. Follow-up questions

**"Why not a Lambda Function URL? That removes a service."**
> It would, and it would be cheaper still. But a Function URL has no
> throttling, no access logging and no usage plans. Throttling is the thing we
> most need, because of the concurrency limit, so removing the gateway would
> remove our main load-shedding mechanism.

**"How would you add WAF?"**
> HTTP APIs don't support WAF directly — that's a REST API feature. The usual
> approach is to put CloudFront in front of the API and attach the web ACL
> there, or switch to a REST API. For us, the stage throttle is the practical
> defence, and I'd add WAF via CloudFront if this were handling real data.

**"What's in `$context` for the access log?"**
> Request id, source IP, time, method, route key, status, integration latency
> and any integration error message. The integration error is the useful one
> — if the gateway can't invoke the Lambda at all, because of a permission
> problem or a throttle, that's where the reason appears.

**"Does the gateway validate the JSON body?"**
> No — HTTP APIs don't support request validation. Our handlers parse and
> validate, which we'd want anyway: our rules are things like "units must be
> positive and not exceed what's unreserved", which a JSON schema can't express.
> A malformed body returns 400 `VALIDATION_ERROR` from our code.

---

## 13. Cross-references

- [05_AWS_Lambda.md](05_AWS_Lambda.md)
- [../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md](../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md)
- [../03_REPOSITORY_AND_CODE/04_API_And_Handler_Mapping.md](../03_REPOSITORY_AND_CODE/04_API_And_Handler_Mapping.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/07_Showing_API_Gateway_And_Requests.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/07_Showing_API_Gateway_And_Requests.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §E
