# Evaluation and Dataset

Use this reference whenever creating or validating a dataset or evaluation method.

## Contents

1. Evaluation selection
2. Mandatory calibration
3. Quality diagnosis and repair choice
4. Dataset construction
5. Held-out set and claims

## Evaluation selection

Select the lowest-complexity method that measures the real task:

| Task/output | Preferred evaluation |
|---|---|
| Labels, yes/no, multiple choice | Normalized deterministic comparison |
| JSON or structured extraction | Parse/schema gate plus field-level correctness |
| Numeric value | Numeric comparison with a justified tolerance |
| Sets or unordered collections | Order-insensitive set comparison |
| Code | Parser/compile gate plus unit or execution tests |
| Tool/action workflow | Final-state or side-effect check in an isolated environment |
| Retrieval/grounded answer | Citation/grounding checks plus semantic correctness |
| Summary, explanation, writing, story | Rubric-based LLM judge, optionally preceded by deterministic gates |

Do not use exact-string comparison where multiple semantically correct answers are possible. Do
not use an LLM judge when deterministic product logic can express correctness. Do not optimize a
metric merely because it is easy to implement.

When the user's existing evaluator is present, preserve it and explain "correct" in one sentence.
Validate it; do not silently redesign it.

Treat the output task kind as run-scoped validation state. Pass it as `--task-kind` to every
readiness invocation from the opening gate onward only when project evidence grounds a recognized
kind; never infer it only from a filename, language, or benchmark family. If unresolved, omit
`--task-kind` and report task fit as not yet measured.

When building an evaluator:

- Preserve an existing evaluator unchanged. Expose its grading logic through a thin generated
  calibration adapter under `traigent-runs/` with the skill-owned keyword contract
  `(output, expected, input_data, metadata)`. The adapter does not replace the evaluator or change
  its provenance.
- Keep calibration and SDK registration as separate boundaries. The calibration adapter above is
  for deterministic probe execution; it is not proof that the SDK can bind the evaluator. After
  installation, build the runtime adapter only from the installed SDK's public evaluation models,
  documentation, and validation. Never reproduce or guess SDK callback aliases or positional
  fallbacks in first-run code.
- Infer the rubric from real labels, tests, accepted outputs, product rules, and failure reports.
- Ask one product-grading question only if unresolved ambiguity would materially change which
  output is correct or how candidate configurations rank. Do not ask for generic approval of the
  probe matrix or the assistant's semantic-coverage review.
- Prefer partial credit when correctness has meaningful degrees.
- Return a normalized score in `[0, 1]` from every metric helper.
- Fail evaluator/runtime errors distinctly; do not let a crashed harness look like an incorrect
  agent answer.
- Name the primary metric after what it measures, such as `label_accuracy`, `schema_accuracy`,
  `task_success`, or `judge_quality`.

## Mandatory calibration

Before any optimization, construct at least four probes for each materially distinct case:

1. `good` - clearly correct.
2. `equivalent_good` - semantically correct with a different valid surface form.
3. `partial` - contains some correct information but misses an important requirement.
4. `bad` - clearly incorrect.

Choose and record `score_mode` from the real task semantics before running each case:

- `graded` - use when correctness has meaningful degrees, such as field coverage, rubric quality,
  or partially completed workflows. Require:

```text
good ~= equivalent_good > partial > bad
```

- `binary` - use only when the product decision is nominal classification or pass/fail and partial
  correctness has no valid intermediate meaning. Require `good` and `equivalent_good` to pass,
  and require both `partial` and `bad` to fail.

Binary mode is not an escape hatch for a graded task whose evaluator fails to recognize meaningful
partial correctness. Repair that evaluator and keep `score_mode: "graded"`. Never select binary
mode, thresholds, or tolerances because they make the current evaluator pass; derive them from
product semantics before any probe scores exist and let calibration expose a mismatch.

Use materially distinct inputs and outcome classes. Record each case name, `score_mode`, input,
expected outcome, candidate outputs, scores, checks, and exception status. One input with four
output variants is not enough when the scorer depends on input fields, labels, schema branches,
metadata, or rubric branches. Cover each material scoring path with at least one probe family and
confirm that every helper returns a normalized score in `[0, 1]`. Before executing calibration,
record the exact pass/fail and approximate-equivalence threshold values for each case and explain
why they match that task and score mode; do not rely on unstated CLI defaults.

### Assistant semantic-coverage review

The coding assistant performs and records a rigorous semantic-coverage review before execution;
do not require an outside reviewer merely to approve the case matrix. Use the strongest available
product evidence, in this order where present:

1. Product contracts, requirements, and documented success or unacceptable-failure rules.
2. Tests, fixtures, golden files, and accepted outputs.
3. Dataset labels, examples, metadata, and schema variants.
4. Existing evaluator rules, rubrics, failure reports, and reviewed traces.

Save the detailed case matrix in `traigent-runs/calibration-cases.json` and capture executed
scores, checks, and exceptions separately in `traigent-runs/calibration-results.json`. Record only
those paths and this concise summary in `traigent-runs/run-plan.md`:

- The semantic-coverage reviewer as the coding assistant and the evidence sources, with paths,
  stable identifiers, or representative case IDs.
- The materially distinct input shapes, outcome classes, and scoring branches covered.
- The mode/threshold rationale and any evidence or coverage gap that could change correctness or
  candidate ranking.
- A semantic-coverage verdict of `sufficient` or `ambiguous`, with a concise evidence-based
  rationale.

Script/schema validation proves only that the matrix is well formed. The assistant's review must
connect the selected probes to the product's meaning of correctness. If the evidence supports a
`sufficient` verdict, proceed without asking or pausing. Run static preflight immediately, then
follow SKILL stage 4 for calibration sequencing.

If the evidence leaves unresolved product-grading ambiguity that would materially change which
output is correct or how candidate configurations rank, record an `ambiguous` verdict, ask
exactly one product-grading question that states the competing interpretations and affected
ranking decision, and **STOP and wait for the answer**. Do not invent an answer or silently
change real grading policy. After the answer, update the evidence, affected probe families,
rationale, gaps, and verdict before continuing. If implementing the answer would change real
labels, expected answers, examples, or rubric policy, show the exact judgment-dependent change
and obtain explicit approval before editing it.

For a calibration `permutation_question`, first resolve it against the semantic-coverage evidence
already inspected. If product contracts or tests explicitly establish whether order matters,
record it and continue without asking. Ask before paid work only when the competing order semantics
remain unresolved.

The bundled matrix interface accepts this exact per-case shape. Adapt the values and scoring paths
to the real task and save the JSON as `traigent-runs/calibration-cases.json`. Keep the command's
working directory at the **user's project root** so default imports resolve from that project.
Resolve the selected Python interpreter to an absolute path and resolve the absolute directory
containing the loaded `SKILL.md`; substitute those actual paths into the assignments below after
the evaluator-execution gate. Never execute the illustrative assignments unchanged, fall back to
an arbitrary `python3`, or assume the skill is inside the user's project:

