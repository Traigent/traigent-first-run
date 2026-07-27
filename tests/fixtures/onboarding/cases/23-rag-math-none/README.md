# Case 23 - RAG-over-docs math (nothing)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: math
- Dataset: 0 rows, UNLABELED (inputs only), provenance=none
- Evaluator: none
- Agent knobs: 2 (model, retrieval)
- Component states (agent/dataset/evaluation): {'agent': 'missing', 'dataset': 'missing', 'evaluation': 'missing'}

## What the onboarding SHOULD conclude
- Readiness band: Not ready
- Caps triggered: no-dataset (20), would-be generated (65)
- Recommended action: Synthesize 18 seeded Qs easy->very hard, build eval, wire basic knobs.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
