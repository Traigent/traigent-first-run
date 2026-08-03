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

Use the bundled tools:

- Static/free validation: invoke `scripts/preflight.py --help` through the selected Python using
  the script's literal absolute path under the resolved skill directory.
- Mandatory readiness score (opening gate, re-scored after repair/creation) and state planning:
  invoke `scripts/readiness.py --help` the same way.
- Compact internal run record: resolve `assets/run-plan.md` beneath that absolute skill directory.
- Tested first-run SDK stack: resolve `assets/requirements-first-run.txt` there too.

When the minimal `.env` is created, treat it as a local handoff: if a GUI handler is available,
open the file explicitly for the user; if the session is headless, print the absolute path and
stop rather than implying a popup happened.

## User-facing promise

Use this short opening, adapting only what inspection already established:

> I will inspect what you already have, preserve it, and prepare anything missing for a complete
> walkthrough. If an existing dataset or evaluation method has a material limitation, I will
> explain the evidence and offer to repair and revalidate a working copy before any paid model
> calls. I will then show one combined estimate for the baseline and optimization. If I prepare
> temporary components, I will keep them clearly separate from real-world readiness so the result
> is not overclaimed.

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
   assistant auto-selects the user's existing vendor route when one is already available; the user
   only gets asked to choose if there is no usable route to inherit. The user sees its best
   configuration, tuning score, trial/failure count, and tracked or unmeasured cost before any
   Traigent account/key request.
2. After that checkpoint, a zero-LLM portal probe and one **connected managed optimization** that
   contains every baseline value, adds meaningful non-model knobs by default, and targets 10-13
   trials (12 by default) from a materially larger search space.

The assistant attempts to upload the completed baseline without rerunning it only when the
installed SDK exposes a public exact sync id; otherwise that result remains local. Then it compares
the two selected configurations on held-back validation data. That validation is called sealed only
when its split and labels were hidden until the candidate was locked; assistant-inspected or
assistant-authored data is explicitly non-blind. In plain language, think of that split as
test data: rows kept aside so the best config found by tuning can be checked on unseen examples
rather than scored on the same rows it optimized against. Include all calls in the combined
approval. Trial counts and knob selection are assistant-owned implementation choices, not new user
questions.

Before each baseline and optimization run, give the user a short run card: which models will be
tested, which knobs will vary, the explicit values for each knob, and the total combination count.
Keep that summary concise and exact so the user can see what is about to be tested before any paid
work starts.

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
evidence of expected production performance. A synthetic holdout is still synthetic evidence.

Keep every experiment actually persisted in the portal and finish with its verified direct link.
Label an unsynced baseline local-only. Do not delete portal experiments as walkthrough cleanup;
deletion requires an explicit later request from the user.

Only provide advanced learning links and lifecycle suggestions after the user has seen the result.
