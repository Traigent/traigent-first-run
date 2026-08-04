# Evaluation and Dataset

Use this reference whenever creating or validating a dataset or evaluation method.

## Contents

1. Evaluation selection
2. Mandatory calibration
3. Quality diagnosis and repair choice
4. Dataset construction
5. Validation split and claims

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
- In `binary` mode, partial output receiving a passing score.
- Bad output receiving a passing score.
- Parse/evaluator exceptions converted silently to an ordinary zero.

For deterministic calibration, the helper runs authored probes in a credential-stripped child.
Each deterministic supplemental attempt gets a fresh child, also stripped of credentials, isolating
process-local scorer and dependency state from other attempts. This is process separation, not
sandbox isolation. Its supplemental phase may use one additional `--timeout` budget. Follow the
SKILL stage-4 gate for permitted paths; `run-safety.md` owns execution-evaluator containment.

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
| Corrupted rows | Invalid count, total count, percentage, and representative line errors | Some cases never reach the agent/evaluator; reported accuracy is incomplete |
| Duplicate or narrow cases | Duplicate counts, dominant scenarios/labels, representative rows | Repetition overweights one behavior and can manufacture a high score |
| Easy-only coverage | Cite representative trivial cases and name absent boundary/failure modes | Most plausible configurations may tie near 100%, leaving no measurable headroom |
| Missing or overlapping validation split | Split sizes and overlap evidence | No independent generalization claim is supported |
| Task-inappropriate evaluator | Show the exact rule and one valid answer it rejects or bad answer it accepts | Optimization rewards the wrong behavior |
| Degenerate evaluator | Four-probe scores, exceptions, or constant/inverted ordering | Candidate configurations cannot be ranked reliably |
| Present-but-unresolved evaluator | A file exists but no method could be honestly declared without executing it (a syntax error, or a return that plainly ignores the input) | Nothing can be scored yet; this is a repair/inspect gap on an existing file, not a create/select gap |
| Baseline ceiling | Baseline score, number and type of failures, and per-example outcomes | This sample/evaluator may show little headroom; the cause is not established |

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
   estimate.
3. **Pause for a user-authored fix** - provide the exact acceptance checks that the revision must
   pass.

Make objective, reversible repairs in the working copy, such as schema normalization, adapters,
stable IDs, or a disjoint split. Do not silently delete real rows, change expected answers, invent
product policy, or broaden a rubric. For those judgment-dependent changes, propose the exact diff
and ask first.

After any repair, re-run the same checks that produced the advisory, the applicable calibration,
and the readiness score; record the new score, band, and caps beside the opening result. Do not
clear `❗` because a file changed or because the score rose; clear it only when new evidence
resolves the limitation.

## Dataset construction

Prefer, in order:

1. Reviewed product fixtures, golden sets, regression tests, or accepted examples.
2. Redacted real logs/traces with independently reviewed expected outcomes.
3. User-provided examples expanded into additional tuning candidates.
4. Fully synthetic walkthrough data.

For a fully generated walkthrough, create 18 tuning examples by default: 3 easy, 5 medium,
5 hard, and 5 very hard. Use those rows for the baseline and enhanced comparison; do not create a
held-back validation set for the default first run. Independent validation is optional later, when
the project already has that data or a real decision justifies collecting it.

Adjust size when cost or task shape requires it, but keep all four bands represented.

### Declaring provenance

Provenance answers one question twice: was the question observed, and was the answer? Declare the
first on the row as `provenance` (or `source`), the second as `output_provenance` (or
`output_source`) - either at the top level or under `metadata`.

Each row earns its own share of the 10 provenance points, and the sub-score is their average:

| The row | Points |
|---|---|
| Observed question, observed answer | 10 |
| Observed question, answer written by a model | 6 |
| Says nothing about where it came from | 6 |
| Neither was observed | 3 |

Because it is a per-row average, a mixture scores like a mixture: 99 collected rows and one
generated one score 9.93, not 3. What a mixture cannot do is escape a ceiling - see the cap ladder
below.

Words are matched by prefix, so `production-2026-q1` and `synthetic-walkthrough` both land where you
would expect. `synthetic`, `generated`, `llm`, `gpt`, `claude`, `model-written`, `ai-`,
`walkthrough`, `mock`, `fake`, `placeholder`, `simulated` and `template` all mean the same thing - nobody
observed this - and are not different classes. `production`, `real`, `collected`, `logged`,
`customer`, `human`, `curated`, `annotated`, `benchmark` and `gold` mean it was.

A word on neither list keeps the collected score, so a project's own vocabulary (`crm-export`) is
not silently demoted - but preflight raises `dataset-provenance-vocabulary` naming it, because an
unknown word quietly earning the production band is the failure that check exists to prevent. If the
data is generated, say so with a word from the first list.

Do not express a generated answer in the row's own `provenance` token: that marks the whole row
generated, scoring 3 rather than 6 and moving it under the synthetic ceilings.

### Provenance ceilings

Points alone cannot keep a score honest here. Provenance is 10 points inside a pillar worth 40% of
the total, so the whole 10-to-3 range moves the overall score by under 3 points - a fully generated
dataset that was perfect on every other dimension still reported 93 and read as production-ready.
So how much of the data was invented also sets a ceiling on the entire run:

