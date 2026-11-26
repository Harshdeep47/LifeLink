# S3 and CloudFront

How the website is hosted. Two S3 buckets, one CloudFront distribution, and a
bucket that is completely private even though the site is public.

---

## 1. What S3 is

**Simple version.** Unlimited file storage addressed by a key, reached over
HTTPS.

**The analogy, and its limit.** It is like a hard drive in the cloud — except
it is not a filesystem. There are **no real directories**. `assets/index.js`
is a *key* that happens to contain a slash; the Console displays slashes as
folders for convenience. That is why you cannot "rename a folder" in S3.

**Mechanism.** Objects are stored redundantly across multiple Availability
Zones within a Region, giving 99.999999999% (eleven nines) durability.
Buckets are **regional**, but bucket *names* are **globally unique** across all
AWS accounts — which is why ours have the account id appended.

**Why LifeLink uses it.** The React build is static files. Static files need a
file store, not a server. S3 is the cheapest, most durable option AWS sells.

---

## 2. The two buckets

| Bucket | Purpose | Contents |
|---|---|---|
| `lifelink-dev-frontend-426150327442` | the compiled React application | 13 files, ~few MB |
| `lifelink-dev-uploads-426150327442` | user uploads | currently unused |

Settings on both, verified live:

| Setting | Value |
|---|---|
| Default encryption | **SSE-S3 (`AES256`)** |
| S3 Bucket Keys | **disabled** |
| Block Public Access | **all four true** |
| Object ownership | `BucketOwnerEnforced` (ACLs disabled) |
| Versioning (frontend) | **Enabled** |
| Static website hosting | **not configured** |
| Lifecycle (uploads) | abort incomplete multipart uploads after 7 days |

Full treatment of every one of these, including the S3 Bucket Keys and KMS
question in detail:
[../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md)
§A.

**The short version of the Bucket Keys answer:** they are **disabled**, both
buckets use **SSE-S3** with no KMS at all, and enabling Bucket Keys would save
**nothing** because they only reduce **SSE-KMS** request costs. Independent
proof: `alias/aws/s3` has no key behind it in this account.

---

## 3. What CloudFront is

**Simple version.** A content delivery network: a global network of edge
locations that cache your files close to users.

**The analogy.** Instead of everyone travelling to one warehouse in Sydney,
copies are kept in local shops worldwide. A user in Punjab gets the file from a
nearby edge location, not from Sydney.

**Mechanism.** A request hits the nearest edge. If the file is cached there, it
is served immediately. If not, the edge fetches it from the **origin** (our S3
bucket), caches it, and serves it. Subsequent requests at that edge are local.

**CloudFront is a global service.** It is not "in" a Region. In the Console its
Region selector reads **Global**.

---

## 4. The distribution

| Setting | Value |
|---|---|
| Id | `E236QHMFXHDEDL` |
| Domain | `https://d324z37do52g8f.cloudfront.net` |
| Comment | "LifeLink dev frontend" |
| Price class | **`PriceClass_100`** |
| HTTP version | `http2and3` |
| IPv6 | enabled |
| Default root object | `index.html` |
| Origin | `lifelink-dev-frontend-426150327442.s3.ap-southeast-2.amazonaws.com` |
| Origin access | **OAC `E2QR15L70UVPZT`** |
| Viewer protocol policy | **`redirect-to-https`** |
| Allowed methods | `GET`, `HEAD`, `OPTIONS` |
| Compression | **true** |
| Cache policy | `658327ea-...` — AWS managed **CachingOptimized** |
| Custom error responses | **403 -> `/index.html` 200**, **404 -> `/index.html` 200**, TTL 10 s |
| Alternate domain names | none |
| Certificate | CloudFront default, `MinimumProtocolVersion: TLSv1` |
| WAF | **none** |
| Standard logging | **disabled** |

---

## 5. The three things worth understanding deeply

### A. Origin Access Control — a public site on a private bucket

**The question to anticipate: "if the bucket blocks all public access, how does
anyone see the website?"**

CloudFront signs its requests to S3 with SigV4 using an **Origin Access
Control**, and the bucket policy accepts only requests from this specific
distribution. So:

- The S3 URL directly -> **Access Denied**
- The CloudFront URL -> **200**

Two layers: Block Public Access means nothing *can* make the bucket public, and
the bucket policy means the only identity allowed to read it is our
distribution.

**OAC versus the legacy OAI:** OAI is the older mechanism and does not support
SSE-KMS or all HTTP methods. OAC is the current recommendation.

