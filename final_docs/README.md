# LifeLink — Master Documentation and Teaching Library

**What this is.** A complete, verified teaching library for the LifeLink
project: a blood-availability platform running on AWS. It is written so that
someone who has never seen the project can understand it, demonstrate it, and
answer hard questions about it.

**What it is not.** It is not a brochure and it is not a generic AWS tutorial.
Every technical claim here was checked against the running system, the
infrastructure template, or the source code on **24 November 2026**. Where
something could not be verified, it says so.

---

## The single most important thing to understand first

LifeLink is **deployed and working**, but "working" has layers, and a teacher
will probe exactly where those layers end. Learn this table before anything
else:

| Layer | Status | What it means |
|---|---|---|
| Code in the repository | `REPO` | 951 automated tests pass |
| Deployed to AWS | `DEPLOYED` | 66 resources live in `ap-southeast-2` |
| Verified by automated tests | `TEST-VERIFIED` | A test asserts it |
| Verified live against AWS | `DEPLOYED` + checked | 56 live checks were run by script |
| Verified in a real browser by a human | **`BROWSER-VERIFIED` — NOT DONE** | **12 checks are still pending** |

**If a teacher asks "have you tested this in the browser?", the honest answer
is: the API and the AWS resources were verified by script; the browser
workflows have not been independently watched by a person.** Saying that
plainly is worth more than a bluff that collapses under one follow-up
question. The 12 pending checks are listed in
[05_Known_Limitations_And_Actual_Status.md](13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md).

---

## Status labels used throughout this library

| Label | Meaning |
|---|---|
| `DEPLOYED` | Verified present in the live AWS environment by an API call |
| `REPO` | Present in the current repository at commit `668a771` |
| `UNDEPLOYED` | Implemented locally, not deployed |
| `TEST-VERIFIED` | Verified by an automated test that currently passes |
| `BROWSER-VERIFIED` | Independently confirmed in a real browser by a person |
| `NEEDS-VERIFICATION` | Insufficient evidence — do not claim this |
| `NOT-IMPLEMENTED` | Does not exist; discussed only as a concept or comparison |

---

## The two-day study path

You will not read this whole library in two days, and you should not try. Read
in this order. Anything marked **REFERENCE ONLY** is for looking things up
during the evaluation, not for reading in advance.

### DAY 1 — Understand the project and its architecture

| # | Read | Why | Priority |
|---|---|---|---|
| 1 | [01_LifeLink_From_Zero.md](01_START_HERE/01_LifeLink_From_Zero.md) | What the project is, in plain language | **MUST LEARN** |
| 2 | [03_Project_Features_And_User_Roles.md](01_START_HERE/03_Project_Features_And_User_Roles.md) | The four features and ten roles | **MUST LEARN** |
| 3 | [01_Complete_System_Architecture.md](02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md) | The whole system on one page | **MUST LEARN** |
| 4 | [02_End_To_End_Data_Flow.md](02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md) | One request, traced all the way down | **MUST LEARN** |
| 5 | [01_Complete_File_Structure.md](03_REPOSITORY_AND_CODE/01_Complete_File_Structure.md) | Where everything lives | **MUST LEARN** |
| 6 | [04_API_And_Handler_Mapping.md](03_REPOSITORY_AND_CODE/04_API_And_Handler_Mapping.md) | Button to route to handler to table | **MUST LEARN** |
| 7 | [03_S3_And_CloudFront.md](04_AWS_COMPLETE_GUIDE/03_S3_And_CloudFront.md), [04_API_Gateway.md](04_AWS_COMPLETE_GUIDE/04_API_Gateway.md), [05_AWS_Lambda.md](04_AWS_COMPLETE_GUIDE/05_AWS_Lambda.md) | How it is hosted | **MUST LEARN** |
| 8 | [01_DynamoDB_Data_Model.md](05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md) | The 12 tables and why they are shaped that way | **MUST LEARN** |
| 9 | [03_Synthetic_Data_Generation.md](05_DATABASE_AND_DATA/03_Synthetic_Data_Generation.md) | Where the demo data came from | **SHOULD LEARN** |

**End of Day 1, you should be able to:** draw the architecture from memory,
open the right file for any feature, show records in the DynamoDB console, and
trace one feature from a button click to a database row.

### DAY 2 — AWS configuration, security and demonstrations

