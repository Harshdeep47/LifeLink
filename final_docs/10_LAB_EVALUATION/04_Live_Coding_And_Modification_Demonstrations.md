# Live Coding and Modification Demonstrations

Six demonstrations you can perform on the spot, in order of risk. Rehearse the
first three.

> **The project is under an engineering freeze.** These are for a **local**
> copy. **Do not commit, deploy or push.** Revert with `git checkout`.

---

## The rule to state before you touch anything

> **"I'll do this on my local copy and revert it. The deployed system is frozen
> at commit `668a771`."**

Saying that unprompted is worth more than it costs.

---

## Demo 1 — Change a heading (2 minutes, no risk)

```bash
# 1. Find it
grep -rn "Find blood near you" frontend/src/

# 2. Edit the file the grep names

# 3. Watch it hot-reload
cd frontend && npm run dev          # http://localhost:5173

# 4. Prove it is a real change
git diff

# 5. Revert
git checkout frontend/src/features/home/HomePage.jsx
```

**What to say:**
> "Vite's dev server watches the file, rebuilds only the changed module and
> pushes it over a WebSocket — which is why that took under a second with no
> full reload. That's development only; production is a static bundle in S3.
>
> And `git diff` is the proof it's a real file change rather than something I
> did in the browser."

---

## Demo 2 — Trace a button to its backend handler (3 minutes, no risk)

**Five greps. This is the one most likely to be asked for.**

```bash
# 1. Visible text -> component
grep -rn "Request hold" frontend/src/

# 2. The api. call in that component
grep -n "api\." frontend/src/features/discovery/ReservationPanel.jsx

# 3. The method -> the route
grep -n "requestReservation" frontend/src/api/client.js
#   => POST /facilities/${facilityId}/reservations

# 4. The route -> the handler
grep -n "def request_reservation" -A 12 backend/src/handlers/api.py
```

**What to say:**
> "Five steps and about thirty seconds. The reason it's that quick is that every
> API call lives in one module — `api/client.js` — so I never have to search for
> a URL scattered through components. And the route table in `api.py` maps every
> route to its handler and the permission it requires."

**Then show the handler is four lines of real work:**
> "Notice the handler just parses input, delegates to a service, and shapes the
> response. No business rule lives in a handler — that's the layering being
> honest rather than aspirational."

---

## Demo 3 — Break a rule and watch the tests catch it (3 minutes)

**The most persuasive demonstration available, because a passing test proves
little and a *failing* one proves the test was real.**

```bash
# 1. Edit backend/src/domain/freshness.py
#    FRESH_MAX_HOURS = 6.0   ->   100.0

# 2. Run the tests
python -m pytest backend/tests/unit/test_freshness_and_eligibility.py -q
#    => FAILURES, naming the boundary assertions

# 3. Revert
git checkout backend/src/domain/freshness.py
python -m pytest backend/tests/unit/test_freshness_and_eligibility.py -q
#    => passes
```

**What to say:**
> "Rather than show you tests passing, which doesn't prove much, I'll break a
> rule. Widening the fresh-data threshold from six hours to a hundred makes the
> boundary tests fail immediately and name the assertion. That's how we know the
> suite constrains behaviour rather than just exercising it."

### The variant worth having ready

```bash
# Give DONOR a permission it shouldn't have, in backend/src/appcore/rbac.py
python -m pytest backend/tests/unit/test_authorization.py -q
git checkout backend/src/appcore/rbac.py
```

> "Same idea on the authorization matrix. There are thirty-three authorization
> tests, including one that enumerates the whole route table and fails if any
> route is missing its authorization metadata — which is what makes 'no endpoint
> was left unprotected' a checked property rather than a claim."

---

## Demo 4 — DevTools versus source code (2 minutes)

**The distinction a teacher may specifically test.**

1. On the live site, open **Elements**, double-click a heading, type something
   else.
2. **Refresh.** It is gone.

**What to say:**
> "That changed nothing. It was only the page in my browser's memory — refresh
> and it's gone, and nobody else ever saw it. It doesn't appear in `git diff`
> either.
>
> A real change means editing the file in `frontend/src`, rebuilding with Vite,
> uploading the bundle to S3, and **invalidating the CloudFront cache** —
> because until you do that, the edge keeps serving the old file and it looks
> like your deployment didn't work."

