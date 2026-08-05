---
name: traigent-first-run
description: Guide a professional first Traigent optimization from any starting point, including projects missing or containing weak agent, evaluation dataset, or evaluation method components. Use when a user asks to try Traigent, get started with Traigent, run a first optimization, optimize an agent for the first time, set up Traigent, or opens the Traigent/traigent-first-run repository. Inspect what already exists, preserve real components, diagnose limitations with concrete evidence, offer repair and revalidation before spending, create only the missing pieces as one coherent system, distinguish demonstration substitutes from production readiness, preserve the user's baseline or generate a credible small sweep, run one broader bounded optimization, and report what the result does and does not prove.
---

# Traigent Guided First Run

Help the user see a credible optimization quickly without overstating synthetic evidence.
Do the technical work. Ask only for information or approval that changes the result, cost,
data egress, or project behavior.

## Bundled guidance index

Load each reference when its stage begins:

1. [`references/component-creation.md`](references/component-creation.md) - after inventory and
   before completing or integrating any missing component.
2. [`references/evaluation-and-dataset.md`](references/evaluation-and-dataset.md) - when a dataset
   or evaluation method is assessed, repaired, or created.
3. [`references/run-safety.md`](references/run-safety.md) - before environment changes,
   evaluator execution, mock checks, or any paid execution.
4. [`references/sdk-execution.md`](references/sdk-execution.md) - only before writing the wrapper
   or running the baseline and optimization.
5. [`references/glossary.md`](references/glossary.md) - not a stage: consult it whenever
   explaining a concept to the user or phrasing a confirmation question, so terms stay
   consistent across the run and depth is calibrated from evidence, never by asking the user
   how experienced they are.

Use [`scripts/preflight.py`](scripts/preflight.py) for the free static preflight. Use
[`scripts/readiness.py`](scripts/readiness.py) as a mandatory gate, never only when it seems
useful: score all three pillars at the start of every guided run before any creation or repair,
again as a required step of local validation, and again after each repair or creation, so the
closing report can show the recorded opening score beside the closing one. Use
[`scripts/calibrate_evaluator.py`](scripts/calibrate_evaluator.py) for the separate,
explicit evaluator-execution gate. Supply lifecycle-permitted evidence from the current run;
an absent or deferred input scores its pillar from absent evidence and is never a reason to skip
the score. A config-space file found before this run's enhanced search is historical context, not
current-run readiness evidence. Only after task intent is anchored, copy
[`assets/run-plan.md`](assets/run-plan.md) into `traigent-runs/run-plan.md` and fill it from
discovered evidence. Record every readiness result there: overall score, band, and binding caps.
Update the latest result in place and never overwrite the recorded opening score.
Keep it concise and internal; do not ask the user to complete or review it.
When the project has no compatible exact SDK declaration, use the tested pins in
[`assets/requirements-first-run.txt`](assets/requirements-first-run.txt); never install an
unversioned `traigent` package.

## Operating contract

- Treat this as the user's **first Traigent run**, not as evidence about their expertise.
- Never classify or announce the user's expertise level.
- Name the actor truthfully: "I will prepare the walkthrough dataset" for assistant-created
  artifacts, and "Traigent will run the managed search" only for work the service performs.
- The loaded guide source is not automatically the target project. Resolve the user-selected agent's
  root before every write or run; guide-source artifacts never count as its results.
- Before readiness or results, state and record `Target project: <absolute path> · Agent: <absolute
  path>:<function or command>`. A mismatched resumed artifact is historical, never current.
  If none is credible, use `Agent: none discovered` until intent selects or creates one.
- A user-named external credential file is the selected handoff: after safety checks add only
  missing keys there; never copy or re-request values. Otherwise use the target `.env`.
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- After task intent is anchored, put generated artifacts under `traigent-runs/`. If
  `git -C "<project-root>" rev-parse --is-inside-work-tree` succeeds, add `/traigent-runs/` to the
  project-root `.gitignore`; otherwise do not create `.gitignore`. Never overwrite source material.
- Do not put educational or advanced-skill links in the active run. Offer links after the result.
- Keep internal check IDs, SDK internals, and optimization jargon out of user-facing progress.
- Open with `GUIDE.md`'s five-stage journey. At boundaries/long work, use `Stage <n>/5 · <name>` and
  `Done / Now / Next`. Show observed readiness score, rows checked, calls/trials, cost, or time;
  keep finished stages as compact checkmarks. Label estimates; never invent progress/ETA.
- Explain a blocked step in plain language and give one recommended recovery.
- Never silently rewrite real examples, expected answers, or grading policy. Repair a working copy
  and preserve provenance; ask before any judgment-dependent change.
- Never expose secrets in chat, commands, logs, diffs, or metadata.

## Action authorization

Use this closed authorization table. An action not listed here is forbidden until it is classified
and approved. Before beginning a new action class, re-ground in this table and the latest user
approval.

