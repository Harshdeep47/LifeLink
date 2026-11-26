# IAM — Complete Guide

**One of the two highest-priority topics.** Every role, trust policy and
permission in LifeLink, read from the live account.

---

## 1. What IAM is

**Simple version.** IAM (Identity and Access Management) decides **who** can do
**what** to **which** AWS resource.

**The analogy, and its limit.** IAM is like a building's keycard system: each
card opens only certain doors. The analogy breaks down in a useful way —
in AWS, cards are usually **not given to people at all**. They are given to
*services*, temporarily, and expire after a few hours. That is the part worth
understanding.

**Mechanism.** Every AWS API call is signed with credentials. Before executing
it, AWS evaluates every applicable policy and decides allow or deny.

---

## 2. The vocabulary, with LifeLink examples

| Term | Meaning | In LifeLink |
|---|---|---|
| **User** | A long-lived identity with a password or access keys | **We have none.** Deliberately |
| **Group** | A collection of users | none |
| **Role** | An identity something *assumes* temporarily, receiving short-lived credentials | **9 roles** |
| **Trust policy** | Who is allowed to assume this role | `lambda.amazonaws.com`, `scheduler.amazonaws.com`, `cognito-identity.amazonaws.com` |
| **Permissions policy** | What the role may do | 2 managed + 16 inline on the API role |
| **Managed policy** | Reusable, AWS- or customer-owned | `AWSLambdaBasicExecutionRole` |
| **Inline policy** | Embedded in one role, cannot be reused | all our per-table policies |
| **Resource-based policy** | Attached to the *resource*, naming who may use it | our S3 bucket policy |
| **Service principal** | An AWS service acting as an identity | `lambda.amazonaws.com` |
| **Least privilege** | Grant only what is needed | one policy per table |
| **Explicit deny** | A `Deny` that cannot be overridden by any `Allow` | our SCPs |

### Why there are no IAM users

**A near-certain question.** Three reasons:

1. **Lambda does not need one.** A function assumes its execution role
   automatically and receives temporary credentials that rotate.
2. **Human access is managed.** This is a new AWS experience account: people
   are invited by email and permissions are managed by AWS, not by creating IAM
   users.
3. **Access keys leak.** A long-lived access key in a config file or a git
   commit is the single most common cause of AWS compromise. No users means no
   keys to leak.

**Say this:**
> "We have zero IAM users and zero access keys. Lambda assumes its execution
> role automatically and gets temporary credentials that rotate, and human
> access to the account is through a managed sign-in rather than IAM users. The
> most common way AWS accounts get compromised is a long-lived access key
> committed to a repository — if you never create one, that can't happen."

---

## 3. Role versus Cognito — the comparison teachers ask for

**These are completely different systems and confusing them is a classic
mistake.**

| | IAM | Cognito user pool |
|---|---|---|
| Who it identifies | AWS services and AWS account principals | **application end users** |
| Credentials | temporary AWS credentials (SigV4) | **JWTs** |
| Who checks | the AWS API | **our Lambda code** |
| Example | "can this Lambda read the inventory table?" | "is this person a signed-in donor?" |
| Where the rules live | IAM policies | `backend/src/appcore/rbac.py` |
| Scale | ~9 roles | 11 users, could be millions |

**Say this:**
> "They answer different questions. IAM controls what our AWS *services* can do
> — can this Lambda function read this DynamoDB table. Cognito identifies our
> *application users* and gives them a JWT. A blood bank admin has no IAM
> identity at all; they have a Cognito token, and our own code decides what
> they may do.
>
> There's exactly one place they meet: the identity pool, which can exchange a
> Cognito token for temporary IAM credentials. We deployed that for map tiles —
> `MapReaderRole` — though we ended up not using it."

---

## 4. All nine roles

