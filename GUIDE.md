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
paths follow one canonical workflow. Resolve the **absolute directory containing the loaded
`SKILL.md`** from the path the coding assistant actually loaded. Keep every tool's working
directory at the user's project root and interpolate that literal absolute skill directory into
each invocation; do not depend on an exported variable surviving a later tool call. In a clone the
resolved directory ends in `skills/traigent-first-run`; after Agent Skill installation it may live
elsewhere.

## Keep the guide source separate from the project being optimized

The clone or installed directory that supplies this guide is **not automatically the project being
optimized**. Before work, resolve the user-selected project's root and agent callable or command at
run time; never substitute a path, agent, dataset, or result from this guide or the assistant's
workspace, or a prior run. When the guide clone and that project are separate, use the
chosen agent's project root for inspection, environments,
`traigent-runs/`, tests, and every baseline or enhanced run. Do not create walkthrough artifacts
for the guide clone or treat an old result beside the guide as a result for the user's agent.

Before showing readiness, a baseline, or an optimization result, identify the target in one line:
`Target project: <absolute path> · Agent: <absolute path>:<function or command>`. On a resumed
run, compare that identity with the recorded artifact. If it differs, label the artifact
**historical — different agent** and do not quote its scores as the current result.
If none is credible, use `Agent: none discovered`; replace it before later results.

An already-supplied local credential file is an availability inventory, not an agent selection. If
the user explicitly identifies a different owner-only local file as the credential handoff for
this run, use that same file for the run and, after its safety checks, add only a genuinely
missing key there. Never print, copy, or ask them to paste a value already in it. Keep the agent,
dataset, evaluator, and run artifacts in the chosen project. If no such source was identified,
use the chosen project's local `.env` handoff.

Use the bundled tools:

- Static/free validation: invoke `scripts/preflight.py --help` through the selected Python using
  the script's literal absolute path under the resolved skill directory.
- Mandatory readiness score (opening gate, re-scored after repair/creation) and state planning:
  invoke `scripts/readiness.py --help` the same way.
- Compact internal run record: resolve `assets/run-plan.md` beneath that absolute skill directory.
- Tested first-run SDK stack: resolve `assets/requirements-first-run.txt` there too.

When a credential handoff is needed, use the selected credential source: normally the chosen
project-root `.env`, or the external local file the user explicitly named for this run. Open that
exact absolute path once, using the first available GUI editor; if that is unavailable, fall back
to the IDE or editor associated with the chosen project directory, and if headless, print the full
path and stop. Open it only for the missing key, never to duplicate one that is already available.
For a new Traigent key after the baseline, refresh/reopen the same file so the new
`TRAIGENT_API_KEY=` line is visible, then follow `references/run-safety.md` for the clickable
registration link and the two 10-day windows.

## User-facing promise

Opening:

> **Welcome to Traigent Onboarding!**
>
> 1. **Inspect** - preserve your agent, dataset, and evaluator.
> 2. **Readiness** - run free readiness research and explain its score.
> 3. **Baseline** - measure today's setup with calls, cost, and time.
> 4. **Optimize** - preview a bounded Traigent search after the baseline.
> 5. **Results** - compare the runs and recommend one next step.
>
> I will mark each stage with measured numbers when available. Readiness checks the score and
> setup—not agent accuracy or an optimization result. I explain details only if action is needed.
> Baseline evidence decides the next step.

Proceed with read-only inspection after stating the plan. Do not make the user approve safe
discovery. Stop only for:

- A genuine choice between multiple agent candidates, or between multiple existing environments to
  install into.
- Installing into an environment other work of yours depends on, rather than one created for this
  run or holding only a previous walkthrough's packages.
- One task-intent question when nothing anchors the walkthrough.
- Secrets that must be pasted into a preserved or newly created owner-only local `.env`.
- Paid/provider calls or private-data egress.
- Judgment-dependent changes to real expected answers or grading policy.
- Destructive or production-affecting changes.

Creating the isolated environment and minimal `.env` is separate from installing dependencies.
A dependency install may proceed without another approval only when it is confined to an
environment this run created, uses the exact packages and versions declared at the top level plus
their package-declared dependencies, fetches package artifacts only, and permits no
project/provider/Traigent code execution or private-data transfer. Installing into an environment
that other work depends on is confirmed once first: the other four conditions bound what is
installed, and none of them bounds what a resolution can move inside an environment you built for
something else.
A project without compatible exact declarations uses the skill's pinned first-run requirements;
never run an unversioned `pip install traigent`.
A user or environment install policy still takes precedence and may require approval. Provider,
connected Traigent, private-data, and all other external calls remain behind their stated
approval gates.

## Default run

The default paid path uses two measurements with the same tuning data, evaluator, objectives, and
agent call path:

1. A provider-paid **local fixed baseline**, preserving the user's configuration exactly. Only
   when no baseline exists does the assistant prepare a credible six-configuration sweep. The
   assistant automatically uses the vendor the project already has configured when one is already
   available; the user only gets asked to choose if there is no usable vendor already configured
   for the project. The user sees its best configuration, primary tuning metric, cost, latency,
   trial/failure count, and a short note for each knob before any Traigent account/key request.
2. After that checkpoint, a zero-LLM portal probe and one **connected managed optimization** that
   contains every baseline value, adds meaningful non-model settings by default, and tests up to 12
   configurations from a materially larger search space.

The assistant uploads the completed baseline without rerunning it only when the installed SDK
exposes a public exact sync id; otherwise that result remains local. Then it shows the baseline
result and the connected enhanced result side by side, with a verified portal link for every
persisted run and an explicit `local-only` label for an unsynced baseline, and compares the best
configs and their measured tuning behavior directly. It also discloses the enhanced winner's
held-out score here, with a note saying how little ten examples can settle.
Approve the provider-paid baseline first. After its result, preview and approve the connected
optimization separately. The assistant chooses how many configurations it tests and which knobs it
varies.

Do not add an offline baseline rerun or a mandatory third optimization pass. Do not expand,
shrink, or weaken a user-owned baseline to reach a row count; one row is correct when that is what
the user actually defined. When the assistant prepares the walkthrough agent and its missing
baseline,
generate enough real controls for the six-row baseline and add further controls to the enhanced
run. Another iteration is optional only after the result identifies a specific hypothesis.

## Result interpretation

Always report the component provenance:

- `✅` real and validated.
- `❗` missing, invalid, or evidence-limited real-world component.
- `🛠️` generated walkthrough substitute.

If anything is `🛠️`, say before the numbers that the result demonstrates the workflow and is not
evidence of expected production performance. Any walkthrough-only substitute is still walkthrough
evidence.

Keep every experiment actually persisted in the portal and finish with its verified direct link.
Label an unsynced baseline local-only. Do not delete portal experiments as walkthrough cleanup;
deletion requires an explicit later request from the user.

Only provide advanced learning links and lifecycle suggestions after the user has seen the result.