```json
[
  {
    "name": "support intent - billing",
    "score_mode": "binary",
    "expected": "billing",
    "input_data": {"message": "I was charged twice"},
    "metadata": {"scoring_path": "intent"},
    "probes": {
      "good": "billing",
      "equivalent_good": "BILLING",
      "partial": "account",
      "bad": "sales"
    }
  },
  {
    "name": "required account fields",
    "score_mode": "graded",
    "expected": ["name", "email", "plan"],
    "input_data": {"message": "Extract the available account fields"},
    "metadata": {"scoring_path": "field_coverage"},
    "probes": {
      "good": ["name", "email", "plan"],
      "equivalent_good": ["plan", "email", "name"],
      "partial": ["name", "email"],
      "bad": ["shipping_address"]
    }
  }
]
```

```bash
TRAIGENT_FIRST_RUN_PYTHON="/absolute/path/to/the-selected-python"
TRAIGENT_FIRST_RUN_SKILL_DIR="/absolute/path/to/the-loaded-skill-directory"
"$TRAIGENT_FIRST_RUN_PYTHON" "$TRAIGENT_FIRST_RUN_SKILL_DIR/scripts/calibrate_evaluator.py" \
  --scorer traigent-runs/evaluator.py:task_score \
  --cases @traigent-runs/calibration-cases.json \
  --allow-execution \
  --json > traigent-runs/calibration-results.json
```

That form is for a calibration that returns in seconds, which a deterministic scorer doing local
work does. The trigger is the ESTIMATE "When calibration runs long" has you state before the wait
starts - calls times what one call costs this evaluator - and not the budget: the budget is minutes
for every calibration at every case count, 600 seconds at the two-pair minimum `--cases` accepts, so
a reader taking that as the trigger would never use this form at all. Once the estimate is minutes -
a judge, or any evaluator costing about a minute per call - use the detached form in "When
calibration runs long" instead: this one can be killed from outside before it writes anything, and
its warnings arrive on a stderr nobody is reading.

The calibration adapter must accept the keyword arguments `output`, `expected`, `input_data`, and
`metadata`. It may translate them into an existing evaluator's unchanged local convention. The
adapter can import project modules because the import root defaults to the directory where the
command is launched. When launching elsewhere, pass `--import-root /path/to/project` explicitly;
the adapter's own directory remains available for sibling imports.

The exact thresholds depend on the metric, but reject all of these:

- All scores equal or nearly equal.
- All scores zero or all scores one.
- Equivalent-good output penalized only for wording/order/format that the product accepts.
- In `graded` mode, partial output ranked at or above a fully correct output or at or below a bad
  output.
- In `binary` mode, partial output above `--bad-maximum` (`0.2`), the threshold `bad` must clear -
  not merely below the passing score: a binary partial at `0.50` fails.
- Bad output receiving a passing score.
- Parse/evaluator exceptions converted silently to an ordinary zero. Nothing enforces this one:
  `exception_probe_advisory` reports it and leaves PASS alone - reject it yourself.

Calibration runs two sets of probes, and they answer different questions. The authored probes are
the verdict: the answers the author wrote, scored against the thresholds above, and the only thing
`passed`, the exit code, and the readiness score are built from. The supplemental probes ask what
those four cannot - a wrong answer built by reordering the expected one, and malformed or
exception-raising outputs - and they only ever raise a question, never a verdict, because a
permutation scoring full marks is correct for a genuinely order-free task and only the author knows
which this task is. That difference is also why they stay separate. A probe an author can revise
until it passes is weak evidence about a repair the author just wrote; these are generated from the
expected answer and cannot be revised, so in the re-calibration a repair requires they are the half
of the evidence not confirming its own fix. Read the first as the verdict and the second as the
questions.

For deterministic calibration, the helper runs authored probes in a credential-stripped child.
Each deterministic supplemental attempt gets a fresh child, also stripped of credentials, isolating
process-local scorer and dependency state from other attempts. This is process separation, not
sandbox isolation. Its supplemental phase shares the single `--timeout` budget. The stage-4 scope
gate ends this guide before any evaluator executes candidate code or SQL.

Read `exception_probe_advisory` as an advisory, not a verdict. The probe family exercises common
`ValueError`, `TypeError`, and runtime-error operations, plus malformed Python and JSON text that
reaches `SyntaxError` or `JSONDecodeError` when the scorer uses those parsers; it is not exhaustive.
A returned zero is consistent with a swallowed parser/evaluator exception but can also be a
deliberate unsupported-input rejection; the probes cannot prove which. Inspect the scorer's error
path with a task-valid malformed case and ensure genuine parser/runtime failures remain distinct
before optimizing. The advisory never changes the authored probes' PASS by itself.

Read `supplemental_probe_advisory` as unavailable evidence: setup failure, timeout-budget
exhaustion, or a worker crash prevented one or more generated probes from answering their question.
It never changes authored PASS. Do not count an unavailable probe as distinguished; inspect or
rerun it before relying on that supplemental evidence.

For LLM judges:

- Use a task-specific rubric with anchored score levels and strict structured output.
- Include concise-correct versus verbose-correct, polished-wrong versus rough-correct, answer
  order swap, and self-comparison probes where applicable.
- Use temperature 0 when supported and repeat borderline cases if stability matters.
- Count judge calls separately in the approval and cost estimate.
- Get explicit approval before calibration because it makes provider calls.
- Label every resulting measure as a judge score, not objective truth.

If a judge cannot pass calibration, switch to a hybrid/deterministic method or keep Evaluation
`❗`. Never optimize judge noise.

## Quality diagnosis and repair choice

The presence of a file is not readiness. Diagnose whether the real dataset and evaluator can
meaningfully rank candidate configurations before creating substitutes or spending.

Report each material finding as:

```text
❗ <Component> - <measured fact or cited examples>.
Why it matters: <specific optimization consequence>.
Recommended: repair a working copy and re-run validation.
```

Use concrete evidence:

| Finding | Evidence to report | Optimization consequence |
|---|---|---|
| Too few usable examples | Usable count; fewer than 10 is only a wiring-level signal | Each row moves the score sharply; rankings are unstable |
| Corrupted rows | Invalid count, total count, percentage, and what the named lines actually contain | Some cases never reach the agent/evaluator; reported accuracy is incomplete |
| Duplicate or narrow cases | Duplicate counts, dominant scenarios/labels, representative rows | Repetition overweights one behavior and can manufacture a high score |
| Easy-only coverage | Cite representative trivial cases and name absent boundary/failure modes | Most plausible configurations may tie near 100%, leaving no measurable headroom |
| Missing or overlapping held-out split | Split sizes and overlap evidence | No independent generalization claim is supported |
| Task-inappropriate evaluator | Show the exact rule and one valid answer it rejects or bad answer it accepts | Optimization rewards the wrong behavior |
| Degenerate evaluator | Four-probe scores, exceptions, or constant/inverted ordering | Candidate configurations cannot be ranked reliably |
| Present-but-unresolved evaluator | A file exists but no method could be honestly declared without executing it (a syntax error, or a return that plainly ignores the input) | Nothing can be scored yet; this is a repair/inspect gap on an existing file, not a create/select gap |
| Baseline ceiling | Baseline score, number and type of failures, and per-example outcomes | This sample/evaluator may show little headroom; the cause is not established |

