# How to Modify LifeLink

Safe, practical modifications you can demonstrate — and the critical
distinction between a temporary browser change and a permanent source change.

> **The project is under an engineering freeze.** These exercises are for
> learning and for demonstrating understanding on a local copy. **Do not
> commit, deploy, or push anything.** Revert with `git checkout` when finished.

---

## 1. Browser DevTools changes versus source code changes

**This is a near-certain question and an easy trap.** If a teacher watches you
edit text in the Elements panel and asks "have you changed the website?", the
answer is **no**.

| | Browser DevTools | Source code |
|---|---|---|
| What changes | the page in **your** browser's memory | the file on disk |
| Who sees it | only you | everyone, after a rebuild and deploy |
| Survives refresh | **no** | yes |
| Needs a rebuild | no | yes (`npm run build`) |
| Needs a deploy | no | yes (upload to S3 + invalidate CloudFront) |
| Shows in `git diff` | **no** | yes |

**Say it like this:**
> "What I just did in the Elements panel only changed the page in my browser's
> memory. If I refresh, it's gone, and nobody else ever saw it. A real change
> means editing the file in `frontend/src`, rebuilding with Vite, uploading the
> new bundle to S3, and invalidating the CloudFront cache so the edge serves
> the new file instead of the cached one."

That last clause matters: **even after uploading to S3, CloudFront may serve
the old cached file** until the invalidation completes. That is why
`scripts/deploy_frontend.py` creates an invalidation as part of deploying.

---

## 2. Demonstration 1 — change a heading (easiest)

**Goal:** show that you can find and change what is on screen.

```bash
# 1. Find the text
grep -rn "Find blood near you" frontend/src/

# 2. Edit the file the grep names, e.g. frontend/src/features/home/HomePage.jsx

# 3. See it live — Vite hot-reloads
cd frontend && npm run dev     # http://localhost:5173

# 4. Prove it is a real change
git diff

# 5. Revert
git checkout frontend/src/features/home/HomePage.jsx
```

**What to explain:** Vite's dev server watches the file, rebuilds only the
changed module, and pushes it to the browser over a WebSocket — which is why
the change appears in under a second without a full reload. That is
development only; production is a static bundle.

---

## 3. Demonstration 2 — find the API request a button makes

**Goal:** connect a click to an HTTP request. This is the single most
convincing thirty seconds of a demo.

1. Open the live site and press **F12** -> **Network** tab.
2. Tick **Fetch/XHR** to filter out images and scripts.
3. Click **Find blood** with a location set.
4. Click the request that appears.

| Tab | What to point out |
|---|---|
| **Headers** | the full URL with `/dev/facilities?lat=...`, the method, and the **`Authorization: Bearer ...`** header if signed in |
| **Payload** / Query String | `lat`, `lon`, `radiusKm`, `bloodGroup`, `component` |
| **Response** | the `{data: [...], meta: {...}, correlationId: "corr-..."}` envelope |
| **Timing** | time to first byte — mostly the trip to Sydney |

**The move that impresses:** copy the `correlationId` from the response, then
open CloudWatch Logs Insights on `/aws/lambda/lifelink-dev-api` and search for
it. You have just traced a click to a server log line.

**Do not paste a real token anywhere.** Point at the header; do not copy its
value into a chat, a document, or a slide.

---

## 4. Demonstration 3 — trace a button to its backend handler

Five steps, all greps:

```bash
# 1. The visible text -> the component
grep -rn "Request hold" frontend/src/

# 2. The api. call inside that component
grep -n "api\." frontend/src/features/discovery/ReservationPanel.jsx

# 3. The method -> the route
grep -n "requestReservation" frontend/src/api/client.js
#   => POST /facilities/${facilityId}/reservations

# 4. The route -> the handler  (or use the mapping document)
grep -n "reservations" backend/src/handlers/api.py | head

# 5. The handler itself
grep -n "def request_reservation" -A 12 backend/src/handlers/api.py
```

See [04_API_And_Handler_Mapping.md](04_API_And_Handler_Mapping.md) for the
complete table, which turns step 4 into a lookup.

---

## 5. Demonstration 4 — read a backend validation rule

**Goal:** show that rules live somewhere readable.

```bash
# The freshness thresholds — the whole model in four constants
sed -n '1,65p' backend/src/domain/freshness.py

# The haversine formula
grep -n "def haversine_km" -A 14 backend/src/domain/geo.py

# The maximum search radius guard
grep -n "MAX_SEARCH_RADIUS_KM" -A 3 backend/src/domain/geo.py
```

**What to say about `freshness.py`:**
> "These four constants are the entire freshness model — six hours for fresh,
> twenty-four for aging, forty-eight before we call it outdated. Verification
> has its own separate seventy-two-hour window, because someone typing a number
> and someone independently checking it are different things. Note the function
> takes `now` as a parameter rather than calling the clock itself, so a test can
> put a record exactly on the six-hour boundary."

