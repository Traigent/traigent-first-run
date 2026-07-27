# Case 08 - MBPP code (broken eval)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: code
- Dataset: 30 rows, labeled (has expected outputs), provenance=real
- Evaluator: broken
- Agent knobs: 3 (model, temperature, prompt_style)
- Component states (agent/dataset/evaluation): {'agent': 'real', 'dataset': 'real', 'evaluation': 'invalid'}

## What the onboarding SHOULD conclude
- Readiness band: Blocked
- Caps triggered: evaluator-broken (25)
- Recommended action: Replace the verifier before trusting any number.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)  [DELIBERATELY BROKEN]
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