Those findings are where to look, not what to report. When rows could not be read, the score's
reason forwards the check's own summary - a count, a percentage, and the first line each distinct
cause was seen on. Open the file at those lines and say what is actually wrong: the line, the field
the rows use against the field the run selected, and the malformation. So
`6/6 rows (100.0%) are unusable; line 1 (+5 more): missing selected input field 'input'` becomes
`every row names its question 'question' and its answer 'answer', and the run selected
'input'/'output', so no row matched - the rows are fine and the field selection is not`. The
assistant has the file open and the user does not, so relaying a summary they could have read
themselves is the one thing this stage must not do.

Then act on it: correct the shape, not the data - re-run preflight with the field paths the file
actually uses, or convert a non-JSONL file into a JSONL working copy, then re-score. The data is at
fault only when mapped rows still yield no input and expected answer, as a truncated line never can.

A conversion that drops or reorders a row while the working copy is what everything downstream reads
makes every later reference to "the third row" point somewhere the customer cannot follow. So when
the rows carry no id of their own, stamp one as you convert: each row gets its 1-based position in
the file the CUSTOMER holds, counting data rows only, as `row-<n>`. That is the stable-ID repair
already permitted below, done at the moment the position is still known rather than reconstructed
later from a working copy that no longer matches. If a row cannot be converted, keep its number
spent - the ids record where a row came from, not how many survived - and say which numbers are
missing and why.

Do not infer "easy-only" from short inputs alone. Tie the explanation to the real task: show which
decision boundaries, realistic noise, edge cases, or known failure modes are absent. If that
cannot be established from project evidence, say difficulty is unverified rather than declaring
the dataset easy.

When a per-example signal flags high response variance (the same example scoring differently
across trials), separate three causes before acting - a generic "add repetitions" only fixes the
first: (1) sampling noise from a nonzero agent temperature - pin temperature 0 for exact-match or
deterministic scoring, open it only when the scorer tolerates surface variation, and add
repetitions for genuinely stochastic configurations; (2) a configuration that structurally fails
on some models - a prompt or knob value that returns empty or erroring outputs (watch the
empty-output rate) drags every example's score and inflates variance, so exclude that
configuration rather than repeating it; (3) a brittle exact-match scorer that grades a
correct-but-differently-phrased answer inconsistently - robustify the ruler with an
equivalence-aware match or a calibrated judge. Repetitions do not fix causes (2) or (3).

When a material limitation is found, offer:

1. **Repair and re-evaluate (recommended)** - create a working copy under `traigent-runs/`, preserve
   the original, make the smallest defensible fix, and re-run static checks, compatibility, and
   evaluator calibration.
2. **Continue as a workflow demonstration** - only when the component executes safely. Keep it
   `limited` and `❗`; state before and after the run that the result is not a credible performance
   estimate. Say what this route *does* - continue now, on material this run writes or keeps.
   Never word it as a "replacement" or as continuing "once a valid one is available": a blinded
   worker offered exactly that phrasing read it as a second way to pause, so all three routes it
   presented were ways of stopping and the user was given no way to go on. This is the one route
   whose whole purpose is that the run does not stall.
3. **Pause for a user-authored fix** - provide the exact acceptance checks that the revision must
   pass.

Make objective, reversible repairs in the working copy, such as schema normalization, adapters,
stable IDs, or a disjoint split. Do not silently delete real rows, change expected answers, invent
product policy, or broaden a rubric. For those judgment-dependent changes, propose the exact diff
and ask first.

After any repair, re-run the same checks that produced the advisory, the applicable calibration,
and the readiness score. Do not clear `❗` because a file changed or because the score rose; clear
it only when new evidence resolves the limitation.

Name what changed by row id. Whenever this run repairs rows into a working copy or generates rows
to fill a gap, record both lists in `traigent-runs/run-plan.md` and say them to the user: these ids
were repaired, these ids are synthetic. A count cannot be inspected and "some rows were fixed"
cannot be audited; an id opens the exact row. Ids already do that job here - the bounded subset
records the ones it chose and an excluded degenerate gold records its own - so reuse them rather
than inventing a second way to point at a row.

## Dataset construction

Prefer, in order:

1. Reviewed product fixtures, golden sets, regression tests, or accepted examples.
2. Redacted real logs/traces with independently reviewed expected outcomes.
3. User-provided examples expanded into additional tuning candidates.
4. Fully synthetic walkthrough data.

For a fully generated walkthrough, create 28 examples by default: 18 tuning rows (3 easy, 5
medium, 5 hard, 5 very hard) plus the held-out ten. "Held-out set and claims" below owns that
split wherever its rows come from - its composition, when it is reserved, where it is written,
what it is for, when it is scored and disclosed, and why the count stays at ten.

Adjust the tuning size when cost or task shape requires it, but keep all four bands represented in
it. The held-out ten do not move.

### Topping a real dataset up to that size

A project that arrives with real rows but fewer than 28 comparable ones gets a bounded offer only
when the available generation room can make the comparison meaningfully larger; existing rows that
lack usable labels are reviewed or labelled first. Twenty-eight is a ceiling on the offer rather
than a target the run pursues by itself. Two states sit outside it. A project that maintains its own held-out split keeps that split as it stands, per
"Held-out set and claims" below, so nothing here re-cuts it. And a dataset whose tuning side holds
nothing scoreable is stopped on a split to repair, where more rows answer nothing at all.

Draw only the difference, and derive every drawn row from the rows already there so the added ones
match the task the real ones describe. Where each row lands - real and generated alike - is owned by
"Real rows reach both sets before either is topped up" below, which is this same shortfall seen from
the split's side; a placement rule here would be a second answer to one question, and the two would
be free to disagree. Never draw past 28 in total, and never draw to replace a real row.

**Agreeing can lower the ceiling, so the offer says so before it is accepted.** The rows this adds
are generated and are declared as such, so the provenance ladder below prices them exactly as it
prices any other generated row - and on a small real dataset the generated share after a top-up is
most of the set. Measured on nine real rows topped to twenty-eight: the card moves from a
small-comparison-set ceiling to a mostly-generated one, four points lower. That is the trade the
customer is being asked to make, and it is the reason the offer is a question rather than a service:
more to compare on, against a claim bounded by who wrote the rows. A topped-up dataset is a dataset
this run can compare on, not a dataset that has been improved.

### Declaring provenance

Provenance answers one question twice: was the question observed, and was the answer? Declare the
first on the row as `provenance` (or `source`), the second as `output_provenance` (or
`output_source`) - either at the top level or under `metadata`.

Each row earns its own share of the 10 provenance points, and the sub-score is their average:

| The row | Points |
|---|---|
| Observed question, observed answer | 10 |
| Observed question, answer written by a model | 6 |
| Says nothing about where it came from | 3 |
| Neither was observed | 3 |

A row that says nothing scores as a generated row: silence is not a declaration.

Because it is a per-row average, a mixture scores like a mixture: 99 collected rows and one
generated one score 9.93, not 3. What a mixture cannot do is escape a ceiling - see the cap ladder
below.

