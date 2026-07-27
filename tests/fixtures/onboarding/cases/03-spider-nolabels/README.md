# Case 03 - SPIDER text2SQL (no labels)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: sql
- Dataset: 40 rows, UNLABELED (inputs only), provenance=real
- Evaluator: set
- Agent knobs: 4 (model, temperature, prompt_style, output_format)
- Component states (agent/dataset/evaluation): {'agent': 'real', 'dataset': 'limited', 'evaluation': 'limited'}

## What the onboarding SHOULD conclude
- Readiness band: Partial
- Caps triggered: rows-no-outputs (30)
- Recommended action: Synthesize expected SQL; ask user to review at the end.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
