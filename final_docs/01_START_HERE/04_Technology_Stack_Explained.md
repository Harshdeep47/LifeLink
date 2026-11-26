# Technology Stack Explained

Every technology in LifeLink, what it does, why it was chosen, and what the
alternative would have cost.

---

## 1. The whole stack

| Layer | Technology | Version |
|---|---|---|
| UI framework | **React** | 18 |
| Build tool | **Vite** | 6 |
| Routing | React Router | — |
| Maps | **MapLibre GL JS** | v6 |
| Frontend tests | Vitest + Testing Library | — |
| Linting | ESLint 9 (flat config) | — |
| Backend language | **Python** | **3.14** |
| Web framework | **none — deliberately** | — |
| JWT library | PyJWT + `cryptography` | — |
| AWS SDK | boto3 | — |
| Backend tests | pytest + **moto** | — |
| Linting | ruff | — |
| Database | **DynamoDB** | — |
| Auth | **Cognito** user pool | — |
| Compute | **Lambda** `python3.14` / `arm64` | — |
| API | API Gateway **HTTP API** | v2 |
| Hosting | **S3 + CloudFront** | — |
| Background | EventBridge Scheduler, DynamoDB Streams, SQS | — |
| Observability | CloudWatch, X-Ray | — |
| Infrastructure | **AWS SAM / CloudFormation** | — |

---

## 2. Frontend choices

### React 18

**What it is.** A JavaScript library for building user interfaces from
components — reusable pieces that each manage their own piece of the screen.

**Why.** Component reuse genuinely paid off here. `StatusBadges.jsx` exports
eight badge components used across every page, so "how we display availability"
is defined once. React's ecosystem also meant Testing Library was available,
which is how 294 frontend tests exist.

**The alternative.** Plain JavaScript would have worked for a smaller app, and
would have avoided a build step. With six role dashboards sharing badges,
cards, forms and error states, the component model earns its keep.

### Vite 6

**What it is.** A build tool: it bundles the source into static files, and runs
a development server with hot reload.

**Why it matters here specifically:** Vite emits **content-hashed filenames** —
the live bundle is `index-AW8_zfLM.js`. Because a new build produces a new
filename, CloudFront cannot serve stale JavaScript; only `index.html`, whose
name never changes, needs cache invalidation.

**That is a direct link between a build tool choice and a deployment property**,
and a good thing to mention.

**The alternative.** Create React App is deprecated; Webpack is slower to
configure and slower in development.

### MapLibre GL JS v6

**What it is.** An open-source map rendering library — the community fork of
Mapbox GL JS from before it became proprietary.

**Why.** It is genuinely open source with no API key or usage limit, and it
renders vector and raster tiles from any source.

**The critical thing to understand: MapLibre is a *renderer*. It does not
supply tiles, geocoding or routing.** Those come from somewhere else — which is
the whole reason ADR-0012 and ADR-0019 exist.

**A version detail that caused a real test:** MapLibre v6 removed default
exports, so only named imports work. `src/test/maplibreExports.test.js` pins
that contract so an upgrade cannot silently break the map.

### ESLint 9 flat config

> **Worth telling.** The project had a `lint` script from the start but **no
> working config**, so `npm run lint` failed with "ESLint couldn't find an
> eslint.config.js". A legacy `.eslintrc.json` existed and was **silently
> ignored** by ESLint 9, which uses flat config. It was deleted rather than left
> in place: *a config file that looks authoritative and changes nothing is worse
> than no config file, because someone will edit it and conclude the linter is
> broken.*
>
> Turning the linter on properly found a **real bug on day one** — an undefined
> variable inside an empty `catch`, which meant expired sessions were never
> cleared.

---

## 3. Backend choices

### Python 3.14

**Why.** ADR-0013: the local interpreter is 3.14, Lambda supports
`python3.14` as GA on Amazon Linux 2023 with deprecation in 2029, and matching
local to deployed removes a whole class of "works on my machine" problem.
Python 3.15 was avoided because it is public preview and outside the Lambda
SLA.

