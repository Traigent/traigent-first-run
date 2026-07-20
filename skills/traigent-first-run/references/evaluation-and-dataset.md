# Evaluation and Dataset

Use this reference whenever creating or validating a dataset or evaluation method.

## Contents

1. Evaluation selection
2. Mandatory calibration
3. Quality diagnosis and repair choice
4. Dataset construction
5. Holdout and claims

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

When building an evaluator:

- Expose it to Traigent through a thin metric adapter with an explicit `output` parameter and only
  SDK-supported names such as `expected`, `input_data`, and `metadata`. Preserve an existing
  evaluator that uses names such as `prediction` or `reference`, but adapt those names at the
  boundary instead of registering that function directly.
- Infer the rubric from real labels, tests, accepted outputs, product rules, and failure reports.
- Ask one product question only if ambiguity would materially change who wins.
- Prefer partial credit when correctness has meaningful degrees.
- Fail evaluator/runtime errors distinctly; do not let a crashed harness look like an incorrect
  agent answer.
- Name the primary metric after what it measures, such as `label_accuracy`, `schema_accuracy`,
  `task_success`, or `judge_quality`.

## Mandatory calibration

Before any optimization, construct at least four probes from the same task:

1. `good` - clearly correct.
2. `equivalent_good` - semantically correct with a different valid surface form.
3. `partial` - contains some correct information but misses an important requirement.
4. `bad` - clearly incorrect.

Require:

```text
good ~= equivalent_good > partial > bad
```

The exact thresholds depend on the metric, but reject all of these:

- All scores equal or nearly equal.
- All scores zero or all scores one.
- Equivalent-good output penalized only for wording/order/format that the product accepts.
- Partial output ranked at or above a fully correct output.
- Bad output receiving a passing score.
- Parse/evaluator exceptions converted silently to an ordinary zero.

For deterministic evaluators, run probes locally in an isolated subprocess with provider keys
removed.

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
| Missing or contaminated holdout | Split sizes and overlap evidence | Improvement cannot be separated from tuning-set fit |
| Task-inappropriate evaluator | Show the exact rule and one valid answer it rejects or bad answer it accepts | Optimization rewards the wrong behavior |
| Degenerate evaluator | Four-probe scores, exceptions, or constant/inverted ordering | Candidate configurations cannot be ranked reliably |
| Baseline ceiling | Baseline score, number and type of failures, and score resolution | The search may have nothing measurable to improve |

Do not infer "easy-only" from short inputs alone. Tie the explanation to the real task: show which
decision boundaries, realistic noise, edge cases, or known failure modes are absent. If that
cannot be established from project evidence, say difficulty is unverified rather than declaring
the dataset easy.

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

After any repair, re-run the same checks that produced the advisory. Do not clear `❗` because a
file changed; clear it only when new evidence resolves the limitation.

## Dataset construction

Prefer, in order:

1. Reviewed product fixtures, golden sets, regression tests, or accepted examples.
2. Redacted real logs/traces with independently reviewed expected outcomes.
3. User-provided examples expanded into additional tuning candidates.
4. Fully synthetic walkthrough data.

For a fully generated walkthrough, create 24 examples by default:

- 6 easy.
- 6 medium.
- 6 hard.
- 6 very hard but still unambiguously solvable.

Adjust size when cost or task shape requires it, but keep all four bands represented.

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
- Agent-signature binding.
- Difficulty, boundary, and known failure-mode coverage.
- Dominant-output or majority-label baselines that could hide a ceiling. For structured output,
  inspect common label/category fields and pass `--outcome-field result.label` to the static
  preflight when the task's discrete outcome uses a nonstandard or nested field.

Do not manufacture deliberately wrong gold labels or ambiguous inputs merely to make the
optimization look better.

## Holdout and claims

Reserve the holdout before optimization. Keep the same split across all comparisons and
iterations.

For generated 24-row walkthrough data, a practical split is 18 tuning / 6 holdout, stratified
across difficulty and scenario. The holdout checks whether the walkthrough configuration
generalizes to unseen synthetic examples. It does not validate production performance.

Synthetic examples may enter a production holdout only after independent human review against
the real task. Until then:

- Report them as synthetic holdout evidence.
- Do not promote the result to production.
- Do not describe the measured lift as expected customer lift.

For small real holdouts, state the resolution honestly: an observed difference smaller than
roughly one example's contribution is directional, not decisive.
