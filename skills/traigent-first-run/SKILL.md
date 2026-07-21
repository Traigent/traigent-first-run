---
name: traigent-first-run
description: Guide a professional first Traigent optimization from any starting point, including projects missing or containing weak agent, evaluation dataset, or evaluation method components. Use when a user asks to try Traigent, run a first optimization, optimize an agent for the first time, set up Traigent, or opens the Traigent/traigent-first-run repository. Inspect what already exists, preserve real components, diagnose limitations with concrete evidence, offer repair and revalidation before spending, create only the missing pieces as one coherent system, distinguish demonstration substitutes from production readiness, run an honest current-configuration baseline plus one bounded optimization, and report what the result does and does not prove.
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

Use [`scripts/preflight.py`](scripts/preflight.py) for the free static preflight. Use
[`scripts/readiness.py`](scripts/readiness.py) to verify the readiness-state transition when
helpful. Use [`scripts/calibrate_evaluator.py`](scripts/calibrate_evaluator.py) for the separate,
explicit evaluator-execution gate. Only after task intent is anchored, copy
[`assets/run-plan.md`](assets/run-plan.md) into `traigent-runs/run-plan.md` and fill it from
discovered evidence. Keep it concise and internal; do not ask the user to complete or review it.
When the project has no compatible exact SDK declaration, use the tested pins in
[`assets/requirements-first-run.txt`](assets/requirements-first-run.txt); never install an
unversioned `traigent` package.

## Operating contract

- Treat this as the user's **first Traigent run**, not as evidence about their expertise.
- Never classify or announce the user's expertise level.
- Speak for a capable system: "Traigent will generate..." and "I will validate...", not
  "Traigent can use a sample..."
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- After task intent is anchored, put generated artifacts under `traigent-runs/` and add that
  directory to the project `.gitignore`. Never overwrite source material.
- Do not put educational or advanced-skill links in the active run. Offer links after the result.
- Keep internal check IDs, SDK internals, and optimization jargon out of user-facing progress.
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
| Create `traigent-runs/` artifacts and add that path to `.gitignore` | Proceed only after inspection and once task intent is anchored; preserve source material and provenance. |
| Create an isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run; do not fetch or install packages as part of environment creation. |
| Install dependencies in the isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run, and for the exact packages and versions declared for the run, as a package-artifact fetch/install with no provider or Traigent calls, private-data transfer, or user/project code execution. A user or environment policy that requires install approval still takes precedence. |
| Create or update a minimal `.env` | Proceed only after every applicable free component, capability, and safe mock check has run. Preserve existing values, comments, and unrelated keys; append only missing selected-provider and Traigent key names with blank values. Before opening it, require mode `0600` on POSIX, then stop once for local secret entry. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate from the failed gate. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves the evaluator path is local-only or every mock model call is intercepted, with no external side effects. |
| Make provider, private-data, connected Traigent, or external calls other than the narrow dependency fetch above | Obtain one concise approval for recipients/data, planned scope, approximate runtime, and the total walkthrough ceiling. |
| Perform destructive or production-affecting actions | Obtain separate explicit approval for the exact action. |

## Status language

Track two different facts:

1. **Real-world readiness** - whether the project contains a real, validated component.
2. **Walkthrough setup** - whether Traigent prepared a temporary substitute to demonstrate the
   workflow.

Use exactly these meanings:

- `✅` - real component found and validated.
- `❗` - real component is missing, failed validation, or exists with evidence too limited for a
  credible optimization claim.
- `🛠️` - temporary walkthrough substitute created by Traigent.

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
> Traigent will generate a coherent agent, varied dataset, and suitable evaluation method for
> this walkthrough. The result will demonstrate the optimization workflow, not expected
> production performance.

After creation, keep the three `❗` lines and add three `🛠️` lines describing the substitutes.
For mixed states, show real components as `✅` and only generated substitutes as `🛠️`.

## Guided flow

### 1. Inspect quietly

Perform safe, read-only discovery without asking for approval:

- Identify the project language, Python version, dependency system, and existing virtual
  environment.
