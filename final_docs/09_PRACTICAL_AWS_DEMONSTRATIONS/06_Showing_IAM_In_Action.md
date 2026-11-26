# Showing IAM in Action

The demonstration built around a role that **cannot** do something — which is
the only convincing way to show least privilege.

---

## 1. The opening claim

```
IAM -> Roles -> search "lifelink-dev"      ->  9 roles
IAM -> Users                               ->  (none for this project)
```

**Say this:**
> "Nine IAM roles and zero IAM users. There is no access key anywhere in this
> project — which matters, because a long-lived access key committed to a
> repository is the single most common way AWS accounts get compromised. If you
> never create one, that can't happen.
>
> Lambda doesn't need a user: the service assumes the function's execution role
> automatically and injects temporary credentials that rotate."

---

## 2. The nine roles

| Role | Trusted principal |
|---|---|
| `lifelink-dev-ApiFunctionRole-vBxc6ik9DHz7` | `lambda.amazonaws.com` |
| `lifelink-dev-PriorityDispatcherRole-DdW8sTj2Bu1q` | `lambda.amazonaws.com` |
| `lifelink-dev-ScheduledMaintenanceRole-UZjM6YOVbvAw` | `lambda.amazonaws.com` |
| `lifelink-dev-OutboxPublisherRole-2e8515GoKwU8` | `lambda.amazonaws.com` |
| `lifelink-dev-WorkQueueWorkerRole-SNaAEIBsML8d` | `lambda.amazonaws.com` |
| `lifelink-dev-NotificationWorkerRole-AaXaqZVKLZFl` | `lambda.amazonaws.com` |
| `lifelink-dev-PriorityDispatcherEveryMinuteRole-XUMrzUO2505M` | **`scheduler.amazonaws.com`** |
| `lifelink-dev-ScheduledMaintenanceEveryTenMinutesRol-bmZJfsq8imdQ` | **`scheduler.amazonaws.com`** |
| `lifelink-dev-MapReaderRole-bmIqIg8VSi3H` | **`cognito-identity.amazonaws.com`** |

**On the random suffixes:** CloudFormation generates them when the template
does not name the role, which guarantees uniqueness on redeployment. **Search
for `lifelink-dev` rather than typing a full name.**

**One function, one role** — six functions, six execution roles. That is what
makes least privilege possible.

---

## 3. Start with the smallest role

```
IAM -> Roles -> lifelink-dev-PriorityDispatcherEveryMinuteRole-XUMrzUO2505M
```

| Tab | Content |
|---|---|
| **Trust relationships** | `scheduler.amazonaws.com`, `sts:AssumeRole` |
| **Permissions** | one inline policy, one action, one resource |

```json
{ "Effect": "Allow",
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:ap-southeast-2:426150327442:function:lifelink-dev-dispatcher" }
```

**Say this:**
> "Start with the simplest one. This role exists so EventBridge Scheduler can
> invoke our dispatcher — and that's **all** it can do. One action, one named
> function. It can't invoke any other Lambda, and it can't touch anything else
> in the account.
>
> Notice there are **two** policies on any role, answering different questions.
> The trust policy says *who may assume this role* — here, the Scheduler
> service. The permissions policy says *what it may then do*. People forget the
> trust policy, but it's the more security-critical half."

**Three lines, obviously minimal. It is the right place to start.**

---

## 4. The demonstration that actually proves least privilege

```
IAM -> Roles -> lifelink-dev-PriorityDispatcherRole-DdW8sTj2Bu1q
             -> Permissions -> expand the policies -> JSON view
```

| Table | Actions granted |
|---|---|
| `emergency` | **full** read/write |
| `notifications` | **full** read/write |
| **`inventory`** | **`GetItem`, `Scan`, `Query`, `BatchGetItem`, `DescribeTable` — READ ONLY** |
| `facilities` | **read only** |
| `organizations` | **read only** |
| SQS `notifications` | `SendMessage*` |