**The alternative.** Node.js would have meant one language across the stack,
which is a real advantage. Python won on readability for the domain logic and
on library maturity for the data work.

### No web framework — the most distinctive choice

**FastAPI, Flask and Mangum were all deliberately not used.**

**Why.** An API Gateway proxy integration gives you a JSON event and expects a
JSON response. A route table plus path matching is all that requires — about
255 lines in `backend/src/handlers/router.py`.

**The payoff that matters:** the **same route table drives the local
development server**, so local and deployed behaviour cannot diverge. A
framework would have added a dependency, cold-start weight, and a second
routing concept to keep in step.

**The honest cost.** No automatic request validation from type hints, no
generated OpenAPI document for free — which is why
`scripts/generate_openapi.py` exists, with a `--check` mode that fails the
build on drift.

**Say this:**
> "We deliberately didn't use a web framework. An API Gateway proxy integration
> hands you a JSON event and wants a JSON response — a route table plus path
> matching is all that needs, and it's about 255 lines. The payoff is that the
> same route table drives our local development server, so local and deployed
> behaviour can't drift. The cost is that we don't get request validation from
> type hints or a free OpenAPI document, so we have a script that generates the
> spec and a `--check` mode that fails the build if it goes stale."

### PyJWT + `cryptography`

**Why this matters more than it looks.** RS256 verification needs
`cryptography`, which ships as a **compiled binary wheel**. That single fact is
why:

- `sam build` **must not** be used on this Windows host — it would install the
  Windows wheel, which cannot load on an arm64 Linux function.
- `scripts/build_lambda_package.py --verify` exists, fetching
  `manylinux2014_aarch64` wheels explicitly: 505 files, 23.4 MB.

**A good example of a dependency choice driving a build process.**

### moto for integration tests

**What it is.** A library that mocks AWS services in-process.

**Why.** The 91 integration tests create real table shapes — from
`repositories/schema.py` — and run the real repository code against them, with
no AWS account, no network and no cost.

**The honest limitation to state:** moto is a *simulation*. It does not
perfectly reproduce DynamoDB, so an integration test passing is not proof the
deployed system works. **That is exactly why 56 live checks were run against
real AWS**, and why two defects still slipped through.

---

## 4. AWS choices, and the alternative each avoided

| Chosen | Alternative | Why chosen |
|---|---|---|
| **Lambda** | EC2 | no idle cost, no patching. Trade-off: cold starts, concurrency limit of 10 |
| **DynamoDB** | RDS | no connection pooling problem with Lambda; ~$0 idle. Trade-off: no joins, no ad-hoc queries |
| **S3 + CloudFront** | EC2 + nginx | no server, HTTPS free, global caching |
| **CloudFront + OAC** | public S3 website hosting | HTTPS, and the bucket stays private |
| **HTTP API** | REST API | ~70% cheaper. Trade-off: no request validation, no WAF, no caching |
| **Cognito** | custom auth | not storing passwords is the single biggest risk removed |
| **EventBridge Scheduler** | EventBridge Rules | timezones, one-time schedules, retry policy |
| **SQS** | SNS alone | messages persist until processed |
| **SAM** | raw CloudFormation | serverless shorthand; expands into functions, roles and permissions |
| **AWS-managed KMS keys** | customer-managed | free. Trade-off: cannot revoke or control rotation |

### The one worth explaining at length: DynamoDB over RDS

**The two reasons that actually decided it:**

1. **Connection model.** Lambda scales to many concurrent executions, and each
   one wanting a database connection is a genuine problem with RDS — you end up
   adding RDS Proxy to solve it. DynamoDB is stateless HTTPS: nothing to pool.
2. **Idle cost.** An RDS instance bills per hour whether anyone uses it.
   DynamoDB on-demand costs effectively nothing at our volume.

**What it cost us:** no joins and no ad-hoc querying. We designed 24 indexes up
front, and a query nobody anticipated is expensive.

