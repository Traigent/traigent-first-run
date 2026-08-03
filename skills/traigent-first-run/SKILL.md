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
   or running the baseline, optimization, and holdout.
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
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- After task intent is anchored, put generated artifacts under `traigent-runs/`. If
  `git -C "<project-root>" rev-parse --is-inside-work-tree` succeeds, add `/traigent-runs/` to the
  project-root `.gitignore`; otherwise do not create `.gitignore`. Never overwrite source material.
- Do not put educational or advanced-skill links in the active run. Offer links after the result.
- Keep internal check IDs, SDK internals, and optimization jargon out of user-facing progress.
- At each stage boundary, and before and after any step that may take more than about a minute,
  give a compact `Done / Now / Next` update. Use only observed milestones. Report trial counts,
  the current best, spend, or remaining time only when the running SDK exposes those values;
  never invent a percentage or ETA to fill silence.
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
| Create or update a minimal `.env` | Proceed only after every applicable free component, capability, and safe mock check has run. Preserve existing values, comments, unrelated keys, and any Traigent key already present. Before the local baseline, append only the missing selected-provider key name with a blank value. Before opening it, require mode `0600` on POSIX. In a Git worktree, run `git -C "<project-root>" ls-files --error-unmatch -- .env`: exit 0 means tracked and must stop; continue only on exit 1 with no match, and stop on any other status. Preserve the project-root `.gitignore` while ensuring it contains an effective `/.env` rule, then require `git -C "<project-root>" check-ignore -q -- .env` to succeed; stop before secret entry if the effective-ignore check fails. Open the full absolute `.env` path, not a relative path or vague popup, so the user can see which file to edit. Outside Git, do not create `.gitignore`. Then stop once for the local secret. Add or request the Traigent key only after the baseline checkpoint in stage 7. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate from the failed gate. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves a non-executing evaluator path is local-only or every mock model call is intercepted, with no external side effects. Any path that executes or imports candidate output as code, shells out with it, or submits it to a code/SQL engine must satisfy the `run-safety.md` execution-evaluator containment contract on every invocation; otherwise do not run it. |
| Make provider, private-data, connected Traigent, or external calls other than the narrow dependency fetch above | Obtain one concise approval for recipients/data, planned scope, approximate runtime, and the total walkthrough ceiling. |
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
evaluator method exists, omit the flag from both; never let one half infer a different method.

#### Opening readiness gate

After the read-only inventory and before any component creation or repair, select the opening
interpreter from evidence already recorded in stage 1. If there is exactly one compatible
Python 3.11-3.13 isolated-environment candidate overall and its resolved path is inside the user's
project root, use its resolved interpreter for every bundled script before stage 5 and report
`python-version` as measured. Otherwise use the
host `python3` as a narrow, no-install bootstrap and mark only that bootstrap's `python-version`
provisional. Multiple compatible candidates and environments outside the project remain unresolved
until the stage-5 choice; if the single recorded candidate no longer launches, record why and fall
back to the host bootstrap. The environment selected or created in stage 5 remains authoritative
for the connected run.

Run the bundled static preflight with `--defer-missing-sdk` over whatever dataset was discovered,
omitting `--dataset` when none exists, then run `scripts/readiness.py` on that preflight JSON and
any applicable calibration result. Apply the run-scoped evaluator-method rule above to both
scripts.
Explicitly omit every config-space file found before this run's enhanced search, including one left
by an earlier guided run: it is historical, unverified context, not current wiring evidence. Record
its provenance and describe the agent pillar as not yet measured; a timestamp, hash, or non-empty
`wired` list does not make it current. Every guided run does this, including a zero-anchor run.
The opening score is not skippable, always reports all three pillars, and is the baseline the
closing report measures against. Show it before anything is created or repaired.

Announce it by what it does for the reader, not by the rule that binds you. "Mandatory" describes
the assistant's obligation and tells the user nothing about their run; "static" is a word from the
tooling. Say that it reads the project and changes nothing in it - which is the fact a reader
actually wants before a tool inspects their code - and let the obligation stay internal.

