# Showing Cognito in Action

Demonstrating authentication — including the two moments that prove it works
rather than describing it.

---

## 1. Privacy first

> **The user pool contains TWO REAL PERSONAL EMAIL ADDRESSES.**
>
> **Do not read them aloud. Do not screenshot the user list. Do not put it on a
> projector without being ready to scroll past them.**

The nine demo accounts use `@demo.lifelink.invalid`. **`.invalid` is a reserved
top-level domain that can never resolve**, so a demo address cannot
accidentally email a real person — a small deliberate detail worth mentioning.

**If the user list must be shown**, filter to `demo.lifelink.invalid` first.

---

## 2. The walkthrough

```
Cognito -> User pools -> lifelink-dev   (ap-southeast-2_Z91jyFm1d)
```

| # | Where | Show | Say |
|---|---|---|---|
| 1 | Overview | the pool id | "notice it literally starts `ap-southeast-2_` — Cognito is a regional service" |
| 2 | **Groups** tab | **EMPTY** | **the key point — see §4** |
| 3 | Sign-in / Authentication | password policy | 12 chars + symbol — see §3 |
| 4 | **App clients** -> `lifelink-dev-web` | no secret, `code` flow, 1-hour tokens | see §5 |
| 5 | App integration -> Domain | the hosted UI domain | |
| 6 | Sign-up -> Attributes | **no `custom:` attributes** | reinforces §4 |
| 7 | Users | **filtered to demo accounts** | 9 demo + a suspended one |

---

## 3. The password policy, and the bug it caused

```
Cognito -> the pool -> Sign-in / Authentication -> Password policy
```

| Requirement | Value |
|---|---|
| Minimum length | **12** |
| Uppercase, lowercase, numbers | required |
| **Symbols** | **required** |

**Say this:**
> "Twelve characters with upper, lower, a number and a symbol. We found a real
> bug here. Three screens in our frontend said 'at least 8 characters' and none
> mentioned a symbol, so users were being rejected by Cognito after following
> our own on-screen instructions.
>
> The obvious fix is to correct the text. What we did instead was put the rules
> in one shared module — and then write a test that **reads the CloudFormation
> template** and asserts the UI matches the deployed policy. So they can't drift
> apart again. Forty-nine tests cover it now.
>
> And we verified it live: Cognito refuses `Password1` with an
> `InvalidPasswordException` — exactly the password the old frontend would have
> accepted."

**That is a fix of the class of bug, not the instance, and it is worth
emphasising.**

---

## 4. The empty Groups tab — the most important screen

```
Cognito -> the pool -> Groups        ->  EMPTY
```

**Say this:**
> "This is the screen I'd most want you to see, and it's empty.
>
> There are no Cognito groups and no custom attributes in our pool. All
> authorization data — the user's role, their organization, their account status
> — lives in DynamoDB and is read on **every single request**.
>
> That's deliberate. If a role were a claim in the token, revoking someone's
> access would take up to an hour, because that's the token lifetime. Reading it
> from the database means a revoked role applies on the very next request.
>
> It also handles something a flat group can't express. A blood bank admin isn't
> an admin in general — they have authority over *their own* facility. That's a
> role plus an organization plus a relationship, which is a record, not a flag.
>
> The cost is one extra DynamoDB read per request. A few milliseconds, and worth
> it."

**Then show the proof** — §6.

---

## 5. The app client

```
Cognito -> the pool -> App clients -> lifelink-dev-web
```

| Setting | Value | Say |
|---|---|---|
| **Client secret** | **none** | "a browser can't keep a secret — anyone can read the JavaScript. So it's a public client, and PKCE replaces the secret" |
| OAuth flow | **`code`** | Authorization Code |
| Scopes | `openid email profile` | |
| **`PreventUserExistenceErrors`** | **ENABLED** | "a wrong password and an unknown email return the **same** error — otherwise you could enumerate valid addresses" |
| Access / ID token | **1 hour** | |
| Refresh token | **30 days** | |
| Token revocation | **enabled** | |
| Callback URL | `https://d324z37do52g8f.cloudfront.net/auth/callback` | "an **exact** string match — a trailing slash breaks sign-in" |
| Auth flows | SRP, refresh, **`ADMIN_USER_PASSWORD_AUTH`** | see below |

