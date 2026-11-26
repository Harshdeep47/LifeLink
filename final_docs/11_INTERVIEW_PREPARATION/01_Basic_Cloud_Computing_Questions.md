# Level 1 — Cloud Computing Fundamentals

Fundamentals, each answered with a LifeLink example. **The example is what
makes the answer yours rather than memorised.**

---

### Q1. What is cloud computing?

**Short:** Renting computing resources over the internet, on demand, paying for
what you use, instead of buying and running hardware.

**Detailed:** The useful part is not that the computers are elsewhere — it is
that you can create a database with one API call, destroy it just as easily,
and stop paying. That changes design: when a server took six weeks to procure,
you bought one big one and put everything on it. When it takes six seconds, you
use the right tool per job.

**LifeLink:** 66 resources from one template, created in minutes, costing about
$0.00 net/month (gross ~$0.45-0.50, offset by credits). Twelve small databases
rather than one large one, because creating
a table is trivial.

**Follow-up — "What are the drawbacks?"** Vendor lock-in — our SAM template and
DynamoDB access patterns are AWS-specific, and moving would be a rewrite, not a
redeploy. Less control: we cannot tune the database host. And cost can surprise
you — our NAT Gateway would have been $32/month, eighty times our whole bill,
for a thing we did not need.

---

### Q2. IaaS, PaaS, SaaS — and where does serverless fit?

| Model | You manage | Example |
|---|---|---|
| IaaS | OS, runtime, code | EC2 |
| PaaS | runtime config, code | Elastic Beanstalk |
| **FaaS / serverless** | **code only** | **Lambda** |
| SaaS | nothing — you use it | Gmail |

**LifeLink is entirely FaaS/serverless.** No server in this project is logged
into, patched or restarted.

**Follow-up — "So where does your code run?"** In a micro-VM AWS creates on
demand and destroys afterwards. There *is* a computer; we never see it, name it,
or pay for it when idle.

---

### Q3. What does "serverless" actually mean?

**Short:** You never provision or manage a server. You upload code; the provider
runs it on demand and charges per request.

**The four myths to correct:**

| Myth | Reality |
|---|---|
| "No servers" | There are. You never touch one |
| "Scales infinitely" | Up to a limit. **Ours is 10 concurrent executions** |
| "Always cheaper" | Cheaper when spiky or low. More per request at steady high volume |
| "No ops" | Less. You still own monitoring, permissions, cost, failure handling |

**LifeLink:** our concurrency limit of 10 is the constraint that shaped the
architecture — gateway throttle at 10/s, queue consumers capped at 2, one API
function rather than 58.

---

### Q4. Scaling up versus scaling out?

| | Up (vertical) | Out (horizontal) |
|---|---|---|
| Means | a bigger machine | more machines |
| Limit | the biggest available | effectively none |
| Downtime to change | usually | no |

**LifeLink:** Lambda scales **out** automatically. DynamoDB on-demand scales
out. We have no vertical dimension at all — except Lambda memory, which is
interesting: memory also allocates CPU, so raising it is vertical scaling of a
single invocation. 512 MB is where our workload stopped getting faster.

---

### Q5. Region, Availability Zone, edge location?

| Term | Definition | LifeLink |
|---|---|---|
| **Region** | a geographic area of isolated data centre clusters | **`ap-southeast-2`** |
| **Availability Zone** | one or more discrete data centres within a Region | **we never choose one** |
| **Edge location** | a CDN point of presence, hundreds worldwide | CloudFront, `PriceClass_100` |

**The good answer on AZs:** we do not choose one, and that is the point of
managed serverless services. S3 and DynamoDB replicate across at least three
AZs automatically and do not let you choose. With EC2 or RDS we would be picking
subnets and deciding on a multi-AZ standby.

**On the Region:** Sydney, for a Punjab project, because the account permits one
assigned Region. CloudFront absorbs most of the latency impact — only API calls
make the trip.

---

### Q6. CapEx versus OpEx?

**CapEx** is buying an asset up front; **OpEx** is an ongoing operational
charge. The cloud converts capital expenditure into operating expenditure.

**LifeLink:** zero capital cost, **$0.00 net** operating (gross ~$0.45-0.50,
offset by credits). The real benefit for a
student project is not the amount — it is that there was nothing to buy before
finding out whether the idea worked.

---

### Q7. High availability versus fault tolerance versus durability?

| Term | Means |
|---|---|
| **High availability** | stays reachable through a failure |
| **Fault tolerance** | keeps operating correctly despite a fault |
| **Durability** | data is not lost |

**LifeLink:** S3 gives **eleven nines durability** — your object will not be
lost. That is durability, not availability: it does not mean always reachable.
Within the Region we are highly available because DynamoDB and S3 span AZs. We
are **not** Region-fault-tolerant — a Region outage takes us down, and
multi-Region is denied by our account's policy.

---

### Q8. What is the shared responsibility model?

**AWS is responsible for security *of* the cloud; the customer for security *in*
the cloud.**

