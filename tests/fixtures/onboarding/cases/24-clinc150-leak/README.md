# Case 24 - CLINC150 intents (leakage)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: intent
- Dataset: 120 rows, labeled (has expected outputs), provenance=real
- Evaluator: exact
- Agent knobs: 2 (model, fewshot_k)
- Component states (agent/dataset/evaluation): {'agent': 'real', 'dataset': 'limited', 'evaluation': 'real'}

## What the onboarding SHOULD conclude
- Readiness band: Partial
- Caps triggered: shared-splits (50)
- Recommended action: Re-split so the check is honest; warn about leakage.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
