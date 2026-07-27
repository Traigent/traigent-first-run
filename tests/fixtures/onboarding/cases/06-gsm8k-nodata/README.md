# Case 06 - GSM8K math (no data)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: math
- Dataset: 0 rows, UNLABELED (inputs only), provenance=none
- Evaluator: none
- Agent knobs: 1 (model)
- Component states (agent/dataset/evaluation): {'agent': 'limited', 'dataset': 'missing', 'evaluation': 'missing'}

## What the onboarding SHOULD conclude
- Readiness band: Not ready
- Caps triggered: no-dataset (20)
- Recommended action: Synthesize ~18 seeded questions easy->very hard, then build an evaluator.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
