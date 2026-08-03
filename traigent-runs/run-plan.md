# Traigent First-Run Record

## Objective and provenance

- Task and primary success measure: optimize the existing support-intent agent without replacing its evaluator.
- Unacceptable failure: optimize against a broken or invented grading signal, or claim production evidence from walkthrough material.
- Agent (`real`/`limited`/`demo`/`missing`/`invalid`) - source, wrapper, evidence, gap: `real` - `tests/behavioral/scenarios/partial-missing-dataset/seed/agent.py` routes support messages to `billing`, `cancellation`, or `technical-support`; gap is no broader production agent surface than that small routing function.
- Dataset (`real`/`limited`/`demo`/`missing`/`invalid`) - source, generated copy, evidence, gap: `missing` for real readiness - no project-owned production dataset is connected; a synthetic walkthrough dataset exists at `tests/behavioral/scenarios/partial-missing-dataset/generated/evaluation-dataset.jsonl`, but it is explicitly walkthrough material.
- Evaluation (`real`/`limited`/`demo`/`missing`/`invalid`) - source, adapter, evidence, gap: `real` - `tests/behavioral/scenarios/partial-missing-dataset/seed/evaluator.py` is a deterministic exact matcher over normalized labels; gap is narrow metric scope, not absence.

## Quality evidence

- Dataset rows, split, difficulty/scenario coverage, corruption, duplicates, and ceiling risk: no real dataset is connected; the walkthrough-only synthetic set has 28 rows, 18 tune / 10 holdout, with tuning split 3 easy / 5 medium / 5 hard / 5 very-hard and holdout split 2 easy / 3 medium / 3 hard / 2 very-hard; no obvious corruption in the generated fixture.
- Evaluator meaning of "correct": exact case/whitespace-insensitive match on the normalized label.
- Calibration cases and results artifacts: three calibration cases in `tests/behavioral/scenarios/partial-missing-dataset/generated/calibration-cases.json`; no calibration run has been executed yet.
- Semantic-coverage evidence, verdict (`sufficient`/`ambiguous`), and known gaps: support routing is class-label output; the evaluator checks label/value binding and case/whitespace normalization, but not richer task behavior. Verdict remains `sufficient` for this narrow routing task.
- Quality advisory, user choice, and revalidation result if applicable: none yet.
- Walkthrough dataset substitute: `🛠️` `traigent-runs/walkthrough-dataset.jsonl` with 28 synthetic rows, 18 tune / 10 holdout, tuning at 3 easy / 5 medium / 5 hard / 5 very-hard and holdout at 2 easy / 3 medium / 3 hard / 2 very-hard, plus explicit label coverage for the three support branches.
- Walkthrough agent/config-space substitute: `🛠️` `traigent-runs/walkthrough_agent.py` and `traigent-runs/config-space.json` expose three tunable routing knobs for the walkthrough.
- Opening readiness score before any creation or repair - overall, band, binding caps: `2/3` from the required readiness gate; binding cap is dataset-absent / no real component connected.
- Latest revalidated readiness score - overall, band, binding caps, and what changed: `65/100 WORKABLE`; caps are `dataset-fully-synthetic` and `dataset-below-measurable-size`; the score rose after adding a synthetic dataset plus a walkthrough agent/config-space wrapper with wired knobs.

## Planned comparison

- Current configuration: existing support-intent router plus a walkthrough wrapper with `prompt_style`, `routing_bias`, and `fallback_label` knobs, evaluated by the exact deterministic label matcher.
- Search dimensions and maximum trials: 3 wired knobs, 27 combinations, max trials 12; this is a walkthrough search space, not production readiness.
- Tuning / test-data rows and visibility (`sealed holdout` or `held-back, non-blind`): 18 tuning / 10 held-back test rows, fully visible synthetic walkthrough data. The test split is kept separate so the best config found by tuning can be checked on unseen examples rather than judged on the same rows it optimized against.
- Agent and evaluator/judge calls per example: one routing call plus one exact comparison.
- Services/routes receiving data: local-only; no provider or Traigent backend calls were required for the deterministic local search.
- Approximate runtime: local exhaustive comparison over 27 configs completed in under a second on the current machine.
- Estimated spend: $0.00 local-only.
- Total walkthrough ceiling (default `$5.00`): not applicable to this local-only pass.
- User approval: not required for the local-only pass.

## Running state

- Portal-tracking probe (zero-LLM): not run.
- Tracked spend, or conservative deduction where untracked: not started.
- Remaining total ceiling: not started.
- Minimal `.env`: created at `.env` with `OPENROUTER_API_KEY=` blank, mode `0600`, ignored by git.
- Local baseline checkpoint - artifact, best configuration/tuning score, executed/failed trials, provider-reported cost or `not measured`, and limits: `traigent-runs/baseline-results.json`; baseline config `{"prompt_style":"direct","routing_bias":"balanced","fallback_label":"technical-support"}` scored 9/18 on tuning and 7/10 on held-back test data; 1 executed, 0 failed, cost not measured, local-only.
- Exact-baseline sync - public sync ID, successful CLI URL, or `local-only` with reason: `local-only` because this workspace has not yet been handed a connected route selection for a live run.
- Connected optimization run ID, partial/final result, stop reason, and verified portal link: `traigent-runs/optimized-results.json`; best config `{"prompt_style":"criteria_first","routing_bias":"balanced","fallback_label":"cancellation"}` scored 13/18 on tuning and 4/10 on held-back test data; 27 executed, 0 failed, stop_reason `completed`, local-only.
- Validation comparison - paired outcomes, visibility, and justified claim strength: held-back, non-blind test comparison on the 10-row test split; the best tuning config overfits test data relative to baseline, so the local search is useful as a walkthrough only.

## Interpretation

- Components that remain walkthrough substitutes: `🛠️` walkthrough dataset at `traigent-runs/walkthrough-dataset.jsonl`, `🛠️` walkthrough agent at `traigent-runs/walkthrough_agent.py`, and `🛠️` config-space at `traigent-runs/config-space.json`; the only real components remain the support router and deterministic evaluator.
- What the result demonstrates: the repo currently has a real support-intent agent and deterministic evaluator, plus a synthetic walkthrough dataset and wrapper that can be searched locally.
- What the result does not establish: production optimization performance.
- Recommended next real-world improvement: add or connect a real dataset and a real tunable agent wrapper, then re-run the opening gate.
- Readiness transition - opening score beside the latest, caps cleared and remaining, and whether the gain came from real repair or a `🛠️` substitute: opening `2/3`; latest `65/100 WORKABLE`; the gain came entirely from `🛠️` substitutes.