**Say this — this is the moment:**
> "This is the demonstration that actually proves least privilege is real rather
> than decorative, because it shows what a role **cannot** do.
>
> The dispatcher's job is to rank blood banks for an emergency request, so it
> needs to read inventory levels. Look at the actions on the inventory table:
> Get, Query, Scan, BatchGet, Describe. **No PutItem. No UpdateItem. No
> DeleteItem.**
>
> The dispatcher physically cannot modify stock. Not because the code doesn't
> try — because the permission doesn't exist. Even a bug or a compromise in that
> function couldn't alter inventory through this role."

**Then the audit table**, on `ScheduledMaintenanceRole`:

```json
{ "Effect": "Allow", "Action": ["dynamodb:PutItem"],
  "Resource": "arn:...:table/lifelink-dev-audit" }
```

> "And on the audit table, the maintenance role has `PutItem` only — it can
> append an audit record and physically cannot read, modify or delete one. The
> API's role has PutItem and Query, so it can append and read back, and still
> can't alter anything. That's an audit trail enforced by IAM rather than by
> everyone remembering not to."

---

## 5. The per-table policy pattern

```
IAM -> lifelink-dev-ApiFunctionRole-vBxc6ik9DHz7 -> Permissions
```

**2 managed policies + 16 inline policies.**

| Managed | Grants |
|---|---|
| `AWSLambdaBasicExecutionRole` | `logs:CreateLogGroup`, `CreateLogStream`, `PutLogEvents` |
| `AWSXrayWriteOnlyAccess` | X-Ray trace segments |

> "That first managed policy is why a Lambda can write logs at all. A function
> with a hand-written role that omits it appears to run and produces no logs,
> which is a confusing afternoon."

Open one inline policy and show both resource ARNs:

```json
"Resource": [
  "arn:aws:dynamodb:ap-southeast-2:426150327442:table/lifelink-dev-inventory",
  "arn:aws:dynamodb:ap-southeast-2:426150327442:table/lifelink-dev-inventory/index/*"
]
```

**Say this:**
> "Sixteen inline policies, one per table. One broad policy would be easier to
> write and impossible to audit.
>
> And notice the **second ARN ending `/index/*`**. Querying a global secondary
> index needs permission on the index as a separate resource. Omit it and every
> GSI query fails with Access Denied while table reads work perfectly — a
> genuinely confusing failure, and worth knowing about."

Also worth showing:

```json
{ "Action": ["cognito-idp:AdminGetUser", "cognito-idp:ListUsers"],
  "Resource": "arn:aws:cognito-idp:ap-southeast-2:426150327442:userpool/ap-southeast-2_Z91jyFm1d" }
```

> "Two Cognito actions, scoped to **our** pool by ARN. Not all pools in the
> account."

---

## 6. The `Resource: "*"` — be ready

Find it in `ApiFunctionRolePolicy11`:

```json
{ "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "*",
  "Condition": { "StringEquals": {
      "kms:ViaService": "dynamodb.ap-southeast-2.amazonaws.com" }}}
```

**Say this — do not wait to be asked:**
> "There's exactly one wildcard resource in our policies, and I'd rather point
> it out than have you find it.
>
> DynamoDB encrypts with the AWS-managed `aws/dynamodb` key, and that key's ARN
> contains an id AWS generated — `95806067-714f...`. It isn't knowable when we
> write the template, so CloudFormation can't reference it and the policy can't
> name it.
>
> But look at the condition: `kms:ViaService` pinned to
> `dynamodb.ap-southeast-2.amazonaws.com`. So this permission can only be
> exercised **through DynamoDB**. If the function tried to call KMS directly to
> decrypt something else — an S3 object, a secret — the condition fails and KMS
> denies it.
>
> It's scoped by **condition** rather than by **resource**, which is the right
> tool when the resource ARN isn't knowable in advance. If I wanted to remove
> the wildcard entirely, I'd switch the tables to a customer-managed KMS key —
> then I'd have a known ARN to name, at about a dollar a month per key."

**Never say "it's safe because it's just KMS."** That answer invites one
follow-up question and collapses.

---

## 7. The federated trust policy

```
IAM -> lifelink-dev-MapReaderRole-bmIqIg8VSi3H -> Trust relationships
```

```json
{ "Effect": "Allow",
  "Principal": { "Federated": "cognito-identity.amazonaws.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": { "StringEquals": {
      "cognito-identity.amazonaws.com:aud": "ap-southeast-2:31685707-e3c3-4aa0-b4ca-b753c70b8688" }}}
```