Show the script's rendered card verbatim in a code block, not a retyped table or the durable
markdown report. Preserve its pillar bars, measured-check counts, and `LIMITED TO` versus
`WOULD LIMIT TO` wording. Add the overall score, band, and each cap's plain-language reason around
it while keeping internal condition ids out of the conversation. Caps select stage-4 branches; by
themselves they do not stop the run. Describe an existing but unmeasured component as not yet
measured rather than repeating an absence-oriented card reason.

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

   When `calibrate_evaluator.py` returns a `permutation_question`, put it to the user before any
   paid run; it asks whether order genuinely matters and is not a failed calibration check.
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
   containing the combined tuning and holdout rows, so local structure and quality problems are
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
a failure, and an optional provider package may defer only its own check. Record independent
dataset-quality and safe-calibration results separately. Do not reproduce SDK normalization,
injection, binding, or callback rules here.

Do not execute an LLM judge or an evaluator with an uncertain or external call path here. Keep it
pending behind the combined egress and paid approval; removing keys or setting offline flags does
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

Evaluator and agent caps route through the rules that already own them: the invalid-evaluator
paragraph above, and the absent-evidence reading in the opening readiness gate. After any repair
or substitute creation, re-run the affected checks, the applicable calibration, and the score,
then update the latest recorded result without overwriting the opening one.

### 5. Prepare the environment and finish free checks

Only after the standard-library-only component checks:

1. Determine the current provider route from the agent's actual model call and configuration. Treat
   discovered credential names only as an availability inventory; they never select or change an
   existing route. Prefer the vendor already implied by the project or current agent wiring, and
   select models from that vendor automatically. If no usable vendor is already implied by the
   project or current agent wiring, ask the user which vendor they want and try to configure it
   automatically from the available credentials. Only when the walkthrough must prepare a missing
   baseline, require the chosen vendor to supply the three-model ladder. If it cannot and the user
   already has a second supported direct-provider credential, offer that for the missing rung;
   otherwise stop with one clear mismatch and ask for help. A user-owned baseline requires only its
   existing route and credential. Never rewrite the model identifier or provider prefix merely to
   match an available key.
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
6. After all applicable free checks, create or minimally update `.env` per
   `references/run-safety.md`: preserve every existing value and unrelated entry, add only the
   blank selected-provider key, require mode `0600` on POSIX, and stop once for only that secret
   locally. Do not request or route the Traigent key before the stage-7 baseline checkpoint.

Before approval, explain the recipients and content using `references/run-safety.md`: the selected
provider receives its normal model-call content; OpenRouter and every allowed upstream inference
provider/route may receive it; and connected Traigent runs synchronize configuration keys and
values, numeric measures, run state, and content-free metadata. State the documented exclusions
and exceptions there, call this a service contract rather than a packet audit, and stop if observed
runtime behavior contradicts it.

### 6. Ask once before paid work

Scope the run before pricing it. When the dataset carries more than about 100 usable rows, select the
bounded first-run subset described in `references/evaluation-and-dataset.md` - 18 rows by default, at
least four from each difficulty band, drawn within each split rather than across it - and estimate
runtime and spend from that subset, not from the full row count.

Select only after scoring the full dataset and before pricing the run. Record the chosen row ids,
report subset and full sizes, and state that the small first-run sample limits the claim.

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup.
Do not repeat a provider choice already resolved in stage 5; keep the paid-work approval request
combined.
Prepare one concise combined approval immediately before paid work. It covers the smallest live
provider-credential check, any required LLM-judge calibration, the preserved baseline or a
generated six-row sweep, one broader bounded optimization, and baseline winner versus enhanced
winner validation comparison. Follow the complete disclosure checklist in
`references/run-safety.md`; it owns the sizing, objectives, decision rule, model-space, cost,
recipient, and execution-sandbox detail. Use a `$5.00` total walkthrough ceiling by default.

Immediately before each paid baseline and enhanced run, show a short run card with the model ids,
each varying knob and its explicit values, one plain-language note per knob, and the total
combination count. For the enhanced card, repeat the baseline knobs and label every addition new.

Put the runtime estimate and the default **30-minute completion target** in the same approval as the
money ceiling. This is an estimate and an up-front sizing target, not a hard wall-clock guarantee.
The default synchronous enhanced run may expose neither an interruptible checkpoint nor live
partial results, so never promise a pause at minute 30. Size the run to fit before it starts.

When the SDK exposes trustworthy live progress, report only those values; otherwise report only
observable phase milestones. Never invent progress or quietly drop validation. A timeout with
completed trials yields an honest partial result and a stop-or-bounded-continuation choice; zero
trials requires diagnosis.