| The dataset | Ceiling |
|---|---|
| Every row generated | 65 |
| More than half generated | 70 |
| Real questions, but every expected answer written by a model | 75 |

The ladder is ordered by how much of the result is the model talking to itself. The last rung is the
highest because the questions are still real - but an accuracy number computed against an answer key
a model wrote reports agreement with that model, not correctness, and nothing inside the run can
falsify it. A ceiling is not a deduction and not a refusal: the run continues, the pre-cap average
stays in the output, and the number simply cannot claim more than the data supports.

Every generated row must:

- Have a unique stable `id`.
- Record `difficulty`, `source: "synthetic"`, and a short `coverage`/scenario tag.
- Match the exact agent input and evaluator gold contract.
- Have a correct, scoreable expected outcome.
- Represent a distinct scenario, not a superficial paraphrase.
- Avoid secrets, PII, proprietary content, or claims that it came from real users.

Run quality checks:

- Usable count and corrupted-row percentage.
- Exact duplicate inputs.
- Duplicate IDs.
- Normalized duplicate outputs/labels where diversity is expected.
- Near-duplicate inputs using normalized token shingles or another explainable local heuristic.
- Missing difficulty bands.
- Repeated scenario tags that crowd out coverage.
- Tuning/holdout overlap by ID and normalized input.
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
bounded first-run subset records its own ids, but it is only drawn above about 100 rows - so on the
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

## First-run subset for a large dataset

A first run has to show the capability, not exhaust the dataset. Above roughly 100 usable rows,
every trial pays for every row, so a large set turns the walkthrough into a long, expensive run
that demonstrates nothing the smaller one would not. Select a bounded subset instead: **18 rows by
default**, at least four from each of the four difficulty bands (`easy`, `medium`, `hard`,
`very-hard`), so the subset keeps the spread that makes a result informative rather than landing on
one cluster.

Five rules make the subset honest:

1. **Score the dataset, not the subset.** Both readiness scores - the opening gate and the
   re-score after local validation - run on the **whole** dataset. The subset is chosen afterwards,
   as run scoping, immediately before the paid comparison. Getting this backwards makes the user's
   data wear the run's limitation: measured on 500 labelled, difficulty-tagged production rows, the
   dataset pillar sees 249 comparable examples; the same dataset scored as an 18-row subset sees
   only 8 and calls it `a wiring check, not a score`. That sentence
   is true of the run and false of the dataset, and the recorded opening-to-closing transition would
   show an 18-point drop that is nothing but our own sampling. Difficulty and diversity survive a
   compliant sample; evidence volume collapses, so that limitation must be attributed correctly.
2. **Report the run's sample-size limitation separately.** It belongs in the run report, not the
   dataset score: "this run compares configurations on 18 of your 4,812 rows; treat a small
   difference as directional unless paired uncertainty from the completed outputs supports it."
   Sample size alone cannot supply a confidence interval or minimum detectable effect for a paired
   comparison, so never invent a percentage-point threshold before those outcomes exist.
3. **Sample within each split, never across it.** Draw the tuning rows from the tuning split and
   the holdout rows from the holdout split, keeping them disjoint. A subset drawn over the combined
   set can pull the same input into both sides and fabricate a tune/holdout overlap that the
   original dataset did not have.
4. **Record what was chosen.** Write the selected row `id`s to `traigent-runs/run-plan.md`, plus
   the seed when the pick inside a band was random. The recorded ids are what makes the run
   reproducible - a seed alone does not, because the selection also depends on judgment about which
   rows are hard.
5. **Name the bound to the user.** Report the subset size beside the full row count ("18 of 4,812
   rows for this first run"). Never let a bounded run read as though the whole dataset was
   evaluated.

Keeping at least four rows from every band is what protects the spread: a careless trim to 18 that
drops a band costs difficulty points and prints a spread complaint about a dataset that has all four.

When the rows carry no difficulty tags, spread the pick across the coverage/scenario tags instead
and say which axis was used. When neither exists, take a random seeded sample and record that the
subset is unstratified - an unlabelled pick is still bounded and reproducible, just less
representative, and that limitation belongs in the report.

The full dataset stays the dataset. A real optimization after the walkthrough runs against all of
it; this bound exists only so the first run finishes.

## Optional validation split and claims

When the project already has independent validation data, or when a later real decision warrants
adding it, reserve that data before optimization and keep the same split across comparisons. It is
not part of the default first-run walkthrough. Call it a sealed holdout only when its split and
labels were fixed and hidden from component design, tuning, and winner selection until the
candidate was locked. If the assistant inspected or authored it, call it held-back, non-blind
validation.

Synthetic examples may support later promotion validation only after independent human review
against the real task and only when the split and labels remained sealed from design, tuning, and
winner selection. This is a later production-promotion safeguard, not a calibration gate or a
reason to pause the first walkthrough. Until then:

- Report them as synthetic, non-blind validation evidence.
- Do not promote the result to production.
- Do not describe the measured lift as expected customer lift.

For small validation sets, report the paired outcome counts. State a difference as directional
unless a justified paired uncertainty analysis supports a stronger claim.
