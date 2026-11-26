# JWT and Token Verification

**The highest-value security topic in the project**, because it contains a
real, specific, well-understood bug and its fix.

---

## 1. What a JWT is

**JSON Web Token** — three Base64url-encoded parts separated by dots:

```
eyJraWQiOiJ...  .  eyJzdWIiOiI...  .  SflKxwRJSMeKK...
   HEADER              PAYLOAD            SIGNATURE
```

| Part | Contains |
|---|---|
| **Header** | the algorithm (`RS256`) and the key id (`kid`) |
| **Payload** | the **claims** — who, what, when |
| **Signature** | a cryptographic signature over header + payload |

### The point people miss

**A JWT is encoded, not encrypted.** Anyone holding one can read its claims —
that is by design. What they **cannot** do is change a claim, because any
change invalidates the signature.

**Say this:**
> "A JWT isn't encrypted — it's Base64, so anyone can decode it and read the
> claims. That's intentional. What they can't do is modify it, because the
> signature covers the header and payload. Change one character of the payload
> and verification fails. So you should never put a secret in a JWT, and you
> should never trust one you haven't verified."

---

## 2. Cognito's three tokens

| Token | Purpose | Key claims | Validity |
|---|---|---|---|
| **Access** | authorize API calls | `sub`, **`client_id`**, `scope`, `token_use: "access"`, `exp`, `iss` | 1 hour |
| **ID** | describe the user | `sub`, **`aud`**, `email`, `token_use: "id"`, `exp`, `iss` | 1 hour |
| **Refresh** | obtain new tokens | **opaque — not a JWT** | 30 days |

**LifeLink sends the access token** in `Authorization: Bearer`.

### Access versus ID token — the standard question

| | Access token | ID token |
|---|---|---|
| Answers | **"may this request do X?"** | **"who is this person?"** |
| Audience claim | **`client_id`** | **`aud`** |
| Intended consumer | the **API** | the **client application** |
| Contains profile data | no | yes (email etc.) |
| OAuth 2.0 / OIDC | OAuth 2.0 | OpenID Connect |

**Say this:**
> "The access token authorizes API calls — it's meant for the resource server,
> and it carries scopes. The ID token describes who the user is and is meant for
> the client application; it carries the email and profile claims. We send the
> access token, because that's the one designed for authorizing an API call.
>
> The detail that bit us is that they put the audience in **different claims** —
> an access token has `client_id` and no `aud`; an ID token has `aud` and no
> `client_id`."

---

## 3. The bug and the fix

> **A Cognito access token carries `client_id` and has NO `aud` claim.
> A Cognito ID token carries `aud` and has NO `client_id`.**

Code that checks only one field **silently fails to validate the other token
type**. If you check `aud` only, an access token has no `aud` — so the check
either passes vacuously or rejects every valid access token, depending on how
it is written. Either way, one token type is not properly validated.

### The deployed code

`backend/src/appcore/auth.py`:

```python
presented = claims.get("client_id") if token_use == "access" else claims.get("aud")
allowed = presented if isinstance(presented, (list, tuple)) else [presented]
if self.client_id not in allowed:
    raise UnauthenticatedError("token was not issued for this client")
```

**Three details worth pointing out:**

1. **`token_use` selects the claim.** The check is per token type, not a guess.
2. **`aud` may be a list.** The spec permits an array, so it is normalised
   before the membership test. A naive `==` comparison would reject a valid
   multi-audience token.
3. **Membership, not equality.** `self.client_id not in allowed`.

### Proof, and its honest limit

| | |
|---|---|
| Tests | **23** in `backend/tests/unit/test_cognito_token_verifier.py` |
| Reverting the fix | **fails 3 of them** |
| Live demonstration of the attack | **impossible** |

**The attack this closes is a validly pool-signed ID token issued for a
*different* app client. Our pool has exactly one app client, so no such token
can be produced — which is also why the weakness was never exploitable here.**