| # | Read | Why | Priority |
|---|---|---|---|
| 1 | [01_Cognito_Authentication_Flow.md](08_SECURITY_AND_RELIABILITY/01_Cognito_Authentication_Flow.md) | How login works | **MUST LEARN** |
| 2 | [03_JWT_And_Token_Verification.md](08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md) | Access vs ID token — a favourite question | **MUST LEARN** |
| 3 | [08_IAM_Complete_Guide.md](04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md) | Roles, policies, least privilege | **MUST LEARN** |
| 4 | [CONFIGURATION_WALKTHROUGHS.md](09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) | "Show me where you configured it" | **MUST LEARN** |
| 5 | [09_PRACTICAL_AWS_DEMONSTRATIONS](09_PRACTICAL_AWS_DEMONSTRATIONS/) 01–09 | The actual click-by-click demos | **MUST LEARN** |
| 6 | [02_Map_Rendering_And_Tiles.md](07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md) | Why the basemap is OpenStreetMap, not AWS | **MUST LEARN** |
| 7 | [01_Complete_Lab_Demonstration_Script.md](10_LAB_EVALUATION/01_Complete_Lab_Demonstration_Script.md) | The demo, in order, with timings | **MUST LEARN** |
| 8 | [02_Teacher_Question_And_Answer_Bank.md](10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md) | Spoken answers | **MUST LEARN** |
| 9 | [05_Known_Limitations_And_Actual_Status.md](13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md) | What to admit, and how | **MUST LEARN** |
| 10 | [05_Last_Minute_Revision.md](10_LAB_EVALUATION/05_Last_Minute_Revision.md) | Last 30 minutes before the lab | **MUST LEARN** |

**End of Day 2, you should be able to:** open the AWS Console and find any
significant LifeLink setting, explain why it is set that way, and answer
questions on authentication, authorization, the database and the architecture
without contradicting the implementation.

### For each study session, use this loop

```
Concept  ->  How LifeLink uses it  ->  The source file  ->  The AWS Console
         ->  Say the answer out loud  ->  Answer one follow-up question
```

Saying it out loud is not optional. Reading an answer and speaking an answer
are different skills, and the lab tests the second one.

---

## Complete index

### 01_START_HERE — *read this first*
- [01_LifeLink_From_Zero.md](01_START_HERE/01_LifeLink_From_Zero.md) — the project explained from nothing
- [02_Project_Overview.md](01_START_HERE/02_Project_Overview.md) — scope, scale, current status
- [03_Project_Features_And_User_Roles.md](01_START_HERE/03_Project_Features_And_User_Roles.md) — four features, ten roles, 39 permissions
- [04_Technology_Stack_Explained.md](01_START_HERE/04_Technology_Stack_Explained.md) — every technology and why it was chosen

### 02_SYSTEM_ARCHITECTURE
- [01_Complete_System_Architecture.md](02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md)
- [02_End_To_End_Data_Flow.md](02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md)
- [03_Frontend_To_Backend_Communication.md](02_SYSTEM_ARCHITECTURE/03_Frontend_To_Backend_Communication.md)
- [04_AWS_Architecture.md](02_SYSTEM_ARCHITECTURE/04_AWS_Architecture.md)
- [05_Architecture_Decisions.md](02_SYSTEM_ARCHITECTURE/05_Architecture_Decisions.md)

### 03_REPOSITORY_AND_CODE
- [01_Complete_File_Structure.md](03_REPOSITORY_AND_CODE/01_Complete_File_Structure.md)
- [02_Frontend_Code_Walkthrough.md](03_REPOSITORY_AND_CODE/02_Frontend_Code_Walkthrough.md)
- [03_Backend_Code_Walkthrough.md](03_REPOSITORY_AND_CODE/03_Backend_Code_Walkthrough.md)
- [04_API_And_Handler_Mapping.md](03_REPOSITORY_AND_CODE/04_API_And_Handler_Mapping.md)
- [05_Database_Code_Locations.md](03_REPOSITORY_AND_CODE/05_Database_Code_Locations.md)
- [06_How_To_Modify_LifeLink.md](03_REPOSITORY_AND_CODE/06_How_To_Modify_LifeLink.md)

