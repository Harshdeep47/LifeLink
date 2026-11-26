# Authentication and User Workflows

Sign-up, sign-in, getting a role, and managing an account — the workflows
every other feature depends on.

---

## 1. The workflows

| Workflow | Entry point |
|---|---|
| Sign up | `/sign-up` |
| Sign in | `/sign-in` -> Cognito hosted UI -> `/auth/callback` |
| View my activity | `/activity` |
| Manage my profile | `/profile` |
| Request an institutional role | `POST /me/organization-request` |
| Notification preferences | `/profile` |
| Sign out | Cognito logout redirect |

---

## 2. Sign-up

| File | Role |
|---|---|
| `frontend/src/features/account/SignUpPage.jsx` | the form |
| `frontend/src/auth/cognitoSignUp.js` | the Cognito call |
| `frontend/src/auth/passwordPolicy.js` | **the single source of password rules** |

```javascript
export const MIN_LENGTH = 12
```

Plus an explicit `SYMBOLS` set and a `PASSWORD_REQUIREMENTS` list the page
renders.

### The bug, and the fix worth describing

**Three places in the UI said "at least 8 characters" and none mentioned a
symbol**, while the deployed Cognito pool required **12 characters including a
symbol**. Users following the on-screen rules were rejected with an unhelpful
Cognito error.

**The fix was two parts:**

1. One shared module, so the rules exist once.
2. **A test that reads `infrastructure/template.yaml`** and asserts the UI
   requirements match the deployed pool policy.

**49 tests** cover it. **Live proof:** Cognito refuses `Password1` with
`InvalidPasswordException` — exactly the password the old frontend accepted.

**Say this:**
> "This is the fix I'm happiest with. The symptom was that users following our
> own on-screen password rules were being rejected by Cognito, because three
> screens said eight characters and the pool required twelve with a symbol.
>
> The obvious fix is to correct the text. What we did instead was put the rules
> in one shared module and then write a test that reads the CloudFormation
> template and asserts the UI matches the deployed policy. So they can't drift
> apart again. That fixes the class of bug rather than the instance."

---

## 3. Sign-in — Authorization Code with PKCE

```
1. beginSignIn()        generate a random verifier, send SHA256(verifier)
2. redirect             to the Cognito hosted login URL
3. user signs in        at Cognito, using SRP — the password never reaches us
4. redirect back        /auth/callback?code=...
5. completeSignIn()     exchange code + the ORIGINAL verifier for tokens
6. saveSession()        localStorage under 'lifelink.session'
7. setTokenProvider()   the API client gets a FUNCTION, not a token
```

| File | Function |
|---|---|
| `frontend/src/auth/cognito.js` | `beginSignIn`, `completeSignIn`, `refreshSession`, `loadSession`, `saveSession`, `clearSession`, `isExpired`, `signOutRedirect` |
| `frontend/src/features/account/AuthCallbackPage.jsx` | handles the redirect |
| `frontend/src/auth/AuthContext.jsx` | `AuthProvider`, `useAuth` |
| `frontend/src/auth/redirect.js` | safe post-login redirect handling |

### Why PKCE

The app client is **public** — no secret, because a browser cannot keep one.
PKCE binds the code exchange to the browser that started it: an intercepted
authorization code is useless without the verifier, which never left the
browser and cannot be derived from its hash.

### Why the API client holds a function, not a token

```javascript
setTokenProvider(() => currentSession?.accessToken ?? null)
```

**One copy of the session exists.** No component can hold a stale token,
because no component ever sees one.

### The safe-redirect detail

`redirect.js` exists because a naive implementation takes a `returnTo` from the
URL and navigates to it after login — which is an **open redirect** if an
attacker supplies an external URL. The module constrains it to internal paths.
`src/test/redirect.test.js` covers it.

---

## 4. Session expiry — and the bug it hid

| | |
|---|---|
| Access / ID token | **1 hour** |
| Refresh token | **30 days** |
| On expiry | API returns **401**; `ApiError.isAuthError` is true; the frontend clears the session and redirects to sign-in |
| Token revocation | **enabled** on the app client |