**Three differences from the Lambda roles, all worth pointing out:**

1. **`Federated`**, not `Service` — the caller is an external identity provider.
2. **`sts:AssumeRoleWithWebIdentity`**, not `sts:AssumeRole`.
3. **A condition on `aud`** restricting it to **our** identity pool.

**Say this:**
> "This is the only federated role, and the condition is the important part.
> Without that `aud` condition, **any** Cognito identity pool in **any** AWS
> account could assume this role. That's the confused-deputy problem, and the
> condition is the defence.
>
> Its permissions are four read-only map-tile actions on one map ARN. And I
> should be honest: it's **deployed but never used**. It was for browser access
> to Amazon Location tiles, and ADR-0019 replaced that with OpenStreetMap
> because Location API keys are denied by our account's policy. So it's leftover
> infrastructure from a superseded decision. It costs nothing, and it's a good
> example of a federated trust policy if you want one."

---

## 8. Access Advisor — the underused tab

```
IAM -> any role -> Access Advisor
```

Shows which services the role has **actually used**.

**Say this:**
> "This tab is how you tighten a policy with evidence instead of guesswork — it
> shows services the role was granted but hasn't touched. If I were narrowing
> these policies, I'd start here rather than reasoning about it."

**Mentioning Access Advisor signals real familiarity with IAM.**

---

## 9. Policy evaluation — with a real example

> "Evaluation order is: explicit Deny anywhere wins, then the organization's
> service control policies, then whether anything allows it — and if nothing
> does, it's denied by default. That default-deny is why we never write Deny
> statements: not granting something is already enough.
>
> We hit the explicit-deny case for real. Our account has a service control
> policy that denies creating an Amazon Location API key. It didn't matter what
> our IAM permissions said — an SCP deny can't be overridden, so the resource
> creation failed outright and we changed the design. That's ADR-0019, and it's
> the clearest demonstration of policy evaluation I have."

---

## 10. Do not

| Action | Why |
|---|---|
| **Create an IAM user** | the project deliberately has none |
| Attach or detach a policy | template-controlled |
| Edit a trust policy | would break the function immediately |
| Edit an inline policy | creates drift |
| Delete a role | |
| Use the policy simulator to *change* anything | reading is fine |

**If asked to grant a permission:**
> "I'd add it to the template and redeploy, not here. Changing it in the Console
> creates drift — the role would no longer match the code that defines it, so
> the next deployment would either overwrite my change or fail confusingly."

---

## 11. Questions and answers

**"Could you tighten these further?"**
> Yes, in two places. The API function's role is the union of all fifty-eight
> routes' needs, so a route that only reads facilities runs with permission to
> write inventory. Splitting the API into per-feature functions would narrow
> that, at the cost of more cold starts against a concurrency limit of ten. And
> the DynamoDB action list is a standard ten-action set; some tables are only
> ever read by the API and could drop the write actions. Access Advisor would
> tell me which with evidence.

**"What if a Lambda were compromised?"**
> The attacker gets that function's role with temporary credentials. From the
> API role they could read and write our twelve tables and send to our two
> queues. They could **not** create AWS resources, touch IAM, read S3, or
> decrypt anything outside DynamoDB — the KMS condition blocks that. They also
> couldn't escape the account's service control policies. And they couldn't
> alter an audit record, because that role has no update or delete permission on
> that table.

**"Why inline policies rather than managed?"**
> Inline policies are deleted with the role, so removing a function leaves no
> orphaned policy behind, and SAM generates them from the template
> automatically. Customer-managed policies would be better if several roles
> shared the same permission set — ours deliberately don't, because sharing
> would mean granting each function the union of their needs.

**"Is IAM the same as Cognito?"**
> No, and it's worth separating them. IAM controls what our AWS *services* can
> do. Cognito identifies our *application users* and issues JWTs. A blood bank
> admin has no IAM identity at all. The one place they meet is the identity pool
> — `MapReaderRole` — which we deployed and don't use.

---

## 12. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) §I
- [../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md](../04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md)
- [../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md](../08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
- [05_Showing_Cognito_In_Action.md](05_Showing_Cognito_In_Action.md)