---

## 5. What is deliberately absent

| Absent | Why |
|---|---|
| **Step Functions** | **Zero in the template.** No workflow needs durable state between steps |
| TypeScript | would have caught some bugs; the project is small and tests cover the logic. A fair criticism |
| Redux / Zustand | React context plus four hooks is sufficient |
| axios / React Query | `fetch` plus ~20 lines in one file does what we need |
| Tailwind / a CSS framework | plain CSS with design tokens in `styles/tokens.css` |
| Docker | ADR-0011 — local development without it |
| ORM | repositories are thin and explicit |
| GraphQL | 58 REST routes with known shapes |
| VPC | not needed, and a NAT Gateway would cost ~$32/month |

**On TypeScript, give the honest answer:**
> "I'd use TypeScript if I were starting again. It would have caught a class of
> bug for free — and one of our real defects was an undefined variable, which
> TypeScript would have flagged immediately. What we did instead was put the
> logic with real decisions in it into plain modules with their own tests, which
> gets you correctness but not the editor feedback."

---

## 6. Versions pinned, and why

| Pinned | Where |
|---|---|
| `python3.14` | `infrastructure/template.yaml` Runtime + the local virtualenv |
| `arm64` | template Architectures |
| Python dependencies | `manylinux2014_aarch64` wheels via `build_lambda_package.py` |
| npm dependencies | `frontend/package-lock.json` |
| MapLibre named exports | pinned by a **test**, not by config |

**That last row is the interesting one.** A test can pin a contract that a
version number cannot — `package.json` constrains the version, but only a test
proves the API shape you rely on still exists.

---

## 7. Spoken answers

### "What's your tech stack?" — 30 seconds
> "React 18 with Vite on the frontend, Python 3.14 on Lambda for the backend,
> DynamoDB for data, Cognito for authentication, and S3 with CloudFront for
> hosting — all defined in one AWS SAM template. The choice people ask about is
> that we didn't use a web framework on the backend: an API Gateway proxy
> integration just needs a route table, and using our own means the same table
> drives our local development server, so local and deployed can't diverge."

### 1–2 minutes
> "The frontend is React 18 built with Vite. One Vite detail matters for
> deployment: it puts a content hash in every asset filename, so a new build
> produces new filenames and CloudFront can't serve stale JavaScript — only
> index.html needs cache invalidation.
>
> The backend is Python 3.14 on arm64 Lambda, with no web framework. An API
> Gateway proxy integration hands you a JSON event and wants JSON back, so a
> route table and path matching is all that's needed — and because the same
> table drives our local server, local and deployed behaviour can't drift. The
> cost is no free request validation and no free OpenAPI document, so we
> generate the spec with a script that has a `--check` mode to fail the build on
> drift.
>
> One dependency drove our whole build process. RS256 token verification needs
> the `cryptography` library, which is a compiled binary. That means we can't
> use `sam build` on Windows — it would install a Windows wheel that can't load
> on an arm64 Linux function. So there's a script that fetches the right
> manylinux arm64 wheels explicitly.
>
> If I were starting again I'd use TypeScript. One of our real bugs was an
> undefined variable that TypeScript would have caught immediately."

---

## 8. Cross-references

- [../02_SYSTEM_ARCHITECTURE/05_Architecture_Decisions.md](../02_SYSTEM_ARCHITECTURE/05_Architecture_Decisions.md)
- [../03_REPOSITORY_AND_CODE/02_Frontend_Code_Walkthrough.md](../03_REPOSITORY_AND_CODE/02_Frontend_Code_Walkthrough.md)
- [../03_REPOSITORY_AND_CODE/03_Backend_Code_Walkthrough.md](../03_REPOSITORY_AND_CODE/03_Backend_Code_Walkthrough.md)
- [../04_AWS_COMPLETE_GUIDE/](../04_AWS_COMPLETE_GUIDE/) — each AWS service in depth