| Action class | Authorization |
|---|---|
| Read-only discovery and static validation | Proceed without approval; do not import or execute user code. |
| Create `traigent-runs/` artifacts; when the project root is inside a Git worktree, add `/traigent-runs/` to the project-root `.gitignore` | Proceed only after inspection and once task intent is anchored; when the Git probe fails, do not create `.gitignore`; preserve source material and provenance. |
| Create an isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run; do not fetch or install packages as part of environment creation. |
| Install dependencies in the isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run, and for the exact packages and versions declared for the run, as a package-artifact fetch/install with no provider or Traigent calls, private-data transfer, or user/project code execution. Name the environment's absolute path either way. Into an environment this run created, or one holding nothing but this walkthrough's own pinned set, proceed; into one with other dependents, obtain one confirmation first, because that resolution can move a package the user's other work depends on. A user or environment policy that requires install approval still takes precedence. |
| Create or update a minimal `.env` | Proceed only after free checks. Use the user-named handoff or target `.env`; preserve existing values and comments, append only its missing provider key, and require `0600` before opening. Before writing, run `references/run-safety.md`'s git-tracked-file safety check and its ignore verification; that reference owns the exact commands and exit-code handling, and stop before secret entry if either check fails. Outside Git, do not create `.gitignore`. Never copy or request a duplicate key. Add or request the Traigent key only after the baseline checkpoint. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate from the failed gate. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves a non-executing evaluator path is local-only or every mock model call is intercepted, with no external side effects. Any path that executes or imports candidate output as code, shells out with it, or submits it to a code/SQL engine must satisfy the `run-safety.md` execution-evaluator containment contract on every invocation; otherwise do not run it. |
| Make provider, private-data, connected Traigent, or external calls other than the narrow dependency fetch | Obtain stage-specific approval for recipients/data, scope, runtime, and ceiling: baseline first; connected optimization after its checkpoint. |
| Perform destructive or production-affecting actions | Obtain separate explicit approval for the exact action. |

## Status language

Track two different facts:

1. **Real-world readiness** - whether the project contains a real, validated component.
2. **Walkthrough setup** - whether the assistant prepared a temporary substitute to demonstrate the
   workflow.

Use exactly these meanings:

- `✅` - real component found and validated.
- `❗` - real component is missing, failed validation, or exists with evidence too limited for a
  credible optimization claim.
- `🛠️` - temporary walkthrough substitute created by the coding assistant.

Never mark synthetic material `✅`, never count it as real-world-ready, and never say "3/3 ready"
when any component is synthetic.

Example when nothing exists:

> **Real-world readiness**
>
> ❗ **Agent** - no production agent is connected. This is the behavior Traigent ultimately
> needs to optimize.
>
> ❗ **Dataset** - no real examples are connected. Synthetic examples may not represent
> customer traffic.
>
> ❗ **Evaluation** - no validated grading method is connected. A generated method may not
> reflect the decisions that matter to the product.
>
> **Walkthrough setup**
>
> I will prepare a coherent agent, varied dataset, and suitable evaluation method for this
> walkthrough, then Traigent will optimize that system. The result will demonstrate the
> optimization workflow, not expected production performance.

After creation, keep the three `❗` lines and add three `🛠️` lines describing the substitutes.
For mixed states, show real components as `✅` and only generated substitutes as `🛠️`.

## Guided flow

### 1. Inspect quietly

Perform safe, read-only discovery without asking for approval:

- Identify the project language, Python version, dependency system, and every existing virtual
  environment - not the first one found. A tree can hold several, under names no convention
  covers (`env`, `.direnv`, `.tox`, a tool-managed path outside the project), and stage 5 cannot
  choose between candidates it was never told about.
- Record the chosen target project's absolute root and the selected agent's absolute path plus
  callable or command. When an old artifact names another target or agent, preserve it as
  historical context but exclude it from this run's score and report.
- Find LLM/model call sites and the smallest scoreable agent function.
- Find datasets, fixtures, golden files, accepted traces, tests, rubrics, scorers, evaluators,
  and outcome checks.
- Infer the agent input/output contract and the product behavior being attempted.
- Validate the apparent quality of real Dataset and Evaluation candidates, not only their
  existence. Record concrete evidence for Agent, Dataset, and Evaluation. Do not guess.

Only ask which agent to use if multiple credible candidates remain.

Treat the resolved evaluator method as run-scoped validation state. Resolve it from the currently
selected evaluator, update it whenever that evaluator is created, repaired, or replaced, and pass
the same current `--evaluator-method` value to every paired preflight/readiness invocation. When no
evaluator method exists, omit the flag from both; never let one half infer a different method. When
a file exists but no method can be honestly declared for it without executing it - a syntax error,
or behavior that plainly ignores its input - still omit `--evaluator-method`, but pass its path to
preflight's `--evaluator` for a static syntax check; this reports present-but-unresolved, not absent.

Ground readiness task kind per the evaluation reference.

#### Opening readiness gate

Before any component creation or repair, choose from the recorded inventory. If there is exactly
one compatible Python 3.11-3.13 isolated-environment candidate overall and its resolved path is
inside the user's project root, use its resolved interpreter and report `python-version` as
measured. Otherwise use the host
`python3` as a provisional, no-install bootstrap. Multiple compatible candidates and environments
outside the project wait for stage 5; if the sole candidate fails, record why and fall back to the
host. Stage 5 remains authoritative for the connected run.