Words are matched by prefix, so `production-2026-q1` and `synthetic-walkthrough` both land where you
would expect. `scripts/preflight.py` declares the three classes once and is the only copy:
`SYNTHESISED_SOURCE_PREFIXES` (nobody observed this), `COLLECTED_SOURCE_PREFIXES` (somebody did),
and `UNDECLARED_SOURCE_TOKENS`, matched whole not by prefix - a row saying `n/a` or `tbd` declines
to answer, scores 3 like a row with no field, raises no vocabulary warning, and prints as
`declared sources: n/a` under a card line calling it undeclared.

A word on none of the three is read as `undeclared` too: it scores 3 like a row with no field and
never above a row that declares itself generated, because an unverifiable declaration must not
outscore a verifiable one - `crm-export` and three junk characters read the same from here.
Preflight raises `dataset-provenance-vocabulary` naming the word and the card prints both grades,
so a project using its own vocabulary sees what one relabel onto the lists above is worth before it
changes anything. If the data is generated, say so with a word from the first list.

Do not express a generated answer in the row's own `provenance` token: that marks the whole row
generated, scoring 3 rather than 6 and moving it under the synthetic ceilings.

### Provenance ceilings

Points alone cannot keep a score honest here: provenance is 10 points inside a pillar worth 40% of
the total, so the whole 10-to-3 range moves the overall score by under 3 - a fully generated dataset
perfect on every other dimension still reported 93. So how much of the data was invented also sets a
ceiling on the entire run:

| The dataset | Ceiling |
|---|---|
| Every row generated, or no row declared collected | 65 |
| More than half generated or undeclared | 70 |
| Real questions, but most expected answers written by a model | 74 |
| Real questions, but every expected answer written by a model | 74 |

An undeclared corpus reaches the first two rungs exactly as a generated one does. It asks for a
declaration rather than new data unless over half the corpus is declared generated - a ceiling no
declaration can lift. Half declared collected and half silent is 50%, under the threshold, and is
capped by neither. The two differ only in the remedy: declaring is a change to the file rather than
data anyone has to go and collect, so the undeclared rungs put that word to the customer where the
declared twins ask for nothing. Neither holds the paid run. The question rides on the approval that
already halts before the first billed call. Its two answers are not the same size: saying where the
rows came from lifts the ceiling, and agreeing to run without saying leaves the number and the band
exactly where they were.

The ladder is ordered by how much of the result is the model talking to itself. The last two rungs
are the highest because the questions are still real - but an accuracy number computed against an
answer key a model wrote reports agreement with that model, not correctness, and nothing inside the
run can falsify it. All four rungs stay inside Workable: data a model supplied, on either side of
the row, can be workable and cannot be good. The answer-key rungs are 74 and not 75 because 75 is
the Strong boundary itself, and presenting as Strong is the one claim they exist to refuse. They
are also not raised at all for a corpus where no row was observed: the 65 above governs there and
says strictly more.

The last two share a ceiling and a remedy, and differ only in how much of the key it covers. Each
bounds the run and never stops it: the review is what to do first rather than instead, and neither
waits for it. When most of the expected answers are a model's, the review covers
those answers only; when *all* of them are, a sample of the whole key, because nothing left in it
was written by anything but the kind of thing the run is scoring. The rung exists because with one
rung the cap turned on the last row: a dataset with every answer generated was capped at 74 and the
same dataset with one human-written answer scored 94 and Excellent.

A ceiling is not a deduction: the pre-cap average stays in the output, and the number simply cannot
claim more than the data supports. Whether the run also waits is the remedy's answer, not the
ceiling's.

Every generated row must:

- Have a unique stable `id`.
- Record `difficulty`, `source: "synthetic"`, and a short `coverage`/scenario tag.
- Match the exact agent input and evaluator gold contract.
- Have a correct, scoreable expected outcome.
- Represent a distinct scenario, not a superficial paraphrase.
- Avoid secrets, PII, proprietary content, or claims that it came from real users.

Run quality checks:

- Usable count and corrupted-row percentage.
- Repeated inputs: exact duplicates, and near-duplicates at or above the similarity line
  `preflight.py` prints on the check's own line - one finding, scored once.
- Duplicate IDs.
- Normalized duplicate outputs/labels where diversity is expected.
- Missing difficulty bands.
- Repeated scenario tags that crowd out coverage.
- Tuning/holdout overlap by ID and normalized input.
- A tuning/holdout split drawn along the task families instead of across them - disjoint inputs, and
  every recurring kind of input on one side only. `preflight.py` infers the kinds from the leading
  words of each input and reports on its own line whether they cross the split; it skips rather than
  passes where no form recurs, because a corpus of one-off phrasings gives it nothing to read.
- Constant or empty expected outputs.
- Agent/dataset contract consistency, confirmed later through the installed SDK's public
  validation or safe mock execution rather than a first-run reimplementation.
- Difficulty, boundary, and known failure-mode coverage.
- Dominant-output or majority-label baselines that could hide a ceiling. For structured output,
  inspect common label/category fields and pass `--outcome-field result.label` to the static
  preflight when the task's discrete outcome uses a nonstandard or nested field.

When a scorer compares against gold references, run every real reference through it before trusting
an aggregate score: count references that are degenerate (empty, constant, or that score a right and
a wrong answer identically), tell the user what fraction is unscoreable, and quote accuracy on the
reliably-scoreable subset with that caveat rather than the raw aggregate. Even authentic benchmark
data carries some - for example empty or case-sensitive golds - and a small random slice can land on
a cluster of them.

This is a report-and-continue case, not a question to put to the user, and the difference is worth
stating because the guide's ambiguity rule looks as though it applies. It does not: when a real
gold scores a right and a wrong answer identically - empty, constant, or matching nothing because
of a leading space or a case-sensitive comparison - there are no competing interpretations to
offer. No configuration can earn that row, so it separates none of them.

So name the count and the share, quote the result on the subset that can actually be scored, and
record the excluded row ids so the run repeats exactly. That recording is unconditional. The
bounded first-run subset records its own ids, but it is only drawn with more than 100 usable rows - so on the
small datasets where a handful of degenerate golds decides the outcome, nothing else would be left
behind at all.

Do not offer scoring the full set as an equal option. Those rows hand free points to any
configuration that emits valid-but-empty output, so including them biases the ranking toward bad
configurations, and a menu listing a known-bad choice beside the right one is not a real question.

Two conditions bound the exclusion, and both exist to stop it quietly changing what the run
measures. What remains must still be enough for the scorer to call the comparison a measurement
rather than a wiring check - the same floor the card itself names - and the degenerate rows must be
a minority of the set. When either fails, the exclusion is the story rather than a footnote, so
stop and ask instead. Repairing a gold is a different act in any case: it edits the user's expected
answers, so it stays behind the explicit approval the action table requires and is offered only if
the user asks for it.

Do not manufacture deliberately wrong gold labels or ambiguous inputs merely to make the
optimization look better.