- Find LLM/model call sites and the smallest scoreable agent function.
- Find datasets, fixtures, golden files, accepted traces, tests, rubrics, scorers, evaluators,
  and outcome checks.
- Infer the agent input/output contract and the product behavior being attempted.
- Validate the apparent quality of real Dataset and Evaluation candidates, not only their
  existence. Record concrete evidence for Agent, Dataset, and Evaluation. Do not guess.

Only ask which agent to use if multiple credible candidates remain.

#### Zero-anchor intent gate

When the read-only inventory finds no agent, dataset, evaluation, product documentation, tests,
fixtures, or other component that anchors task intent, follow this exact order:

1. Present the three real-world gaps:
   - ❗ **Agent** - no production agent is connected.
   - ❗ **Dataset** - no real examples are connected.
   - ❗ **Evaluation** - no validated grading method is connected.
2. State that Traigent will create the coherent walkthrough substitutes after the user chooses
   the task, and that synthetic results will demonstrate workflow rather than production
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
with the remaining stages.

### 2. Show readiness once

For a zero-anchor project, the intent gate already rendered the initial readiness board; do not
render it again before the user answers. For every other starting state, render the initial
real-world readiness board after inspection. State what Traigent will create for the walkthrough.
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
   assistant-performed semantic-coverage review described in
   `references/evaluation-and-dataset.md`. Ground it in the strongest available product evidence:
   contracts and documentation, tests and fixtures, labels and examples, accepted outputs,
   rubrics, and failure reports. Record the semantic-coverage reviewer and evidence, materially
   distinct inputs, outcome classes, and rubric/schema branches, the mode and threshold rationale,
   known gaps, and a `sufficient` or `ambiguous` verdict.
2. If unresolved product-grading ambiguity would materially change which output is correct or how
   candidate configurations rank, ask exactly one product-grading question, explain the competing
   interpretations and affected decision, then stop and wait. Otherwise record that no material
   ambiguity remains and proceed without a generic review pause. A clarification does not
   authorize changing real labels, expected answers, examples, or rubric policy; show any exact
   judgment-dependent change and obtain the explicit approval required by the action table.
3. Run the bundled static preflight with `--defer-missing-sdk` and the combined dataset argument
   so local structure and quality
   problems are checked without importing user modules. Omit optional model-pricing checks in this
   standard-library-only pass. It checks canonical `input`/`output` fields by default. For another
   schema, pass explicit `--input-field` and `--expected-field` dot paths selected from the user's
   data and task; do not infer SDK aliases. This heuristic check does not assert SDK compatibility.
4. Run deterministic evaluator calibration only when the semantic-coverage verdict is
   `sufficient` and the complete inspected import and call path
   is local-only, has no external side effects, and needs no unavailable third-party package.
   Execute it in the isolated subprocess with provider credentials removed.

A missing Traigent SDK is `SKIP` in this explicitly deferred pre-install pass; an installed but
unsupported SDK remains a failure. A missing optional provider package may defer its own check.
Neither condition may block independent dataset-quality or safe
deterministic-calibration results. Record those component results separately. Do not reproduce
SDK dataset normalization, injection, agent-binding, or evaluator-callback rules in this skill.

Do not execute an LLM judge or an evaluator with an uncertain or external call path here. Keep it
pending behind the combined egress and paid approval; removing keys or setting offline flags does
not prove an external evaluator is safe.

Classify a structurally usable but evidence-limited real component as `limited`; keep it `❗`.
Classify a component that cannot execute or measure the task as `invalid`.

For a limited component, recommend repairing a copy under `traigent-runs/`, then re-run every
relevant check and calibration from the start. The user may continue unchanged only as an
explicitly labeled workflow demonstration. Record the limitation before execution and repeat it
beside the result.

For an invalid evaluator, incompatible schema, corrupted required rows, or unverified call path,
do not run paid optimization against it. Offer to repair and revalidate it, pause for a
user-authored fix, or use a generated `🛠️` substitute for the walkthrough. Never treat
"continue as is" as permission to optimize against a broken grading signal.

### 5. Prepare the environment and finish free checks

Only after the standard-library-only component checks:

1. Determine the current provider route from the agent's actual model call and configuration. Treat
   discovered credential names only as an availability inventory; they do not select or change the
   route. If no route exists, default to OpenRouter because one key can exercise multiple model
   vendors. Do not create a separate provider-choice question; mention that the user may request a
   direct provider instead. If the current route is clear but its credential is absent while a
   different provider credential is present, stop with one clear mismatch: recommend adding the
   current route's key, and offer an explicit route change as the alternative. Never rewrite the
   model identifier or provider prefix merely to match an available key.
2. Reuse an existing compatible isolated environment. Otherwise, create the conventional `.venv`
   with Python 3.11-3.13 without fetching packages. Only when `.venv` already exists but is
   incompatible, preserve it and create `.venv-traigent` as a non-destructive fallback. Treat the
   fallback name as an implementation detail, not a user choice.
3. Install the exact declared dependencies under the narrow authorization above: use the project's
   compatible exact declarations, or otherwise the exact pins in
   `assets/requirements-first-run.txt`. Never use an unversioned `pip install traigent`.
4. Verify the installed SDK's capabilities and public signatures instead of relying on a
   hardcoded "current" version statement. Use its public dataset validator/loader and construct the
   wrapper through its public decorator and evaluation models so the installed SDK owns
   normalization, injection, agent-call, and evaluator-callback decisions. If the installed SDK
   exposes a public no-execution evaluation-contract validator, use it. Otherwise do not claim
   exhaustive static compatibility; finish the check with the safe mock plumbing step below. Never
   recreate SDK binding or callback fallbacks in first-run code. Normalize dataset paths to
   resolved absolute paths before passing them to SDK 0.25.0's public validator; its nested-relative
   path defect is tracked upstream. A missing SDK may block only these
   SDK and mock checks, not the component checks already recorded.
5. Run any safe deterministic calibration that was deferred solely for an installed local
   dependency. Then run a fresh-process Traigent mock plumbing check only when every model call is
   known to be intercepted. Raw provider clients, external evaluators, subprocesses, HTTP
   services, tools, and custom judges are not free merely because mock mode is enabled. Exit the
   mock process and never reuse it for a real run.
6. After every applicable free check is complete, create the minimal `.env` when none exists, or
   append only missing selected-provider and Traigent key names to the existing file. Leave new
   entries blank; never replace existing values, comments, unrelated keys, or blank alternate
   provider entries. Create a new file with a restrictive umask and mode `0600` on POSIX; correct
   any other existing mode before opening the file.
   Stop once and ask the user to enter both keys locally, never in chat. If the portal key is not
   yet available, provide only the required account/key destination and resume from this step
   afterward.

With OpenRouter, OpenRouter is the gateway and an automatically selected upstream inference
provider may also receive the prompts, examples, and outputs. Name OpenRouter and every allowed
upstream provider or route in the later approval, disclose whether fallback routing is enabled,
and pin allowed routes and disable fallbacks when the user requires an exact recipient set.

Explain truthfully:

- Prompts, examples, and outputs are not sent to Traigent by the optimization service.
- The selected direct provider receives the content the agent normally sends during model calls.
  For OpenRouter, both the OpenRouter gateway and the selected upstream inference provider may
  receive it.
- Connected runs send configuration identifiers, numeric measures, and run status to Traigent.

### 6. Ask once before paid work

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup.
Prepare one concise combined approval immediately before paid work containing:

- What will run: the smallest live provider/key check, any required LLM-judge calibration,
  current-configuration baseline, one bounded optimization, and current-versus-winner holdout.
- Tuning/holdout sizes, trial limit, and approximate total calls.
- Approximate runtime and estimated spend.
- A `$5.00` total walkthrough ceiling by default.
- Any call path whose cost is untracked; describe the ceiling as a stop target rather than a
  provider-billing guarantee in that case.
- What leaves the machine and every service or route that may receive it. For OpenRouter, name
  OpenRouter plus every allowed upstream inference provider/route and disclose fallback behavior.

If the estimated first run exceeds `$5.00` or is materially long, recommend a smaller
representative tuning slice or fewer trials while preserving meaningful difficulty and a holdout.
Ask about a larger/longer run only when the user prefers it. Proceed after one explicit approval.
Keep approval in the current process only; never persist a cost-approval flag in `.env`.

