# Case 25 - NL2Bash command-gen (bad knobs)

Handicap fixture for the Traigent onboarding (traigent-first-run). Point the
onboarding at this directory as the target project.

- Task type: bash
- Dataset: 30 rows, labeled (has expected outputs), provenance=real
- Evaluator: set
- Agent knobs: 8 (model, temperature, prompt_style, output_format, fewshot_k, retrieval, reasoning, routing)
- Component states (agent/dataset/evaluation): {'agent': 'limited', 'dataset': 'real', 'evaluation': 'real'}

## What the onboarding SHOULD conclude
- Readiness band: Workable
- Caps triggered: knob-count decays at 7+, low variation quality
- Recommended action: Fix knob ranges/resolution; prune to the vital few.

See expected-assessment.json for the machine-checkable version. A run passes if
the readiness card matches, on all three coding agents (Claude Code, Codex CLI,
Gemini CLI).

## Files
- dataset.jsonl - rows of {input, output?, metadata{difficulty, split, provenance}}
- evaluator.py - the scorer (returns a normalized [0,1] score)
- traigent-runs/calibration-cases.json - good/equivalent_good/partial/bad probes
- config_space.json - the agent's tunable knobs
- agent.py - minimal walkthrough agent stub