Run the bundled static preflight with `--defer-missing-sdk` over whatever dataset was discovered,
omitting `--dataset` when none exists, then run `scripts/readiness.py` on that preflight JSON and
any applicable calibration result. Apply the run-scoped evaluator-method rule above to both
scripts, and apply the run-scoped task-kind rule to readiness only.
Explicitly omit every config-space file found before this run's enhanced search, including one left
by an earlier guided run: it is historical, unverified context, not current wiring evidence. Record
its provenance and describe the agent pillar as not yet measured; a timestamp, hash, or non-empty
`wired` list does not make it current. Every guided run does this, including a zero-anchor run.
The opening score is not skippable, always reports all three pillars, and is the baseline the
closing report measures against. Show it before anything is created or repaired.

Say that the score reads the project and changes nothing in it. Show its rendered card verbatim,
then explain its score, band, and cap reasons without internal ids. Describe an existing but
unmeasured component as not yet measured. Presentation detail lives in the glossary.

Use the readiness-score presentation in `references/glossary.md`: lead with
`Stage 2/5 · Readiness - <score>/100 (<band>)` and show `<opening> → <current>` on re-score. Do not
animate with invented progress or narrate every card line.

The score grades measured evidence, not declared existence. Report an uncalibrated real evaluator
and an agent without current-run wiring evidence as not yet measured, never as absent. Do not infer
`wired` from declared `knobs`, copy it from a historical document, or write it merely to clear a
cap. Re-establish wiring on the current agent before the enhanced search as stage 7 requires; the
zero-anchor opening may proceed through the same absent-evidence cap while local setup continues.
Read-only preflight and readiness runs are static local validation; they authorize no project
write.

#### Zero-anchor intent gate

When the read-only inventory finds no agent *that performs an identifiable task*, and no dataset,
evaluation, product documentation, tests, fixtures, or other component that anchors task intent,
follow this exact order:

Judge that by what the component does, not by whether the file exists. An agent that returns a
constant, echoes its input, or is a fixture or placeholder counts as **missing** for anchoring
intent, however importable it is - the same invalid-component rule as
`references/component-creation.md`, applied here because this gate is evaluated before that
reference is loaded. A stub satisfies a file-presence test and anchors nothing, and the assistant
that treats it as an anchor invents the task the user was supposed to choose.

The opening readiness gate has already scored the empty project. Keep that result in the
conversation; recording it is a write and waits for the answer.

1. Show the rendered card, then the three real-world gaps:
   - ❗ **Agent** - no production agent is connected.
   - ❗ **Dataset** - no real examples are connected.
   - ❗ **Evaluation** - no validated grading method is connected.
2. State that the coding assistant will create coherent walkthrough substitutes after the user
   chooses the task, and that synthetic results demonstrate workflow rather than production
   performance.
3. Ask exactly one task-intent question: **"What should the walkthrough agent do?"** Offer at
   most three short choices and recommend a structured, deterministically scoreable task.
4. **STOP and wait for the answer.** Do not continue setup in the same turn.

Before that answer, make zero writes:

- Do not create `traigent-runs/`.
- Do not copy or fill the run plan.
- Do not change `.gitignore`.
- Do not create an environment.
- Do not install dependencies.
- Do not generate components.

Once the user answers, create the run record before generating the coherent trio, then continue
with the remaining stages. Record the unchanged opening score in that run record as its first
entry, before any substitute exists.

### 2. Show readiness once

For a zero-anchor project, the intent gate already rendered the initial readiness board; do not
render it again before the user answers. For every other starting state, render the initial
real-world readiness board after inspection. Show the rendered card beside that board, as printed.
State what the coding assistant will create for the walkthrough.
Do not show external links. Do not ask the user to solve missing setup pieces. Refresh only
changed evidence after creation; retain unresolved `❗` lines and add the new `🛠️` substitutes
instead of replacing the initial board with a green one.

If real material exists but appears too weak to support a meaningful comparison, show a short
**Quality advisory** immediately below the board:

- Name the affected component and cite measured evidence or specific examples.
- Explain the optimization consequence in one sentence: unreliable ranking, no measurable
  headroom, misleading accuracy, or failure during evaluation.
- Recommend: **"Repair a working copy and re-run validation"**.
- Offer only these alternatives: repair now, continue as a clearly labeled workflow
  demonstration when technically safe, or pause while the user edits it.

Do not call a component weak merely from intuition. For judgment-based findings such as "all
examples are easy," cite representative rows and the missing challenge/failure modes. For
structural findings, report counts and percentages.

### 3. Complete the system

Follow the dependency matrix in `references/component-creation.md`:

- Preserve every real component.
- Build only missing components.
- Derive each created component from all existing anchors, not independently.
- If nothing exists, create the run record and one coherent trio only after the user answers the
  single task-intent question.
- Design compatibility in both directions: dataset inputs fit the agent contract, and agent
  outputs are meaningfully scoreable by the evaluator. Treat this as a design check here; exact
  runtime binding is owned by the installed SDK and is verified in stage 5.

Create a minimal reversible integration under `traigent-runs/` or a thin wrapper around the
existing function. Do not refactor production code just to demonstrate the workflow.