| | DevTools | Source change |
|---|---|---|
| Who sees it | only you | everyone, after deploy |
| Survives refresh | **no** | yes |
| Needs a rebuild | no | yes |
| Needs an invalidation | no | **yes** |
| In `git diff` | **no** | yes |

---

## Demo 5 — Find the API request a button makes (2 minutes)

1. DevTools -> **Network** -> filter **Fetch/XHR**
2. Click **Find blood**
3. Click the request

| Tab | Point at |
|---|---|
| Headers | the full URL with `/dev/`, and **`Authorization: Bearer ...`** |
| Query | `lat`, `lon`, `radiusKm`, `bloodGroup`, `component` |
| Response | `{"data":[...],"meta":{...},"correlationId":"corr-..."}` |
| Timing | time to first byte — mostly the trip to Sydney |

**Then the move that ties it together:** copy the `correlationId` and find it
in CloudWatch Logs Insights.

> **Do not copy the token value anywhere.** Point at the header and say: "that's
> a live credential for an hour — I'm not putting it in a document."

---

## Demo 6 — Add a field to an API response (10 minutes, advanced)

**Only attempt this if asked and you have time.** It touches every layer, which
is the point.

To add `lastVerifiedByName` to the facility detail response:

| Step | File | Change |
|---|---|---|
| 1 | `backend/src/repositories/facility_repo.py` | ensure the attribute is read |
| 2 | `backend/src/handlers/api.py` -> `get_facility` | include it in the response dict |
| 3 | `backend/tests/unit/` | add a test asserting it appears |
| 4 | `frontend/src/features/discovery/FacilityDetailPage.jsx` | render it |
| 5 | `python scripts/generate_openapi.py` | regenerate the spec |
| 6 | both suites | **951 must still pass** |

**Step 5 is the one worth explaining:**
> "`generate_openapi.py --check` fails the build if `docs/openapi.json` no
> longer matches the route table — so forgetting to regenerate is caught rather
> than silently shipping stale documentation."

**Then revert everything.**

---

## What not to demonstrate

| Do not | Why |
|---|---|
| Edit `infrastructure/template.yaml` and deploy | a parameter change can **replace** resources — omitting `CognitoDomainPrefix` replaces the Cognito domain |
| Edit live DynamoDB records | hand-edited data cannot be reproduced by re-seeding |
| Change `emergency_repo.append_event` | deliberately append-only; real history must accumulate |
| Edit IAM, Cognito or S3 in the Console | creates drift |
| Run `seed_cloud.py --apply` during a demo | it works, but it takes time and the dispatcher will then write new events |
| Run `dedupe_request_events.py --apply` | a delete tool; not a demonstration |
| `git commit` or `git push` | the project is frozen |

---

## The verification commands, if asked to prove the state

```bash
python -m pytest backend/tests -q               # 657 passed
cd frontend && npm run test -- --run            # 294 passed
ruff check .                                    # clean
cd frontend && npm run lint                     # exit 0
cd frontend && npm run build                    # succeeds
cfn-lint infrastructure/template.yaml           # clean
python scripts/security_audit.py                # passes
python scripts/generate_openapi.py --check      # "matches the route table"
git log --oneline -1                            # 668a771
git status --short                              # clean
```

**The last two together are worth running:** a clean tree at a named commit is
the evidence that what you are showing is what was released.

---

## If a demonstration fails

**Do not debug live.** Say what happened, say what you would check, and move
on.

> "That's not what I expected — I'd check [the specific thing] before claiming
> anything about it. Let me show you [the next thing] instead."

**A calm non-answer beats five minutes of flailing.** And if the failure is
genuinely interesting, say so: finding something live is a legitimate outcome,
and this project's best material came from exactly that.

---

## Cross-references

- [../03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md](../03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md)
- [01_Complete_Lab_Demonstration_Script.md](01_Complete_Lab_Demonstration_Script.md)
- [../03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md](../03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md)
- [../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md](../13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md)
