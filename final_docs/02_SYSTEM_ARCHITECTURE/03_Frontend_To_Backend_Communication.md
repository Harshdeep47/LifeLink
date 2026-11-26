# Frontend to Backend Communication

How the browser and the server actually talk: the HTTP contract, headers,
errors, CORS, and the things that go wrong.

---

## 1. The contract

Every successful response:

```json
{ "data": <anything>, "meta": <optional>, "correlationId": "corr-..." }
```

Every failed response:

```json
{ "error": { "code": "STABLE_CODE", "message": "human text", "details": {} },
  "correlationId": "corr-..." }
```

**Why an envelope instead of returning the object directly?** Three reasons:

1. **`correlationId` on every response** means any user-visible failure can be
   traced to a server log line.
2. **A stable `code`** lets the UI branch on behaviour without string-matching
   English messages. `NO_UNRESERVED_STOCK` means something; "Sorry, not enough
   units" does not.
3. **`meta`** carries pagination and search metadata (like
   `effectiveRadiusKm`) without polluting the data shape.

The cost: every caller must unwrap `.data`. The client does that once in a
helper, so components never see the envelope.

> **A real mistake worth knowing.** During verification, a probe script read
> `.data` on a response that was actually a `403` error. It reported "0
> entries" and looked like a data bug, when in fact organization isolation was
> working correctly. The lesson: always check the status before reading
> `.data`.

---

## 2. Request headers

| Header | Set when | Purpose |
|---|---|---|
| `Accept: application/json` | always | |
| `X-Correlation-Id: web-<uuid>` | always | client-side tracing id |
| `Authorization: Bearer <access token>` | a token exists | authentication |
| `Content-Type: application/json` | there is a body | |
| `Idempotency-Key: <key>` | the caller supplies one | prevents double-apply |

All five are declared in the API's CORS `AllowHeaders`:
`content-type, authorization, idempotency-key, x-correlation-id`.

**Which token is sent?** The **access token**, not the ID token. The access
token is the one meant for authorizing API calls.

---

## 3. CORS, and why it is configured the way it is

`DEPLOYED` CORS configuration on the HTTP API:

```json
{
  "AllowOrigins": ["https://d324z37do52g8f.cloudfront.net",
                   "http://localhost:5173",
                   "http://127.0.0.1:5173"],
  "AllowMethods": ["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
  "AllowHeaders": ["content-type","authorization","idempotency-key","x-correlation-id"],
  "ExposeHeaders": ["x-correlation-id"],
  "MaxAge": 600
}
```

**What CORS is, simply.** A browser will not let a page at origin A read a
response from origin B unless B says it is allowed. Our page is served from
`d324z37do52g8f.cloudfront.net` and our API is on
`uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com` — **different origins**,
so CORS applies to every call.

**Why three origins?** The CloudFront domain for the deployed site, plus two
localhost forms for development. `localhost` and `127.0.0.1` are *different
origins* to a browser, so both are listed.

**Why not `*`?** Because `Access-Control-Allow-Origin: *` cannot be combined
with credentials, and listing exact origins means a random website cannot make
authenticated calls on a signed-in user's behalf from their browser.

**The deployment hazard.** `CorsAllowOrigins` is a CloudFormation parameter. If
a deployment omits it, the template default takes over and the CloudFront
origin disappears from the list — the live site then fails every API call with
a CORS error while the API itself is perfectly healthy. This is why
[../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md](../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md)
insists all eight parameters are passed explicitly.

**A CORS error in DevTools almost never means CORS is broken.** It usually
means the request failed for another reason and the error response did not
carry the CORS headers. Check the Network tab's status code first.

---

## 4. Error codes you will see

| Status | Code | Meaning | What the UI does |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | bad input | shows field errors |
| 401 | `UNAUTHENTICATED` | no/invalid/expired token | clears session, redirects to sign-in |
| 403 | `FORBIDDEN` | role lacks the permission | explains, does not retry |
| 403 | `ACCOUNT_SUSPENDED` | valid token, suspended account | explains |
| 404 | `NOT_FOUND` | no such record | |
| 405 | — | path exists, wrong method | |
| 409 | `CONCURRENT_MODIFICATION` | optimistic concurrency clash | offers retry (`isRetryable`) |
| 409 | `NO_UNRESERVED_STOCK` | units already held | refreshes availability |
| 429 | `RATE_LIMITED` | throttled | offers retry |
| 500 | — | unexpected | shows the correlation id |
| 0 | `NETWORK_ERROR` | fetch itself failed | "Check your connection" |

`ApiError.isRetryable` is true for 5xx, status 0, `RATE_LIMITED` and
`CONCURRENT_MODIFICATION`. `ApiError.isAuthError` is true for 401 or
`UNAUTHENTICATED`. The UI branches on those two properties rather than on
status numbers scattered through components.

---

## 5. Where the frontend gets its configuration

Build-time environment variables, documented in
`frontend/.env.production.example`:

| Variable | Source |
|---|---|
| `VITE_API_BASE` | stack output `ApiEndpoint` (must include `/dev`) |
| `VITE_COGNITO_DOMAIN` | from stack output `CognitoLoginUrl` (scheme + host only) |
| `VITE_COGNITO_CLIENT_ID` | stack output `UserPoolClientId` |
| `VITE_COGNITO_USER_POOL_ID` | stack output `UserPoolId` |
| `VITE_COGNITO_REDIRECT_URI` | must exactly match a callback URL on the app client |
| `VITE_COGNITO_LOGOUT_URI` | must exactly match a logout URL |
| `VITE_COGNITO_SCOPES` | `openid email profile` |
| `VITE_MAP_STYLE_URL` | **left empty** — empty means the OpenStreetMap basemap |

**Are these secrets?** No, and that is why the example file can be published.
Every value necessarily reaches the browser. The app client is a **public
client with no secret**, which is exactly why it uses Authorization Code with
PKCE. The real secrets — the Lambda execution roles, the Secrets Manager
secret — never leave AWS.

**`.env.production` is not in the repository** (`.gitignore` excludes
`.env.*`). Without it the build still succeeds, but `isCognitoConfigured()`
returns false and sign-in silently does nothing. That is a confusing failure
for anyone cloning the repo, which is why the example file exists and explains
it.

**The redirect URI trap:** Cognito rejects a `redirect_uri` that is not an
exact string match and reports only a bare "redirect_uri mismatch" with no
detail. A trailing slash is enough to break it.

---

## 6. Local development uses the same code

`scripts/local_server.py` runs the **same router and the same handlers** over
plain HTTP on `127.0.0.1:8080`, backed by a local DynamoDB mock. The frontend
dev server proxies to it.

**Why this matters:** the route table, the authorization decorator and the
business logic cannot drift between local and deployed, because there is only
one copy. The only thing that differs is the transport and the data store. See
ADR-0011 (local development without Docker).

---

## 7. Spoken answers

### 20–30 seconds

> "The frontend talks to the backend with plain `fetch` over HTTPS. Every call
> goes through one client module that attaches the Cognito access token as a
> Bearer header and a correlation id. The backend always replies with the same
> envelope — `data` plus a correlation id on success, or an `error` object with
> a stable code on failure — so the UI can react to the code rather than
> parsing English. Because the site and the API are on different domains, CORS
> is configured on the API with our three exact origins rather than a
> wildcard."

### 1–2 minutes

Add the reasoning:

> "We centralised every request in `frontend/src/api/client.js`. That one
> decision removed a whole class of bug: no component can forget the auth
> header, because no component ever sees the token — the client holds a
> *function* that the auth context registers, so there is never a second copy
> of the session going stale.
>
> The envelope also pays for itself. Every response carries a correlation id,
> and the same id is in the CloudWatch log line, so I can take a failure a user
> saw in the browser and find the exact server-side log entry in about thirty
> seconds. And because errors carry a stable machine code, the client can
> compute two properties — is this retryable, and is this an auth failure —
> and the UI branches on those instead of scattering status-code checks
> everywhere."

---

## 8. Follow-up questions

**"Why not use axios or React Query?"**
> `fetch` is built in and sufficient, and every behaviour we needed —
> correlation ids, idempotency keys, the error envelope, abort signals — is
> about twenty lines in one file. Adding a dependency would not have removed
> any of that logic, only moved it. For caching, `frontend/src/hooks/useApi.js`
> handles the loading/error/abort pattern locally. If the app grew to many
> cross-component shared queries, React Query would start to earn its place.

**"How do you cancel a request when the user types quickly?"**
> `request()` accepts an `AbortSignal`, and the search calls pass one, so a
> superseded search is aborted. An `AbortError` is re-thrown unchanged rather
> than being converted to a `NETWORK_ERROR`, so a cancellation never shows the
> user a connection warning.

**"What happens if the API returns HTML instead of JSON?"**
> The client tries to parse the body and throws `MALFORMED_RESPONSE` with the
> real HTTP status rather than crashing. That matters because a gateway or
> proxy error page is HTML, not JSON.

**"Why is the stage name in the API base URL?"**
> Because the HTTP API is deployed to a named stage, `dev`, so it serves at
> `/dev/...`. If `VITE_API_BASE` omitted `/dev`, every route would 404. The
> backend strips the prefix again before matching routes — see
> `strip_stage_prefix` in `backend/src/handlers/router.py`.

---

## 9. Cross-references

- [02_End_To_End_Data_Flow.md](02_End_To_End_Data_Flow.md)
- [../03_REPOSITORY_AND_CODE/02_Frontend_Code_Walkthrough.md](../03_REPOSITORY_AND_CODE/02_Frontend_Code_Walkthrough.md)
- [../04_AWS_COMPLETE_GUIDE/04_API_Gateway.md](../04_AWS_COMPLETE_GUIDE/04_API_Gateway.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/07_Showing_API_Gateway_And_Requests.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/07_Showing_API_Gateway_And_Requests.md)
