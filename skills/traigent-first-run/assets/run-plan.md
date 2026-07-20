# Traigent First-Run Record

The coding assistant fills this file from project evidence. Store the completed copy at
`traigent-runs/run-plan.md`.

## Objective

- Task:
- Primary quality/success measure:
- Secondary measures:
- Unacceptable failure:

## Component provenance

| Component | State (`real`/`limited`/`demo`/`missing`/`invalid`) | Source or generated path | Validation evidence | Real-world gap |
|---|---|---|---|---|
| Agent |  |  |  |  |
| Dataset |  |  |  |  |
| Evaluation |  |  |  |  |

## Dataset

- Input/output contract:
- Tuning rows:
- Holdout rows:
- Split rule:
- Difficulty/scenario coverage:
- Duplicate/overlap check:
- Corrupted/unusable rows and percentage:
- Difficulty, boundary, and failure-mode coverage:
- Ceiling-risk evidence:

## Quality advisory

- Affected component:
- Concrete evidence:
- Optimization consequence:
- Recommended repair:
- User choice (`repair`/`demonstration`/`pause`):
- Revalidation evidence after repair:

## Evaluator calibration

Repeat one row for every materially distinct input, outcome class, and rubric/schema branch.

| Case | Input/fixture | Expected outcome | Rubric/schema branch | Mode | Good probe / score | Equivalent-good probe / score | Partial probe / score | Bad probe / score | Chosen thresholds and rationale | Result / exceptions |
|---|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |  |  |

- Evaluation method:
- Product meaning of "correct":
- Threshold values chosen before execution:
- Threshold rationale:
- Judge model/rubric, if applicable:
- Calibration egress/cost approval, if applicable:
- Semantic-coverage reviewer:
- Semantic-coverage evidence (paths, stable identifiers, or representative case IDs):
- Materially distinct inputs, outcome classes, labels, schema variants, metadata paths, and rubric branches reviewed:
- Mode and threshold rationale from product evidence:
- Known semantic-coverage gaps:
- Semantic-coverage verdict (`sufficient`/`ambiguous`) and rationale:
- Product-grading ambiguity question/answer, if applicable:
- Explicit approval for any real grading-policy change, if applicable:

## Comparison

- Current baseline configuration:
- Optimization space (must include baseline):
- Tuning dataset and evaluator used by both:
- Maximum trials:
- Agent calls per example:
- Evaluator/judge calls per example:
- Provider retry count:
- Provider-request timeout and rationale:
- Live-check timeout and rationale:
- Judge timeout and rationale:
- Baseline timeout and rationale:
- Optimization timeout and rationale:
- Holdout phase timeout and rationale:
- Runtime calculation including retries/composites:
- Combined worst-case spend:
- Total first-run cap:
- Estimated runtime:
- Services and routes receiving data, including OpenRouter upstreams/fallbacks:
- User approval:

## Aggregate budget ledger

Record the charged amount when reliably tracked; otherwise deduct the approved phase worst case.
The remaining value is the aggregate cap after that deduction.

| Phase | Approved calls/routes | Allocation | Phase worst case | Charged or conservative deduction | Remaining aggregate cap | Status/evidence |
|---|---|---:|---:|---:|---:|---|
| Live provider/key check |  |  |  |  |  |  |
| LLM-judge calibration/evaluation |  |  |  |  |  |  |
| Current baseline |  |  |  |  |  |  |
| Bounded search |  |  |  |  |  |  |
| Retries/composites |  |  |  |  |  |  |
| Current-configuration holdout |  |  |  |  |  |  |
| Winner holdout |  |  |  |  |  |  |

## Results

- Baseline tuning result:
- Best tuning result:
- Holdout result:
- Total tracked cost:
- Trials / failures / stop reason:
- Truncation check:
- Persistence status:
- Baseline portal link:
- Optimization portal link:

## Claim

- Components that remain walkthrough substitutes:
- What this run demonstrates:
- What this run does not establish:
- Recommended next real-world improvement:
