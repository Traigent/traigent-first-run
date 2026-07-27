# Case 14 - CNN summarization (slow judge)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: summ
- Dataset: 30 rows, UNLABELED (inputs only), provenance=real
- Evaluator: judge_slow
- Agent knobs: 3 (model, temperature, prompt_style)
- Component states (agent/dataset/evaluation): {'agent': 'real', 'dataset': 'limited', 'evaluation': 'limited'}

## What the onboarding SHOULD conclude
- Readiness band: Partial
- Caps triggered: eval-timeout (45)
- Recommended action: Calibrate the judge, cap its cost, define a rubric.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
