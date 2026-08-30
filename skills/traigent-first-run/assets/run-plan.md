# Traigent First-Run Record

The coding assistant maintains this record at `traigent-runs/run-plan.md`; the user does not fill it in.

## Stage status

`[x]` done · `[~]` in progress · `[ ]` not reached · append `skipped - <reason>` to a stage this run
lawfully never entered, keeping its `[ ]` checkbox. SKILL.md owns every stage's rules; this block records only where the run is.

- [ ] 1. Inspect quietly
- [ ] 2. Show readiness once
- [ ] 3. Complete the system
- [ ] 4. Validate components locally
- [ ] 5. Prepare the environment and finish free checks
- [ ] 6. Approve and run the baseline
- [ ] 7. Run the honest comparison
- [ ] 8. Verify and report

## Objective and provenance

- Target project and selected agent (absolute path plus function or command):
- Task and primary success measure:
- Unacceptable failure:
- Agent (`real`/`limited`/`demo`/`missing`/`invalid`) - source, wrapper, evidence, gap:
- Dataset (`real`/`limited`/`demo`/`missing`/`invalid`) - source, generated copy, evidence, gap:
- Evaluation (`real`/`limited`/`demo`/`missing`/`invalid`) - source, adapter, evidence, gap:

## Quality evidence

- Dataset rows, split, difficulty/scenario coverage, corruption, duplicates, and ceiling risk:
- Evaluator meaning of "correct":
- Calibration cases and results artifacts:
- Semantic-coverage evidence, verdict (`sufficient`/`ambiguous`), and known gaps:
- Quality advisory, user choice, and revalidation result if applicable:
- Row ids repaired into the working copy, and row ids generated to fill a gap:
- Opening readiness score before any Agent, Dataset, or Evaluation component creation or repair - overall, band, binding caps, and the one ask's gaps, answer, and any path given or missed:
- Revalidation gate results - which caps cleared, and on what evidence:

## Shared comparison

- Tuning rows and held-out rows (default 10, reserved at creation), coverage, and known limitations:
- Agent and evaluator/judge calls per example:
- Total walkthrough ceiling (default `$5.00`):

## Baseline plan and approval

- Current configuration/space and provider recipients; pre-baseline comparison invariants after free validation - objective text, baseline model/value set, exact tuning and held-out row files/ids, and SHA-256 for every behavior/data-bearing file used by the agent/call adapter and evaluator/adapter (incomplete if the full local dependency set cannot be enumerated):
- Calls, runtime, and spend:
- Baseline approval - status/scope/ceiling, and the pre-spend material card's proceed/fix answer:

## Running state

- Tracked spend, or conservative deduction where untracked:
- Remaining total ceiling:
- Local baseline checkpoint - artifact, best config/score, trials/failures, cost, and limits:

## Connected-stage plan and approval

- Added dimensions, total combinations, configuration ceiling, and recipients; enhanced-space verification - every recorded baseline model/value retained, with only additions on the approved card:
- Calls, including the winner's held-out scoring, runtime, and spend:
- Connected-stage approval - status/scope, spend, remaining ceiling:
- Portal-tracking probe (zero-LLM): pass/fail and sanitized failure class/message if failed:
- Exact-baseline sync - public sync ID, successful CLI URL, or `local-only` with reason:
- Connected optimization run ID, configurations tested of the total, partial/final result, stop reason, and verified portal link:
- Baseline-versus-enhanced comparison - measured tuning behavior and justified claim strength:
- Accuracy-cost frontier for each run - its points, the recommended one, and the score claim with paired outcome counts:

## Interpretation

- Held-out score for the recommended configuration, the round it came from, its tuning score, the held-out set's real/generated counts, and the small-sample note:
- Components that remain walkthrough substitutes:
- What the result demonstrates:
- What the result does not establish:
- Recommended next real-world improvement:
