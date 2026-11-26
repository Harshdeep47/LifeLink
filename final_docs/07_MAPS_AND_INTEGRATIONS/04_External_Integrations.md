# External Integrations

Everything LifeLink talks to outside its own AWS resources — and, more
importantly, everything it **does not**.

---

## 1. The complete list

| Integration | Status | Where |
|---|---|---|
| **OpenStreetMap tile servers** | **ACTIVE** — browser | `tile.openstreetmap.org` |
| **Amazon Location place index** (Esri) | **ACTIVE** — server | `GET /geocode` |
| **Amazon Location route calculator** (Esri) | **ACTIVE** — server | `GET /facilities/{id}/route` |
| Cognito hosted UI | **ACTIVE** — browser redirect | AWS, but a separate origin |
| External provider inventory API | **`NOT-IMPLEMENTED`** — route and secret exist, nothing connected | `POST /facilities/{id}/inventory/ingest` |
| Amazon SES (email) | **`NOT-IMPLEMENTED` as deployed** | `SES_SENDER` is **empty** |
| SMS | **`NOT-IMPLEMENTED`** | ADR-0015 + SCP |
| Amazon Location **browser tiles** | **`NOT-IMPLEMENTED`** | API keys denied (ADR-0019) |
| OpenRouteService | **deliberately rejected** | ADR-0012 |
| Payment, analytics, ads, social login | **none** | — |

**Four active integrations. That is the honest count.**

---

## 2. What the browser talks to

| Origin | Why |
|---|---|
| `d324z37do52g8f.cloudfront.net` | the site itself |
| `uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com` | our API |
| `lifelink-dev-426150327442.auth.ap-southeast-2.amazoncognito.com` | the hosted login |
| **`tile.openstreetmap.org`** | **the only non-AWS origin** |

**Worth stating:** there are **no third-party analytics, no advertising, no
social login, no CDN-hosted JavaScript** and no tracking pixels. The only
external service the browser contacts is a map tile server.

**Say this:**
> "The browser talks to four origins: our site, our API, Cognito's hosted
> login, and OpenStreetMap's tile servers. That's it — no analytics, no ad
> networks, no social login, no third-party JavaScript. For a project handling
> health-adjacent coordination that's deliberate: every extra origin is another
> party seeing that someone is looking for blood."

---

## 3. What the backend talks to

| Service | Permission granted | Scope |
|---|---|---|
| DynamoDB | per-table policies | 12 tables + indexes |
| SQS | `sqs:SendMessage*` | 2 queues |
| Cognito | `cognito-idp:AdminGetUser`, `ListUsers` | **our pool only** |
| Amazon Location | 3 actions | our place index + route calculator |
| KMS | `GenerateDataKey`, `Decrypt` | **condition-bound to DynamoDB** |
| Secrets Manager | read | 1 secret |
| CloudWatch Logs, X-Ray | managed policies | |

**Everything is AWS, reached over HTTPS with SigV4.** There is no outbound call
to a non-AWS service from the backend at all — which is also why the Lambdas
need no VPC and therefore no NAT Gateway (saving ~$32/month).

---

## 4. The provider ingestion seam — built, not connected

| Component | Status |
|---|---|
| Route `POST /facilities/{id}/inventory/ingest` | **exists** |
| Permission `inventory:ingest:api` | **exists**, held by `BLOOD_BANK_ADMIN` |
| Secret `lifelink/dev/provider-api-keys` | **exists** |
| Adapter seam `backend/src/adapters/` | **exists** |
| **An actual provider connected** | **NO** |
| Secret ever accessed | **never** (`LastAccessedDate` is null) |

**Be precise:** the capability is built and the credential store is in place.
Nothing is plugged into it, because no external blood bank system was available
to integrate with.

**That costs $0.40 a month gross** (net $0.00 after credits), and its
`LastAccessedDate` is **null** — the Secrets Manager secret is the project's only
non-free charge.

**Say this:**
> "There's a route for external systems to push inventory, with its own
> permission and a Secrets Manager secret for provider credentials. It's never
> been used — the secret's last-accessed date is null — because we didn't have a
> real blood bank system to integrate with. The seam is built and nothing is
> plugged into it. Slightly amusingly, that unused secret is the only thing in
> the project that generates any charge at all: forty cents a month gross, and
> about seventy percent of our whole gross bill. Net it's zero, because
> FREE-plan credits cover it."

---

## 5. Email and SMS — stated precisely

### Email

| | |
|---|---|
| Seam | exists in `backend/src/adapters/notifications.py` |
| `SES_SENDER` | **empty on all six functions** |
| Notification worker Lambda | **has no CloudWatch log group — never invoked** |
| Notifications that do work | **in-app**, 18 rows in the table |

**The missing log group is the decisive evidence.** A log group is created on
first invocation, so its absence proves the function has never run.

### SMS

**`NOT-IMPLEMENTED`**, for two independent reasons:

1. **ADR-0015** — email and in-app notifications only; SMS not implemented.
2. The account's **SCP blocks SMS sending** anyway.

**Say this:**
> "Notifications are in-app only. When something happens a user should know
> about, we write a record to the notifications table and they see it in the app
> — there are eighteen of those. Email is wired but not configured: the sender
> address is empty, so nothing sends. SMS isn't implemented at all, which is
> ADR-0015, and it's also blocked by our account's service control policy.
>
> The strongest evidence I can give you is that the notification worker Lambda
> has no CloudWatch log group, which means it has literally never been invoked.
> A log group gets created on first invocation, so its absence is proof. I'd
> rather show you that than imply the pipeline runs end to end."

---

## 6. Rejected integrations, and why

| Rejected | Reason |
|---|---|
| **OpenRouteService** | ADR-0012 — a second routing provider that cannot be verified end to end adds risk without benefit. The `RoutingProvider` interface leaves the seam open |
| **Google Maps** | needs a paid API key and a billing account; the project avoids paid subscriptions |
| **Mapbox** | same, and MapLibre is the open fork of its renderer |
| **A commercial tile provider** | paid |
| **Third-party analytics** | another party learning that someone is searching for blood |
| **Social login** | more identity providers, more attack surface, no benefit for institutional users |

**On avoiding paid APIs:** a stated project constraint was no paid APIs or
subscriptions. That is why the basemap is OpenStreetMap rather than a
commercial provider — and the Amazon Location *API key* problem meant the free
AWS path was unavailable too.

---

## 7. How an integration would be added

The adapter pattern (ADR-0010) exists for this.

```
services/        ->  adapters/          ->  the external service
(business logic)     (the seam)
```

| Adapter | Wraps |
|---|---|
| `backend/src/adapters/location.py` | Amazon Location |
| `backend/src/adapters/notifications.py` | notification delivery |

**To add SMS**, for instance: implement a new delivery method in
`adapters/notifications.py`, configure the credential in Secrets Manager, add
the IAM permission to the worker's role — and **no service or domain code
changes**.

**Say this:**
> "Integrations go through an adapter layer, so the business logic never talks
> to an external service directly. If we added SMS, it'd be a new delivery
> method in the notifications adapter, a credential in Secrets Manager, and an
> IAM permission on the worker role — no changes to the services or the domain
> logic. That's the point of the seam: the thing most likely to change is the
> thing most isolated."

---

## 8. Failure handling for each active integration

| Integration | On failure |
|---|---|
| **OSM tiles** | blank basemap; **markers still render**; fallback message |
| **Location geocoding** | place search returns an error; the user can still use device location |
| **Location routing** | "directions unavailable"; the facility list and contacts survive; **never an invented distance** |
| **Cognito hosted UI** | sign-in fails; **anonymous browsing still works** for the 9 public routes |

**The pattern worth naming:** every external dependency degrades **one
feature**, not the application. Nothing in the critical path — finding a blood
bank and seeing its contact details — depends on a non-AWS service.

**That is a genuinely good architectural property and worth claiming
explicitly.**

---

## 9. Status summary

| Integration | Status |
|---|---|
| OSM tiles | `DEPLOYED`, working |
| Location geocoding | `DEPLOYED`, **verified live** (Esri data for "Patiala") |
| Location routing | `DEPLOYED`, responds |
| Cognito hosted UI | `DEPLOYED`; **browser flow NOT VERIFIED by a person** |
| Provider ingestion | route exists; **no provider connected** |
| Email | **`NOT-IMPLEMENTED`** as deployed |
| SMS | **`NOT-IMPLEMENTED`** |
| Location browser tiles | **`NOT-IMPLEMENTED`** — API keys denied |

---

## 10. Spoken answers

### 20–30 seconds
> "Four active external integrations. The browser fetches map tiles from
> OpenStreetMap and redirects to Cognito's hosted login; the backend calls
> Amazon Location for geocoding and routing. That's all — no analytics, no ad
> networks, no third-party JavaScript. Email and SMS are not connected, and the
> external inventory ingestion route exists but has no provider plugged into
> it."

### 1–2 minutes
> "I'd describe it as four active integrations and several deliberate absences.
>
> Active: OpenStreetMap tiles in the browser, Cognito's hosted login as a
> redirect, and Amazon Location server-side for geocoding and routing. The
> backend makes no outbound call to anything that isn't AWS — which is also why
> our Lambdas need no VPC, and therefore no NAT Gateway, which would have cost
> about thirty-two dollars a month on its own.
>
> Not connected: email is wired but the sender address is empty, so nothing
> sends — and the notification worker Lambda has no log group, which proves it's
> never been invoked. SMS isn't implemented, both by decision and because our
> account's policy blocks it. And the external inventory ingestion route exists
> with its own permission and a Secrets Manager secret, but no provider is
> connected and the secret has never been accessed.
>
> The property I'd claim is that every external dependency degrades one feature
> rather than the application. If OpenStreetMap is down you get a blank basemap
> with the markers still on it. If routing fails you lose the ETA but keep the
> facility and its phone number. Nothing in the critical path — finding a blood
> bank and getting its contact details — depends on a non-AWS service."

---

## 11. Follow-up questions

**"Why no analytics?"**
> Because every extra origin the browser contacts is another party learning that
> someone is looking for blood. For a health-adjacent application that's a
> privacy cost with no benefit to the user. We get what we need from CloudWatch
> — request counts, latencies, errors — without a third party in the browser.

**"What's the biggest external risk?"**
> OpenStreetMap, because it's the one non-AWS dependency in the browser and
> it's a free community service we don't have an agreement with. If they blocked
> us or went down, the basemap would be blank — markers would still render, so
> the feature degrades rather than breaks. The real fix is self-hosted or
> commercial tiles, or solving the Amazon Location credential path.

**"Could you integrate with a real blood bank system?"**
> The seam is built for it — the route, the permission, the secret and the
> adapter layer all exist. What's missing is a real counterparty. In practice
> you'd need an agreement, their API shape, and a mapping from their data model
> to ours, and I'd expect the mapping to be the hard part — "units of O-negative"
> is not a universally structured concept across systems.

---

## 12. Cross-references

- [02_Map_Rendering_And_Tiles.md](02_Map_Rendering_And_Tiles.md)
- [../04_AWS_COMPLETE_GUIDE/09_SNS_SQS_And_Notifications.md](../04_AWS_COMPLETE_GUIDE/09_SNS_SQS_And_Notifications.md)
- [../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md](../08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md)
- ADR-0012, ADR-0015, ADR-0019 in `docs/ARCHITECTURE_DECISIONS.md`