Any check that judges whether a row's expected output follows from its input runs on rows the
customer brought and skips rows this run generated. The synthetic ceiling already bounds what a
generated corpus may claim, so re-judging those rows buys no claim they could make anyway, and it
is the model marking its own homework. That check exists for the other case, where a human wrote
the pairing and can have got it wrong. Stated once, here.

## When calibration runs long

Before the stage starts, say what it does and how long it may take: it runs the user's evaluator
over a few known-good and known-bad answers to prove it separates them, four probe calls per
input/expected pair. Multiply those calls by what one call costs the evaluator and state the
number - for a judge, a model call per probe, that is minutes rather than seconds. Finishing
matters more than finishing fast: an evaluator nobody could measure makes every later number
unverifiable.

The script budgets itself the same way, per probe call rather than as one flat number, so a 3-5
pair matrix leaves room for an evaluator taking about a minute per call. That one budget covers the
authored probes and the supplemental ones together, so `--timeout` is the whole wait rather than
half of it, and a calibration slow enough to spend it loses supplemental probes rather than
extending the wait - which the `ADVISORY` line on stderr then names.

**Fifteen minutes is the ceiling on that budget, and say so before the wait starts.** This is
onboarding rather than a full-power run: a calibration that has not separated a good answer from a
bad one in fifteen minutes most probably will not, and the timeout is itself a result to act on.
The ceiling bounds the wait, not the work, so a large case set is cut below the per-probe rate the
budget was derived at: whole to three pairs deterministic and two for a judge, and at five pairs
either way each probe gets 45 seconds - which is a 40% cut against the 75 the deterministic budget
is derived at, and exactly half the 90 a judge is. The judge is cut harder at every size past two
pairs, so quoting one number for both understates what a judge loses. Tell a user whose evaluator takes about a minute per call what that means for them: at that
speed a five-pair matrix cannot finish inside the ceiling, so run fewer pairs or expect the timeout
question. Their own larger `--timeout` is not capped; the ceiling only bounds what this stage
chooses on its own.

**There is no resume.** The authored probes all run in one child that reports only once every case
is done, and nothing is written until it returns, so a calibration stopped part-way records
nothing and a re-run starts at the first probe. Two minutes before the budget expires the script
says exactly that on stderr, in the log the detached invocation below already has you polling.
Relay it as a warning and do not turn it into a "stop or continue" question: continuing costs the
minutes that are left, stopping costs every minute already spent, and offering those as a choice
hides that they are not the same size. The question with real alternatives is the one below, asked
after the budget has actually been spent.

That wait can outlast the point at which a foreground command is killed from outside (see
`references/run-safety.md`), and a calibration killed from outside writes no result at all - not
even the timeout record that makes a slow evaluator legible instead of broken. So run it detached
and poll the log, the same way that reference already requires for a long paid optimization:

```bash
nohup "$TRAIGENT_FIRST_RUN_PYTHON" \
  "$TRAIGENT_FIRST_RUN_SKILL_DIR/scripts/calibrate_evaluator.py" \
  --scorer traigent-runs/evaluator.py:task_score \
  --cases @traigent-runs/calibration-cases.json \
  --allow-execution \
  --json > traigent-runs/calibration-results.json 2> traigent-runs/calibration.log &
```

If a specific avoidable cause is visible - a per-call sleep, a retry loop, an uncached model load -
name that fix in the readiness summary, and again at the close if it was not taken.

On a timeout do not call the evaluator broken; slow and broken look identical from here. Ask once -
one question carrying every option that applies, never one question per option:

- **Wait**, if the evaluator is normally this slow. Re-run with an explicit `--timeout` and size it
  for both phases: calls times cost covers the authored probes only, and the supplemental ones then
  get what is left of it, which is nothing. Say so before the re-run rather than letting the
  `ADVISORY` line report them unavailable afterwards.
- **Take a named fix**, when the cause is certain.
- **Score it differently**, bounding what one scoring call costs: a cheaper judge model, or a
  deterministic comparison - an exact or normalized match against the expected answer, no model
  call - where the task allows one.
- **Retry**, since a provider call that has stalled looks the same from here.
- **Build a new evaluation method** together.

Repeated questions cost more attention than the wait they save.

### The row-level sanity check

Every check above reads one column. Empty golds, constant golds, duplicate inputs, a dominant
answer, an overlapping split - each looks at one field on its own, and none of them reads a row's
input beside its own expected output. So this row passes all of them:

> input: `Refund requested 45 days after purchase; the policy window is 30 days` ·
> expected output: `approve`

Well-formed, unique, difficulty-tagged, perfectly scoreable - and simply wrong. The search then
rewards whichever configuration gets it wrong, and on a ten-row held-out set one bad expected
answer moves the reported number by ten points, which is larger than the gaps configurations are
ranked by.

So read each row and answer one question about it: **is this expected output a sensible answer to
this input?** Answer `yes`, `no`, or `unsure`, with the row id and one sentence.

When the rows carry no stable id - which `preflight.py`'s `dataset-ids` check reports as a warning
on exactly this dataset - use the 1-based source line as `line-<n>`, and say in the conversation
that the ids are positional. Any scheme satisfies the scorer, and that is the problem: four runs
over one dataset each invented their own, and two review documents written for the same file cannot
be compared unless the ids mean the same thing. The line number is chosen because it is the one
identifier the file already has, and because preflight's own warning quotes source lines, so a user
told `line-7` can find row 7 without a mapping. It is not an id the customer owns - if they later
add stable ids, the next run uses theirs.

That reason is also its whole scope, so state it rather than assuming it. A line number identifies a
row only where the file the CUSTOMER holds is one row per line, and `preflight.py` skips blank lines
while still counting them, so one blank line makes `line-7` the sixth row. Use `line-<n>` only for a
JSONL file the customer wrote, and check the last number against the row count rather than assuming
they agree.

Anything else arrives here already carrying `row-<n>`, stamped as it was converted above, because
that is the only moment the customer's own row position is still known. Read that id; do not
re-derive one from the working copy, which no longer numbers what they hold. Two conventions and one
rule: the id names a position in the customer's own file either way, and the run says which
convention it used, because `line-` and `row-` count different things - an id nobody can resolve
against their own file is the mistake here, not the scheme used to build it.
Record the answers
where `SKILL.md`'s opening gate places a scoring's own files, and pass that file to
`scripts/readiness.py --row-review`:

That file is this run's own read, not the customer's material, and it is the one thing a run leaves
in their project - which is why the opening message names it instead of claiming the score wrote
nothing. Every opening gate rewrites it whole. So a re-score after the ask is answered supersedes
it, whether the answer keeps the dataset or points at a different one, and an earlier verdict never
survives to be read as current. A run that stops at the ask leaves it standing as the record of the
score it produced, which is the state it is written for rather than an accident of stopping early.

```json
{
  "reviewer": "assistant",
  "rows": [
    {"id": "ticket-118", "origin": "collected", "verdict": "no", "in_run": true,
     "note": "45 days against a 30-day window, so 'approve' contradicts the input"},
    {"id": "ticket-119", "origin": "undeclared", "verdict": "yes", "in_run": false,
     "note": "inside the stated window, so the expected answer follows"}
  ]
}
```

