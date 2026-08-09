# Traigent First-Run Record

The coding assistant maintains this record at `traigent-runs/run-plan.md`; the user does not fill it in.

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
- Opening readiness score before any creation or repair - overall, band, binding caps, and the one ask's gaps, answer, and any path given or missed:
- Revalidation gate results - which caps cleared, and on what evidence:

## Shared comparison

- Tuning rows and held-out rows (default 10, reserved at creation), coverage, and known limitations:
- Agent and evaluator/judge calls per example:
- Total walkthrough ceiling (default `$5.00`):

## Baseline plan and approval

- Current configuration/space and provider recipients:
- Calls, runtime, and spend:
- Baseline approval - status/scope/ceiling, and the pre-spend material card's proceed/fix answer:

## Running state

- Tracked spend, or conservative deduction where untracked:
- Remaining total ceiling:
- Local baseline checkpoint - artifact, best config/score, trials/failures, cost, and limits:

## Connected-stage plan and approval

- Added dimensions, total combinations, configuration ceiling, and recipients:
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
