---
name: traigent-first-run
description: Guide a professional first Traigent optimization from any starting point, including projects missing an agent, evaluation dataset, or evaluation method. Use when a user asks to try Traigent, run a first optimization, optimize an agent for the first time, set up Traigent, or opens the Traigent/traigent-first-run repository. Inspect what already exists, preserve real components, create only the missing pieces as one coherent system, distinguish demonstration substitutes from production readiness, validate before spending, run an honest current-configuration baseline plus one bounded optimization, and report what the result does and does not prove.
---

# Traigent Guided First Run

Help the user see a credible optimization quickly without overstating synthetic evidence.
Do the technical work. Ask only for information or approval that changes the result, cost,
data egress, or project behavior.

## Load the bundled guidance

Read these files before acting:

1. [`references/component-creation.md`](references/component-creation.md) - inventory all three
   components and complete any missing combination coherently.
2. [`references/evaluation-and-dataset.md`](references/evaluation-and-dataset.md) - choose and
   calibrate a sensible evaluator; create a varied, non-duplicative dataset.
3. [`references/run-safety.md`](references/run-safety.md) - environment, privacy, dry-run, cost,
   execution, portal, recovery, and result-claim gates.
4. [`references/sdk-execution.md`](references/sdk-execution.md) - inspect the installed SDK and
   run the current baseline, bounded optimization, and holdout check with public APIs.

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
- Never expose secrets in chat, commands, logs, diffs, or metadata.

## Status language

Track two different facts:

1. **Real-world readiness** - whether the project contains a real, validated component.
2. **Walkthrough setup** - whether Traigent prepared a temporary substitute to demonstrate the
   workflow.

Use exactly these meanings:

- `✅` - real component found and validated.
- `❗` - real component is missing or failed validation.
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
- Record concrete evidence for Agent, Dataset, and Evaluation. Do not guess.

Only ask which agent to use if multiple credible candidates remain. If nothing anchors the task,
ask one concise question: **"What should the walkthrough agent do?"** Offer at most three
short choices and recommend a structured, deterministically scoreable task.

### 2. Show readiness once

Render the initial real-world readiness board after inspection. State what Traigent will create
for the walkthrough. Do not show external links. Do not ask the user to solve missing setup
pieces. Refresh only changed evidence after creation; retain unresolved `❗` lines and add the
new `🛠️` substitutes instead of replacing the initial board with a green one.

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
alternatives, and ask which service may receive the walkthrough content. Ask the user to paste the
key into that file, never into chat. Add the Traigent portal key only when the connected run is
about to start.

Explain truthfully:

- Prompts, examples, and outputs are not sent to Traigent by the optimization service.
- The chosen LLM provider receives the content the agent normally sends during model calls.
- Connected runs send configuration identifiers, numeric measures, and run status to Traigent.

### 5. Validate before spending

Run the bundled static preflight first. It must not import user modules, execute the agent,
execute the evaluator, contact providers, or consume credits.

Then:

- Validate the generated dataset and evaluator using
  `references/evaluation-and-dataset.md`.
- Run deterministic evaluator calibration locally when applicable.
- Treat LLM-judge calibration as a paid/provider action. Explain its small call count and ask for
  approval before executing it.
- Run a fresh-process Traigent mock plumbing check only when every model call is known to be
  intercepted. Raw provider clients and external services are not free merely because mock mode
  is enabled.
- Exit the mock process. Never reuse it for a real run.

If validation fails, repair the relevant component and reopen its `❗` state. Do not continue to
paid optimization with a degenerate evaluator, incompatible dataset, or unverified call path.

### 6. Ask once before paid work

Prepare one combined approval containing:

- What will run: current-configuration baseline, then one bounded optimization.
- Tuning and holdout sizes.
- Agent calls and any evaluator/judge calls per example.
- Holdout calls for the current and selected configurations.
- Estimated runtime and combined worst-case spend.
- What leaves the machine and which service receives it.
- The total first-run cap and stop condition.

Proceed only after explicit approval. Keep approval in the current process environment; never
persist a cost-approval flag in `.env`.

### 7. Run the honest comparison

Use the same tuning slice and evaluator for both measurements:

1. **Current baseline** - the agent's actual current configuration. If no real agent exists, use
   the generated walkthrough agent's initial configuration and label it as such.
2. **Traigent optimization** - one bounded search that includes the baseline configuration.

Run both connected once when the user wants portal comparison. Do not run an offline baseline and
then pay to repeat it merely to populate the portal. A one-configuration baseline is the honest
"before."

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
- All missing components were built around the existing ones.
- Dataset, agent, and evaluator compatibility passed.
- The evaluator discriminates good, equivalent, partial, and bad outputs.
- Free checks made no provider calls.
- Paid work had explicit combined approval.
- Baseline and optimization used the same tuning data and evaluator.
- Result claims match the provenance and holdout evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