---

## 6. Demonstration 5 — modify a rule and watch tests fail

**Goal:** show that tests actually constrain behaviour. This is the most
persuasive demonstration available, because a passing test proves little and a
*failing* test proves the test was real.

```bash
# 1. Change a threshold
#    In backend/src/domain/freshness.py, set FRESH_MAX_HOURS = 6.0 -> 100.0

# 2. Run the tests
python -m pytest backend/tests/unit/test_freshness_and_eligibility.py -q
#    => failures, naming the boundary assertions

# 3. Revert
git checkout backend/src/domain/freshness.py
python -m pytest backend/tests/unit/test_freshness_and_eligibility.py -q
#    => passes
```

Try the same with the authorization matrix:

```bash
# Give DONOR a permission it should not have in backend/src/appcore/rbac.py
python -m pytest backend/tests/unit/test_authorization.py -q
git checkout backend/src/appcore/rbac.py
```

**What to say:**
> "Rather than show you tests passing, which doesn't prove much, I'll break a
> rule and show the tests catching it. I'll widen the fresh-data threshold from
> six hours to a hundred — and the boundary tests fail immediately and name the
> assertion. That's how we know the suite constrains behaviour rather than just
> exercising it."

---

## 7. Demonstration 6 — add a field to an API response (advanced)

This touches every layer, so it is the best test of whether you understand the
architecture.

To add `lastVerifiedByName` to the facility detail response:

| Step | File | Change |
|---|---|---|
| 1 | `backend/src/repositories/facility_repo.py` | ensure the attribute is read |
| 2 | `backend/src/handlers/api.py` `get_facility` | include it in the response dict |
| 3 | `backend/tests/unit/` | add a test asserting it appears |
| 4 | `frontend/src/features/discovery/FacilityDetailPage.jsx` | render it |
| 5 | `python scripts/generate_openapi.py` | regenerate the specification |
| 6 | `python -m pytest backend/tests -q && cd frontend && npm run test -- --run` | all 951 must still pass |

**Step 5 matters.** `generate_openapi.py --check` fails the build if
`docs/openapi.json` no longer matches the route table, so forgetting it is
caught rather than silently shipping stale documentation.

---

## 8. What not to modify, and why

| Do not touch | Why |
|---|---|
| `infrastructure/template.yaml` | A change here means a CloudFormation deployment. Some parameter changes **replace** resources — omitting `CognitoDomainPrefix` replaces the user pool domain |
| Live DynamoDB records | Hand-edited production data cannot be reproduced by re-seeding |
| `backend/src/repositories/emergency_repo.py` `append_event` | Deliberately append-only. Real history must accumulate |
| IAM roles and policies in the Console | Creates drift from the template. Change the template instead |
| Cognito settings in the Console | Same reason, and the password policy is asserted by a test that reads the template |
| `scripts/dedupe_request_events.py` predicate | It is a delete tool; widening its predicate risks removing genuine records |

**The general principle to state:** a setting controlled by CloudFormation
should be changed in the **template and redeployed**, not in the Console.
Changing it in the Console creates **drift**: the live resource no longer
matches the code that is supposed to define it, so the next deployment either
overwrites your change or fails confusingly. See
[../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md).

---

## 9. The commands that must still pass after any change

```bash
python -m pytest backend/tests -q                 # 657
cd frontend && npm run test -- --run              # 294
ruff check .                                      # clean
cd frontend && npm run lint                       # exit 0
cd frontend && npm run build                      # succeeds
cfn-lint infrastructure/template.yaml             # clean
python scripts/security_audit.py                  # passes
python scripts/generate_openapi.py --check        # matches the route table
```

---

## 10. Spoken answers

### "Can you make a change right now?"

> "Yes. Let me change this heading — I'll find it with grep, edit the JSX, and
> the dev server hot-reloads it in about a second. Then `git diff` shows it's a
> real file change, and I'll revert it. If I wanted that live, I'd rebuild with
> Vite, upload the bundle to S3, and invalidate the CloudFront cache —
> otherwise the edge keeps serving the old file."

### "How do you know your tests are meaningful?"

> "The honest way to show that is to break something. If I widen the
> fresh-data threshold from six hours to a hundred, the boundary tests fail and
> name the assertion. A green suite doesn't prove much on its own — and we
> learned that the hard way: two real defects in this project passed 900-plus
> tests and only showed up when we exercised the deployed system."

---

## 11. Cross-references

- [04_API_And_Handler_Mapping.md](04_API_And_Handler_Mapping.md)
- [02_Frontend_Code_Walkthrough.md](02_Frontend_Code_Walkthrough.md)
- [../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md](../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md)
- [../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md](../10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md)