`origin` is preflight's normalized class, not the row's literal word. A user-owned row declared
`real`, including one written by hand, uses `collected`: it means not generated here, not
event-log data. A walkthrough/model-generated row uses `synthesised`; an unrecognized declaration
uses `undeclared`. In conversation keep the customer's word: "your real rows", not "your collected
rows". The sentence is required on every
verdict - it is what makes a reading inspectable instead of a tally. `in_run` says whether this run
reads that row; set it on every entry or on none, because a file that answers it for some rows lets
the silent ones read as "outside the run". Five rules govern what the answers may do.

**It is your own read, not a billed call.** The dataset is already open. Nothing here calls a model
through the SDK, so it spends nothing, touches no ceiling, and needs no approval - which is why it
can inform the opening readiness gate at all.

**It reads the rows the user brought, and skips the rows this run generated.** That is its purpose
rather than an exemption: it exists to test the data the run cannot vouch for. Generated rows are
bounded by the synthetic ceiling however good they are, most of them will be fine, and a model
re-judging output it wrote itself is marking its own homework. `readiness.py` refuses a review entry
whose origin is `synthesised`, and counts the skipped rows from preflight rather than from the
review.

**It bounds the run and never stops it.** An assistant's opinion may withhold a claim; it may not
manufacture one, and it may not cancel a paid run the user's own sound rows have earned. A material
share of `no` verdicts lowers the ceiling to 70 (`dataset-unsound-expected-outputs`) and the run
proceeds; a clean pass earns no points, no band, and no credit of any kind. What a clean pass does
earn is a sentence in the readiness evidence line, which costs zero score and names who did the
checking. An `unsure` is reported there too and never scored, because uncertainty is not a finding.

Three things put the ceiling there rather than a stop. The run only ever reads the tuning rows plus
the held-out ten, so a wrong answer among rows it never opens changes nothing that happens. On
collected data this reading can be wrong - a refund approved outside the stated window can be the
user's goodwill rule rather than a mistake, and you cannot tell from the row. And the remedy is
`review-answer-key`, a question put to the user rather than a creation or a repair, which is the
same remedy `dataset-generated-answer-key` carries and is scoped the same way.

**A `no` is never a silent edit, and it opens a conversation.** Put the findings to the user before
the run, in this shape:

> I suspect this dataset has rows that need fixing before the run.
>
> - `ticket-118` - input: *"Refund requested 45 days after purchase; the policy window is 30 days"*,
>   expected: `approve`. 45 days is outside the 30-day window the input itself states, so `approve`
>   contradicts it. **This row is in the 28 the run will use.**
> - `ticket-204` - ... (one line per row: the id, the quoted input and expected answer, the reason)
>
> I intend to fix these before the run - do you agree or disagree?

Give every flagged row: the id, the quoted content, and the reason. **Say which of them are inside
the rows this run will actually use** - the 18 tuning rows and the held-out ten. That is the
difference between "your file has a bad row" and "the run is about to be tuned on a bad row", and
only the second one changes what this run measures. Set `in_run` on every entry once those rows are
drawn, so the readiness card says it too; leave it off every entry while they are not.

Drawn means settled, not selected by this run. A split the customer brought is already settled, so
`in_run` is set at the opening gate even though nothing was drawn - the bounded subset is taken only
above 100 usable rows, so on a small brought split no draw ever happens and reading the rule
literally would leave the flag off for the whole run. What leaves it off is rows whose membership is
genuinely unsettled: no declared split, and no subset taken yet. The distinction has to be stated
because both readings pass validation and the card differs - with the flag set it reports how many
flagged rows this run reads, and without it that sentence cannot be said at all.

Then take the answer, because tuning the agent over a correct dataset is what the run is for:

- **Agree** - repair the rows in the working copy, re-run the check, and re-score.
- **Disagree** - proceed with the rows as they stand, and say in the run's own report what it was
  tuned on: the rows you read as wrong, that the user kept them, and that the accuracy figures
  include them.

This is deliberately the opposite of the degenerate-gold rule above, and the contrast is the point.
A gold that scores a right and a wrong answer identically offers no competing interpretation, so it
is reported and excluded without a question. A gold reading `approve` where the input says 45 days
against a 30-day window offers exactly two - the answer is wrong, or the task is not what you took
it to be - and only the user can settle which.

**It is declared as your judgement, never as the user's ground truth.** The file names
`"reviewer": "assistant"` and readiness refuses any other value, so a verdict can never be filed as
though the user gave it. If they approve a repair, the repaired row follows "Declaring provenance"
above: its expected answer is now model-written, carries `output_provenance` saying so, and stops
counting as an answer anyone observed.

Say how much you read. Readiness scores the whole dataset and never a subset, so the evidence line
reports the rows read against the rows the user brought. At or under the size where "First-run
subset for a large dataset" applies, that is all of them. Above it, read what one pass can cover at
the opening gate and let the line name the count - then read the drawn rows again at the stage-4
re-score, because those are the rows the comparison actually runs on.


### Choosing rows when difficulty is not labelled

Every pick this file asks for - the bounded subset below, the reserved split after it - wants
difficulty spread first, because a pick that lands in one band measures one band. Work down this
ladder, stop at the first rung that holds, and record that rung wherever the pick itself is
recorded:

1. **The rows carry difficulty tags.** Stratify on them.
2. **Rank the rows yourself.** You are reading them anyway, so a ranking you can defend is evidence
   you already have, and falling through to a random sample throws away a free judgement. Use it
   only while the ranking is clear by the test below.
3. **The rows carry other tags** - coverage, scenario, topic. Judge by that same test whether those
   groups actually differ in difficulty. If they do, stratify on them as a difficulty proxy and name
   the axis. If they all sit at one level, spread the pick across them anyway - spread beats
   clustering on any axis - but call that topical spread, not difficulty spread.
4. **Neither holds.** Take a seeded random sample and record the pick as unstratified.

Difficulty is clear when the bands differ the way school levels differ: a question a bright
12-to-15-year-old would just answer, against one that needs real research and close reading. A
short single-table SQL query against a long multi-join one. "How many X are in Y" against a PDF,
against "what is the main idea of this article". A lookup of known data, against "compare what this
article says about J with what is known today, and say who is more correct, and why".

"Clear" has to be falsifiable or it is a feeling, and that test is the falsifier: it asks the
estimate to separate the extremes, not to order the middle. Rows that all sit at one level can
still be ranked, and the ranking is still one level. When they do not separate, say so and take the
next rung.

An estimate is the assistant's opinion, not a label the user supplied. Declare it as "Declaring
provenance" above declares an answer nobody observed - `difficulty_provenance`, top level or under
`metadata`, from those same two word lists - and on rows the user brought, keep it out of the
`difficulty` field itself. That field is scored: filling it converts "declares no difficulty" into
full band coverage and clears the spread complaint on the assistant's own opinion, which is the one
thing a self-ranked pick must not be able to do. A generated row is the other case - whoever wrote
the question wrote its band too, and the row already declares itself generated.

## First-run subset for a large dataset

