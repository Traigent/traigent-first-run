# Case 21 - MultiWOZ dialogue (malformed)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: dialogue
- Dataset: 30 rows, labeled (has expected outputs), provenance=real
- Evaluator: none
- Agent knobs: 3 (model, prompt_style, output_format)
- Component states (agent/dataset/evaluation): {'agent': 'real', 'dataset': 'invalid', 'evaluation': 'missing'}

## What the onboarding SHOULD conclude
- Readiness band: Partial
- Caps triggered: structural-check (35)
- Recommended action: Repair the structure first, then stand up a turn-level judge.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