**Say this:**
> "The website is public but the bucket isn't. All four Block Public Access
> settings are on, and the bucket policy only allows reads from our specific
> CloudFront distribution, which signs its origin requests. If you took the S3
> URL for `index.html` and opened it directly you'd get Access Denied — only the
> CloudFront domain works. That means a misconfigured policy can't accidentally
> expose the bucket, and nobody can bypass CloudFront to run up our S3 bill."

### B. Custom error responses — why deep links work

**This is the most interesting setting on the distribution**, and its absence
would be a visible bug.

**The problem.** React Router resolves `/facilities/fac-123` in the browser.
But if a user pastes that URL, CloudFront asks S3 for an object literally named
`facilities/fac-123` — which does not exist.

**Why S3 returns 403, not 404.** With Block Public Access on and no
`s3:ListBucket` permission granted, S3 will not confirm whether an object
exists. A missing key yields **403 Access Denied**. Handling only 404 would
leave every deep link broken.

**The fix.** Both 403 and 404 map to `/index.html` with response code **200**.
The React app loads and routes the path itself.

**Why TTL 10 seconds?** So a genuinely new file appears promptly rather than
being masked by a cached error response.

**Demonstration:** open `https://d324z37do52g8f.cloudfront.net/find` directly
in a fresh tab. It works. Then explain that there is no file called `find` in
S3 at all.

### C. Cache invalidation — the step people forget

**Uploading a new file to S3 does not change what users see.** CloudFront keeps
serving its cached copy until the TTL expires.

```bash
aws cloudfront create-invalidation \
  --distribution-id E236QHMFXHDEDL --paths "/*" --profile lifelink
```

`scripts/deploy_frontend.py` does this automatically. The most recent
deployment's invalidation was `I76XJI99TM91I1THIOYYR9BXFN`, status
**Completed**.

**Why `index.html` is the only file that really needs it.** Vite emits
content-hashed filenames — the live bundle is `index-AW8_zfLM.js`. A new build
produces a *new filename*, so the cache cannot serve stale code; only
`index.html`, whose name never changes, needs invalidating. Using `/*` is
simply the safe default, and the first 1,000 invalidation paths per month are
free.

**Say this:**
> "Deploying the frontend is three steps, and people forget the third.
> Build with Vite, sync to S3, and then invalidate the CloudFront cache —
> because until you do, the edge keeps serving the old file and it looks like
> your deployment didn't work. Our deploy script does all three. Interestingly
> only index.html really needs invalidating: Vite puts a content hash in every
> asset filename, so a new build produces new filenames and stale JavaScript
> can't be served."

---

## 6. The honest gaps

| Gap | Assessment |
|---|---|
| **No WAF** | Defensible for a demo with synthetic data. A production health-adjacent system should have rate-based rules and AWS Managed Rules |
| **No access logging** | CloudFront can log every request; we do not. API Gateway access logging *is* on, so API traffic is logged — only static-file requests are not |
| **`MinimumProtocolVersion: TLSv1`** | Comes with the default CloudFront certificate. A custom domain with an ACM certificate would allow requiring TLS 1.2 |
| **No lifecycle rule on frontend versions** | Versioning is on with nothing expiring old versions. Negligible at a few MB; it would matter on a large bucket |

**Volunteering these is stronger than being shown them.**

---

## 7. Comparisons

### S3 + CloudFront versus hosting on EC2

| | S3 + CloudFront | EC2 with nginx |
|---|---|---|
| Server to manage | **none** | OS, nginx, TLS certificates, patching |
| Global performance | edge caching built in | one location unless you add a CDN |
| Cost | cents | dollars/month minimum, idle or not |
| Scaling | automatic | you configure it |
| HTTPS | AWS certificate, free | you manage certificates |
| Suits | static files | server-rendered applications |

### CloudFront versus direct S3 access

| | Direct S3 | Via CloudFront |
|---|---|---|
| HTTPS with a good certificate | website hosting is **HTTP only** | yes |
| Bucket privacy | must be **public** | stays private |
| Global latency | one Region | edge caching |
| Custom error handling | limited | full — this is what makes SPA routing work |
| Compression | no | yes |
| Cost | S3 request + transfer | often cheaper, since cache hits avoid S3 |

**That last row surprises people:** a CloudFront cache hit does not touch S3 at
all, so you pay CloudFront's cheaper transfer rate and no S3 request charge.

---

## 8. Failure scenarios

| Failure | Effect | Reality |
|---|---|---|
| One edge location fails | another serves it | automatic |
| S3 object deleted | site breaks | **versioning** allows recovery |
| S3 Region outage | site down | single-Region deployment; multi-Region is impossible in this account |
| Stale cache after deploy | users see old code | invalidation; content hashing limits exposure to `index.html` |
| Bucket policy misconfigured | 403 everywhere | would be caught immediately by any page load |
| Certificate expiry | — | AWS manages the default certificate |