A first run has to show the capability, not exhaust the dataset. With more than 100 usable rows,
every trial pays for every row, so a large set turns the walkthrough into a long, expensive run
that demonstrates nothing the smaller one would not. Select a bounded subset instead: **18 tuning
rows by default**, at least four from each of the four difficulty bands (`easy`, `medium`, `hard`,
`very-hard`), so the subset keeps the spread that makes a result informative rather than landing on
one cluster - plus the held-out ten below, drawn to their own composition.

Five rules make the subset honest:

1. **Score the dataset, not the subset.** All readiness scores - the opening gate, each repair or
   validation gate, and the post-run read - run on the **whole** dataset. The subset is chosen
   afterwards, as run scoping, immediately before the paid comparison. Getting this backwards makes
   the user's data wear the run's limitation: measured through `scripts/readiness.py` on 500
   labelled, difficulty-tagged production rows, the dataset pillar sees 249 comparable examples;
   the same dataset scored as an 18-row subset sees only 8 and calls it `a wiring check, not a
   score`. That sentence is true of the run and false of the dataset, and the gate re-score would
   read 18 points below the opening one on nothing but our own sampling. Difficulty and diversity
   survive a compliant sample; evidence volume collapses, so that limitation must be attributed
   correctly.
2. **Report the run's sample-size limitation separately.** It belongs in the run report, not the
   dataset score: "this run compares configurations on 18 of your 4,812 rows; treat a small
   difference as directional unless paired uncertainty from the completed outputs supports it."
   Sample size alone cannot supply a confidence interval or minimum detectable effect for a paired
   comparison, so never invent a percentage-point threshold before those outcomes exist.
3. **Sample within each split, never across it.** Draw the 18 tuning rows from the tuning split
   and the held-out ten from the held-out split, keeping them disjoint. A subset drawn over the combined
   set can pull the same input into both sides and fabricate a tune/holdout overlap that the
   original dataset did not have.
4. **Record what was chosen.** Write the selected row `id`s to `traigent-runs/run-plan.md`, plus
   the seed when the pick inside a band was random. The recorded ids are what makes the run
   reproducible - a seed alone does not, because the selection also depends on judgment about which
   rows are hard.