> **The real bug.** The expiry branch in `AuthContext.jsx` called
> `localStorage.removeItem(STORAGE_KEY)` — but the constant is `TOKEN_KEY`;
> `STORAGE_KEY` did not exist. The resulting `ReferenceError` was **swallowed by
> an empty `catch`**, so expired sessions were **never cleared** and the user was
> stranded in a broken half-signed-in state.
>
> **Found by:** enabling ESLint for the first time.
>
> **Fixed by:** routing through the existing `clearSession()`.
>
> **Prevented by:** `no-empty` with `allowEmptyCatch: false` is now an **error**,
> so an empty catch cannot hide a programming mistake again.

**Say this:**
> "A bug worth describing, because the lesson generalises. Expired sessions were
> never being cleared, and the reason was an undefined variable — the code used
> `STORAGE_KEY` where the constant is `TOKEN_KEY`. Normally that throws
> immediately and you fix it in seconds. But it was inside an empty catch block,
> so the `ReferenceError` was silently swallowed and the user was just left in a
> broken half-signed-in state.
>
> We found it by turning on ESLint, which the project had a script for but no
> working config. And we didn't just fix the line — we made empty catch blocks
> an error, because the real failure was that a programming mistake could hide
> inside error handling."

---

## 5. Getting a role — and why you cannot give yourself one

```
1. Sign up                     -> baseline PUBLIC principal
2. POST /me/organization-request  -> a PENDING request
3. A platform admin reviews    -> POST /admin/organizations/{id}/status
4. The role is stored          -> lifelink-dev-organizations
5. Read on EVERY request       -> check 2 of five
```

**`PATCH /me` updates the display name only.**

| Can a user change their own... | |
|---|---|
| display name | **yes** |
| role | **no** — request only |
| organization | **no** |
| account status | **no** |

**Self-service role elevation is the most obvious privilege-escalation path in
a system like this, and it is closed by design.**
`backend/tests/unit/test_profile_and_org_requests.py` tests exactly that.

---

## 6. Roles are not in the token

| | |
|---|---|
| Cognito groups | **zero** |
| Custom attributes | **zero** |
| Where roles live | DynamoDB |
| Read | **every request** |

**Why:** a role baked into a one-hour token stays effective for up to an hour.
A role read from the database is revoked on the **next request**. Suspension
must be immediate too — and organization scoping needs a relationship, not a
flag.

**Verified live:** a suspended account with a freshly issued, perfectly valid
token receives **403 `ACCOUNT_SUSPENDED`** — not 401, because the token is
genuine.

**The distinction to state:** 401 means *we do not know who you are*; 403 means
*we know exactly who you are and the answer is no.*

---

## 7. `GET /me` — the best single demonstration

Returns the current principal **and their effective permissions**.

**Why it is the best demo request:** one call shows the whole authorisation
model — who the system thinks you are, which organization you belong to, and
exactly what you may do, computed from the role in DynamoDB.

```
GET /me  with a donor's token       -> 200, 13 permissions
GET /me  with no token              -> 401
GET /admin/audit with a donor token -> 403
```

All three **verified live**.

---

## 8. My Activity — and a deliberate scoping decision

`/activity`, `frontend/src/features/account/MyActivityPage.jsx`, 18 tests.

It shows **reservations and emergency requests only**.

**Alerts and camp registrations are deliberately excluded**, because they
already have their own screens — `/alerts` and the donor dashboard — and
duplicating them would mean two places showing the same state, which can
disagree.

**That restraint is worth mentioning.** An earlier version had four sections and
was narrowed on review. A page that aggregates everything sounds helpful and
creates a consistency problem.

---

## 9. The API