If the estimate exceeds `$5.00` or 30 minutes, first recommend a smaller representative slice or
trial target while preserving meaningful difficulty and a holdout; disclose any reduction from the
six-row baseline or 10-13-trial enhanced target. Proceed after one explicit approval and keep it
process-only. Follow `references/run-safety.md` for SDK limits and retries. Maintain its single
running total across every paid phase, stop before the next estimate exceeds the remainder, and
do not layer another retry loop.
never call the walkthrough ceiling a hard provider-billing cap.

The approval covers the later zero-LLM portal-tracking probe, but the Traigent key and probe wait
until after the local baseline checkpoint. At stage 7, follow `references/run-safety.md` to verify
authentication, `experiment.write`, session/trial acceptance, and `cloud_url` before the first
connected paid trial. Sanitize any failure and stop; later local-only degradation also halts paid
work immediately.

After the approved live provider probe, derive internal time bounds from observed latency and the
planned work. If they no longer fit the approval, offer a smaller run or quote the additional
time/cost; do not ask the user to select implementation timeouts.

### 7. Run the honest comparison

Use the same tuning slice, evaluator, objectives, and agent call path for both measurements:

1. **Baseline** - preserve the user's existing baseline exactly, including its original row count;
   never pad it. Only when it is missing, prepare the credible six-configuration fixed sweep in
   `references/run-safety.md`, including the initial configuration.
2. **Enhanced Traigent optimization** - keep every baseline value and model, add only meaningful
   controls the agent consumes, and target 10-13 visible trials with an internal cap of 12. Add
   non-model, task-relevant controls by default; any new model is a separately disclosed
   experiment. The reference owns the generated-space mechanics that make the comparison
   attributable to the managed search rather than a quiet model upgrade.

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

- If any component is `🛠️`, put the provenance limitation before the numbers.
- State what ran: a local fixed grid, not Traigent choosing the trials.
- Show the best configuration, the primary tuning metric by its actual name, cost, latency,
  executed and failed trial counts, and any Pareto note if cost and that metric trade off. Report
  cost or latency as `not measured` when the provider or SDK does not supply it.
- Explain each baseline knob in one plain-language note.
- State that no validation comparison or improvement claim exists yet and that this phase created no
  portal experiment.
- Name the next step: add the Traigent key, verify portal tracking with a zero-LLM probe, attempt an
  exact baseline upload without rerunning it when the installed public API supports that, then run
  the connected enhanced optimization.

This checkpoint is a valid place to stop. If the user stops, preserve the local result and report
the run as baseline-only, not as a completed Traigent optimization.

Only after that checkpoint, ask for the Traigent key. The order is the point: the user has already
seen a provider-backed result before being asked to create an account. Tell them the key needs full
access rather than the read-only default, because a read-only key can leave a paid connected run
unrecorded. Reuse a preserved suitable key or establish exactly one of the four account/key states
in `references/run-safety.md` before naming a destination; follow that reference's single ordered
handoff and have the user enter credentials locally, never in chat. Use the same `.env` file.
Open that project-root `.env` once, using the first available GUI editor; if that is unavailable,
fall back to the IDE or editor already associated with this project directory, and if headless,
print the full path and stop. Open it only so the user can add `TRAIGENT_API_KEY=` for the
enhanced run. Then refresh/reopen it so the new line is visible, and follow
`references/run-safety.md` for the clickable registration link and the two 10-day windows.

Once the key is present, run the zero-LLM portal probe. Then feature-detect a public exact sync id
and follow `references/sdk-execution.md` for its capability-gated exact-session sync. Without a
supported id, keep the baseline local; never inspect private storage or use `--all`. Run the
enhanced optimization connected, require its own verified portal link, and report a direct link for
every persisted run without implying it covers a local-only baseline.

Do not run an offline baseline and then pay to repeat it merely to populate the portal. Do not ask
the user to choose trial counts or knobs; select them from the inspected agent and include their
calls in the combined approval.
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

After the baseline, check whether the dataset and evaluator can distinguish configurations. If
the baseline is perfect or nearly perfect and has no informative failures, stop before the search
and report that this evidence shows little or no accuracy headroom. A ceiling effect remains a
hypothesis; follow `references/run-safety.md` to name live alternatives and recommend harder,
realistic cases. Continue an accuracy-only search solely as a labeled workflow demonstration.
When cost is also an objective, equal accuracy at materially lower cost is a legitimate Pareto win:
run while cost has headroom, report the gain as cost rather than accuracy, and still question a
small, easy, synthetic, narrow, or lenient measurement in parallel.