| AWS | Us |
|---|---|
| physical data centres | IAM policies |
| hypervisor, hardware | our application code |
| managed service patching | who may access what |
| service availability | our data and its encryption choices |

**LifeLink:** AWS patches the Python 3.14 runtime; we are responsible for nine
IAM roles, our authorization logic, and the fact that four log groups never
expire.

**Follow-up — "Where does the line move with serverless?"** Further in AWS's
favour. With EC2 we would own OS patching; with Lambda we do not. What remains
ours is permissions, application logic and configuration — which is exactly
where our four real defects were.

---

### Q9. What is a CDN and why use one?

**Short:** A geographically distributed network of caches that serve content
from close to the user.

**LifeLink:** CloudFront does four jobs — HTTPS with an AWS certificate, global
caching, keeping the S3 bucket private via OAC, and mapping 403/404 to
`index.html` so single-page-app deep links work.

**Follow-up — "Does it reduce cost or just latency?"** Both. A cache hit never
reaches S3, so you pay CloudFront's cheaper transfer rate and no S3 request
charge.

---

### Q10. Infrastructure as code — what and why?

**Short:** Describing infrastructure in a file that a tool applies, rather than
clicking in a console.

**LifeLink:** `infrastructure/template.yaml`, 1490 lines, one CloudFormation
stack. Reproducible, reviewable, diffable.

**The honest limitation, which makes this answer good:** a template only
governs the resources it **declares**. Four of our Lambda log groups were
auto-created by AWS, so the template's 30-day retention never reached them.
That is an **IaC coverage gap** — distinct from drift, where a declared resource
is changed outside the template.

---

### Q11. What is a changeset?

**Short:** A preview of what a CloudFormation deployment would change, before it
runs.

**LifeLink — and this is a real detail worth having:** we reviewed both backend
deployments by **diffing the deployed processed template against the
changeset's template**, not by reading the changeset summary. The summary listed
eleven entries because CloudFormation conservatively flags every resource that
merely *references* a Lambda. The real diff was only the six functions'
`Code.S3Key`.

**Follow-up — "Why does that matter?"** Because a summary that looks alarming
makes you either stop unnecessarily or stop reading. The diff told us nothing
structural was changing — no table property differed, no IAM policy differed.

---

### Q12. Multi-tenancy?

**Short:** One system serving multiple customers with their data isolated.

**LifeLink:** multi-tenant at the application level — many organizations share
the same tables, isolated by an organization scoping check applied centrally in
the authorization decorator. Twenty-two of our 39 permissions are
organization-scoped.

**Follow-up — "How do you know isolation holds?"** It is the fifth check in a
shared decorator, so it cannot be forgotten in one handler out of 58 — which is
how IDOR bugs normally happen. Verified live: the same admin gets 200 on their
own facility's reservation queue and 403 on another's.

---

### Q13. What is vendor lock-in, and are you locked in?

**Yes, substantially, and pretending otherwise would be dishonest.**

| Portable | Locked in |
|---|---|
| React frontend | SAM template — CloudFormation-specific |
| Python domain logic (**no AWS imports**) | DynamoDB access patterns and 24 indexes |
| the route table | Cognito token verification |
| | IAM policies |

**The mitigation we did have:** the `domain/` layer imports nothing from AWS, so
the business rules are portable. Moving clouds would mean rewriting the
repositories and the infrastructure, not the rules. That is a deliberate
architectural choice (ADR-0010), not an accident.

---

### Q14. How do you control cloud costs?

**LifeLink's actual answers:**

| Lever | Saving |
|---|---|
| **No VPC, so no NAT Gateway** | **~$32/month** — 80x our whole bill |
| On-demand DynamoDB | nothing idles |
| HTTP API over REST API | ~70% per call |
| arm64 Lambda | ~20% |
| AWS-managed KMS key | $1/month per key |
| PITR off on 4 ephemeral tables | backup storage |

**The honest failure:** four log groups with no retention. The dispatcher runs
every minute, so that one grows without bound. Trivial today, unbounded over
years — and it is the only part of the deployment whose cost grows without more
usage.

---

### Q15. What would you do differently on a second attempt?

**A real answer, not a humble-brag:**

> "Four things. TypeScript — one of our real bugs was an undefined variable it
> would have caught instantly. Declare a log group per Lambda in the template,
> so retention actually applies. Add the SNS alarm subscription on day one,
> because an alarm nobody's subscribed to is monitoring theatre. And add custom
> business metrics, which we have none of.
>
> The bigger one: I'd exercise the deployed system much earlier. Two of our four
> real defects were invisible to over nine hundred passing tests and only
> appeared when we used the real thing."

---

## Cross-references

- [02_AWS_Interview_Questions.md](02_AWS_Interview_Questions.md)
- [../02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md](../02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md)
- [../04_AWS_COMPLETE_GUIDE/01_AWS_Introduction_For_LifeLink.md](../04_AWS_COMPLETE_GUIDE/01_AWS_Introduction_For_LifeLink.md)
