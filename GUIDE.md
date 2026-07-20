# Traigent First Run - Assistant Guide

This guide is for the coding assistant running a user's first Traigent optimization. It works
whether the project already has all, some, or none of these:

- An agent to optimize.
- An evaluation dataset.
- An evaluation method.

The objective is a fast, professional, honest first result. Generated walkthrough material helps
demonstrate the workflow; it must never be presented as representative production evidence.

## Start here

Read and follow the self-contained skill:

1. [`skills/traigent-first-run/SKILL.md`](skills/traigent-first-run/SKILL.md)
2. [`skills/traigent-first-run/references/component-creation.md`](skills/traigent-first-run/references/component-creation.md)
3. [`skills/traigent-first-run/references/evaluation-and-dataset.md`](skills/traigent-first-run/references/evaluation-and-dataset.md)
4. [`skills/traigent-first-run/references/run-safety.md`](skills/traigent-first-run/references/run-safety.md)
5. [`skills/traigent-first-run/references/sdk-execution.md`](skills/traigent-first-run/references/sdk-execution.md)

The same directory is what the Agent Skill installer copies, so the clone and installed-skill
paths follow one canonical workflow.

Use the bundled tools:

- Static/free validation:
  `python skills/traigent-first-run/scripts/preflight.py --help`
- Readiness-state planning:
  `python skills/traigent-first-run/scripts/readiness.py --help`
- Run record template:
  `skills/traigent-first-run/assets/run-plan.md`

## User-facing promise

Use this short opening, adapting only what inspection already established:

> I will inspect what you already have, preserve it, and prepare anything missing for a complete
> walkthrough. Before any paid model calls, I will validate the setup and show you one combined
> estimate for the baseline and optimization. If Traigent generates temporary components, I will
> keep them clearly separate from real-world readiness so the result is not overclaimed.

Proceed with read-only inspection after stating the plan. Do not make the user approve safe
discovery. Stop only for:

- A genuine choice between multiple agent candidates.
- One task-intent question when nothing anchors the walkthrough.
- Secrets that must be pasted into a local `.env`.
- Paid/provider calls or private-data egress.
- Destructive or production-affecting changes.

## Default run

The default paid path uses exactly two optimization experiments with the same tuning data and
evaluator:

1. The agent's current configuration.
2. One bounded Traigent optimization that includes that configuration.

Then compare the current and selected configurations on the untouched holdout; this is validation,
not another optimization search. Include those calls in the combined approval.

Do not add an offline baseline rerun, a manual-sweep baseline, or a mandatory second optimization
pass. Another iteration is optional after the first result identifies a specific hypothesis.

## Result interpretation

Always report the component provenance:

- `✅` real and validated.
- `❗` real-world gap.
- `🛠️` generated walkthrough substitute.

If anything is `🛠️`, say before the numbers that the result demonstrates the workflow and is not
evidence of expected production performance. A synthetic holdout is still synthetic evidence.

Only provide advanced learning links and lifecycle suggestions after the user has seen the result.
