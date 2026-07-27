# Case 05 - GSM8K math (mini)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: math
- Dataset: 15 rows, labeled (has expected outputs), provenance=real
- Evaluator: numeric
- Agent knobs: 1 (model)
- Component states (agent/dataset/evaluation): {'agent': 'limited', 'dataset': 'real', 'evaluation': 'real'}

## What the onboarding SHOULD conclude
- Readiness band: Partial
- Caps triggered: no-knob-varies (45)
- Recommended action: Propose reasoning and few-shot knobs.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