| Logical name | Physical name | Trusted principal |
|---|---|---|
| `ApiFunctionRole` | `lifelink-dev-ApiFunctionRole-vBxc6ik9DHz7` | `lambda.amazonaws.com` |
| `PriorityDispatcherRole` | `lifelink-dev-PriorityDispatcherRole-DdW8sTj2Bu1q` | `lambda.amazonaws.com` |
| `ScheduledMaintenanceRole` | `lifelink-dev-ScheduledMaintenanceRole-UZjM6YOVbvAw` | `lambda.amazonaws.com` |
| `OutboxPublisherRole` | `lifelink-dev-OutboxPublisherRole-2e8515GoKwU8` | `lambda.amazonaws.com` |
| `WorkQueueWorkerRole` | `lifelink-dev-WorkQueueWorkerRole-SNaAEIBsML8d` | `lambda.amazonaws.com` |
| `NotificationWorkerRole` | `lifelink-dev-NotificationWorkerRole-AaXaqZVKLZFl` | `lambda.amazonaws.com` |
| `PriorityDispatcherEveryMinuteRole` | `lifelink-dev-PriorityDispatcherEveryMinuteRole-XUMrzUO2505M` | **`scheduler.amazonaws.com`** |
| `ScheduledMaintenanceEveryTenMinutesRole` | `lifelink-dev-ScheduledMaintenanceEveryTenMinutesRol-bmZJfsq8imdQ` | **`scheduler.amazonaws.com`** |
| `MapReaderRole` | `lifelink-dev-MapReaderRole-bmIqIg8VSi3H` | **`cognito-identity.amazonaws.com`** (federated) |

**Why the random suffix?** CloudFormation generates it when the template does
not specify a role name, which guarantees uniqueness and avoids a name
collision on redeployment. The cost is that the names are not memorable — so
search for `lifelink-dev` in the IAM Console rather than typing a full name.

**One function, one role.** Six functions, six execution roles. That is what
makes least privilege possible: a shared role would be the union of everything
every function needs.

---

## 5. The trust policy — the half people forget

A role has **two** policies and they answer different questions:

| Policy | Question |
|---|---|
| **Trust policy** | **Who may assume this role?** |
| Permissions policy | What may it do once assumed? |

### The standard Lambda trust policy

```json
{ "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]}
```

Read it literally: *the Lambda service is allowed to call `sts:AssumeRole` on
this role.* That is how the function gets credentials — the service assumes the
role on its behalf and injects temporary credentials into the execution
environment.

### The Scheduler trust policy

```json
{ "Effect": "Allow",
  "Principal": { "Service": "scheduler.amazonaws.com" },
  "Action": "sts:AssumeRole" }
```

Its permission policy is a single statement:

```json
{ "Effect": "Allow",
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:ap-southeast-2:426150327442:function:lifelink-dev-dispatcher" }
```

**One action, one named function.** This is the cleanest least-privilege
example in the project, and it is a good one to show first because it is three
lines and obviously minimal.

### The federated trust policy — `MapReaderRole`

```json
{ "Effect": "Allow",
  "Principal": { "Federated": "cognito-identity.amazonaws.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": { "StringEquals": {
      "cognito-identity.amazonaws.com:aud": "ap-southeast-2:31685707-e3c3-4aa0-b4ca-b753c70b8688" }}}
```

Three differences from the others, all worth pointing out:

1. **`Federated`**, not `Service` — the caller is an external identity provider.
2. **`sts:AssumeRoleWithWebIdentity`**, not `sts:AssumeRole` — the variant that
   accepts a web identity token.
3. **A condition on `aud`** restricting it to *our* identity pool. Without that
   condition, **any** Cognito identity pool in **any** AWS account could assume
   this role. That is the confused-deputy problem, and the condition is the
   defence.

Its permissions:

```json
{ "Effect": "Allow",
  "Action": ["geo:GetMapTile", "geo:GetMapStyleDescriptor",
             "geo:GetMapSprites", "geo:GetMapGlyphs"],
  "Resource": "arn:aws:geo:ap-southeast-2:426150327442:map/lifelink-dev-map" }
```

Four read-only actions on one map. No write actions, no other resource.

**Honest note:** this role is **deployed but never assumed.** ADR-0019 replaced
the Amazon Location browser-tile path with OpenStreetMap, so nothing in the
frontend uses the identity pool. It is leftover infrastructure from a
superseded decision, and it costs nothing.

