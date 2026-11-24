<!-- pagebreak -->

# 49. The Documentation Toolchain

The books you are reading are built by code in this repository, and that code
is part of the implementation rather than incidental to it.

## 49.1 Why generate rather than write

The specification requires the books to be generated from the actual
implementation and to avoid inventing classes, APIs or test results. Prose can
be checked by a reviewer; code listings and metrics cannot be checked at a
glance, and they are exactly what goes stale.

The resolution is to make staleness a build failure.

## 49.2 Directives

Each of the following is written in the source wrapped in double braces. They
are shown here without them, because a directive printed in a book that the
same tool builds would be resolved rather than displayed — a small reminder
that a templating language needs an escape hatch.

| Directive body | Resolves to |
|---|---|
| `include:path:def name` | That function, located by parsing the file |
| `include:path:anchor:TEXT:N` | N lines from the first line containing TEXT |
| `include:path:START-END` | Raw line numbers, discouraged and warned about |
| `fact:name` | A measured value |
| `routes:filter` | A table read from the live router |

*Table 49.1. The directive vocabulary.*

An unresolvable directive is a build failure, so a renamed function breaks the
book build rather than silently leaving a book describing a function that no
longer exists.

## 49.3 Why anchors replaced line numbers

{{include:scripts/bookgen/facts.py:def _extract_region}}

*Listing 49.1. Region extraction from `scripts/bookgen/facts.py`.*

The docstring records the incident that motivated it. A listing captioned "the
audit IAM grant" was selected by line number; an unrelated edit to the template
shifted the file, and the listing silently began showing SQS queue
configuration under a caption about IAM policy.

The failure mode is the worst kind: the output was well-formed, plausible and
wrong. Line-number includes now produce a build warning.

## 49.4 Facts are measured

{{include:scripts/bookgen/facts.py:def collect_test_results}}

*Listing 49.2. Test measurement.*

Two details worth noting.

Quiet mode is deliberately not used, because in this pytest version `-q`
suppresses the summary line — and a missing summary previously produced a
recorded count of **zero**, which would have put a false test result in three
books.

Anything unparseable is recorded as `COULD NOT MEASURE` rather than as a
number. A figure that cannot be measured must not be invented, and zero is an
invention.

## 49.5 Validation

Every build opens the produced PDF and checks it:

| Check | Catches |
|---|---|
| File exists and opens | A build that silently produced nothing |
| Page count | A book far shorter than intended |
| No blank pages in the body | Double page breaks and widows |
| No content outside the page | Clipped tables and overflowing code |
| No unresolved directives | A renamed function or missing fact |
| Diagrams rendered | A diagram DSL change that produced nothing |
| Contents page numbers exact | Layout drift between passes |

*Table 49.2. The seven checks, each of which has caught something.*

## 49.6 The blank-page lesson

The blank-page check is the one worth describing, because the first version of
it did not work.

It measured whether a page had extractable text. Every page passed — because
the running header and footer are drawn on every page, so a page containing
nothing else still yielded sixty characters of text.

The fix measures only the body frame, excluding the header and footer bands.
It immediately found blank pages caused by a chapter heading emitting a page
break when the source already contained one, and the honest page count of each
book dropped substantially once they were removed.

:::key A validation check that cannot fail is not a check
The first version reported PASS on every page of a book that contained blank
pages. It is worth asking, of any check that always passes, whether it is
measuring the thing you believe it is.
:::

## 49.7 Diagrams are vector, not ASCII

{{include:scripts/bookgen/diagrams.py:anchor:def render_layered:10}}

*Listing 49.3. Layered diagram rendering from
`scripts/bookgen/diagrams.py`.*

Diagrams are declared in a small DSL and rendered as ReportLab vector
graphics. The DSL has no free-form positioning — nodes sit on a grid of layers
and columns — which makes overlapping boxes impossible rather than merely
unlikely.

## 49.8 The code highlighter, and a bug worth remembering

The first highlighter applied successive regular expressions: keywords, then
strings, then comments. It produced malformed markup and a parse failure.

The cause is instructive. The keyword pass inserted
`<font color='#7a0f1d'>`, and the string pass then matched `'#7a0f1d'` —
which looks exactly like a string literal — and wrapped it again, producing
nested and unbalanced tags.

The fix is a single tokenising pass that classifies each region once. The
general lesson is that chained substitutions on a string are a pipeline where
each stage can match the previous stage's output.

<!-- pagebreak -->

# 50. A Checklist for the Next Engineer

## 50.1 Before you change anything

- Run the suite: `pytest tests` in `backend`. It takes seconds.
- Read the relevant architecture decision record.
- Find the test that pins the behaviour you are about to change. If there is
  none, that is worth knowing before you start.

## 50.2 While you work

- Put rules in `domain/`, workflows in `services/`, storage in
  `repositories/`. If you are unsure which, the rule is usually: can it be
  tested without AWS? Then it belongs in `domain/`.
- Inject time rather than reading the clock.
- Return reasons rather than booleans.
- Name the rule in the error details.
- If you add a route, declare its permission and run the OpenAPI generator.

## 50.3 Before you commit

| Command | Must show |
|---|---|
| `pytest tests` | all passing |
| `ruff check src tests` | clean |
| `npm test` in `frontend` | all passing |
| `npm run build` in `frontend` | builds |
| `generate_openapi.py --check` | matches |
| `cfn-lint infrastructure/template.yaml` | no findings |
| `build_books.py --no-tests` | all books validated |
| `git diff --cached` | no secrets, no `.env`, no keys |

*Table 50.1. The pre-commit checklist.*

The last row matters most. `.gitignore` covers `.env`, `.local-keys/` and
credentials, but reading the diff is the check that catches what a pattern
missed.

## 50.4 Things that will surprise you

**`-q` hides pytest's summary** in this version, which is why the fact
collector does not use it.

**npm is not on the Git Bash PATH** on this machine. Use PowerShell, or the
full path.

**An unused DynamoDB expression placeholder** produces a `ValidationException`
that names nothing useful. If an update suddenly fails, compare the
placeholders in the expression with the keys of the values dictionary.

**Renaming a function breaks the book build.** That is intended. Update the
anchor.

**The `appcore` package is named that way deliberately.** Do not rename it to
`platform`; it would shadow the standard-library module that botocore imports.
