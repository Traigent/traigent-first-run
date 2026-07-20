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
explicit evaluator-execution gate. Copy [`assets/run-plan.md`](assets/run-plan.md) into
`traigent-runs/run-plan.md` and fill it from discovered evidence; do not ask the user to complete
it.

## Operating contract

- Treat this as the user's **first Traigent run**, not as evidence about their expertise.
- Never classify or announce the user's expertise level.
- Speak for a capable system: "Traigent will generate..." and "I will validate...", not
  "Traigent can use a sample..."
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- Put generated artifacts under `traigent-runs/`; add that directory to the project
  `.gitignore`. Never overwrite source material.
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
| Create `traigent-runs/` artifacts and add that path to `.gitignore` | Proceed after inspection; preserve source material and provenance. |
| Create an isolated environment and minimal `.env` | Proceed without fetching or installing packages; leave secrets blank and ask the user to enter them locally. |
| Install dependencies in the isolated environment | Proceed only for the exact packages and versions declared for the run, as a package-artifact fetch/install with no provider or Traigent calls, private-data transfer, or user/project code execution. A user or environment policy that requires install approval still takes precedence. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate from the failed gate. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves the evaluator path is local-only or every mock model call is intercepted, with no external side effects. |
| Make provider, private-data, connected Traigent, or external calls other than the narrow dependency fetch above | Obtain the unchanged combined approval for recipients, data, calls, runtime, and worst-case spend. |
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

Only ask which agent to use if multiple credible candidates remain. If nothing anchors the task,
ask one concise question: **"What should the walkthrough agent do?"** Offer at most three
short choices and recommend a structured, deterministically scoreable task.

### 2. Show readiness once

Render the initial real-world readiness board after inspection. State what Traigent will create
for the walkthrough. Do not show external links. Do not ask the user to solve missing setup
pieces. Refresh only changed evidence after creation; retain unresolved `❗` lines and add the
new `🛠️` substitutes instead of replacing the initial board with a green one.

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
- If nothing exists, create one coherent trio after the single task-intent question.
- Validate compatibility in both directions: dataset inputs bind to the agent, and agent outputs
  are meaningfully scoreable by the evaluator.

Create a minimal reversible integration under `traigent-runs/` or a thin wrapper around the
existing function. Do not refactor production code just to demonstrate the workflow.

When nothing exists, use this internal order: define the task and output contract, define what
the evaluator accepts, build the agent to that contract, build varied examples against both, then
cross-validate and calibrate the finished trio.

### 4. Prepare the environment

Use Python 3.11-3.13 in an isolated virtual environment. Verify the installed SDK's capabilities
instead of relying on a hardcoded "current" version statement.

Create a minimal `.env` containing only the selected provider's blank key entry and safe run
settings. Reuse a provider already used by the project. If none exists, recommend OpenRouter
because one key can exercise multiple model vendors, offer at most two direct-provider
alternatives, and ask which services may receive the walkthrough content. With OpenRouter,
OpenRouter is the gateway and an automatically selected upstream inference provider may also
receive the prompts, examples, and outputs. Name OpenRouter and every allowed upstream provider
or route in the approval, disclose whether fallback routing is enabled, and pin allowed routes
and disable fallbacks when the user requires an exact recipient set. Ask the user to paste the key
into that file, never into chat. Add the Traigent portal key only when the connected run is about
to start.

Explain truthfully:

- Prompts, examples, and outputs are not sent to Traigent by the optimization service.
- The selected direct provider receives the content the agent normally sends during model calls.
  For OpenRouter, both the OpenRouter gateway and the selected upstream inference provider may
  receive it.
- Connected runs send configuration identifiers, numeric measures, and run status to Traigent.

### 5. Validate before spending

Run the bundled static preflight first. It must not import user modules, execute the agent,
execute the evaluator, contact providers, or consume credits.

Then:

- Validate the generated dataset and evaluator using
  `references/evaluation-and-dataset.md`.
- Choose and record `graded` or `binary` calibration from the real task semantics for every
  materially distinct case. Do not choose a mode merely because it lets the current scorer pass.
- Run deterministic evaluator calibration locally when applicable.
- Treat calibration as free only after inspection establishes a local-only call path with no
  external side effects. If the call path is uncertain or external, route it through the
  egress/paid approval.
- Treat LLM-judge calibration as a paid/provider action. Explain its small call count and ask for
  approval before executing it.
- Run a fresh-process Traigent mock plumbing check only when every model call is known to be
  intercepted. Raw provider clients and external services are not free merely because mock mode
  is enabled.
- Exit the mock process. Never reuse it for a real run.

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

### 6. Ask once before paid work

Prepare one combined approval containing:

- What will run: current-configuration baseline, then one bounded optimization.
- Tuning and holdout sizes.
- Agent calls and any evaluator/judge calls per example.
- Holdout calls for the current and selected configurations.
- Estimated runtime and combined worst-case spend.
- Positive provider-request, baseline, optimization, and holdout timeouts; the explicit provider
  retry count; and an estimated runtime that includes retry and composite-call multipliers.
- What leaves the machine and every service or route that may receive it. For OpenRouter, name
  OpenRouter plus every allowed upstream inference provider/route and disclose fallback behavior.
- An aggregate walkthrough budget and stop condition covering the baseline, search,
  evaluator/judge calls, retries/composites, and both current-versus-winner holdout paths.

Proceed only after explicit approval. Keep approval in the current process environment; never
persist a cost-approval flag in `.env`. Record a remaining-budget ledger with separate rows for
the live provider/key check, judge calls, baseline, search, retries/composites, current holdout,
and winner holdout. Each row records its allocation, phase worst case, charged deduction, and
remaining aggregate cap. Before every paid phase or call batch, check its combined worst-case cost
against the remaining aggregate budget; stop and obtain revised approval when it does not fit.
The SDK `TRAIGENT_RUN_COST_LIMIT` applies to one optimization call and does not enforce the
aggregate walkthrough cap.

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
- A human reviewed the probe families for semantic coverage of every material input, outcome, and
  rubric/schema branch, with gaps recorded before execution.
- Free checks made no provider calls.
- Paid work had explicit combined approval.
- Baseline and optimization used the same tuning data and evaluator.
- Result claims match the provenance and holdout evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
