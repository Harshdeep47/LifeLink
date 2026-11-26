# Showing API Gateway and Requests

Connecting a click in the browser to an AWS service, using DevTools and the
Console together.

---

## 1. The demonstration that lands

**Open DevTools on the live site. Network tab. Filter: Fetch/XHR.**

Then click **Find blood**.

| Tab | What to point at | Say |
|---|---|---|
| **Headers** | the full URL `/dev/facilities?lat=...` | "that's our HTTP API, and note the `/dev` — the stage name is part of the path" |
| | **`Authorization: Bearer ...`** (if signed in) | "the Cognito access token. I'm **not** going to copy that value — it's a live credential for an hour" |
| | `X-Correlation-Id: web-...` | "our client generates this" |
| **Payload / Query** | `lat`, `lon`, `radiusKm`, `bloodGroup`, `component` | |
| **Response** | `{"data":[...],"meta":{...},"correlationId":"corr-..."}` | "every response has the same envelope" |
| **Timing** | time to first byte | "most of that is the round trip to Sydney" |

**Then do the thing that ties it together:** copy the `correlationId` from the
response and find it in CloudWatch — §4.

---

## 2. The API Gateway walkthrough

```
API Gateway -> APIs -> the HTTP API (uk6itz2a5b)
```

| Where | Show | Say |
|---|---|---|
| **Routes** | **only two**: `ANY /{proxy+}` and `ANY /` | see §3 |
| **Authorization** | **EMPTY** | see §3 |
| **Integrations** | `AWS_PROXY` -> `lifelink-dev-api`, payload **2.0**, timeout 30000 ms | |
| **CORS** | 3 exact origins, 4 headers, `ExposeHeaders: x-correlation-id` | see §5 |
| **Stages -> dev** | **throttle 10 req/s, burst 20**; detailed metrics; access logging | see §6 |
| **Metrics** | request count, latency, 4xx, 5xx | make a request and watch it move |

**First, get the product right:**
> "This is an **HTTP API**, not a REST API — different AWS product, different
> Console page, about seventy percent cheaper. We don't need what REST API adds:
> request validation happens in our handlers because our rules are
> business-level, we use a straight proxy so there's nothing to transform, and
> our clients authenticate with Cognito tokens rather than API keys."

---

## 3. Two routes and no authorizer

**Routes:**

| Route | Authorization |
|---|---|
| `ANY /{proxy+}` | **NONE** |
| `ANY /` | **NONE** |

**Say this:**
> "Two routes serve all fifty-eight application endpoints. `{proxy+}` is a
> greedy path variable and `ANY` matches every method, so everything goes to one
> Lambda, which does the real routing.
>
> That's deliberate. If we declared all fifty-eight routes here, the route table
> would exist in two places — the gateway and the code — and they could drift.
> With a proxy route there's one table, in code, and the same table drives our
> local development server. The cost is that the gateway can't reject an unknown
> path for free; a 404 costs a Lambda invocation."

**On the empty Authorization page:**
> "And there's no authorizer, which surprises people. An HTTP API does have a
> built-in JWT authorizer and it would check the signature. But our
> authorization also needs the user's role from DynamoDB, their account status
> and an organization scoping check — so we'd still need the Lambda to do four
> of the five checks, and the logic would be split across two places.
>
> We keep all five in one decorator, with a test that enumerates every route to
> prove none is unprotected. The honest cost is that an invalid request still
> costs us a Lambda invocation — which is exactly why the stage throttles."

---

## 4. The correlation id demonstration — rehearse this

**Thirty seconds, and it demonstrates end-to-end understanding better than any
explanation.**

```
1. DevTools -> Network -> click the request -> Response
   -> copy the correlationId, e.g. corr-c77986b2-9ded-4963-8ff1-bf271402fe2a

2. CloudWatch -> Logs Insights
   -> select /aws/lambda/lifelink-dev-api
   -> run:

      fields @timestamp, @message
      | filter @message like /corr-c77986b2/
      | sort @timestamp asc
```

**Say this:**
> "That's the same request from both ends. Every API response carries a
> correlation id, and the same id is in the Lambda's CloudWatch logs. So if a
> user reports a failure, I take the id from the response they saw and find the
> exact server-side log entry in about thirty seconds. That's the thing I'd
> actually use when debugging, and it's why the envelope exists."

---

## 5. CORS

```
API Gateway -> the HTTP API -> CORS
```

| Field | Value |
|---|---|
| Allow origins | the CloudFront domain + `http://localhost:5173` + `http://127.0.0.1:5173` |
| Allow methods | GET, POST, PUT, PATCH, DELETE, OPTIONS |
| Allow headers | `content-type`, `authorization`, `idempotency-key`, `x-correlation-id` |
| **Expose headers** | **`x-correlation-id`** |
| Max age | 600 |

**Say this:**
> "Our site is on a CloudFront domain and our API is on an execute-api domain —
> different origins, so CORS applies to every call. We list three exact origins
> rather than a wildcard, because `*` can't be combined with credentials, and
> exact origins mean a random website can't make authenticated calls from a
> signed-in user's browser.
>
> Two details worth knowing. `localhost` and `127.0.0.1` are **different
> origins** to a browser, so both are listed. And `ExposeHeaders` matters: by
> default CORS hides almost all response headers from JavaScript even when the
> response arrives fine, so without that line our client couldn't read the
> correlation id header."

**And the trap:**
> "A CORS error in DevTools almost never means CORS is broken. It usually means
> the request failed for another reason and the error response didn't carry the
> CORS headers. Check the status code first."

---

## 6. The stage — throttling and logging

```
API Gateway -> the HTTP API -> Stages -> dev
```

| Setting | Value |
|---|---|
| **Throttle** | **10 req/s, burst 20** |
| Detailed metrics | enabled |
| Access logging | JSON -> `/aws/apigateway/lifelink-dev` |
| Auto deploy | true |

**Say this:**
> "Ten requests a second with a burst of twenty, and that number isn't picked —
> it's derived. Our account's Lambda concurrency limit is ten rather than the
> usual thousand, so throttling here means excess traffic gets a cheap 429
> instead of exhausting the Lambda pool and breaking requests that are already
> running. Shedding load at the edge is better than failing in the middle."

### The access log — and why JSON

```
CloudWatch -> Logs Insights -> /aws/apigateway/lifelink-dev

fields @timestamp, status, latency, routeKey, ip
| filter status >= 400
| sort @timestamp desc
| limit 20
```

> "We log in JSON rather than the default text format, specifically so Logs
> Insights can query the fields by name. With text you'd be writing regular
> expressions. The field that earns its place is `integrationError` — if the
> gateway can't invoke the Lambda at all, because of a permission problem or a
> throttle, that's where the reason appears and nowhere else."

---

## 7. The stage prefix bug — a story worth telling

**Say this while looking at the stage:**
> "The stage name caused a real bug. API Gateway reports the path as
> `/dev/health`, but our route table is written as `/health` — so on the very
> first deployment **every route 404'd**, while working perfectly locally.
>
> The fix is a function called `strip_stage_prefix` that removes a leading
> segment matching the stage. Two details make it a good fix rather than merely
> a working one: it reads the stage **from the event** rather than a hard-coded
> constant, so renaming the stage can't silently reintroduce the bug; and it
> only strips an **exact** segment match, so a route like `/dev-tools` is left
> alone. There's a test file just for its edge cases."

---

## 8. Live request demonstrations

```bash
API=https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev

# Public — no token needed
curl -s $API/health
# {"data":{"status":"ok","environment":"dev","region":"ap-southeast-2",
#  "time":"...","demoEnvironment":true},"correlationId":"corr-..."}

# Protected — 401
curl -s -o /dev/null -w "%{http_code}\n" $API/me
# 401

# Garbage token — 401
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer x.y.z" $API/me
# 401

# Anonymous facility search — 200
curl -s -o /dev/null -w "%{http_code}\n" "$API/facilities?lat=30.34&lon=76.40&radiusKm=20"
# 200
```