When nothing exists, use this internal order: define the task and output contract, define what
the evaluator accepts, build the agent to that contract, build varied examples against both, then
cross-validate and calibrate the finished trio.

### 4. Validate components locally

Immediately after completing the system, run every available bundled component check whose full
path needs only the Python standard library and local project files. Do this before creating an
isolated environment, before installing dependencies, before creating `.env`, before asking for a
provider key, and before any SDK-specific check.

Follow this order:

1. Define the calibration case matrix and thresholds from the task semantics, then record the
   assistant-performed semantic-coverage review in `references/evaluation-and-dataset.md`, grounded
   in the strongest available product evidence. Record its evidence, materially distinct paths,
   mode/threshold rationale, gaps, and `sufficient` or `ambiguous` verdict. Use the outcome-class
   table in `references/run-safety.md` and name each case's classes in `outcome_classes`.

   Resolve any `permutation_question` from inspected evidence; ask before paid work only if the
   competing order semantics remain unresolved.
   On an execution evaluator, a permutation probe distinguished only because rearranged code is
   caught and scored as invalid carries no evidence about label/value binding; a propagated parse
   or runtime exception is not a pass. The semantic-coverage review must cover that axis for code
   tasks.
2. If unresolved product-grading ambiguity would materially change which output is correct or how
   candidate configurations rank, ask exactly one product-grading question, explain the affected
   decision, then stop and wait. Otherwise record that no ambiguity remains and do not add a generic
   review pause. Clarification never authorizes changing real labels, examples, answers, or policy;
   follow `references/evaluation-and-dataset.md` for degenerate-row bounds and gold-repair rules.
3. Run the bundled static preflight with `--defer-missing-sdk` and a single `--dataset` JSONL path
   containing the combined tuning rows, so local structure and quality problems are
   checked without importing user modules. Omit optional model-pricing checks in this
   standard-library-only pass. It checks canonical `input`/`output` fields by default. For another
   schema, pass explicit `--input-field` and `--expected-field` dot paths selected from the user's
   data and task; do not infer SDK aliases. Apply the run-scoped evaluator-method rule above: if
   the evaluator was created or changed, resolve its method again, then pass that same current
   `--evaluator-method` value to this preflight and the paired readiness invocation in step 5 (or
   omit it from both when no method exists). This heuristic check does not assert SDK compatibility.
4. Run deterministic calibration only after a `sufficient` semantic-coverage verdict. A
   non-executing evaluator must have a fully inspected local-only, side-effect-free call path and
   run in the credential-stripped calibration subprocess. An execution evaluator waits until the
   sandbox and declared local dependencies in `references/run-safety.md` are available, and every
   calibration/scored invocation uses that containment; otherwise do not run it.
5. Re-run `scripts/readiness.py` on the fresh preflight JSON plus any applicable calibration
   result. Omit every config-space file found before this run's enhanced search here just as at the
   opening gate. This score is required even when a low score or cap is expected. Record its
   overall score, band, and every binding cap in `traigent-runs/run-plan.md` beside the opening
   score. If calibration was deferred for an installed local dependency, record the preflight-only
   result now and re-run the score immediately after that calibration.

A missing Traigent SDK is `SKIP` in this deferred pre-install pass; an installed unsupported SDK is
a failure, and an optional provider package may defer only its own check. The rendered readiness
card is the summary. Do not separately explain passed calibration/mock wiring unless action is
needed or the user asks; neither is agent accuracy or an optimization result.

Do not execute an LLM judge or an evaluator with an uncertain or external call path here. Keep it
pending behind the applicable stage's egress and paid approval; removing keys or setting offline flags does
not prove an external evaluator is safe.

Classify a structurally usable but evidence-limited real component as `limited`; keep it `❗`.
Classify a component that cannot execute or measure the task as `invalid`.

For a limited component, recommend repairing a copy under `traigent-runs/` and revalidating from
the failed gate. Continuing unchanged is permitted only as an explicitly labeled workflow
demonstration whose limitation appears before and beside the result.

For an invalid evaluator, incompatible schema, corrupted required rows, or unverified call path,
do not run paid optimization against it. Offer to repair and revalidate it, pause for a
user-authored fix, or use a generated `🛠️` substitute for the walkthrough. Never treat
"continue as is" as permission to optimize against a broken grading signal.

`readiness.py` emits these decisions as closed `action_kind` values and one
`recommended_action`: `proceed` unless a blocking cap fires, otherwise the lowest-ceiling blocking
remedy. Present reasons in user language; keep machine vocabulary and condition ids internal.

Route every active dataset cap to the branch this flow already defines, and present the reason
rather than the condition id:

- `dataset-absent` - enter the creation dependency matrix.
- `dataset-no-expected-outputs` - keep it `limited` and `❗`; recommend repairing a labelled working
  copy, with approval for judgment-dependent labels. Do not use unchanged input-only data with a
  reference-requiring evaluator; disclose a reference-free method's absent independent answer key.
- `dataset-integrity-fail` - treat it as invalid; repair and revalidate a working copy or use a
  labeled `🛠️` substitute.