---

## 6. The API function role — least privilege at scale

Two managed policies:

| Managed policy | Grants |
|---|---|
| `AWSLambdaBasicExecutionRole` | `logs:CreateLogGroup`, `CreateLogStream`, `PutLogEvents` |
| `AWSXrayWriteOnlyAccess` | X-Ray trace segments |

**This is why a Lambda can write logs at all** — and why a function with a
hand-written role that omits it appears to run but produces no logs.

Then **16 inline policies**, one per table plus three more:

```json
{ "Effect": "Allow",
  "Action": ["dynamodb:GetItem","dynamodb:DeleteItem","dynamodb:PutItem",
             "dynamodb:Scan","dynamodb:Query","dynamodb:UpdateItem",
             "dynamodb:BatchWriteItem","dynamodb:BatchGetItem",
             "dynamodb:DescribeTable","dynamodb:ConditionCheckItem"],
  "Resource": [
    "arn:aws:dynamodb:ap-southeast-2:426150327442:table/lifelink-dev-inventory",
    "arn:aws:dynamodb:ap-southeast-2:426150327442:table/lifelink-dev-inventory/index/*"
  ]}
```

**Two details worth pointing out:**

- The **second ARN ending `/index/*`** is required. Querying a GSI needs
  permission on the index as a separate resource. Omit it and every GSI query
  fails with Access Denied while table reads work perfectly — a confusing
  failure that is worth knowing about.
- Each policy names **one** table. The API role has 16 because the API touches
  everything; a worker role has three or four.

Beyond DynamoDB:

| Policy | Grants |
|---|---|
| `...Policy11` | `dynamodb:PutItem`, `Query` on `audit` **only** — plus the KMS statement |
| `...Policy12`, `...Policy13` | `sqs:SendMessage*` on the two queues |
| `...Policy14` | `geo:SearchPlaceIndexForText`, `SearchPlaceIndexForPosition`, `CalculateRoute` on the place index and route calculator |
| `...Policy15` | `cognito-idp:AdminGetUser`, `ListUsers` on **our pool only** |

Note the audit policy: `PutItem` and `Query` but **no `UpdateItem` and no
`DeleteItem`**. The API can append audit records and read them back, but
**cannot modify or delete them.** That is an audit trail enforced by
permissions, not by convention.

---

## 7. The `Resource: "*"` — be ready for this

```json
{ "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "*",
  "Condition": { "StringEquals": {
      "kms:ViaService": "dynamodb.ap-southeast-2.amazonaws.com" }}}
```

It appears in `ApiFunctionRole` and `ScheduledMaintenanceRole`.

**Why a wildcard was necessary.** DynamoDB encrypts with the AWS-managed key
`alias/aws/dynamodb`. That key's ARN contains a key id AWS generated
(`95806067-…`) which is **not known when the
template is written**. CloudFormation cannot reference it, so the policy cannot
name it.

**Why it is nevertheless constrained.** The `kms:ViaService` condition means
these actions can only be exercised **through DynamoDB in this Region**. The
role cannot call `kms:Decrypt` directly to decrypt anything else — not an S3
object, not a secret, not another service's data. If the function tried, the
condition would fail and KMS would deny it.

**Do NOT say "it's safe because it's just KMS."** Say:

> "There's exactly one wildcard resource in our policies, and I can explain
> both why it's there and why it's constrained. DynamoDB encrypts with the
> AWS-managed `aws/dynamodb` key, and that key's ARN contains an id AWS
> generates — it isn't known when we write the template, so we can't name it.
>
> But the statement has a `kms:ViaService` condition pinning it to
> `dynamodb.ap-southeast-2.amazonaws.com`. So the permission can only be used
> *through* DynamoDB. If the function tried to call KMS directly to decrypt
> something else, the condition fails and it's denied. It's scoped by condition
> instead of by resource, which is the right tool when the resource ARN isn't
> knowable in advance.
>
> If I wanted to remove the wildcard entirely, I'd switch the tables to a
> customer-managed KMS key — then I'd have a known ARN to name, at about a
> dollar a month per key."