### 04_AWS_COMPLETE_GUIDE
- [01_AWS_Introduction_For_LifeLink.md](04_AWS_COMPLETE_GUIDE/01_AWS_Introduction_For_LifeLink.md)
- [02_Regions_And_Availability_Zones.md](04_AWS_COMPLETE_GUIDE/02_Regions_And_Availability_Zones.md)
- [03_S3_And_CloudFront.md](04_AWS_COMPLETE_GUIDE/03_S3_And_CloudFront.md)
- [04_API_Gateway.md](04_AWS_COMPLETE_GUIDE/04_API_Gateway.md)
- [05_AWS_Lambda.md](04_AWS_COMPLETE_GUIDE/05_AWS_Lambda.md)
- [06_DynamoDB.md](04_AWS_COMPLETE_GUIDE/06_DynamoDB.md)
- [07_Cognito_Complete_Guide.md](04_AWS_COMPLETE_GUIDE/07_Cognito_Complete_Guide.md)
- [08_IAM_Complete_Guide.md](04_AWS_COMPLETE_GUIDE/08_IAM_Complete_Guide.md)
- [09_SNS_SQS_And_Notifications.md](04_AWS_COMPLETE_GUIDE/09_SNS_SQS_And_Notifications.md)
- [10_EventBridge_And_Step_Functions.md](04_AWS_COMPLETE_GUIDE/10_EventBridge_And_Step_Functions.md)
- [11_CloudWatch.md](04_AWS_COMPLETE_GUIDE/11_CloudWatch.md)
- [12_AWS_Security_And_Permissions.md](04_AWS_COMPLETE_GUIDE/12_AWS_Security_And_Permissions.md)
- [13_AWS_Cost_And_Scalability.md](04_AWS_COMPLETE_GUIDE/13_AWS_Cost_And_Scalability.md)

### 05_DATABASE_AND_DATA
- [01_DynamoDB_Data_Model.md](05_DATABASE_AND_DATA/01_DynamoDB_Data_Model.md)
- [02_All_Tables_And_Indexes.md](05_DATABASE_AND_DATA/02_All_Tables_And_Indexes.md)
- [03_Synthetic_Data_Generation.md](05_DATABASE_AND_DATA/03_Synthetic_Data_Generation.md)
- [04_Database_Seeding_Workflow.md](05_DATABASE_AND_DATA/04_Database_Seeding_Workflow.md)
- [05_Database_Access_Patterns.md](05_DATABASE_AND_DATA/05_Database_Access_Patterns.md)
- [06_Concurrency_And_Data_Integrity.md](05_DATABASE_AND_DATA/06_Concurrency_And_Data_Integrity.md)

### 06_FEATURE_IMPLEMENTATION
- [01_Inventory_Management.md](06_FEATURE_IMPLEMENTATION/01_Inventory_Management.md)
- [02_Find_Blood_And_Location.md](06_FEATURE_IMPLEMENTATION/02_Find_Blood_And_Location.md)
- [03_Donation_Camps_And_Donor_Engagement.md](06_FEATURE_IMPLEMENTATION/03_Donation_Camps_And_Donor_Engagement.md)
- [04_Smart_Emergency_Coordination.md](06_FEATURE_IMPLEMENTATION/04_Smart_Emergency_Coordination.md)
- [05_Temporary_Reservations.md](06_FEATURE_IMPLEMENTATION/05_Temporary_Reservations.md)
- [06_Authentication_And_User_Workflows.md](06_FEATURE_IMPLEMENTATION/06_Authentication_And_User_Workflows.md)

### 07_MAPS_AND_INTEGRATIONS
- [01_Browser_Geolocation.md](07_MAPS_AND_INTEGRATIONS/01_Browser_Geolocation.md)
- [02_Map_Rendering_And_Tiles.md](07_MAPS_AND_INTEGRATIONS/02_Map_Rendering_And_Tiles.md)
- [03_Distance_And_Haversine.md](07_MAPS_AND_INTEGRATIONS/03_Distance_And_Haversine.md)
- [04_External_Integrations.md](07_MAPS_AND_INTEGRATIONS/04_External_Integrations.md)

### 08_SECURITY_AND_RELIABILITY
- [01_Cognito_Authentication_Flow.md](08_SECURITY_AND_RELIABILITY/01_Cognito_Authentication_Flow.md)
- [02_IAM_Authorization_Flow.md](08_SECURITY_AND_RELIABILITY/02_IAM_Authorization_Flow.md)
- [03_JWT_And_Token_Verification.md](08_SECURITY_AND_RELIABILITY/03_JWT_And_Token_Verification.md)
- [04_User_And_Facility_Isolation.md](08_SECURITY_AND_RELIABILITY/04_User_And_Facility_Isolation.md)
- [05_Error_Handling_And_Retries.md](08_SECURITY_AND_RELIABILITY/05_Error_Handling_And_Retries.md)
- [06_Security_And_Threat_Scenarios.md](08_SECURITY_AND_RELIABILITY/06_Security_And_Threat_Scenarios.md)

