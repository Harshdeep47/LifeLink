# Showing S3 and CloudFront

A click-by-click demonstration of how the website is hosted, built around one
contrast that proves the whole design.

---

## 1. The demonstration in one move

**The best thirty seconds available in this section:**

1. S3 -> `lifelink-dev-frontend-426150327442` -> Objects -> click `index.html`
2. Copy the **Object URL** (the plain S3 URL, not a presigned one)
3. Paste it into a new tab -> **Access Denied**
4. Open `https://d324z37do52g8f.cloudfront.net` -> **the site loads**

**What to say:**
> "Same file, two URLs. The S3 URL is denied and the CloudFront URL works. That's
> Origin Access Control: the bucket has all public access blocked, and its policy
> only accepts requests signed by our specific CloudFront distribution. So the
> site is public and the bucket is completely private — nobody can bypass
> CloudFront to read our files or run up our S3 bill."

**That single contrast demonstrates OAC better than any explanation.**

---

## 2. S3 — the walkthrough

```
S3 -> Buckets -> lifelink-dev-frontend-426150327442
```

### Objects tab

| What to show | Say |
|---|---|
| `index.html` and `assets/index-AW8_zfLM.js` | "the Vite build output — 13 files" |
| The hashed filename | "**that hash is why cache invalidation is easy** — a new build produces a new filename, so stale JavaScript can't be served. Only index.html, whose name never changes, needs invalidating" |

### Properties tab

| Setting | Value | Say |
|---|---|---|
| **Default encryption** | SSE-S3 (`AES256`), **Bucket Key: Disabled** | see §3 — the Bucket Keys answer |
| **Bucket Versioning** | **Enabled** | "a bad deploy or an accidental delete is recoverable" |
| Static website hosting | **not configured** | "deliberate — that needs a public bucket and only serves HTTP" |

### Permissions tab

| Setting | Value | Say |
|---|---|---|
| **Block public access** | **all four On** | "nothing can make this bucket public, even a misconfigured policy" |
| **Bucket policy** | grants `s3:GetObject` to the CloudFront service principal, conditioned on our distribution's ARN | "this is a **resource-based** policy — attached to the resource, naming who may use it" |
| **Object Ownership** | **Bucket owner enforced** | "ACLs are disabled entirely; access is policy-only" |

---

## 3. The S3 Bucket Keys question

**Expect it. The honest answer is not the flattering one.**

```
S3 -> the bucket -> Properties -> Default encryption
```

You will see **SSE-S3** and **Bucket Key: Disabled**.

| Question | Answer |
|---|---|
| Are Bucket Keys enabled? | **No** |
| Is SSE-KMS used on S3? | **No** — SSE-S3 (`AES256`) |
| Would enabling them save money? | **No.** They reduce **KMS request** costs, and we make no KMS requests from S3 |
| Proof | **`alias/aws/s3` has no key behind it** in this account |
| Where KMS **is** used | **DynamoDB** — all 12 tables, AWS-managed `aws/dynamodb` |

**Say this:**
> "Both buckets use SSE-S3 — AWS manages the keys, no KMS involved. Bucket Keys
> are disabled, and on this project enabling them would save nothing, because
> they only reduce KMS request costs and we don't use SSE-KMS on S3.
>
> What Bucket Keys actually do is worth explaining: with SSE-KMS, S3 calls KMS
> once per object operation — every upload and every download. That's a
> per-request charge and extra latency. A Bucket Key makes S3 fetch a
> short-lived bucket-level key and derive per-object keys locally, cutting KMS
> requests by up to about 99 percent. It only applies to new objects, though.
>
> I can show you independently that we never used SSE-KMS here: in KMS, the
> `alias/aws/s3` alias has no key behind it. AWS creates that key automatically
> on first use, so its absence proves it was never used. Our KMS usage is in
> DynamoDB."