**That answer is worth more than the wildcard costs you.**

---

## 8. Read-only versus read-write — the evidence of real least privilege

The best demonstration is a role that **cannot** do something.

### `PriorityDispatcherRole`

| Table | Actions |
|---|---|
| `emergency` | **full** read/write |
| `notifications` | **full** read/write |
| `inventory` | **read only** — `GetItem`, `Scan`, `Query`, `BatchGetItem`, `DescribeTable` |
| `facilities` | **read only** |
| `organizations` | **read only** |
| SQS `notifications` | `SendMessage*` |

**The dispatcher reads stock levels to rank providers, and cannot modify
stock.** Not because the code does not try, but because the permission does not
exist. Even a bug or a compromise could not alter inventory through this role.

### `ScheduledMaintenanceRole`

Full access to seven tables, **read-only** on `organizations`, and on `audit`
**`dynamodb:PutItem` only** — append, never read, never delete.

### `NotificationWorkerRole` — the narrowest

| Table | Actions |
|---|---|
| `notifications` | full |
| `idempotency` | full |
| `organizations` | **read only** |

Three tables. Nothing else in the account. Plus
`AWSLambdaSQSQueueExecutionRole` for queue polling.

### Say this
> "The clearest evidence that our least privilege is real rather than
> decorative is the dispatcher role. It needs to read inventory to rank which
> blood banks to contact first, so it has read actions on the inventory table —
> Get, Query, Scan — and no write actions at all. It cannot modify stock. Not
> because the code doesn't try, but because the permission isn't there. Same
> pattern on the maintenance role: on the audit table it has PutItem only, so it
> can append audit records and cannot alter or delete one."

---

## 9. Resource-based policy — the S3 bucket policy

A **resource-based** policy is attached to the resource and names who may use
it, which is the mirror image of an identity-based policy.

The frontend bucket's policy grants `s3:GetObject` to the CloudFront service
principal, conditioned on the source ARN being **our** distribution. So:

- CloudFront can read the bucket.
- No other CloudFront distribution can, even in another AWS account.
- No IAM principal can, unless separately granted.

**INSPECT:** `S3 -> lifelink-dev-frontend-426150327442 -> Permissions
-> "Bucket policy"`.

**Why a resource policy rather than giving CloudFront a role?** Because
CloudFront is not something you attach a role to. The resource has to say who
may read it. Cross-account access is the other main use: an IAM policy in
account A cannot grant access to a bucket in account B on its own — the bucket
in B must also allow it.

---

## 10. How AWS evaluates a policy

Simplified, in order:

1. **Explicit `Deny` anywhere?** -> **denied**, full stop. Nothing overrides it.
2. **Organizations SCP allows the action?** -> if not, **denied**.
3. **An `Allow` in an applicable policy?** -> if not, **denied** (implicit deny).
4. Otherwise -> **allowed**.

**Two things to take from this:**

**Default deny.** No policy means no access. You never need to write a `Deny`
to prevent something you have not allowed.

**Explicit deny wins.** This is how our account's **service control policies**
work: an SCP is an explicit deny at the organization level that no IAM policy
can override. That is exactly why `AWS::Location::APIKey` creation failed —
the SCP denies it regardless of our permissions, which is also why ADR-0019
exists.

### Say this
> "Evaluation is explicit deny first, then the organization's service control
> policies, then whether anything allows it — and if nothing does, it's denied
> by default. That default-deny is why we never write Deny statements: not
> granting something is already enough.
>
> We hit the explicit-deny case for real. Our account has a service control
> policy that denies creating an Amazon Location API key. It doesn't matter what
> our IAM permissions say — an SCP deny can't be overridden, so the resource
> creation failed and we changed the design. That's ADR-0019."

---

## 11. Console demonstration

```
IAM -> Roles -> search "lifelink-dev"      (9 results)
```

Open `lifelink-dev-ApiFunctionRole-vBxc6ik9DHz7`:

| Tab | What to show |
|---|---|
| **Permissions** | 2 managed + 16 inline policies. Expand one and switch to the **JSON** view |
| **Trust relationships** | `lambda.amazonaws.com` + `sts:AssumeRole` — "this is *who may become* this role" |
| **Access Advisor** | which services the role has actually used — evidence for tightening |
| **Last activity** | the role is in use |

Then open `lifelink-dev-PriorityDispatcherEveryMinuteRole-XUMrzUO2505M`
for the contrast: **one** policy, **one** action, **one** resource.

**Access Advisor is the underused tab.** It shows services the role was granted
but has not used — which is how you tighten a policy with evidence instead of
guesswork. Mentioning it signals real familiarity.

**Do not** create users, attach policies, or edit anything during an
evaluation. Everything here is read-only and controlled by the template.

---

## 12. Spoken answers

### 20–30 seconds
> "We have nine IAM roles and zero IAM users — no access keys exist to leak.
> Each Lambda function has its own execution role, and each role gets a separate
> inline policy per DynamoDB table, scoped to that table's ARN and its indexes.
> Where a function only reads, it only has read actions: the dispatcher can read
> inventory to rank blood banks and physically cannot modify it."

### 1–2 minutes
> "IAM is about what our AWS services can do, as distinct from Cognito, which
> identifies our application users. A blood bank admin has no IAM identity —
> they have a JWT, and our code decides what they can do.
>
> We have nine roles. Six are Lambda execution roles, two let EventBridge
> Scheduler invoke a function, and one is a federated role for Cognito identity
> pool credentials. Each role has two policies that answer different questions:
> the trust policy says who may assume it, and the permissions policy says what
> it may then do. People tend to forget the trust policy, but it's the more
> security-critical half — our federated role has a condition pinning it to our
> specific identity pool, and without that condition any Cognito identity pool
> in any AWS account could assume it.
>
> The API role has sixteen inline policies, one per table. That's deliberate:
> one broad policy would be easier to write but impossible to audit. And there's
> exactly one wildcard resource, for KMS, because DynamoDB's AWS-managed key has
> an ARN we can't know at template time — but it's constrained with a
> `kms:ViaService` condition so it can only be used through DynamoDB."

---

## 13. Follow-up questions

**"Could you tighten these policies further?"**
> Yes, in two places. The API function's role is the union of all 58 routes'
> needs, so a route that only reads facilities runs with permission to write
> inventory. Splitting the API into per-feature functions would narrow that, at
> the cost of more cold starts against a concurrency limit of ten. And the
> DynamoDB action list is a standard ten-action set; some tables are only ever
> read by the API and could drop the write actions. Access Advisor would tell
> us which ones with evidence.

**"What if a Lambda function were compromised?"**
> The attacker gets that function's role, with temporary credentials. From the
> API role they could read and write our twelve tables and send to our two
> queues. They could **not** create resources, touch IAM, read S3, or decrypt
> anything outside DynamoDB — the KMS statement's `ViaService` condition blocks
> that. They also could not escape the account's SCPs. The realistic damage is
> our own data, which is why the audit table is append-only from that role.

**"Why inline policies instead of managed ones?"**
> Inline policies are deleted with the role, so there is no orphaned policy left
> behind when a function is removed, and SAM generates them from the template
> automatically. Customer-managed policies would be better if several roles
> shared the same permission set — ours deliberately do not, because sharing
> would mean granting each function the union of their needs.

**"Is `Resource: '*'` ever acceptable?"**
> Only when the resource cannot be named — and then it must be constrained
> another way, by a condition. Ours is pinned with `kms:ViaService`. An
> unconstrained `Action: "*"` on `Resource: "*"` is administrator access and is
> never acceptable in an execution role.

---

## 14. Cross-references

- [../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md](../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/06_Showing_IAM_In_Action.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/06_Showing_IAM_In_Action.md)
- [07_Cognito_Complete_Guide.md](07_Cognito_Complete_Guide.md)
- [12_AWS_Security_And_Permissions.md](12_AWS_Security_And_Permissions.md)
- [../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md](../09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) §I