- `dataset-tune-holdout-overlap` - repair a disjoint split and make no generalization claim yet.
- `dataset-fully-synthetic` - apply the walkthrough labeling rules; never claim production readiness.
- `dataset-mostly-synthetic` - apply those rules, name the split out loud, and scope the claim.
- `dataset-generated-answer-key` - require that a person reviews a sample of the answers before a
  correctness claim; until then the score measures model agreement.
- `dataset-below-measurable-size` - call rankings exploratory, not stable comparisons.
- `dataset-coarse-resolution` - after paired outputs exist, report paired outcome counts and
  justified uncertainty; call a small or flat difference directional or inconclusive.

Evaluator and agent caps route through the rules that already own them: `evaluator-unresolved` (a
connected file with no honestly declarable method) and `evaluator-invalid` route through the
invalid-evaluator paragraph above - inspect, repair, or replace; `evaluator-absent` routes through
the absent-evidence reading in the opening readiness gate and the creation dependency matrix -
create or select. `agent-no-varying-knobs` before the enhanced search is an advisory ceiling, not a
repair to route: the search writes the document that lifts it. After any repair or substitute creation, re-run the affected checks, the
applicable calibration, and the score, then update the latest recorded result without overwriting
the opening one.

### 5. Prepare the environment and finish free checks

Only after the standard-library-only component checks:

1. Resolve the route from the selected agent, never from key names. Inventory presence—not values—in
   the process, handoff, and exact credentials a project-declared env loader, launcher, or secret
   manager exposes without external calls. Never enumerate stores or copy values; mark declared-only
   sources unverified. Reuse a matching credential in place when inheritable; on mismatch, do not call the
   file unsaved. Say: `Agent route: <vendor/model>. Provider credentials: <vendors and sources>.
   Traigent key: <present/absent> (not a provider credential). Preserve this route by adding <key>,
   or change to <available vendor>?` Recommend preserving unless the user chose the other vendor.
   A route change requires recipient disclosure and approval; never rewrite a route merely to match
   a key. With no route, use the sole available vendor or ask once. Generated baselines need their
   model ladder; a user-owned baseline requires only its existing route and credential.
2. Resolve and prepare the environment through `references/run-safety.md`, naming its absolute
   path before touching it. Reuse the single compatible project-root environment or, when none
   exists, create the conventional `.venv` with Python 3.11-3.13 without fetching packages.
   Preserve an incompatible `.venv` and treat `.venv-traigent` as the non-destructive
   implementation detail fallback. The reference owns candidate choice, dependent-environment,
   and activation mechanics.
3. Install the exact declared dependencies under the narrow authorization above: use the project's
   compatible exact declarations, or otherwise the exact pins in
   `assets/requirements-first-run.txt`. Never use an unversioned `pip install traigent`.
   Keep this unattended step foregrounded, explain the wait, and do not delegate it; the safety
   reference owns the rationale.
4. Verify capabilities and public signatures from the installed SDK. Use its public dataset
   loader/validator, decorator, and evaluation models; use a public no-execution contract validator
   when available, otherwise finish with safe mock plumbing and do not claim exhaustive static
   compatibility. Never recreate SDK binding fallbacks. Use resolved dataset paths for the pinned
   SDK's tracked nested-relative defect. A missing SDK blocks only these SDK checks.
5. Run calibration deferred solely for a local installed dependency. Then run a fresh-process
   Traigent mock plumbing check only when every model call and external side effect is intercepted;
   exit it and never reuse that process for a real run.
6. After all applicable free checks, create or minimally update `.env`—the selected credential
   handoff per `references/run-safety.md`: the user-named external file, or otherwise the target
   project's `.env`. Preserve every existing value and unrelated entry, add only a genuinely missing
   selected-provider key, require mode `0600` on POSIX, and stop once for only that secret locally.
   Do not request or route the Traigent key before the stage-7 baseline checkpoint.

Before baseline approval, explain only its provider recipients using `references/run-safety.md`:
the selected provider receives normal model-call content; OpenRouter and every allowed upstream
inference provider/route may receive it. Connected synchronization waits until after the baseline checkpoint.

### 6. Approve and run the baseline

Scope the run before pricing it. When the dataset carries more than about 100 usable rows, select the
bounded first-run subset described in `references/evaluation-and-dataset.md` - 18 rows by default, at
least four from each difficulty band, drawn within each split rather than across it - and estimate
runtime and spend from that subset, not from the full row count.

Select only after scoring the full dataset and before pricing the run. Record the chosen row ids,
report subset and full sizes, and state that the small first-run sample limits the claim.

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup, and do
not repeat a provider choice already resolved in stage 5.

Use the baseline checklist in `references/run-safety.md` for one concise baseline preview and
approval covering the live provider check, any pre-baseline LLM-judge calibration, and the
preserved baseline or generated six-row sweep. Say only that a separately previewed managed run may
follow; do not front-load its algorithm, search space, trial arithmetic, portal features, or insights.

Immediately before the paid baseline, show a short run card with model ids, each varying knob and
its explicit values, one plain-language note per knob, and the total combination count. The
enhanced card waits until after the baseline checkpoint.