**Be honest about the third auth flow:**
> "`ADMIN_USER_PASSWORD_AUTH` is enabled, and I'd turn it off in production. We
> use it for test scripting — provisioning demo logins and obtaining real tokens
> non-interactively for our live verification. The browser never uses it; the
> hosted UI uses SRP, where the password never crosses the network. But in a
> production pool it means a compromised backend credential could authenticate
> as any user with a known password."

---

## 6. The two demonstrations that prove it

### Demonstration A — the token is actually checked

```bash
# No token
curl -s -o /dev/null -w "%{http_code}\n" \
  https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/me
# 401

# Garbage token
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer not.a.token" \
  https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/me
# 401

# A public route needs nothing
curl -s https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev/health
# {"data":{"status":"ok",...,"demoEnvironment":true},"correlationId":"corr-..."}
```

All three **verified on 24 November 2026**.

### Demonstration B — `GET /me` shows the whole model

**The single best request to make.** With a signed-in donor's token:

```
GET /me  ->  200, the principal AND their 13 effective permissions
```

**Say this:**
> "One request shows the entire authorization model: who the system thinks I am,
> which organization I belong to, and exactly what I'm allowed to do — computed
> from the role in DynamoDB, not read from the token."

Then the contrast:

```
GET /admin/audit  with the same donor token  ->  403
```

> "Same token, different endpoint. 403, because a donor doesn't hold
> `audit:read`. Note it's 403 and not 401 — **401 means we don't know who you
> are; 403 means we know exactly who you are and the answer is no.**"

### The suspended account — the best single result

```
A suspended demo account, with a freshly issued, perfectly VALID token
   ->  403 ACCOUNT_SUSPENDED
```

**Say this:**
> "That token is completely valid — correct signature, not expired, right
> audience. And the request is refused, because account status is check three of
> five and it's read from the database. That's the payoff of not putting
> authorization data in the token: a stolen or still-valid token cannot outlive
> a revocation."

---

## 7. Inspecting a token safely

> **Never paste a real token into jwt.io or any online decoder during a
> demonstration, and never into a document or a slide. A live access token is a
> credential for a full hour.**

Decode locally instead:

```bash
echo "<token>" | cut -d. -f2 | base64 -d 2>/dev/null | python -m json.tool
```

Point out:

| Claim | Why |
|---|---|
| `token_use` | `access` or `id` |
| **`client_id`** (access) / **`aud`** (ID) | **the audience lives in different claims — the bug we fixed** |
| `exp` | one hour out |
| `sub` | the user id; **note there is no role claim** |
| `iss` | our pool |

**`sub` with no role claim beside it is the visual proof of §4.**

---

## 8. Do not

| Action | Why |
|---|---|
| Create, delete or disable a user | |
| Reset a password | |
| Change the password policy | a test asserts it matches the template |
| **Edit callback or logout URLs** | **breaks sign-in immediately** — exact match required |
| Add a group | would contradict the design |
| Delete the app client | |
| Show the user list unfiltered | **two real personal addresses** |

---

## 9. Questions and answers

**"Where is the user's role stored?"**
> In the `lifelink-dev-organizations` DynamoDB table, with their organization
> and account status. I can show you the record, and I can show `GET /me`
> returning the effective permissions computed from it. The Cognito pool has no
> groups and no custom attributes at all.

**"What happens when a token expires?"**
> The API returns 401, the client's `isAuthError` becomes true, and the frontend
> clears the stored session and redirects to sign-in. If the refresh token is
> still valid — thirty days — it can get new tokens without a password. We
> actually had a bug here: expired sessions were never cleared, because an
> undefined variable threw inside an empty catch block that swallowed the error.

**"Can someone forge a token?"**
> No. It's signed with RS256 using Cognito's private key, which we never have,
> and we verify with the public key from the JWKS endpoint. We tested a token
> with a rewritten audience claim and a self-signed token for a different
> client — both rejected with 401.

**"Why not use a Cognito authorizer on API Gateway?"**
> It would check the signature, but our authorization also needs the role from
> DynamoDB, the account status and an organization scoping check — so we'd still
> need the Lambda to do four of the five checks, and the logic would be split
> across two places. We keep all five in one decorator with a test that
> enumerates every route to prove none is unprotected.

---

## 10. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §D
- [../04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md)
- [../08_SECURITY_AND_RELIABILITY/01_Cognito_Authentication_Flow.md](../08_SECURITY_AND_RELIABILITY/01_Cognito_Authentication_Flow.md)
- [../08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md](../08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md)