| Method | Path | Permission |
|---|---|---|
| GET | `/me` | `profile:manage:own` |
| PATCH | `/me` | `profile:manage:own` — **display name only** |
| POST | `/me/organization-request` | `profile:manage:own` |
| GET | `/me/notifications` | `alert:manage:own` |
| GET | `/me/notification-preferences` | `alert:manage:own` |
| PUT | `/me/notification-preferences` | `alert:manage:own` |
| GET | `/me/reservations` | `reservation:manage:own` |
| GET | `/me/registrations` | `registration:manage:own` |
| GET | `/me/donations` | `registration:manage:own` |
| GET | `/me/donor-profile` | `registration:manage:own` |
| POST | `/admin/users/{id}/status` | **`user:manage`** |
| POST | `/admin/organizations/{id}/status` | **`hospital:verify`** |

---

## 10. Protected routes in the frontend

```jsx
<Route path="/profile"
       element={<RequireAuth><ErrorBoundary><ProfilePage /></ErrorBoundary></RequireAuth>} />
```

`RequireAuth` guards `/profile`, `/activity` and all five role dashboards.

**An important point to make:** `RequireAuth` is a **user-experience**
convenience, not a security boundary. It stops a signed-out user seeing an
empty broken page. **The real enforcement is server-side** — every API call is
authorised independently in the Lambda, so bypassing the frontend guard gets
you a page that cannot load any data.

**Say this if asked whether the frontend protects anything:**
> "The route guard is for user experience, not security. If you removed it in
> DevTools you'd see the dashboard shell and every API call would return 401 or
> 403, because authorisation happens server-side on every request. Client-side
> guards can never be a security boundary — the client is under the user's
> control."

---

## 11. Status

| Aspect | Status |
|---|---|
| Sign-up with the correct policy | `DEPLOYED`, 49 tests, **live Cognito refusal verified** |
| Sign-in (PKCE) | `DEPLOYED` |
| Token verification | **verified live** — 19 authentication checks |
| Session expiry clearing | fixed, `DEPLOYED` |
| Suspended account refusal | **verified live** (403) |
| Role request workflow | `DEPLOYED`, `TEST-VERIFIED` |
| No self-elevation | `TEST-VERIFIED` |
| `GET /me` effective permissions | **verified live** |
| My Activity | `DEPLOYED`, 18 tests |
| **Browser sign-in by a person** | **NOT VERIFIED** — the single most important outstanding manual check |

**If asked which of the 12 pending browser checks matters most: this one.**
Everything else depends on sign-in working in a real browser with a real
Cognito redirect.

---

## 12. Spoken answers

### 20–30 seconds
> "Sign-in redirects to Cognito's hosted login, the user authenticates there,
> and Cognito returns an authorization code that the app exchanges for JWTs
> using PKCE. We never see a password. Every API call then carries the access
> token, and the Lambda verifies it and loads the user's role from DynamoDB —
> not from the token — so revoking a role takes effect on the next request."

### 1–2 minutes
> "Three things worth knowing.
>
> First, the app client is public with no secret, because a browser can't keep
> one. So we use Authorization Code with PKCE: the browser generates a random
> verifier, sends only its hash to start the login, and presents the original
> when exchanging the code. An intercepted code is useless without it.
>
> Second, a user can't give themselves a role. `PATCH /me` changes a display
> name and nothing else. Getting an institutional role means submitting a
> request that stays pending until a platform admin approves it — self-service
> role elevation is the obvious privilege-escalation path in a system like this
> and it's closed by design, with a test for it.
>
> Third, roles aren't in the token. There are no Cognito groups and no custom
> attributes; the role is in DynamoDB and read on every request. That means
> suspension is immediate — we verified live that a suspended account with a
> perfectly valid token gets a 403 saying the account is suspended, rather than
> a 401, because the token itself is genuine."

---

## 13. Cross-references

- [../04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md)
- [../08_SECURITY_AND_RELIABILITY/01_Cognito_Authentication_Flow.md](../08_SECURITY_AND_RELIABILITY/01_Cognito_Authentication_Flow.md)
- [../08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md](../08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md)
- [../01_START_HERE/03_Project_Features_And_User_Roles.md](../01_START_HERE/03_Project_Features_And_User_Roles.md)