Put the baseline runtime estimate and the default **30-minute completion target** in the same
approval as the money ceiling. This is an estimate and an up-front sizing target, not a hard
wall-clock guarantee. Size the baseline to fit before it starts.

When the SDK exposes trustworthy live progress, report only those values; otherwise report only
observable phase milestones. Never invent progress or quietly drop validation. A timeout with
completed trials yields an honest partial result and a stop-or-bounded-continuation choice; zero
trials requires diagnosis.

If the estimate exceeds `$5.00` or 30 minutes, first recommend a smaller representative slice or
trial target while preserving meaningful difficulty coverage; disclose any
reduction from the six-row baseline target. Proceed after one explicit
approval and keep it process-only. Follow `references/run-safety.md` for SDK limits and retries.
Maintain its single
running total across every paid phase, stop before the next estimate exceeds the remainder, and
do not layer another retry loop.

never call the walkthrough ceiling a hard provider-billing cap.

After the approved live provider probe, derive internal time bounds from observed latency and the
baseline work. If they no longer fit the approval, offer a smaller run or quote the additional
time/cost; do not ask the user to select implementation timeouts.

### 7. Run the honest comparison

Use the same tuning slice, evaluator, objectives, and agent call path for both measurements:

1. **Baseline** - preserve the user's existing baseline exactly, including its original row count;
   never pad it. Only when it is missing, prepare the credible six-configuration fixed sweep in
   `references/run-safety.md`, including the initial configuration.
2. **Enhanced Traigent optimization** - keep every baseline value and model, add only meaningful
   controls the agent consumes, and test up to 12 configurations (`references/sdk-execution.md`
   explains that cap and the shortfall it obliges). Add non-model, task-relevant controls by
   default; any new model is a separately disclosed experiment. The reference owns the
   generated-space mechanics that make the
   comparison attributable to the managed search rather than a quiet model upgrade.

The three-tier ladder applies only when this walkthrough supplies a missing baseline: one fast,
one mid, and one strong tier one step below - never the vendor's newest flagship - with a reasoning
tier's calling convention pinned across both spaces. A user-owned baseline is different evidence:
preserve its exact model set and do not add cheaper tiers without the separate disclosure above.
Frame the enhanced run as a deliberately small enhancement whose few evidence-driven knobs are a
small slice of what Traigent can drive, not its full capability.

The baseline needs only the user's provider credential. Run its explicit fixed grid without a
Traigent key in that process, preserving any existing key on disk, so it produces the shortest
path from "nothing set up" to "a number I can see". Say plainly that this is a **local fixed
grid**, not Traigent choosing which configurations to test. It is local, not free: provider calls
spend from the same approved total.

Immediately after it returns, show a **Local baseline checkpoint** before any Traigent-key or
account request:

- Start with the recorded target project and selected agent identity.
- If any component is `🛠️`, put the provenance limitation before the numbers.
- State what ran: a local fixed grid, not Traigent choosing the trials.
- Show the best configuration, the primary tuning metric by its actual name, cost, latency,
  executed and failed trial counts, and any Pareto note if cost and that metric trade off. Report
  cost or latency as `not measured` when the provider or SDK does not supply it.
- Explain each baseline knob in one plain-language note.
- State that no generalization or production-improvement claim exists yet and that this phase
  created no portal experiment.

This checkpoint is a valid place to stop. If the user stops, preserve the local result and report
the run as baseline-only, not as a completed Traigent optimization.

Now check whether the dataset and evaluator distinguish configurations. If not, stop before the search
and recommend the evidenced repair before any connected preview. If the baseline is nearly perfect with no
informative failures, report little or no accuracy headroom and recommend harder realistic cases;
a ceiling effect remains a hypothesis. An accuracy-only search requires a workflow-demonstration
label. A cost objective may proceed at equal accuracy only when materially lower cost remains
possible; report any gain as cost and still flag weak evidence.

Only when this gate supports a measured opportunity, preview the connected step with the CTA and
approval rules in `references/run-safety.md`.

Present `Stage 4/5 · Optimize` with the checklist in `references/run-safety.md`: explain
managed selection, portal history, bounded calls/cost, and deeper insights as conditional
capabilities. Obtain explicit approval for this connected stage before its key, probe, sync, or
calls. In the enhanced run card, repeat the baseline knobs, label every addition new, and give its
total combination count; pair that count with this run's trial cap as a ceiling, never a range: how
many configurations exist and how many of them Traigent will test. `references/run-safety.md` owns
that wording, both numbers' source, and what to say when the count cannot be computed. Disclose any
reduction from that ceiling here rather than at the baseline approval. Never promise a pause at
minute 30; size the synchronous run first.

Now explain Traigent's documented synchronization, exclusions, and exceptions from that reference;
call it a service contract rather than a packet audit and stop if runtime behavior contradicts it.