### 09_PRACTICAL_AWS_DEMONSTRATIONS
- [CONFIGURATION_WALKTHROUGHS.md](09_PRACTICAL_AWS_DEMONSTRATIONS/CONFIGURATION_WALKTHROUGHS.md) — **the "show me where you configured it" document**
- [01_AWS_Console_Navigation.md](09_PRACTICAL_AWS_DEMONSTRATIONS/01_AWS_Console_Navigation.md)
- [02_Showing_S3_And_CloudFront.md](09_PRACTICAL_AWS_DEMONSTRATIONS/02_Showing_S3_And_CloudFront.md)
- [03_Showing_Lambda_And_Execution.md](09_PRACTICAL_AWS_DEMONSTRATIONS/03_Showing_Lambda_And_Execution.md)
- [04_Showing_DynamoDB_Records.md](09_PRACTICAL_AWS_DEMONSTRATIONS/04_Showing_DynamoDB_Records.md)
- [05_Showing_Cognito_In_Action.md](09_PRACTICAL_AWS_DEMONSTRATIONS/05_Showing_Cognito_In_Action.md)
- [06_Showing_IAM_In_Action.md](09_PRACTICAL_AWS_DEMONSTRATIONS/06_Showing_IAM_In_Action.md)
- [07_Showing_API_Gateway_And_Requests.md](09_PRACTICAL_AWS_DEMONSTRATIONS/07_Showing_API_Gateway_And_Requests.md)
- [08_Showing_CloudWatch_Logs.md](09_PRACTICAL_AWS_DEMONSTRATIONS/08_Showing_CloudWatch_Logs.md)
- [09_Showing_Maps_And_Location.md](09_PRACTICAL_AWS_DEMONSTRATIONS/09_Showing_Maps_And_Location.md)

### 10_LAB_EVALUATION
- [01_Complete_Lab_Demonstration_Script.md](10_LAB_EVALUATION/01_Complete_Lab_Demonstration_Script.md)
- [02_Teacher_Question_And_Answer_Bank.md](10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md)
- [03_Scenario_Based_Questions.md](10_LAB_EVALUATION/03_Scenario_Based_Questions.md)
- [04_Live_Coding_And_Modification_Demonstrations.md](10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md)
- [05_Last_Minute_Revision.md](10_LAB_EVALUATION/05_Last_Minute_Revision.md)

### 11_INTERVIEW_PREPARATION — *partially created*
- [01_Basic_Cloud_Computing_Questions.md](11_INTERVIEW_PREPARATION/01_Basic_Cloud_Computing_Questions.md) — 15 fundamentals questions
- [02_AWS_Interview_Questions.md](11_INTERVIEW_PREPARATION/02_AWS_Interview_Questions.md) — 32 service questions across S3, CloudFront, Lambda, DynamoDB, Cognito, IAM, API Gateway, SQS, EventBridge

**Not created** (see §"What was not created" below): frontend/backend,
database, security, system-design and advanced-scenario question banks. Their
material is covered by
[10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md](10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md)
and
[10_LAB_EVALUATION/03_Scenario_Based_Questions.md](10_LAB_EVALUATION/03_Scenario_Based_Questions.md).

### 12_TEAMMATE_HANDOVER — **not created**

Teammates should read, in this order:
[01_START_HERE/01_LifeLink_From_Zero.md](01_START_HERE/01_LifeLink_From_Zero.md),
[01_START_HERE/03_Project_Features_And_User_Roles.md](01_START_HERE/03_Project_Features_And_User_Roles.md),
[02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md](02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md),
[03_REPOSITORY_AND_CODE/01_Complete_File_Structure.md](03_REPOSITORY_AND_CODE/01_Complete_File_Structure.md)
and
[10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md](10_LAB_EVALUATION/02_Teacher_Question_And_Answer_Bank.md).
Local setup and test commands are in the repository's own
`docs/LOCAL_DEVELOPMENT.md` and `docs/TESTING.md`.

### 13_REFERENCE_AND_REVISION — *partially created*
- [05_Known_Limitations_And_Actual_Status.md](13_REFERENCE_AND_REVISION/05_Known_Limitations_And_Actual_Status.md) — **MUST LEARN**