5. **Name the bound to the user.** Report the subset size beside the full row count ("18 tuning
   and 10 held-out rows of your 4,812 for this first run"). Never let a bounded run read as though
   the whole dataset was evaluated.

Keeping at least four rows from every band is what protects the spread: a careless trim to 18 that
drops a band costs difficulty points and prints a spread complaint about a dataset that has all four.

When the rows carry no difficulty tags, work down the ladder in "Choosing rows when difficulty is
not labelled" above. An unlabelled pick is still bounded and reproducible, just less
representative, and that limitation belongs in the report.

The full dataset stays the dataset. A real optimization after the walkthrough runs against all of
it, and over a wider knob space than this first look reaches; this bound exists only so the first
run finishes.

## Held-out set and claims

Reserve 10 held-out rows (2 easy, 3 medium, 3 hard, 2 very hard) at creation time, before any
component design, calibration, or optimization touches the dataset, and keep the same rows aside
for the rest of the run. That composition holds wherever the rows come from - a fully generated
walkthrough or a bounded subset drawn from a large real dataset alike - because the rule governs
the split this run reserves, not where the data originated. A project that already maintains its
own independent held-out split is the exception: use it as it stands rather than re-cutting it
to ten, and follow every claim rule below. When the rows carry no usable difficulty tags, work down
the same ladder the bounded subset uses, and record the rung the split was cut on.

**Real rows reach both sets before either is topped up.** Take the customer's own rows first
and generate only the shortfall - and when there are too few to fill both sets, divide the real
ones between them in the same proportion as the sets themselves, rounding in the tuning set's
favour, before a single row is generated. Against the 18/10 default that is about two real rows to
tuning for every one held back: ten real rows split seven and three, four split three and one, two
split one and one. Below two there is nothing to divide, so the one row goes to tuning where the
search can at least see it. Filling one set with the real rows and generating the other is the
failure this rule exists to stop, and it fails in both directions: a held-out set of generated rows
validates nothing about real inputs, and a tuning set of generated rows searches a task the
customer does not have.

Then top each set up to its composition with generated rows rather than dropping a band, placing
each real row in the band its own difficulty puts it in, and declare the mixture through the
provenance fields above so the row says what it is. State what the top-up costs rather than leaving
it implied: a generated held-out row cannot show that the winner generalizes to real inputs, only
that it survives rows the tuning search never saw. Such a split is non-blind either way, so the
synthetic-evidence rules at the end of this section already govern what it may claim.

Write the reserved rows to their own file. The tuning rows and the held-out rows are two files,
not one file with a column, because that separation is what physically keeps a reserved row out
of the search: the optimization's `eval_dataset` names the tuning file only, so no candidate
configuration can be scored on a held-out row even by accident.
`references/sdk-execution.md` carries the two paths and the scoring code. The combined,
split-labelled dataset stays the input to preflight and readiness - it is scoring evidence about
the data, never the search's input.

Two files is a choice, not a limitation the SDK imposes: `eval_dataset` also takes rows directly,
so the search could be handed a filtered slice of one file instead. It is still the safer shape,
because a filter is a predicate that has to keep being right, while a file the search was never
given cannot leak a row however the predicate drifts - and it is two files, written beside the
user's untouched original, not a folder of them.

Ten rows is the design, not a placeholder on the way to a larger split. Ten is what the
composition costs: 2 easy, 3 medium, 3 hard, 2 very hard, no band holding a spare. Take one from
an outer band and it drops to a single row, whose one outcome becomes that band's whole result - a
band present without being measured. Take one from a middle band and the split loses resolution
where configurations separate, which is why those two carry more. Nine rows is not a smaller
version of this split; it is this split with a hole in it. Above ten,
each extra row is another paid call on the winner bought from the same walkthrough ceiling, spent
on the check instead of on the search this run exists to show. Ten is therefore exact in both
directions, never a floor to grow from. The one split that is not ten is a project's own, kept at
the size it already has, whatever its composition. So the resolution stays coarse, and
the honest move is to say so plainly rather than to grow the split until the number sounds
authoritative. What this walkthrough shows is what Traigent can do; the full picture comes from
running the whole dataset over a wider knob space, as "First-run subset for a large dataset" above
already says.

A gap between the tuning score and the held-out score is expected, and it is explained by two
separate things - neither is a bug:

- **Selecting on the tuning rows inflates the tuning score.** Scoring several candidate
  configurations on the same rows and keeping the best one selects partly on real signal and
  partly on that sample's noise. The winner's tuning score is inflated by the act of choosing it
  and will not fully repeat on a fresh sample even when nothing is actually overfitted. This is
  exactly what the held-out rows exist to check.
- **Ten rows cannot resolve a small gap.** One *standard error* on an accuracy measured from ten
  items is about 15 points near 50% and still about 10 points near 90% - and a 95% interval is
  roughly twice that, about +/-31 and +/-19 points. Quote the interval as the interval; a standard
  error presented as "the uncertainty" understates it about twofold. This bounds one accuracy from
  its sample size, and is not the paired uncertainty rule 2 above defers until outcomes exist. A
  gap inside that range is neither confirmed overfitting nor confirmed fine - it is inconclusive,
  and no wording should claim otherwise.

Do not say Traigent prevents or corrects this: holdout support is not yet a first-class SDK
feature, so that claim would not be true. Do not call a gap in this range "overfitting," either -
name it for what it is, the ordinary result of picking the best of several configurations on a
small sample, and say plainly that ten examples cannot tell how much of it is real. Giving
Traigent real holdout support instead of this guide-authored split is tracked internally as a
Traigent-owned follow-up - never surface a repository, issue, or tracker reference to the user;
the disclosure note below stays free of one.

Score the held-out rows once, on one configuration: the one this run recommends. This walkthrough
pays for two measurements, the baseline grid and the enhanced search, so select it on the **tuning**
scores across both of them - the tuning rows are the ones already spent on selection. The enhanced
search's winner is not the answer by position: when the baseline's best configuration still scores
higher on the tuning rows, that is the one this run recommends and the one that gets scored. Then
run that configuration, and only that configuration, against the reserved rows. Include those calls
in the combined paid-work approval alongside the enhanced search.

**The held-out rows arbitrate nothing.** Scoring two configurations on them and keeping whichever
came back higher is selection, and a set used for selection is not held out: its number would carry
the same optimism as the tuning score, which is the single thing this split exists to avoid. It
reports on a candidate that was already chosen; it does not choose one. So the choice is made where
selection is already paid for, and only its outcome is measured here.

Cost belongs in that choice, on the tuning side. When two configurations score the same on the
tuning rows, prefer the cheaper one; at equal cost prefer the stronger model, whose headroom a
wider search after this walkthrough is likelier to use. That is a decision taken on the rows
selection is allowed to use, so it costs the held-out set nothing.

SKILL stages 7 and 8 own when that score is disclosed. The split itself does not change between
the two checkpoints; only its disclosure moves, so the walkthrough shows one comparison, once,
when the winner it is scoring actually exists. Report it as one line each, not as a statistics
lesson:

```text
Tuning set (<n> ex):   <correct> of <n> correct
Held-out set (<m> ex): <correct> of <m> correct
Note: the best of several configurations was picked on the tuning rows, so the
held-out number can land lower, level, or higher. <m> examples cannot settle
which.
```

Report counts, not percentages, while the split is this small: on ten rows only multiples of ten
exist, so "60%" claims a resolution of one point where the truth is ten - and the static preflight
already prints that arithmetic for whatever size the split actually is. Substitute the run's own
`<n>` and `<m>`; a project that brought its own 500/120 split copies its numbers here, not the
walkthrough's. Keep the note only while one row still moves the held-out figure materially. On a
held-out set large enough that it does not, drop the note rather than pasting a caveat the
numbers do not need.

Then say the forward half out loud instead of leaving it implied: at full capability this same check
runs over the customer's whole dataset, and that is where real-world validation actually happens -
the walkthrough is showing the shape of that step cheaply rather than performing it, which is a
choice and not a shortfall. State it without apologizing for the ten rows and without saying what a
larger run would find; the close's skills handoff is already the route to it.

When the split was topped up, say so on the same line as its score. "Held out" is a claim about what
the search never saw, not a claim that the rows came from the customer's world, and a reader who is
not told the difference will hear the second one. The details layer below carries the counts.

Name both written files in the closing summary's details layer, by absolute path -
`<project root>/traigent-runs/tuning.jsonl` and `<project root>/traigent-runs/holdout.jsonl` - and
say the reserved rows are the second one, so a user who wants them gone knows which file to open.
Both are derived: their dataset was read and rows were copied out of it. Nothing was moved and
nothing has to be put back - the original was never modified, lost no row, and stays the canonical
copy - so deleting either derived file loses nothing. This is housekeeping, so it goes below the
outcome and the recommendation, never beside them.

Those two are not the only files this run wrote, and a user who wants to know where everything
went should not have to ask twice. In the same layer, list the rest under the same project root:
`traigent-runs/run-plan.md`, `traigent-runs/run-log.jsonl`, `traigent-runs/config-space.json`,
`traigent-runs/calibration-cases.json`, `traigent-runs/calibration-results.json`, plus any
`traigent-runs/walkthrough_agent.py`, `traigent-runs/evaluator.py`, readiness report, and
SDK run logs that exist. Name only what was actually written. The sentence above covers all of
them - every one is derived, and that whole folder is git-ignored and can be deleted without
losing anything. Four writes sit outside the folder and are not covered by it: the
`/traigent-runs/` line added to the project `.gitignore`; the provider key line in `.env`, or the
whole file when this run created it; the dedicated first-run virtual environment at the project
root, `.venv-traigent`; and the credential handoff when the user named a file of their own, which
is outside the project by definition. Name only the ones this run actually performed, and for the
last two give the absolute path, because "delete the folder and nothing is lost" is false of them
and a reader cannot find them from here. Existing environments and their site-packages are not
first-run writes: this guide preserves them.

Skills installed during this run are the one item the list cannot hand over ready to use. Name the
absolute directory the install wrote to; it is outside the project, so deleting `traigent-runs/`
never removes it and removing a skill means deleting that directory. Skills load when a session
starts, so a skill installed here is inert in the session that installed it. Say it plainly: start
a new session, or refresh this one, and they are available.

One thing does have to travel back, and only the user can carry it: a repair made under "Quality
diagnosis and repair choice" above lives in the working copy, so their own dataset still has the
defect this run worked around. Name what changed and in which rows, and leave applying it to them.
Offer it; never write it.

Those are three kinds of row, and the details layer keeps them apart: a row the customer brought, a
row of theirs this run repaired - named just above - and a row this run generated. Merging them into
one "modified" bucket destroys the only answer the user came for, which is which rows are whose. A
repair changed a field, not an origin, so that row is still theirs; only a generated row is ours.
Give each set its own line saying it as a mixture - how many rows are the customer's and how many
this run generated, with the generated ids. That is counts and ids rather than a path because the
generated rows sit in those same two files, interleaved with the real ones; there is no third file
to point at. The provenance fields the rows already carry and the id lists this run already writes
are where both numbers come from.

Call it a sealed holdout only when its split and labels were fixed and hidden from component
design, tuning, and winner selection until the candidate was locked. Because the assistant creates
and can inspect the generated split, call the held-out set held-back and non-blind instead.

Synthetic examples may support later promotion validation only after independent human review
against the real task and only when the split and labels remained sealed from design, tuning, and
winner selection. This is a later production-promotion safeguard, not a calibration gate or a
reason to pause the first walkthrough. Until then:

- Report them as synthetic, non-blind held-out evidence.
- Do not promote the result to production.
- Do not describe the measured lift as expected customer lift.

Beside those two totals, report the paired outcome counts - how many examples the enhanced winner
scored correctly that the baseline did not, how many went the other way, and how many tied. This
is required on the ten-row default, not only above it: at that size the paired counts are the
whole resolution the split has, and a percentage claims one it does not. State a difference as
directional unless a justified paired uncertainty analysis supports a stronger claim.
