# Traigent First Run - Assistant Guide

This guide is for the coding assistant running a user's first Traigent optimization. It works
whether the project already has all, some, or none of these:

- An agent to optimize.
- An evaluation dataset.
- An evaluation method.

The objective is a fast, professional, honest first result. Generated walkthrough material helps
demonstrate the workflow; it must never be presented as representative production evidence.

## Start here

Read and follow the self-contained
[`skills/traigent-first-run/SKILL.md`](skills/traigent-first-run/SKILL.md).
The skill routes its bundled references at the stage where each is needed; do not front-load them
before starting inspection.

The same directory is what the Agent Skill installer copies, so the clone and installed-skill
paths follow one canonical workflow.

Use the bundled tools:

- Static/free validation:
  `python skills/traigent-first-run/scripts/preflight.py --help`
- Readiness-state planning:
  `python skills/traigent-first-run/scripts/readiness.py --help`
- Compact internal run record:
  `skills/traigent-first-run/assets/run-plan.md`
- Tested first-run SDK stack:
  `skills/traigent-first-run/assets/requirements-first-run.txt`

## User-facing promise

Use this short opening, adapting only what inspection already established:

> I will inspect what you already have, preserve it, and prepare anything missing for a complete
> walkthrough. If an existing dataset or evaluation method has a material limitation, I will
> explain the evidence and offer to repair and revalidate a working copy before any paid model
> calls. I will then show one combined estimate for the baseline and optimization. If Traigent
> generates temporary components, I will keep them clearly separate from real-world readiness so
> the result is not overclaimed.

Proceed with read-only inspection after stating the plan. Do not make the user approve safe
discovery. Stop only for:

- A genuine choice between multiple agent candidates.
- One task-intent question when nothing anchors the walkthrough.
- Secrets that must be pasted into a preserved or newly created owner-only local `.env`.
- Paid/provider calls or private-data egress.
- Judgment-dependent changes to real expected answers or grading policy.
- Destructive or production-affecting changes.

Creating the isolated environment and minimal `.env` is separate from installing dependencies.
A dependency install may proceed without another approval only when it is confined to that
environment, uses the exact packages and versions declared at the top level plus their
package-declared dependencies, fetches package artifacts only, and permits no
project/provider/Traigent code execution or private-data transfer.
A project without compatible exact declarations uses the skill's pinned first-run requirements;
never run an unversioned `pip install traigent`.
A user or environment install policy still takes precedence and may require approval. Provider,
connected Traigent, private-data, and all other external calls remain behind their stated
approval gates.

## Default run

The default paid path uses exactly two connected optimization experiments with the same tuning
data, evaluator, objectives, and agent call path:

1. The user's existing baseline/configuration exactly as defined. Only when Traigent creates the
   missing baseline does it generate a credible small sweep of six distinct standard parameter
   combinations, including the generated current configuration.
2. One broader Traigent optimization that contains the baseline values, adds meaningful knobs,
   and targets 10-13 trials (12 by default) from a materially larger search space.

Then compare the two selected configurations on the untouched holdout; this is validation, not
another optimization search. Include all calls in the combined approval. Trial counts and knob
selection are assistant-owned implementation choices, not new user questions.

Do not add an offline baseline rerun or a mandatory third optimization pass. Do not expand,
shrink, or weaken a user-owned baseline to reach a row count; one row is correct when that is what
the user actually defined. When Traigent generates the walkthrough agent and its missing baseline,
generate enough real controls for the six-row baseline and add further controls to the enhanced
run. Another iteration is optional only after the result identifies a specific hypothesis.

## Result interpretation

Always report the component provenance:

- `✅` real and validated.
- `❗` missing, invalid, or evidence-limited real-world component.
- `🛠️` generated walkthrough substitute.

If anything is `🛠️`, say before the numbers that the result demonstrates the workflow and is not
evidence of expected production performance. A synthetic holdout is still synthetic evidence.

Keep the customer's connected baseline and optimization experiments in the portal and finish with
their direct links. Do not delete them as walkthrough cleanup; deletion requires an explicit later
request from the user.

Only provide advanced learning links and lifecycle suggestions after the user has seen the result.