**Not created:** glossary, command reference, diagram collection and file-path
reference. Substitutes: the commands are in
[10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md](10_LAB_EVALUATION/04_Live_Coding_And_Modification_Demonstrations.md)
§"verification commands"; the diagrams are inline in
[02_SYSTEM_ARCHITECTURE/01](02_SYSTEM_ARCHITECTURE/01_Complete_System_Architecture.md)
and [02](02_SYSTEM_ARCHITECTURE/02_End_To_End_Data_Flow.md); the file paths are
in [03_REPOSITORY_AND_CODE/01_Complete_File_Structure.md](03_REPOSITORY_AND_CODE/01_Complete_File_Structure.md);
and terminology is defined where it first appears, with the AWS vocabulary in
[04_AWS_COMPLETE_GUIDE/01_AWS_Introduction_For_LifeLink.md](04_AWS_COMPLETE_GUIDE/01_AWS_Introduction_For_LifeLink.md) §8.

### For another AI assistant
- [AI_TEACHING_CONTEXT.md](AI_TEACHING_CONTEXT.md) — the complete, accurate project briefing in one file

---

## What was not created, and why

The library was prioritised for **evaluation usefulness over completeness**.
**70 documents** covering the architecture, source code, AWS configuration,
features, security, practical demonstrations and lab evaluation are complete.

**18 planned documents were not created:**
`11_INTERVIEW_PREPARATION/03`–`07`, all of `12_TEAMMATE_HANDOVER`, and
`13_REFERENCE_AND_REVISION/01`–`04` and `06`.

**None of them is required for the laboratory evaluation**, and their
substance is covered elsewhere as noted in each section above. Some
cross-reference links inside the completed documents still point at these
planned files; those are **forward references to documents that do not exist**,
not errors in the documents that contain them.

**Every document that the two-day study path depends on exists.**

---

## The numbers, verified on 24 November 2026

| Fact | Value | How it was verified |
|---|---|---|
| AWS account | `426150327442` | `aws sts get-caller-identity` |
| Region | `ap-southeast-2` (Sydney) | stack output `DeployedRegion` |
| Account plan | FREE, active, credits remaining | `aws freetier get-account-plan-state` |
| Deployed resources | 66 | `describe-stack-resources` |
| Live site | `https://d324z37do52g8f.cloudfront.net` | HTTP 200 |
| Live API | `https://uk6itz2a5b.execute-api.ap-southeast-2.amazonaws.com/dev` | `/health` returned 200 |
| Lambda functions | 6, all `Active` | `get-function` |
| DynamoDB tables | 12, with 24 GSIs | `describe-table` x12 |
| Rows of demo data | 742 | `Select=COUNT` scan x12 |
| API routes | 58 (9 allow anonymous) | route table enumerated in Python |
| Permissions / roles | 39 / 10 | `appcore.rbac` enumerated |
| Backend tests | 657 (566 unit, 91 integration) | `pytest`, exit 0 |
| Frontend tests | 294 | `vitest --run`, 12 files passed |
| **Total tests** | **951 passing** | both suites run on 24 Nov 2026 |
| Release commit | `668a771` on `main` | `git log` |
| Cost | **$0.00 net** — $0.1628 gross for 1-25 Nov, offset by credits | [13_AWS_Cost_And_Scalability.md](04_AWS_COMPLETE_GUIDE/13_AWS_Cost_And_Scalability.md) |

---

## Honesty rules this project is built on

These five sentences appear throughout the codebase and the documentation. A
teacher who notices them will ask about them, and they are the strongest thing
you can say about the project's engineering quality.

1. **Unknown is not zero.** A blood bank that has never reported stock is not a
   blood bank with no stock. The two lead to opposite actions.
2. **Updated is not verified.** Someone typing a number is different from
   someone independently checking it.
3. **An offer is not a reservation.** A provider saying "we have units" is not
   a hold on those units.
4. **Dispatch order is not clinical priority.** The system orders who gets
   asked first; it never decides who deserves blood.
5. **Fail closed.** If authorization cannot be determined, the request is
   refused rather than allowed.

---

## Where the original project documentation lives

This library is new and additive. The project's original documentation in
`docs/` is untouched and remains the engineering record:

| For | Read |
|---|---|
| What is deployed vs what is only in the repo | `docs/REPOSITORY_VS_DEPLOYED.md` |
| Every known limitation, numbered | `docs/KNOWN_LIMITATIONS.md` |
| The 19 architecture decisions | `docs/ARCHITECTURE_DECISIONS.md` |
| Database design rationale | `docs/DATABASE_DESIGN.md` |
| Security posture | `docs/SECURITY.md` |
| API reference | `docs/API_DOCUMENTATION.md` and `docs/openapi.yaml` |
| Deployment procedure | `docs/DEPLOYMENT.md` |
| Three long-form technical books | `docs/books/` |