Only after that checkpoint, ask for the Traigent key. The order is the point: the user has already
seen a provider-backed result before being asked to create an account. Tell them the key needs full
access rather than the read-only default, because a read-only key can leave a paid connected run
unrecorded. Reuse a preserved suitable key or establish exactly one of the four account/key states
in `references/run-safety.md` before naming a destination; follow that reference's single ordered
handoff and have the user enter credentials locally, never in chat. Use the same selected
credential file: the target-project `.env`, or the user-named external source already used for
the baseline. Open that exact absolute path once, using the first available GUI editor; if that is
unavailable, fall back to the IDE or editor already associated with the selected project directory,
and if headless, print the full path and stop. Open it only so the user can add
`TRAIGENT_API_KEY=` for the enhanced run. Then refresh/reopen that same file so the new line is
visible, and follow
`references/run-safety.md` for the clickable registration link and the two 10-day windows.

Once the key is present, run the zero-LLM portal probe. Then feature-detect a public exact sync id
and follow `references/sdk-execution.md` for its capability-gated exact-session sync. Without a
supported id, keep the baseline local; never inspect private storage or use `--all`. Run the
enhanced optimization connected, require its own verified portal link, and report a direct link for
every persisted run without implying it covers a local-only baseline.

Do not run an offline baseline and then pay to repeat it merely to populate the portal. Do not ask
the user to choose trial counts or knobs; select them from the inspected agent and include their
calls in the connected-stage approval.
Every knob must change real behavior, native booleans must stay booleans, and the enhanced space
must be materially larger than its trial cap so Traigent is choosing what to test rather than
replaying the same tiny grid.

Before the enhanced search, re-establish current wiring in memory using the pure per-model,
per-input request-diff probe and explicit outside-request claims in
`references/sdk-execution.md`; a historical `wired` attestation is never proof. Once the enhanced
space is final, follow that reference's freeze/remove/persist lifecycle. Save
`traigent-runs/config-space.json` only after this search returns nonzero trials, from the exact
space it received, and use only that current-run document for the closing `--config-space` score.

If provider, Traigent backend, or portal connectivity is unavailable, stop with the concrete
failure and one recommended recovery. Never fall back automatically to mock or synthetic results,
and never present offline checks as a completed optimization. Resume the connected path after the
failure is resolved.

Do not fabricate configurations to hit a row count. A preserved one-row user baseline is an honest
one-row before and stays unchanged. An assistant-prepared walkthrough must not proceed with a one-
row baseline; generate enough real controls for the six-configuration default.

Do not require a third optimization pass. Recommend another iteration only after the first result
reveals a specific, worthwhile hypothesis.

### 8. Verify and report

Before saying the run succeeded, apply every post-run verification in
`references/run-safety.md`. Also verify that the baseline was preserved exactly or the generated
six-row default (including its initial configuration) ran, subject only to an approved disclosed
reduction; the enhanced run used real controls and either produced at least 10 of its 12 permitted
trials, matched an explicitly approved and disclosed reduced target, or reports a concrete
stop/failure reason; and a
best configuration and non-degenerate measures exist. Report truncation and persistence failures,
require the portal probe to have stayed green, and verify each portal link before claiming
visibility.

Lead with a layered summary whose opening layers are enough for a quick read and whose details are
auditable:

1. **Outcome** - baseline versus enhanced result and whether a recommendation is supported.
2. **What the evidence establishes** - baseline tuning result, enhanced tuning result, and actual
   persisted runs.
3. **Current state and limits** - component provenance, exclusions, uncertainty, incomplete
   phases, and any small-data overfitting risk.
4. **Next action** - one action selected from the latest closing evidence.
5. **Details** - configurations, objectives, trials, failures, cost, stop reason, artifacts, and
   verified links.

Include:

- Best baseline configuration versus best enhanced configuration on the tuning set.
- Cost, the configurations tested out of the space's total, failures, stop reason, and direct
  portal links.
- Which components were `✅` real and which were `🛠️` walkthrough substitutes.
- The readiness transition: the recorded opening score and band, the closing score and band, and
  which caps cleared and which remain.
- The run's scope, in this run's own recorded numbers: rows scored beside the dataset's usable
  rows, trials executed beside the enhanced space's combination count, and knobs varied beside the
  controls this run identified on the agent. Say plainly that those bounds were the walkthrough's
  own choice - a getting-familiar run rather than the largest one available - and keep it a scope
  statement, never a pitch. Drop any clause this run did not measure instead of estimating it.
  `references/run-safety.md` owns each number's source and how the sentence degrades.
- When the enhanced run does not beat the baseline, report the observed flat/negative delta first,
  then separate verified facts, evidence-backed inferences, and untested hypotheses. Use
  `cause not established by this run` unless the evidence rules a cause in. The hypotheses and
  rule-out order in `references/run-safety.md` guide the next test; they are not mandatory
  diagnoses. When the reference is demonstrably ambiguous, wrong, or degenerate, say so rather
  than blaming the model. A flat result on demonstration data shows only that this comparison ran
  and found no lift on its evidence, not that production cannot improve. Carry the run-scope
  statement above into this no-lift report beside the delta itself, not only in the scope line: the
  bounds are what let no lift be read at the scale it was actually measured at.

Retain every experiment that was actually persisted in the Traigent portal. Never delete one as
automatic teardown or cleanup. Give the user a direct verified link for each persisted run and
label the baseline local-only when exact sync was unsupported or failed.

If any substitute was used, lead the interpretation with:

> Completed in this run: `<verified phases>`. Not completed or independently verified:
> `<missing phases>`. Because `<components>` were prepared as walkthrough substitutes, the
> measured result is not evidence of expected production performance.

Do not promote a configuration from a fully synthetic run. For real components, promotion still
requires explicit user approval and a later validation check that is tracked separately from the
baseline/enhanced comparison. When the assistant inspected or authored that material, call it
assistant-authored or assistant-inspected evidence and do not present it as independent
production-promotion evidence.

Name every row the comparison did not score, with its id: rows excluded as degenerate references,
and the ids of the bounded subset when one was drawn. A result quoted on 25 of 30 rows is a
different claim from one quoted on 30, and the reader cannot reproduce either without knowing
which rows they were. State it even when nothing was excluded, so silence never has to be
interpreted.

Close the loop on the readiness score the run opened with: re-run `scripts/readiness.py` on the
post-run evidence and show opening beside closing, naming cleared and remaining caps. Pass the
current run's `--config-space traigent-runs/config-space.json` only when its enhanced search emitted
it; otherwise score the agent from absent evidence. Treat every gain from a `🛠️` substitute as
walkthrough setup, restate its real-world cost, and leave the user knowing which remaining gap to
close first.

Feature-detect local audit and connected insight capabilities. Report only fields actually
returned, attribute each claim to its artifact, and otherwise say no verified local artifact was
available. Surface deeper signals only when a verified run-scoped platform artifact actually
returned them. Never fill the DEEPER-INSIGHTS template from expectation, infer labels from a flat
score, promise a numeric dataset-quality score, or imply the platform graded an unrun dataset;
over substitutes, every insight describes only the walkthrough.

After the readiness transition, close by saying what a further run would be worth. Name the ones
still open and what each is now costing; use the user's own measured evidence rather than
encouragement. Say what this walkthrough cannot close. Then give the one next action the **latest
validated state** earns: re-rank the remaining closing caps and run limits, ignore cleared gaps,
and name its value:

- Generated or mostly generated data - collect or export a real sample of the same task and re-run.
  This is the gap that ceilings the score no matter how good everything else is, so it is first
  whenever it applies.
- Real inputs with model-written answers - have a person review a sample of the answer key. Until
  then the accuracy number measures agreement with a model, not correctness.
- Rows without expected outputs when the evaluator requires references - label a representative
  slice rather than the whole set. Symbol-only outputs are an explicit verification question, not
  silently discarded labels.
- One difficulty band, or answers that are nearly all the same - add examples where the agent
  currently fails, which is also where a search has room to win.
- A substitute component still standing in for a real one - connect the production agent, dataset or
  evaluator it replaced, and say which of the reported numbers would change.
- A thin evaluator, or one that was never calibrated - align the method with the product's own
  grading policy before trusting a comparison built on it.

A menu offered *instead of* a recommendation is the same as no recommendation; put extras later.

End with the CTA in `references/run-safety.md`; `continue` never bypasses approval.

Those state-specific moves are the ones this run measured. Separately, and only after the result,
these are available whenever the user wants them rather than because their state calls for them:

- Hand over the Traigent optimization skills so the user can continue alone, at their full dataset,
  more controls, and their own iterations. Tell the user first and remind them to restart the
  session so the new skills load. List them with `npx skills add Traigent/traigent-skills --list`,
  install one with `npx skills add Traigent/traigent-skills --skill <name>`, or take all of them
  with `--skill '*'`. Then name the two or three this run's own evidence points at and what each
  would let them do next; `references/run-safety.md` owns that map. Offering this is not a
  state-specific recommendation and never displaces the one above; only which skills get named
  comes from this run's evidence.
- Every observation carried into that handoff is a hypothesis to test at full scale, never a
  finding. At this run's row and trial counts a control that moved nothing was mostly not sampled
  enough to say so; write what is worth testing next, never that a control was shown not to matter.
- Continue into the advanced Traigent lifecycle.

## Completion criteria

The first run is complete only when:

- The starting state and provenance of all three components are recorded.
- Material quality limitations were explained with evidence and a repair/continue/pause choice.
- Any repaired component was revalidated before its status changed.
- The opening readiness score was computed before any creation or repair, recorded with its band
  and caps, and closed with the later score in the final report.
- All missing components were built around the existing ones.
- Dataset, agent, and evaluator compatibility passed.
- The evaluator passes the recorded semantic mode for every case: graded tasks distinguish
  good/equivalent, partial, and bad outputs; binary tasks accept good/equivalent and reject both
  partial and bad outputs.
- Calibration covers and records materially distinct inputs and outcome classes when scoring
  depends on inputs, labels, schemas, or rubric branches.
- The assistant performed and recorded an evidence-backed semantic-coverage review of every
  material input, outcome, and rubric/schema branch, including mode and threshold rationale, known
  gaps, and the verdict before execution.
- Any unresolved ambiguity that would materially change correctness or ranking was resolved by one
  product-grading question before calibration; absent such ambiguity, no review-only pause
  occurred.
- Free checks made no provider calls.
- Each paid stage had explicit approval before its calls.
- Baseline and optimization used the same tuning data and evaluator.
- Result claims match the provenance and validation evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