**Do not claim Bucket Keys were enabled.** Full detail:
[CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §A1.

---

## 4. CloudFront — the walkthrough

```
CloudFront -> Distributions -> E236QHMFXHDEDL
```

| Tab | Show | Say |
|---|---|---|
| **General** | domain `d324z37do52g8f.cloudfront.net`, **PriceClass_100**, default certificate | "price class 100 limits us to the cheaper edge locations" |
| **Origins** | the S3 origin with **Origin access control** | "this is what signs CloudFront's requests to S3" |
| **Behaviors** -> Default (*) | **redirect-to-https**, CachingOptimized, GET/HEAD/OPTIONS, compress on | "any HTTP request gets a 301 to HTTPS" |
| **Error pages** | **403 -> `/index.html` 200** and **404 -> `/index.html` 200** | see §5 — the best setting here |
| **Invalidations** | the history, including `I76XJI99TM91I1THIOYYR9BXFN` | "that's the deployment record" |

---

## 5. The deep-link demonstration

**The most interesting CloudFront setting, and you can see its effect.**

1. Open `https://d324z37do52g8f.cloudfront.net/find` **directly** in a fresh
   tab. It works.
2. Then go to CloudFront -> **Error pages**.

**Say this:**
> "That URL worked — but there is no file called `find` in our S3 bucket. React
> Router resolves the path in the browser, which only works if the browser gets
> index.html first.
>
> Here's why it does. Both 403 and 404 are mapped to index.html with a **200**
> status. Without that, pasting a deep link would ask S3 for an object named
> `find`, which doesn't exist, and you'd get an error page.
>
> And it has to catch 403 as well as 404 — which surprises people. With Block
> Public Access on and no list permission, S3 won't admit whether an object
> exists; a missing key returns 403 Access Denied, not 404. If we only handled
> 404, every deep link would still break."

**That is a genuinely non-obvious detail**, and explaining it well signals real
understanding.

---

## 6. The deployment story

```
1. npm run build                          Vite -> static files with hashed names
2. aws s3 sync   ->  S3                    upload
3. create-invalidation  ->  CloudFront     so the edge stops serving the old file
```

`scripts/deploy_frontend.py` does all three.

**Say this:**
> "Deploying the frontend is three steps and people forget the third. Build,
> upload to S3, and invalidate the CloudFront cache — because until you do, the
> edge keeps serving the cached copy and it looks like your deployment didn't
> work. You can see our invalidation history on the distribution, which is
> effectively a deployment log."

---

## 7. The gaps — volunteer them

| Gap | Say |
|---|---|
| **No WAF** (`WebACLId` empty) | "defensible for a demo with synthetic data; for production I'd add rate-based rules via CloudFront" |
| **Access logging disabled** | "CloudFront can log every request and we don't. API Gateway logging **is** on, so API traffic is logged — only static-file requests aren't" |
| **`MinimumProtocolVersion: TLSv1`** | "that comes with the default CloudFront certificate. A custom domain with an ACM certificate would let us require TLS 1.2" |
| **No lifecycle rule on old versions** | "versioning is on with nothing expiring old versions — negligible at a few megabytes, but it would matter on a large bucket" |

---

## 8. Questions and answers

**"Why not S3 static website hosting?"**
> It needs the bucket to be public and only serves plain HTTP. CloudFront with
> an OAC gives HTTPS with an AWS-managed certificate, global caching,
> compression, and a bucket that stays private. The only thing we give up is
> S3's own index and error document handling, which CloudFront's default root
> object and custom error responses replace.

**"If someone knew your bucket name, what could they do?"**
> Nothing. The name isn't secret — it's in our CloudFormation outputs. All four
> public access blocks are on, ACLs are disabled, and the bucket policy only
> allows our specific CloudFront distribution. They couldn't list it, read it,
> or write to it.

**"How would you add a custom domain?"**
> Request an ACM certificate **in `us-east-1`** — CloudFront only accepts
> certificates from that Region, which catches people out — add the domain as an
> alternate domain name, point a DNS record at the CloudFront domain, and then
> raise the minimum TLS version to 1.2, which the default certificate doesn't
> allow.

**"What does 'eleven nines' durability mean?"**
> 99.999999999% annual durability for objects, achieved by replicating across at
> least three Availability Zones automatically. It's durability, not
> availability — it means the object won't be lost, not that it's always
> reachable. And it's also why we never choose an Availability Zone: S3 does it
> and doesn't give us the option.

---

## 9. Do not

| Action | Why |
|---|---|
| Edit the bucket policy | breaks the site immediately |
| Change Block Public Access | severe security change |
| Delete objects | breaks the site; versioning allows recovery but it is live surgery |
| Disable the distribution | breaks the site |
| Create an invalidation | harmless but pointless, and the first 1,000 paths/month are the free allowance |

---

## 10. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §A, §B
- [../04_AWS_COMPLETE_GUIDE/03_S3_And_CloudFront.md](../04_AWS_COMPLETE_GUIDE/03_S3_And_CloudFront.md)
- [01_AWS_Console_Navigation.md](01_AWS_Console_Navigation.md)
