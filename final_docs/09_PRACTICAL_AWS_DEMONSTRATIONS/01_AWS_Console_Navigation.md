# AWS Console Navigation

How to find anything in LifeLink's AWS account, and how to start a
demonstration well.

---

## 1. Before you start

| Check | Value |
|---|---|
| Signed into the right account | **`426150327442`** (top-right menu) |
| **Region selector** | **Asia Pacific (Sydney) `ap-southeast-2`** |
| Browser zoom | increase it — Console text is small on a projector |
| Tabs pre-opened | see §3 |

### The mistake that wastes two minutes

> **If your resources "have disappeared", you are in the wrong Region.**

Every regional resource is in `ap-southeast-2`. Switch to Mumbai or Virginia
and every list is empty. **Check the Region selector first, every time.**

**Turn it into a demonstration instead of a fumble:**
> "Quick point worth making — everything regional is in ap-southeast-2. If I
> switch to Mumbai, watch: the table list is empty. That's not a failure,
> that's single-Region deployment. It's also the single most common confusion
> when you start with AWS."

---

## 2. The best place to start: CloudFormation

```
CloudFormation -> Stacks -> lifelink-dev -> Outputs
```

**Why this is the right opening move:**

1. It proves everything belongs to **one managed stack** — nothing was clicked
   together by hand.
2. The **Outputs** tab gives you every identifier on one screen.
3. The **Resources** tab is a clickable index to all 66 resources.

### The Outputs

```
ApiEndpoint         https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev
FrontendUrl         https://d324z37do52g8f.cloudfront.net
FrontendBucketName  lifelink-dev-frontend-426150327442
UserPoolId          ap-southeast-2_Z91jyFm1d
UserPoolClientId    5hp4pm3ictvetfupddvl41pnf
IdentityPoolId      ap-southeast-2:31685707-e3c3-4aa0-b4ca-b753c70b8688
CognitoLoginUrl     https://lifelink-dev-426150327442.auth.ap-southeast-2.amazoncognito.com/login?...
MapName             lifelink-dev-map
AlarmTopicArn       arn:aws:sns:ap-southeast-2:426150327442:lifelink-dev-alarms
DeployedRegion      ap-southeast-2
```

### The four tabs worth knowing

| Tab | Shows |
|---|---|
| **Outputs** | every identifier — **start here** |
| **Resources** | all 66, each a link to its own Console page |
| **Parameters** | the 8 deployed parameter values |
| **Events** | the deployment history, including the 24 Nov updates |

**The Resources tab is an underused navigation tool.** Instead of hunting
through service menus, click the logical id and land on the resource.

**Say this:**
> "I'd start here, because it answers a question before you ask it: everything
> was deployed from one CloudFormation template, not clicked together. The
> Outputs tab gives every identifier on one screen, and the Resources tab is
> effectively a clickable index to all sixty-six resources."

---

## 3. The tabs to pre-open

Open these **before** the demonstration starts. Hunting through menus live
looks unprepared.

| # | Tab |
|---|---|
| 1 | CloudFormation -> `lifelink-dev` -> **Outputs** |
| 2 | DynamoDB -> Tables (filtered to `lifelink`) |
| 3 | Lambda -> Functions (filtered to `lifelink`) |
| 4 | Cognito -> User pools -> `lifelink-dev` |
| 5 | IAM -> Roles (searched for `lifelink-dev`) |
| 6 | API Gateway -> the HTTP API |
| 7 | S3 -> `lifelink-dev-frontend-426150327442` |
| 8 | CloudFront -> `E236QHMFXHDEDL` |
| 9 | CloudWatch -> Dashboards -> `LifeLink-dev` |
| 10 | **The live site** — `https://d324z37do52g8f.cloudfront.net` |
| 11 | **DevTools open on the live site**, Network tab, Fetch/XHR filtered |

---

## 4. Find anything — the quick table

| To find | Path |
|---|---|
| Any resource | CloudFormation -> `lifelink-dev` -> **Resources** |
| The 12 tables | DynamoDB -> Tables -> filter `lifelink` |
| Table records | DynamoDB -> the table -> **Explore table items** |
| The 6 functions | Lambda -> Functions -> filter `lifelink` |
| Function logs | Lambda -> the function -> **Monitor -> Logs** |
| The API | API Gateway -> APIs -> `uk6itz2a5b` |
| API routes | the API -> **Routes** |
| API throttle | the API -> **Stages -> dev** |
| The user pool | Cognito -> User pools -> `lifelink-dev` |
| Users | the pool -> **Users** |
| Password policy | the pool -> **Sign-in / Authentication** |
| App client | the pool -> **App clients** |
| The 9 roles | IAM -> Roles -> search `lifelink-dev` |
| Role permissions | the role -> **Permissions** |
| Who may assume a role | the role -> **Trust relationships** |
| The frontend files | S3 -> `lifelink-dev-frontend-426150327442` |
| Bucket encryption | the bucket -> **Properties** |
| Public access settings | the bucket -> **Permissions** |
| The distribution | CloudFront -> `E236QHMFXHDEDL` |
| SPA error mapping | the distribution -> **Error pages** |
| Deployment history | the distribution -> **Invalidations** |
| Log groups + retention | CloudWatch -> **Log groups** -> filter `lifelink` |
| The 8 alarms | CloudWatch -> **Alarms** |
| Log search | CloudWatch -> **Logs Insights** |
| Traces | CloudWatch -> **X-Ray traces** |
| The 4 queues | SQS -> filter `lifelink` |
| The alarm topic | SNS -> Topics -> `lifelink-dev-alarms` |
| **The 2 schedules** | **EventBridge -> Scheduler -> Schedules** (NOT Rules) |
| Map / places / routes | Amazon Location Service |
| The secret | Secrets Manager -> `lifelink/dev/provider-api-keys` |

