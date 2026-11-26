# Regions and Availability Zones

Where LifeLink physically runs, and why it is not where you would expect.

---

## 1. The concepts

| Term | Definition |
|---|---|
| **Region** | A geographic area containing multiple isolated data centre clusters. Independent of every other Region |
| **Availability Zone (AZ)** | One or more discrete data centres within a Region, with independent power, cooling and networking, connected to the other AZs by low-latency links |
| **Edge location** | A CloudFront caching point of presence. Hundreds worldwide, far more numerous than Regions |
| **Global service** | Not tied to a Region at all: CloudFront, IAM, Route 53 |

**Why AZs exist.** A data centre can lose power or flood. Multiple AZs in one
Region let a service survive the loss of one building while staying close
enough for synchronous replication — typically under a couple of milliseconds
apart.

**Why Regions exist.** Latency (be near your users), data residency (laws about
where data may live), and isolation (a Region-wide failure should not spread).

---

## 2. Where LifeLink actually is

| Component | Location |
|---|---|
| Everything regional | **`ap-southeast-2`** — Asia Pacific (Sydney) |
| CloudFront | **Global** — edge locations, `PriceClass_100` |
| IAM | **Global** |

Verified: stack output `DeployedRegion = ap-southeast-2`, and the Cognito pool
id is literally `ap-southeast-2_Z91jyFm1d`.

### Where the AZs are, and why you never see them

LifeLink uses **no AZ-level configuration at all**, and that is not an
oversight — it is a property of the services chosen:

| Service | AZ behaviour |
|---|---|
| **S3** | Replicates across **at least three AZs** automatically. You cannot choose |
| **DynamoDB** | Replicates across **three AZs** automatically. You cannot choose |
| **Lambda** | AWS runs your function in multiple AZs automatically |
| **SQS** | Redundant across AZs automatically |
| **Cognito** | Managed, multi-AZ |

**This is the interesting answer to "which Availability Zone are you in?"**

> "We don't choose one, and that's the point of using managed serverless
> services. If we were running EC2 instances or an RDS database, we'd be
> selecting subnets in specific AZs and deciding whether to pay for a
> multi-AZ standby. S3 and DynamoDB replicate across at least three AZs
> automatically and don't let you choose — the redundancy is built in and we
> can't get it wrong. The trade is that we also can't tune it."

**That is a much better answer than naming an AZ**, and it demonstrates you
understand why the question has a different shape for serverless.

---

## 3. Why Sydney and not Mumbai

**Expect this question. The answer is a constraint, not a preference.**

LifeLink's data is about **Punjab, India**. The obvious Region on latency
grounds is `ap-south-1` (Mumbai). It was not available.

**Why:** the account is a **new AWS experience** project. All regional
resources must be created in the single Region derived from the account's
contact address, and resources cannot be created in other Regions.

### The measurable consequence

| Path | Approximate round trip from Punjab |
|---|---|
| Static site (HTML, JS, CSS) via CloudFront | **tens of milliseconds** — served from a nearby edge |
| API call to Sydney | **~150–200 ms** |
| Mumbai, if it were available | ~30–50 ms |

**So CloudFront already solves most of it.** The user interface feels local
because it is cached locally. Only API calls cross the ocean, and for a
coordination tool where a user searches a few times, that is noticeable but not
disqualifying.

### Say this
> "Everything regional is in ap-southeast-2, Sydney. That's a constraint of our
> account rather than a design choice — it's a new AWS experience project with a
> single assigned Region, so Mumbai wasn't available even though our data is
> about Punjab.
>
> CloudFront softens the impact a lot. The static site is cached at an edge
> location near the user, so the interface loads quickly; only API calls
> actually travel to Sydney, around 150 to 200 milliseconds each way, against
> maybe 30 to 50 for Mumbai. If I could move it, I would — and the move would
> be a parameter change and a redeploy, because everything is in one template."

**That last sentence is worth adding**, because it turns a limitation into
evidence that the infrastructure is portable.

---

## 4. Global versus regional — the table to memorise

| Service | Scope | Evidence you can point at |
|---|---|---|
| **CloudFront** | **Global** | the Console Region selector reads "Global" |
| **IAM** | **Global** | roles have no Region in their ARN |
| S3 | Regional | `...s3.ap-southeast-2.amazonaws.com` |
| API Gateway | Regional | `...execute-api.ap-southeast-2...` |
| Lambda | Regional | the ARN contains the Region |
| DynamoDB | Regional | the ARN contains the Region |
| **Cognito** | Regional | the pool id **starts with** `ap-southeast-2_` |
| SQS / SNS | Regional | the queue URL contains the Region |
| CloudWatch | Regional | log groups are per Region |
| Amazon Location | Regional | |
| Secrets Manager | Regional | |

### Two subtleties worth knowing

**S3 bucket names are global; buckets are regional.** The *namespace* is shared
across every AWS account on earth, which is why ours have the account id
appended — `lifelink-dev-frontend-426150327442`. The bucket and its data live
in Sydney.

**An IAM role ARN has an empty Region field:**
`arn:aws:iam::426150327442:role/...` — note the two colons. That is a quick way
to show a service is global.

---

## 5. What this account cannot do

| Not possible | Why |
|---|---|
| Cross-Region DynamoDB, S3 or RDS replication | denied by account policy |
| Multi-Region KMS keys | denied |
| CloudFormation StackSets | no multi-account or multi-Region deployment |
| Route 53 latency, geolocation or failover routing | not available |
| Lambda@Edge | excluded |
| Resources in a second Region | only the assigned Region |

