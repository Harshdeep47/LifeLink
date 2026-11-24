<!-- pagebreak -->

# 58. Whiteboard Drills

Six drills to practise aloud. Time yourself; each should take five minutes.

## 58.1 Drill one: draw the read path

Draw what happens when someone searches for O-negative packed red cells within
twenty kilometres.

**What a complete answer includes.** Browser to API Gateway. Lambda resolves
the search origin. Geohash precision chosen from the radius. Cells covering
the circle queried against the facilities index. Exact Haversine filtering.
For each surviving facility, an eligible-stock query against the inventory
index. Aggregation into an availability state. Ranking. Response with
explanations.

**What most people miss.** That eligibility filtering happens before ranking,
and that a facility with no reported inventory is carried through as unknown
rather than dropped or zeroed.

## 58.2 Drill two: draw the write path with its failure branch

Draw a stock deduction including what happens when it loses a race.

**What a complete answer includes.** Read with version. Domain decides the new
state. Transaction containing the conditional write, the audit record and the
outbox event. On condition failure: re-read, recompute, retry, bounded.

**What most people miss.** That the retry recomputes rather than resubmitting,
and that the audit and event are inside the transaction rather than after it.

## 58.3 Drill three: explain the two priorities

Explain why the system has `clinicalPriority` and `effectivePriority` to
someone who thinks it is duplication.

**The shape of the answer.** Start with the problem — starvation. Introduce the
standard remedy — aging. Then show why the remedy is dangerous if it writes the
clinical field, and only then introduce the second field as the resolution.

**What most people miss.** Leading with the solution. "We have two fields" is
not an argument; "aging a clinical priority would overrule a doctor" is.

## 58.4 Drill four: the dual-write problem

Explain why writing to a database and then publishing a message is unsafe,
without using the word "outbox" until the end.

**The shape of the answer.** Describe the crash window. Emphasise that the
failure is silent. Then name the options — two-phase commit, change data
capture, outbox — and say which was chosen and why.

## 58.5 Drill five: design the reservation feature

You decided not to build it. Design it anyway, in five minutes.

**What a complete answer includes.** A reservation entity with an expiry.
Conditional write against the specific batch so two cannot claim the same
units. Automatic release on timeout. Facility override. A short expiry. And a
statement about what it costs: stock held for someone who may not arrive.

## 58.6 Drill six: the bug

Tell the geohash story in three minutes, including both problems and both
fixes.

**What a complete answer includes.** The symptom and why it was invisible. The
cause. The first fix and the performance problem it created. The real fix.
What the tests now assert — properties rather than examples.

<!-- pagebreak -->

# 59. Answering Questions You Cannot Answer

Interviewers ask questions you do not know the answer to, deliberately. How
you handle that is often weighted more heavily than the questions you can
answer.

## 59.1 The structure of a good "I don't know"

**Say it plainly.** "I don't know" is a complete sentence and costs nothing.

**Say what you do know.** "I have not used Kinesis. I have used SQS, and my
understanding is that the difference is ordered, replayable streams with
multiple independent consumers versus a queue where a message is consumed
once. Is that the distinction that matters here?"

**Reason toward an answer.** "If I had to choose now, I would ask whether
multiple consumers need the same events. If yes, the stream. If no, the
queue."

**Offer to find out.** Genuinely, not as a formula.

## 59.2 What not to do

Do not guess confidently. An interviewer who knows the answer learns that your
confident statements cannot be trusted, which contaminates everything else you
said.

Do not deflect into something you do know. It is transparent and wastes the
remaining time.

Do not apologise repeatedly. One acknowledgement is enough.

## 59.3 Questions where "I don't know" is the right answer for this project

**"What is your p99 latency?"** Unknown. It is deployed, but nothing has been
load-tested, and at a concurrency ceiling of {{fact:lambda_concurrency}} a
measurement would mostly describe the ceiling.

**"How does it behave at a thousand requests per second?"** Unknown, and it
would throttle long before that. I can say what would break first and in what
order.