---

## 9. Console demonstration

### S3
```
S3 -> Buckets -> lifelink-dev-frontend-426150327442
  Objects tab      -> index.html, assets/index-AW8_zfLM.js, ...
  Properties tab   -> Default encryption (SSE-S3), Versioning (Enabled)
  Permissions tab  -> Block public access (all On), Bucket policy (OAC), Object Ownership
```

**The best moment:** open the object `index.html`, copy its **S3 URL** (not the
presigned one), paste it in a new tab -> **Access Denied**. Then open the
CloudFront URL -> the site loads. That single contrast demonstrates OAC better
than any explanation.

### CloudFront
```
CloudFront -> Distributions -> E236QHMFXHDEDL
  General tab      -> domain name, price class, certificate
  Origins tab      -> the S3 origin with Origin access control
  Behaviors tab    -> redirect-to-https, CachingOptimized, GET/HEAD/OPTIONS
  Error pages tab  -> 403 -> /index.html 200, 404 -> /index.html 200
  Invalidations    -> the deployment history
```

**Do not** disable the distribution, edit the bucket policy, change Block
Public Access, or delete objects.

---

## 10. Spoken answers

### "Where is the website hosted?" — 30 seconds
> "The React app is compiled to static files and stored in a private S3 bucket,
> `lifelink-dev-frontend-426150327442`, in ap-southeast-2. It's served through
> CloudFront at `d324z37do52g8f.cloudfront.net`. The bucket has all public
> access blocked — CloudFront reaches it with an Origin Access Control, so S3
> only accepts requests signed by our distribution."

### 1–2 minutes
> "There are two parts. S3 holds the files: the Vite build output, a few
> megabytes, encrypted at rest with SSE-S3, with versioning on so a bad deploy
> can be rolled back. CloudFront serves them globally over HTTPS.
>
> The detail I'd point out is that the bucket is completely private even though
> the site is public. All four Block Public Access settings are on, and the
> bucket policy only allows reads from our specific CloudFront distribution,
> which signs its origin requests. If you opened the S3 URL directly you'd get
> Access Denied.
>
> The other setting worth knowing about is the custom error responses. Both 403
> and 404 are mapped to index.html with a 200 status, because React Router
> resolves paths in the browser — if you paste a facility URL, there's no file
> with that name in S3. It has to catch 403 as well as 404, because with public
> access blocked S3 returns 403 for a missing object rather than admitting it
> doesn't exist.
>
> And deploying means three steps: build, sync to S3, and invalidate the
> CloudFront cache. Skip the third and the edge keeps serving the old file."

---

## 11. Follow-up questions

**"Why not use S3 static website hosting?"**
> It needs the bucket to be public and only serves plain HTTP. CloudFront with
> an OAC gives us HTTPS with an AWS-managed certificate, global caching,
> compression, and a bucket that stays private. The only thing we lose is
> S3's own index/error document handling, which CloudFront's default root object
> and custom error responses replace.

**"What does PriceClass_100 mean, and would you change it?"**
> It restricts CloudFront to the cheapest set of edge locations — North
> America, Europe and some Asian locations. Users elsewhere still reach the
> site, just from a slightly further edge. Given our users are in India and our
> traffic is tiny, it is the right trade. If we had significant Indian traffic
> and measured the latency as a problem, moving to PriceClass_200 would add
> more Asian edges.

**"If someone found your S3 bucket name, what could they do?"**
> Nothing. The name is not a secret — it is in our CloudFormation outputs. All
> public access is blocked, ACLs are disabled, and the bucket policy only
> allows our CloudFront distribution. They could not list it, read it, or write
> to it.

**"How would you add a custom domain?"**
> Request an ACM certificate **in `us-east-1`** — CloudFront only accepts
> certificates from that Region, which catches people out — add the domain as an
> alternate domain name on the distribution, point a DNS record at the
> CloudFront domain, and then raise the minimum TLS version to 1.2, which the
> default certificate does not allow.

---

## 12. Cross-references

- [../09_PRACTICAL_AWS_DEMONSTRATIONS/02_Showing_S3_And_CloudFront.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/02_Showing_S3_And_CloudFront.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §A, §B
- [02_Regions_And_Availability_Zones.md](02_Regions_And_Availability_Zones.md)
- [13_AWS_Cost_And_Scalability.md](13_AWS_Cost_And_Scalability.md)