**Say the limit out loud:**
> "I should be honest about the limit of this. The exact attack it closes is a
> token legitimately signed by our pool but issued for a different app client.
> Our pool has exactly one app client, so no such token can exist — which is
> also why this was never actually exploitable. I can't demonstrate the attack;
> I can only prove the check works by unit test, and by reverting the fix and
> watching three tests fail.
>
> I'd rather tell you that than claim I demonstrated an attack I couldn't
> construct."

**That answer is worth more than the bluff.** Claiming a demonstrated attack
invites exactly one follow-up question that destroys it.

---

## 4. What is verified on every request

| # | Check | How | Catches |
|---|---|---|---|
| 1 | **Signature** | RS256 against the pool's JWKS public keys | forged or modified tokens |
| 2 | **Issuer** (`iss`) | `https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_Z91jyFm1d` | a token from a different pool |
| 3 | **Expiry** (`exp`) | compared to now | a stale token |
| 4 | **`token_use`** | `access` or `id` as expected | an ID token used where an access token belongs |
| 5 | **Audience** | `client_id` or `aud`, per type | a token for a different app client |

### Why RS256 and not HS256

| | RS256 (asymmetric) | HS256 (symmetric) |
|---|---|---|
| Signing key | Cognito's **private** key, never shared | a shared secret |
| Verifying key | the **public** key from JWKS | the **same** secret |
| Can the verifier forge a token? | **no** | **yes** |

**That last row is the whole argument.** With HS256, every service that can
validate a token can also mint one — so a compromised API server could issue
valid tokens for any user. With RS256 it can only verify.

### JWKS caching — the obvious objection answered

`PyJWKClient` **caches** the public keys, so there is **not** a network call to
Cognito per request.

**Pre-empt the question:**
> "We verify every token on every request — and to answer the obvious
> objection, that doesn't mean calling Cognito each time. Verification is a
> local cryptographic operation using Cognito's public keys, which we fetch once
> and cache. The only reason to refetch is key rotation."

### Why this makes `cryptography` a build constraint

RS256 verification needs the `cryptography` library, which ships as a
**compiled binary wheel**. That single fact is why `sam build` must not be used
on this Windows host — it would install a Windows wheel that cannot load on an
`arm64` Linux function — and why
`scripts/build_lambda_package.py --verify` fetches `manylinux2014_aarch64`
wheels explicitly.

**A dependency choice driving a build process. Good detail.**

---

## 5. What is NOT in the token

| Not in the token | Where it lives |
|---|---|
| The user's **role** | `lifelink-dev-organizations` in DynamoDB |
| Their **organization** | same |
| Their **account status** | same |
| Their **permissions** | computed from the role per request |

**The pool has zero groups and zero custom attributes.**

**Why:** a role baked into a one-hour token stays effective for up to an hour.
A role read from the database is revoked on the **next request**.

**Verified live:** a suspended account with a freshly issued, perfectly valid
token receives **403 `ACCOUNT_SUSPENDED`** — not 401, because the token is
genuine.

> **401 means we do not know who you are. 403 means we know exactly who you
> are and the answer is no.**

---

## 6. Live verification results

**19 authentication checks, all passing:**

| Test | Result |
|---|---|
| No token on `/me` | **401** |
| No token on `/admin/audit` | **401** |
| Reservation POST without a token | **401** |
| Real **access** token on `/me` | **200** |
| Real **ID** token on `/me` | **200** |
| **Garbage** token | **401** |
| Token with a **rewritten `aud`** | **401** |
| **Self-signed** token for another client | **401** |
| Suspended account, valid token | **403 `ACCOUNT_SUSPENDED`** |
| Public endpoints with no token | **200** |

**"Real ID token on `/me` returns 200" is worth understanding** — both token
types verify correctly, each against its own audience claim. That is the fix
working in both directions.

---

## 7. Inspecting a token — safely

**Decode locally. Do not paste a real token into a website.**

```bash
echo "<token>" | cut -d. -f2 | base64 -d 2>/dev/null | python -m json.tool
```

Point out `token_use`, `client_id` (access) or `aud` (ID), `exp`, `sub`, `iss`.