Do not require a third optimization pass. Recommend another iteration only after the first result
reveals a specific, worthwhile hypothesis.

### 8. Verify and report

Before saying the run succeeded, apply every post-run verification in
`references/run-safety.md`. Also verify that the baseline was preserved exactly or the generated
six-row default (including its initial configuration) ran, subject only to an approved disclosed
reduction; the enhanced run used real controls and either produced 10-13 trials, matched an
explicitly approved and disclosed reduced target, or reports a concrete stop/failure reason; and a
best configuration and non-degenerate measures exist. Report truncation and persistence failures,
require the portal probe to have stayed green, and verify each portal link before claiming visibility.

Lead with a layered summary whose opening layers are enough for a quick read and whose details are
auditable:

1. **Outcome** - baseline versus enhanced result and whether a recommendation is supported.
2. **What the evidence establishes** - tuning result, validation result, and actual persisted runs.
3. **Current state and limits** - component provenance, exclusions, uncertainty, and incomplete
   phases.
4. **Next action** - one action selected from the latest closing evidence.
5. **Details** - configurations, objectives, trials, failures, cost, stop reason, artifacts, and
   verified links.

Include:

- Best small-sweep configuration versus best enhanced configuration on the tuning set.
- Validation result separately, including whether it was sealed or held-back and non-blind.
- Cost, trial count, failures, stop reason, and direct portal links.
- Which components were `✅` real and which were `🛠️` walkthrough substitutes.
- The readiness transition: the recorded opening score and band, the closing score and band, and
  which caps cleared and which remain.
- When the enhanced run does not beat the baseline, report the observed flat/negative delta first,
  then separate verified facts, evidence-backed inferences, and untested hypotheses. Use
  `cause not established by this run` unless the evidence rules a cause in. The hypotheses and
  rule-out order in `references/run-safety.md` guide the next test; they are not mandatory
  diagnoses. When the reference is demonstrably ambiguous, wrong, or degenerate, say so rather
  than blaming the model. A flat result on demonstration data shows only that this comparison ran
  and found no lift on its evidence, not that production cannot improve.

Retain every experiment that was actually persisted in the Traigent portal. Never delete one as
automatic teardown or cleanup. Give the user a direct verified link for each persisted run and
label the baseline local-only when exact sync was unsupported or failed.

If any substitute was used, lead the interpretation with:

> Completed in this run: `<verified phases>`. Not completed or independently verified:
> `<missing phases>`. Because `<components>` were prepared as walkthrough substitutes, the
> measured result is not evidence of expected production performance.

Do not promote a configuration from a fully synthetic run. For real components, promotion still
requires explicit user approval and a sealed validation set: the split and labels were fixed and
hidden from component design, tuning, and winner selection until the candidate was locked. When
the assistant inspected or authored that material, call it **held-back, non-blind validation**,
not an untouched holdout, and do not present it as independent production-promotion evidence.

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

Close by saying what a further run would be worth, grounded in the two facts already on the table:
the gaps the opening readiness score named, and which of them this run actually closed. Name the
ones still open and what each is now costing - an unlabelled half of the dataset, a single-band
difficulty spread, a substitute component still standing in for a real one - so the motivation is
the user's own measured evidence rather than encouragement. Where a gap is one this walkthrough
cannot close, say that plainly instead of implying a further run would fix it.

Then give the one next action the **latest validated state** earns, not generic advice. Re-rank the
remaining closing caps and observed run limitations; do not repeat an opening gap that this run
cleared. Name the specific move and what it would buy:

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

One action, named for their state, with the reason attached. A menu offered *instead of* a
recommendation is the same as no recommendation - so this is the recommendation, and anything else
comes after it and says so.

Those state-specific moves are the ones this run measured. Separately, and only after the result,
these are available whenever the user wants them rather than because their state calls for them:

- Install the Traigent optimization skills with `npx skills add Traigent/traigent-skills` for a
  stronger enhanced run, telling the user first and reminding them to restart the session so the
  new skills load.
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
- Paid work had explicit combined approval.
- Baseline and optimization used the same tuning data and evaluator.
- Result claims match the provenance and validation evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