**The one permitted exception:** AWS WAF and CloudWatch Logs resources *may* be
created in `us-east-1` when a global resource requires a dependency there.
LifeLink does not use this. **But it means a complete resource inventory should
check both `ap-southeast-2` and `us-east-1`** — ours has only the one Region
in use.

**One more exception worth knowing:** CloudFront is global and its actions are
performed in `us-east-1`. A CloudFront distribution may point at a resource in
the project Region, which is exactly what ours does. And if we ever added a
custom domain, the ACM certificate would have to be requested **in
`us-east-1`** — CloudFront accepts certificates only from there, which catches
people out.

---

## 6. If this were a production multi-Region system

**A good answer to "how would you make this highly available across
Regions?", given it is impossible here:**

> "Not possible in this account, but architecturally: DynamoDB global tables to
> replicate the data, a second copy of the stack in the other Region, and Route
> 53 latency-based routing to send users to the nearer one. CloudFront and S3
> would need origin failover.
>
> The hard part isn't the infrastructure, it's the data. Global tables are
> eventually consistent and resolve conflicts last-writer-wins, which is
> actively wrong for our reservation counters — two Regions could both accept a
> hold on the same units. So you'd have to pin all writes for a given facility
> to one Region and treat the other as read-only for that data. That's the
> conversation that matters, and it's more interesting than the Route 53 part.
>
> In this account none of it is available anyway: cross-Region replication,
> multi-Region keys, StackSets and latency routing are all denied by policy."

**That answer is strong because it identifies the real difficulty** rather than
listing services.

---

## 7. Console demonstration

| Step | What to show |
|---|---|
| 1 | The Region selector in the top-right reads **Asia Pacific (Sydney) ap-southeast-2** |
| 2 | CloudFormation -> `lifelink-dev` -> Outputs -> `DeployedRegion = ap-southeast-2` |
| 3 | Switch the Region to, say, Mumbai -> the resource lists are **empty** |
| 4 | Open CloudFront -> the selector now reads **Global** |
| 5 | Cognito -> the pool id begins `ap-southeast-2_` |

**Step 3 is the convincing one.** Switching Region and finding nothing proves
single-Region deployment better than any assertion — and it also demonstrates
the common beginner confusion of "my resources disappeared", which is really
just the wrong Region selected.

---

## 8. Spoken answers

### 20–30 seconds
> "Everything regional is in ap-southeast-2, Sydney. CloudFront and IAM are
> global services, so they aren't in a Region at all. We don't pick Availability
> Zones anywhere, because S3, DynamoDB and Lambda all replicate across multiple
> AZs automatically — that's a property of using managed serverless services
> rather than something we configured."

### 1–2 minutes

Combine §3 and §2:

> "One Region, ap-southeast-2. That's an account constraint — a new AWS
> experience project gets a single assigned Region from its contact address, so
> Mumbai wasn't an option even though our data is about Punjab. The cost is
> about 150 to 200 milliseconds per API call instead of 30 to 50. CloudFront
> absorbs most of the user-visible impact, because the static site is cached at
> an edge near the user; only API calls make the trip.
>
> On Availability Zones — we don't choose any, and that's deliberate rather than
> an omission. If we ran EC2 or RDS, we'd be picking subnets in specific AZs and
> deciding whether to pay for a multi-AZ standby. S3 and DynamoDB replicate
> across at least three AZs automatically and don't give us the choice, so the
> redundancy is built in and we can't misconfigure it. We also can't tune it,
> which is the other side of that bargain."

---

## 9. Follow-up questions

**"How many Availability Zones does ap-southeast-2 have?"**
> Three. But our resources don't reference them — DynamoDB and S3 spread across
> them for us. The honest answer is that I know the number, and I also know it
> isn't something this architecture exposes.

**"What if ap-southeast-2 goes down entirely?"**
> LifeLink would be unavailable. It's a single-Region deployment, and
> multi-Region isn't possible in this account — cross-Region replication and
> StackSets are denied by policy. CloudFront would keep serving cached static
> files for a while, so the shell of the site might load, but every API call
> would fail. For a production system I'd want global tables and a second
> stack, and the hard part there is the reservation counters, which can't
> tolerate last-writer-wins conflict resolution.

**"Is your data subject to Indian data residency rules?"**
> It's a fair question and the honest answer is that it would be a real problem
> with real data. Our data is entirely synthetic — 16 fictional facilities with
> validated-but-invented details — so there's no personal health information in
> Sydney. If this handled actual patient or donor data, storing it outside India
> would need legal review, and the Region constraint would become a blocker
> rather than a latency annoyance.

**"Why is CloudFront's price class 100 rather than all locations?"**
> It restricts us to the cheaper edge locations — North America, Europe and some
> Asian locations. Users elsewhere still reach the site, just from a slightly
> more distant edge. Given tiny traffic, it's the right trade; if I measured
> Indian latency as a real problem I'd move to PriceClass_200 for more Asian
> edges.

---

## 10. Cross-references

- [01_AWS_Introduction_For_LifeLink.md](01_AWS_Introduction_For_LifeLink.md)
- [../02_SYSTEM_ARCHITECTURE/04_AWS_Architecture.md](../02_SYSTEM_ARCHITECTURE/04_AWS_Architecture.md)
- [03_S3_And_CloudFront.md](03_S3_And_CloudFront.md)
- [13_AWS_Cost_And_Scalability.md](13_AWS_Cost_And_Scalability.md)