> **A live access token is a credential for a full hour.** Never paste one into
> jwt.io or any online decoder during a demonstration, never put one in a
> document or a slide, and if one does get exposed, sign out — token revocation
> is enabled on the app client.

---

## 8. Spoken answers

### "What's the difference between an access token and an ID token?" — 30 s
> "The access token authorizes API calls — it's meant for the resource server
> and carries scopes. The ID token describes who the user is and is meant for
> the client application; it carries profile claims like email. We send the
> access token. The detail that matters is that Cognito puts the audience in
> different claims — `client_id` on an access token and `aud` on an ID token —
> which is exactly the bug we found and fixed."

### "Can someone modify a JWT?" — 30 s
> "They can change the bytes, but not without breaking the signature. It's
> signed with RS256 using Cognito's private key, which we never have, and we
> verify with the public key from the JWKS endpoint. Any change fails
> verification — we tested that specifically: a token with a rewritten audience
> claim is rejected with a 401."

### 1–2 minutes on the whole topic
> "We verify five things on every request: the RS256 signature against
> Cognito's public keys, the issuer, the expiry, the `token_use` claim, and the
> audience.
>
> The audience check is where we found a real bug. Cognito puts the audience in
> different claims depending on the token type — an access token has `client_id`
> and no `aud`; an ID token has `aud` and no `client_id`. Code that checks only
> one field silently fails to validate the other token type. So we select the
> claim based on `token_use`, and we normalise it, because the spec allows `aud`
> to be an array.
>
> We use RS256 rather than HS256 deliberately. RS256 is asymmetric — Cognito
> signs with a private key it never shares, and we verify with the public key.
> So we can verify but we can't forge. With a symmetric algorithm, every service
> that validates tokens could also mint them, which means a compromised API
> server could issue valid tokens for any user.
>
> And verification doesn't mean calling Cognito on every request — it's a local
> cryptographic operation with cached public keys.
>
> One honest limitation: I can't demonstrate the attack the audience fix
> prevents, because our pool has exactly one app client, so a token for a
> different client can't be produced. That's also why it was never exploitable.
> It's proven by unit test — reverting the fix fails three of twenty-three."

---

## 9. Follow-up questions

**"What if Cognito's signing key is rotated?"**
> The JWKS endpoint publishes multiple keys, and the token's header carries a
> `kid` identifying which one signed it. `PyJWKClient` matches on `kid` and will
> refetch if it sees an unknown one, so rotation is handled without a
> deployment.

**"Why not validate the token at API Gateway?"**
> An HTTP API does have a built-in JWT authorizer, and it would check the
> signature. But our authorization also needs the user's role from DynamoDB,
> their account status and an organization scoping check, so we'd still need the
> Lambda to do four of the five checks. Splitting it would mean authorization
> logic in two places. The cost of our choice is that an invalid request still
> costs a Lambda invocation, which is why the gateway throttles at ten per
> second.

**"What stops someone replaying a stolen token?"**
> Within its one-hour lifetime, nothing — that's inherent to bearer tokens.
> What limits the damage is that the lifetime is short, revocation is enabled on
> the app client, and critically the role isn't in the token: if we suspend the
> account, the very next request with that token gets a 403, because the status
> is read from the database. So a stolen token can't outlive a revocation.

**"Is the token stored securely in the browser?"**
> It's in `localStorage` under `lifelink.session`. That's the common choice and
> it has a known trade-off: it's readable by JavaScript, so it's vulnerable to
> XSS. The more secure option is an httpOnly cookie, which JavaScript can't
> read, but that needs a backend session endpoint and brings CSRF
> considerations. For this project `localStorage` with a one-hour token was the
> accepted trade — and I'd call that a fair criticism rather than defend it as
> optimal.

---

## 10. Cross-references

- [01_Cognito_Authentication_Flow.md](01_Cognito_Authentication_Flow.md)
- [02_IAM_Authorization_Flow.md](02_IAM_Authorization_Flow.md)
- [../04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/05_Showing_Cognito_In_Action.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/05_Showing_Cognito_In_Action.md)