### Two paths that catch people out

| Wrong | Right |
|---|---|
| EventBridge -> **Rules** (empty) | EventBridge -> **Scheduler** -> Schedules |
| API Gateway -> REST APIs | API Gateway -> the **HTTP API** |

---

## 5. Safe to inspect, never to change

### Safe — do all of this freely

| Action |
|---|
| Viewing any configuration page |
| **Explore table items** (read) |
| Reading log groups and streams |
| Running Logs Insights queries |
| Viewing IAM policies in JSON |
| Viewing alarm history |
| Viewing the X-Ray service map |
| Viewing invalidation history |

### Never during an evaluation

| Action | Why |
|---|---|
| **Create / Edit / Delete item** in DynamoDB | hand-edited data cannot be reproduced by re-seeding |
| Lambda **Test** with a fabricated event | a malformed event produces an error that looks like a broken function |
| Editing any Lambda configuration | template-controlled; creates drift |
| Editing IAM roles or policies | same |
| Editing Cognito settings | the password policy is asserted by a test that reads the template |
| **Editing Cognito callback URLs** | **breaks sign-in immediately** — Cognito requires an exact match |
| Creating / deleting / disabling a Cognito user | |
| Editing the S3 bucket policy or Block Public Access | |
| Disabling the CloudFront distribution | |
| Purging an SQS queue | |
| Clicking **Retrieve secret value** | displays a credential on a projector |
| Deleting the stack | deletes all 66 resources; **deletion protection is off** |

### The answer when asked to change something

> "I'd change it in the CloudFormation template and redeploy, rather than in the
> Console — let me show you the line. Changing it here would create drift: the
> live resource would no longer match the code that's supposed to define it, so
> the next deployment would either overwrite my change or fail confusingly."

**That answer is better than making the change.**

---

## 6. The five-minute AWS tour

If you have five minutes and want to show breadth:

| Time | Show | Say |
|---|---|---|
| 0:00 | CloudFormation -> Outputs | "66 resources, one template, nothing clicked together" |
| 0:45 | DynamoDB -> `lifelink-dev-facilities` -> Explore items | "16 facilities, `PK = FACILITY#...`" |
| 1:30 | the same table -> **Indexes** | "five GSIs — three are geohash tiers for different search radii" |
| 2:15 | Lambda -> `lifelink-dev-api` -> Monitor | **make a request on the live site; watch the count rise** |
| 3:00 | IAM -> `...PriorityDispatcherRole...` | "read-only on inventory — it ranks blood banks and cannot modify stock" |
| 3:45 | Cognito -> Groups tab (**empty**) | "no groups — roles are in DynamoDB, read every request" |
| 4:30 | CloudWatch -> Logs Insights | **paste a correlation id from DevTools and find the log line** |

**Steps 2:15 and 4:30 are the two that land.** They connect the website to AWS
visibly rather than describing a connection.

---

## 7. The CLI alternative — read-only

Sometimes faster than clicking, and it demonstrates comfort with the tooling.

```bash
P="--profile lifelink --region ap-southeast-2"

aws sts get-caller-identity --profile lifelink
aws cloudformation describe-stacks --stack-name lifelink-dev \
  --query 'Stacks[0].Outputs' --output table $P
aws dynamodb list-tables $P
aws dynamodb scan --table-name lifelink-dev-facilities --select COUNT $P
aws lambda list-functions --query 'Functions[?starts_with(FunctionName,`lifelink`)].FunctionName' $P
aws iam list-roles --query 'Roles[?starts_with(RoleName,`lifelink-dev`)].RoleName'
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/lifelink $P \
  --query 'logGroups[].[logGroupName,retentionInDays]' --output table
```

**Every command above is read-only.**

**The last one is worth running**, because it shows the retention gap: two log
groups at 30 days and four with no value at all.

---

## 8. Common confusions, and how to answer them

| Confusion | Answer |
|---|---|
| "Your resources are gone" | wrong Region — everything is in `ap-southeast-2` |
| "CloudFront isn't in your Region" | CloudFront is a **global** service; the selector reads "Global" |
| "The item count doesn't match what you said" | `DescribeTable`'s count is approximate and refreshes ~every 6 hours; five tables disagreed when checked |
| "I can't find your EventBridge rules" | we use **Scheduler**, not Rules; there are zero rules |
| "Where are your Step Functions?" | there are none — check the template |
| "Where's your Cognito authorizer?" | there isn't one; the Lambda verifies tokens itself |
| "The S3 URL gives Access Denied" | **correct** — that is OAC working; only CloudFront may read the bucket |
| "Your map isn't using AWS" | the **basemap** is OpenStreetMap; geocoding and routing **are** Amazon Location |

---

## 9. Cross-references

- [CONFIGURATION_WALKTHROUGHS.md](CONFIGURATION_WALKTHROUGHS.md) — every setting, with its exact path
- [02_Showing_S3_And_CloudFront.md](02_Showing_S3_And_CloudFront.md) through [09_Showing_Maps_And_Location.md](09_Showing_Maps_And_Location.md)
- [../10_LAB_EVALUATION/01_Complete_Lab_Demonstration_Script.md](../10_LAB_EVALUATION/01_Complete_Lab_Demonstration_Script.md)
