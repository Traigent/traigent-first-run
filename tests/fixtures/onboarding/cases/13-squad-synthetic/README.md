# Case 13 - SQuAD reading-comp (synthetic)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: qa
- Dataset: 100 rows, labeled (has expected outputs), provenance=synthetic
- Evaluator: judge
- Agent knobs: 4 (model, temperature, prompt_style, retrieval)
- Component states (agent/dataset/evaluation): {'agent': 'real', 'dataset': 'demo', 'evaluation': 'real'}

## What the onboarding SHOULD conclude
- Readiness band: Workable
- Caps triggered: generated-data (65)
- Recommended action: Proceed but flag synthetic; recommend a small real holdout.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