**"Is the compatibility data correct?"** I cannot certify it. It reflects
standard relationships from teaching material, it has not been reviewed by a
qualified professional for this deployment, and every response says so.

**"How long does a restore take?"** Unknown. The procedure is written from the
AWS documentation and has never been executed; PITR is enabled on the deployed
tables, but no restore has been rehearsed against them.

Each of those is a stronger answer than a number I would have had to invent.

<!-- pagebreak -->

# 60. Twenty Rapid-Fire Technical Questions

Short, specific, and the kind asked in a screening call.

| # | Question | Answer |
|---|---|---|
| Q1 | What is a conditional write? | A write that commits only if a condition on the item holds, evaluated atomically |
| Q2 | What does `attribute_not_exists` guarantee? | That the item is being created, not overwritten |
| Q3 | Why is a GSI eventually consistent? | It is maintained asynchronously after the base-table write |
| Q4 | What is a composite sort key? | Several attributes encoded into one sort key so a range condition can filter on them |
| Q5 | Difference between a filter and a key condition? | A filter runs after items are read and billed; a key condition runs during the read |
| Q6 | What is a hot partition? | One partition key receiving disproportionate traffic, throttling despite table capacity |
| Q7 | What is TTL in DynamoDB? | Automatic deletion of items past an epoch timestamp attribute, on a best-effort schedule |
| Q8 | What does `TransactWriteItems` guarantee? | All items commit or none do, across up to 100 items and multiple tables |
| Q9 | What is at-least-once delivery? | A message may be delivered more than once but never zero times |
| Q10 | What is a dead-letter queue? | Where a message goes after failing a configured number of receives |
| Q11 | What is visibility timeout? | How long a received message is hidden from other consumers before reappearing |
| Q12 | What is a cold start? | The latency of initialising a new execution environment before the handler runs |
| Q13 | What is reserved concurrency? | A guaranteed share of the account pool for one function, subtracted from the rest |
| Q14 | What does `kid` do in a JWT? | Names which key in the issuer's key set signed the token |
| Q15 | Why is a JWT not revocable? | It is self-contained and validated offline; nothing is consulted at verification |
| Q16 | What is PKCE? | A proof-of-possession exchange that lets a public client use the authorization code flow safely |
| Q17 | What is Origin Access Control? | A mechanism letting CloudFront read a private S3 bucket without making it public |
| Q18 | What is a geohash? | A base-32 encoding of coordinates where a shared prefix means geographic proximity |
| Q19 | What is the Haversine formula? | Great-circle distance between two points on a sphere |
| Q20 | What is the confused deputy problem? | A privileged service tricked into acting on an attacker's behalf |

*Table 60.1. Rapid-fire technical definitions.*

<!-- pagebreak -->

# 61. Closing: How to Use These Three Books

## 61.1 Reading order

**Book 1** for the architecture and the reasoning behind each AWS choice. Read
it once end to end; it is the one that makes the others make sense.

**Book 2** when you need to change something. It is a reference, organised by
the part of the system you are touching, with the real source in it.

**Book 3** in the week before an examination or interview. Work the question
banks aloud rather than reading them.

## 61.2 The three things worth internalising

**The design is organised around what the system refuses to claim.** Unknown
is not zero. Updated is not verified. An offer is not a reservation. Dispatch
order is not clinical priority. Each of those is a refusal, and together they
account for most of what is distinctive here.

**Correctness lives in the datastore, not in the code.** Eight invariants are
enforced by conditional writes and transactions. The domain layer produces good
error messages; the condition expression produces the guarantee.

**Testing against a real datastore found what review did not.** Five bugs,
four of them silent. That is the strongest single argument this project makes
about engineering practice.

## 61.3 A note on the honesty running through these books

Readers may notice how often these pages say that something was not done, not
tested or not available. That is deliberate and it is the point.

A technical book that reports only successes is a brochure. One that records
the bug it shipped, the validation check that did not work, the page count that
turned out to be inflated by blank pages, and the operational figures that were
never measured, is a document someone can actually rely on.

If you take one habit from this project, take that one.