All **verified on 24 November 2026**.

**`"demoEnvironment": true` is worth pointing at:** the API itself says it is a
demonstration environment.

---

## 9. The HTTP status codes to be able to explain

| Code | Means | In LifeLink |
|---|---|---|
| **200** | OK | |
| **201** | Created | a new reservation |
| **204** | No content | |
| **301** | Moved permanently | **CloudFront's HTTP -> HTTPS redirect** |
| **400** | Bad request | `VALIDATION_ERROR` |
| **401** | **Unauthenticated** | **we don't know who you are** |
| **403** | **Forbidden** | **we know exactly who you are, and no** |
| **404** | Not found | |
| **405** | Method not allowed | path exists, wrong method — our router tracks this deliberately |
| **409** | Conflict | `CONCURRENT_MODIFICATION`, `NO_UNRESERVED_STOCK` |
| **429** | Too many requests | the stage throttle |
| **500** | Server error | |
| **502** | Bad gateway | the gateway couldn't invoke the Lambda |
| **504** | Gateway timeout | shouldn't happen — our function times out at 29 s first |

**The 401 vs 403 distinction is the one to have ready.** It comes up constantly
and most people blur it.

---

## 10. DevTools — the three tabs

### Console
JavaScript errors and warnings. **Should be clean on the live site.** If there
is a MapLibre warning, know what it is before showing it.

### Network
Covered above. Also useful: **throttle to Slow 3G** to show loading states
working, and look at the **Size** column to show the content-hashed bundle
being cached.

### Elements
**The critical distinction:**

> "I can edit this heading right here in the Elements panel — and it changes
> nothing. It's only the page in my browser's memory. Refresh and it's gone, and
> nobody else ever saw it. A real change means editing the file in
> `frontend/src`, rebuilding with Vite, uploading to S3, and invalidating the
> CloudFront cache."

See
[../03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md](../03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md).

---

## 11. Do not

| Action | Why |
|---|---|
| **Copy a token value** into anything | it is a live credential for an hour |
| Edit the CORS configuration | would break the live site instantly |
| Change the throttle | derived from the concurrency limit |
| Delete a route | |
| Create a new stage | |

---

## 12. Questions and answers

**"Why is the stage in the URL?"**
> Because the API is deployed to a named stage, `dev`, so it serves at `/dev/...`
> — and our frontend's `VITE_API_BASE` includes it. If it didn't, every route
> would 404. The backend strips it again before matching routes, which is itself
> a bug we had to fix after the first deployment.

**"What happens if someone sends 100 requests a second?"**
> The stage throttles at ten per second with a burst of twenty, so the excess
> gets 429 Too Many Requests. That's cheap — the gateway rejects it without
> invoking a Lambda. There's also an alarm on Lambda throttles. What we don't
> have is a WAF, so there are no per-IP rate rules; a distributed flood would hit
> the throttle and legitimate users would get 429s too.

**"Does the gateway validate the request body?"**
> No — HTTP APIs don't support request validation; that's a REST API feature.
> Our handlers parse and validate, which we'd want anyway: our rules are things
> like "units must be positive and not exceed what's unreserved", which a JSON
> schema can't express. A malformed body returns 400 `VALIDATION_ERROR` from our
> code.

**"How do you know the API is actually deployed and not mocked?"**
> Three ways. The `/health` response reports the region as ap-southeast-2 and a
> fresh server timestamp. The Lambda's invocation count rises when I use the
> site. And the correlation id in the response appears in CloudWatch Logs —
> which I can show you.

---

## 13. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §E
- [../04_AWS_COMPLETE_GUIDE/04_API_Gateway.md](../04_AWS_COMPLETE_GUIDE/04_API_Gateway.md)
- [../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md](../02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md)
- [08_Showing_CloudWatch_Logs.md](08_Showing_CloudWatch_Logs.md)