Use the installed SDK's default per-optimization cost limit unless it exceeds the remaining total
walkthrough ceiling; if it does, lower the process-only per-run limit. The SDK owns optimization
cost enforcement, timeout partial results, Traigent-backend retries, and provider-error
classification. Do not add or ask the user to configure another retry policy. Preserve an
existing agent/provider client's retry behavior; generated walkthrough code does not add provider
retries and leaves `TRAIGENT_VENDOR_MAX_RETRIES` unset. When preserved provider retries are
bounded, include their possible extra calls in the internal time/spend estimate without turning
the retry count into a user choice.

Until the SDK exposes a cumulative budget across baseline, search, evaluator/judge, and holdout,
maintain only one running total: add tracked cost after each paid phase, or deduct that phase's
conservative estimate when cost is untracked. Before the next phase, compare its estimate with the
remaining total ceiling. Stop before exceeding it and ask only if more paid work is required.
Never call the walkthrough ceiling a hard provider-billing cap.

After the approved live probe, derive internal request and optimization time bounds from observed
latency, rows, trials, calls per example, and concurrency. Do not show or ask the user to choose
those implementation values. If the measured runtime no longer fits the approved estimate,
offer either a smaller run or the additional approximate time/cost. On SDK timeout, report a
usable partial result when trials completed; request another bounded pass only when the evidence
suggests more search could help. With zero completed trials, diagnose the failure instead of
requesting more time.

### 7. Run the honest comparison

Use the same tuning slice and evaluator for both measurements:

1. **Current baseline** - the agent's actual current configuration. If no real agent exists, use
   the generated walkthrough agent's initial configuration and label it as such.
2. **Traigent optimization** - one bounded search that includes the baseline configuration.

Run both connected once when the user wants portal comparison. Do not run an offline baseline and
then pay to repeat it merely to populate the portal. A one-configuration baseline is the honest
"before."

After the baseline, check whether the dataset and evaluator can distinguish configurations. If
the baseline is perfect or nearly perfect and has no informative failures, stop before the search
and explain the likely ceiling effect. Recommend adding realistic boundary, failure, and harder
cases, then revalidate. Continue only if the user accepts that the run is a workflow
demonstration and may have no measurable room to improve.

Do not require a second enhanced pass. Recommend another iteration only after the first result
reveals a specific, worthwhile hypothesis.

### 8. Verify and report

Before saying the run succeeded, verify:

- Trials executed and no silent mock response leaked into the real run.
- Real provider cost is positive or explicitly reported as untracked.
- The baseline configuration was evaluated.
- The optimized result has a best configuration and non-degenerate measures.
- No trial silently truncated.
- Portal persistence completed or a precise degraded/failed state is reported.
- Any portal link is present before claiming the result is visible there.

Report:

- Baseline versus best configuration on the tuning set.
- Holdout result separately, when a valid holdout exists.
- Cost, trial count, failures, stop reason, and direct portal links.
- Which components were `✅` real and which were `🛠️` walkthrough substitutes.

Retain the customer's baseline and optimization experiments in the Traigent portal so the user can
open and compare them after the walkthrough. Never delete portal experiments as automatic teardown
or cleanup. Delete one only after the user explicitly requests that destructive action; otherwise,
finish by giving the user the direct link to every persisted first-run experiment.

If any substitute was used, lead the interpretation with:

> This run demonstrates that the Traigent optimization workflow works end to end. Because
> `<components>` were generated for the walkthrough, the measured improvement is not evidence of
> expected production performance.

Do not promote a configuration from a fully synthetic run. For real components, promotion still
requires the untouched holdout and explicit user approval.

Only after the result, offer optional next steps:

- Connect the production agent.
- Replace synthetic examples with reviewed real examples.
- Align the evaluation method with the product's grading policy.
- Continue into the advanced Traigent lifecycle.

## Completion criteria

The first run is complete only when:

- The starting state and provenance of all three components are recorded.
- Material quality limitations were explained with evidence and a repair/continue/pause choice.
- Any repaired component was revalidated before its status changed.
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
- Result claims match the provenance and holdout evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
