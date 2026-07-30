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
closing report can show the recorded opening score beside the closing one. Supply whichever
preflight, calibration, and config-space evidence exists; an absent input scores its pillar from
absent evidence and is never a reason to skip the score. Use
[`scripts/calibrate_evaluator.py`](scripts/calibrate_evaluator.py) for the separate,
explicit evaluator-execution gate. Only after task intent is anchored, copy
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

#### Opening readiness gate

After the read-only inventory and before any component creation or repair, use the host `python3`
interpreter as a narrow bootstrap for every bundled script that runs before stage 5 creates the
isolated environment - the standard-library-only static checks and the calibration adapter alike;
nothing is installed into the host interpreter. Every `python-version` result from those
pre-environment passes therefore describes that host bootstrap interpreter and is provisional; the
stage-5 environment is the interpreter the connected run is judged on. Score readiness from what
actually exists: run the bundled static preflight with `--defer-missing-sdk` over whatever dataset
was discovered - omitting `--dataset` entirely when no dataset exists rather than passing a path
that does not exist yet - then run `scripts/readiness.py` on that preflight JSON plus any
calibration or config-space evidence already present. Every guided run does this, the zero-anchor
walkthrough included, and this opening score is not skippable. It always reports all three
pillars; a project with no dataset, no calibration, and no config-space document still scores -
typically 0 and `NOT READY` - and that capped baseline is the honest opening the closing report is
measured against. Always show that opening score to the user before anything is created or
repaired, so the user knows the state they are starting from.

Present the overall score, band, and the plain-language reason behind each cap beside the
readiness board, and keep the internal cap condition ids out of those user-facing lines. Caps
select the branches in stage 4; they do not stop the run by themselves. When a cap fires on a
component that does exist but has not been measured yet, say so in your own words instead of
repeating the card's reason, which is phrased for the component being absent.

The score grades measured evidence, not declared existence. A real evaluator that has not been
calibrated yet, and a real agent with no config-space document yet, both score from absent
evidence: report them as not yet measured, never as "no evaluator connected" or "nothing to tune".
The config-space document's `wired` list is weaker than that, and the difference matters: nothing
here reads the agent's code, so the list is an attestation the score takes at its word and never
verifies. Declaring a knob is not a statement that the agent consumes it, so a document that
declares knobs but does not state which of them the agent consumes has attested no wiring, scores
the agent pillar as having nothing to search, and keeps its cap binding until the wired knobs are
named. Describe that state in your own words too, as the rule above requires - declared search
controls whose wiring the document never states. Never infer `wired` from `knobs`, never describe a
declared-only knob as wired or varying, and never write a `wired` list merely to clear the cap:
nothing enforces the attestation, which is exactly why writing one you cannot stand behind is a
false statement rather than a shortcut. Continue with local wiring work and a rescore; while a
document declares knobs without an attested `wired` list, do not begin paid optimization. That
restriction keys on this state, not on the cap id - `agent-no-varying-knobs` also fires for the
zero-anchor opening, which this skill proceeds through.
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

1. Present the opening readiness score and band, then the three real-world gaps:
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
with the remaining stages. Record the unchanged opening score in that run record as its first
entry, before any substitute exists.

### 2. Show readiness once

For a zero-anchor project, the intent gate already rendered the initial readiness board; do not
render it again before the user answers. For every other starting state, render the initial
real-world readiness board after inspection. Show the opening readiness score and band beside that
board. State what Traigent will create for the walkthrough.
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
3. Run the bundled static preflight with `--defer-missing-sdk` and a single `--dataset` JSONL path
   containing the combined tuning and holdout rows, so local structure and quality problems are
   checked without importing user modules. Omit optional model-pricing checks in this
   standard-library-only pass. It checks canonical `input`/`output` fields by default. For another
   schema, pass explicit `--input-field` and `--expected-field` dot paths selected from the user's
   data and task; do not infer SDK aliases. This heuristic check does not assert SDK compatibility.
4. Run deterministic evaluator calibration only when the semantic-coverage verdict is
   `sufficient` and the complete inspected import and call path
   is local-only, has no external side effects, and needs no unavailable third-party package.
   Execute it in the isolated subprocess with provider credentials removed.
5. Re-run `scripts/readiness.py` on the fresh preflight JSON plus the calibration results and
   config-space document, whichever exist by this point. This is a required step of local
   validation, not an optional aid, and it runs even when a low score or a cap is expected. Record
   the overall score, band, and every binding cap in `traigent-runs/run-plan.md` beside the
   recorded opening score. If calibration was deferred for an installed local dependency, record
   the preflight-only result now and re-run the score right after that deferred calibration.

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

Route every active dataset cap to the branch this flow already defines, and present the reason
rather than the condition id:

- `dataset-absent` - treat Dataset as missing and enter the creation dependency matrix in
  `references/component-creation.md`.
- `dataset-no-expected-outputs` - the rows are `limited` and stay `❗`; recommend repairing a
  labelled working copy. Adding or changing expected outputs is judgment-dependent and needs the
  explicit approval the action table already requires. Do not optimize against the unchanged
  input-only data.
- `dataset-integrity-fail` - treat the dataset as invalid: repair and revalidate a working copy,
  or use a clearly labeled `🛠️` substitute; do not optimize against the unrepaired file.
- `dataset-tune-holdout-overlap` - repair a disjoint split in the working copy and revalidate;
  until then make no holdout or generalization claim.
- `dataset-fully-synthetic` - continue only under the walkthrough labeling rules: keep the real
  Dataset gap `❗`, mark the substitute `🛠️`, and never read the score gain as production
  readiness.
- `dataset-mostly-synthetic` - the same walkthrough labeling rules apply to the generated majority.
  Name the split out loud ("62 of 100 rows are generated"), and when reporting the result, say which
  side of the mixture the claim rests on. Adding real examples is the cheapest way to clear it.
- `dataset-generated-answer-key` - the questions are real but every expected answer was written by a
  model, so the score measures agreement with that model rather than correctness. Recommend that a
  person reviews a sample of the answers before any accuracy claim leaves the run, and make no
  correctness claim on the unreviewed key.

Evaluator and agent caps route through the rules that already own them: the invalid-evaluator
paragraph above, and the absent-evidence reading in the opening readiness gate. After any repair
or substitute creation, re-run the affected checks, the applicable calibration, and the score,
then update the latest recorded result without overwriting the opening one.

### 5. Prepare the environment and finish free checks

Only after the standard-library-only component checks:

1. Determine the current provider route from the agent's actual model call and configuration. Treat
   discovered credential names only as an availability inventory; they never select or change an
   existing route. If no route exists and exactly one supported direct provider credential is
   already present, select that provider so the walkthrough needs no second account or key. If no
   route exists and no single direct credential is present, default to OpenRouter because one key
   can exercise multiple model vendors. Do not create a separate provider-choice question; mention
   that the user may request a direct provider instead. If the current route is clear but its credential is absent while a
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
   Stop once and ask the user to enter the keys they already hold locally, never in chat. Do not
   send a user who has no Traigent account through registration at this step: the provider key is
   all the baseline needs, and the account ask belongs after that first result (stage 7). If the
   portal key is not yet available, provide only the required account/key destination and resume
   from this step afterward. If the user has already completed portal registration and created
   their key in the portal, skip the create-account and generate-key ask and have
   them paste that key. If they have not registered yet, route them by
   which of the four account states they are in per `references/run-safety.md` - do not assume the
   emailed access code was ever used. The key authenticates the run; the account's portal access
   period is what authorizes it, so do not treat a valid key as proof the run will be accepted.

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

Scope the run before pricing it. When the dataset carries more than about 100 usable rows, select the
bounded first-run subset described in `references/evaluation-and-dataset.md` - 18 rows by default, at
least four from each difficulty band, drawn within each split rather than across it - and estimate
runtime and spend from that subset, not from the full row count.

The window matters in both directions. It comes *after* the stage-4 re-score, because the score is a
statement about the user's dataset and a score taken on our sample would report this run's precision
limit as though it were a property of their data. It comes *before* the approval below, because an
estimate priced on 4,812 rows and then run on 18 asks the user to approve a run that never happens -
and a decision made on a number that large may simply be no.

Record the chosen row ids, report the subset size beside the full row count, and give the run's own
resolution as its own sentence rather than letting it colour the dataset's score. A first run shows
the capability; it does not exhaust the dataset.

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup.
Prepare one concise combined approval immediately before paid work containing:

- What will run: the smallest live provider/key check, any required LLM-judge calibration,
  the preserved baseline or a generated six-row sweep, one broader bounded optimization, and
  baseline winner versus enhanced winner holdout comparison.
- Tuning/holdout sizes, trial limit, and approximate total calls.
- The walkthrough model ladder in play: the three tiers both runs share, and that the vendor's
  newest flagship is deliberately not among the selected models, with the one-line reason below.
- Approximate runtime and estimated spend.
- A `$5.00` total walkthrough ceiling by default.
- Any call path whose cost is untracked; describe the ceiling as a stop target rather than a
  provider-billing guarantee in that case.
- What leaves the machine and every service or route that may receive it. For OpenRouter, name
  OpenRouter plus every allowed upstream inference provider/route and disclose fallback behavior.

Give time a stated ceiling as well as money, and put both in the same approval. The walkthrough
promises one sitting, so budget the whole paid phase at about **30 minutes** - roughly 10 for the
baseline and 20 for the enhanced run - and say the numbers out loud rather than only the cost. A user
who knows the run is bounded at half an hour reads a pause differently from one watching an
open-ended process.

Treat that ceiling exactly as the cost ceiling is treated: a stop target, not a hard cap the
provider enforces. When a phase is going to exceed it, stop at the boundary rather than after it,
keep every completed trial, and report what was actually covered - "the enhanced run completed 7 of
13 trials inside the 20-minute budget; the winner below is chosen from those 7, and the four
configurations not reached are listed". A partial comparison that says which configurations it
never tried is honest; the same comparison presented as complete is not. Never silently drop the
holdout check to fit the budget - a smaller comparison with a holdout beats a larger one without.

If the estimated first run exceeds `$5.00` or about 30 minutes, first recommend a smaller
representative tuning slice while preserving meaningful difficulty and a holdout. Reduce the
generated six-row baseline or the 10-13-trial enhanced target only when the approved ceiling,
runtime, or plan quota still binds, and disclose that reduced comparison in the approval. Ask
about a larger/longer run only when the user prefers it. Proceed after one explicit approval. Keep
approval in the current process only; never persist a cost-approval flag in `.env`.

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

After approval and before the first connected paid trial, run a zero-LLM portal-tracking probe with
a trivial stub agent that makes no provider call: confirm the whole connected path in one pass - the
portal key is present and authenticated, is scoped for `experiment.write`, a session is created, the
first trial is accepted, and a `cloud_url` comes back. The baseline is not gated on this probe. It
runs on the user's own provider credential with no portal key at all, so a user who has not
registered yet still reaches a first real result without front-loading the account funnel; run the
probe once that key is in hand, before the first trial meant to reach the portal. Paid is not the
trigger - reaching the portal is. A baseline spends real provider money and has no tracking to lose;
a connected trial does. A present-but-unscoped key (HTTP 403 without
`experiment.write`) and a rejected config (HTTP 400) both otherwise degrade silently to local-only
tracking while paid trials keep running and never reach the portal. If any rung fails, surface the
backend reason verbatim and stop before any paid trial. Treat any degradation to local-only tracking
that appears later in the connected run the same way: halt further paid work at once and report it in
the result, never discovered afterward. The connected-run readiness detail is in
`references/run-safety.md`.

After the approved live probe, derive internal request and optimization time bounds from observed
latency, rows, trials, calls per example, and concurrency. Do not show or ask the user to choose
those implementation values. If the measured runtime no longer fits the approved estimate,
offer either a smaller run or the additional approximate time/cost. On SDK timeout, report a
usable partial result when trials completed; request another bounded pass only when the evidence
suggests more search could help. With zero completed trials, diagnose the failure instead of
requesting more time.

### 7. Run the honest comparison

Use the same tuning slice, evaluator, objectives, and agent call path for both measurements:

1. **Baseline** - preserve the user's existing baseline or fixed configuration exactly as defined,
   including its original row count. Do not add variants to make it look fuller. Only when the
   configuration is missing and Traigent creates it, generate a credible quick manual-style sweep
   of six distinct configurations: by default, three credible models by two safe temperature
   values, with enhanced-only controls pinned to their ordinary/off values. The three models are
   the fast, mid, and strong rungs of the walkthrough model ladder below, never the vendor's
   newest flagship.
2. **Enhanced Traigent optimization** - a materially larger space that contains every baseline
   value and adds meaningful controls that the agent actually consumes. Target 10-13 visible
   trials, using 12 as the internal default cap. For the generated walkthrough, keep the model
   list identical to the baseline's, add prompt-policy
   choices and a native boolean self-check control without adding another model call, and refine
   swept values around the baseline's top rows - the added value hugs a winner rather than a far
   point - while keeping every baseline value, so an
   enhanced win is attributable to the added knobs and the managed search, never to a
   quietly upgraded model. For a real
   agent, prefer task-specific controls tied to observed failure modes, such as retrieval depth,
   context format, few-shot count, tool policy, or repair behavior.

Both runs share the models Traigent selects: a deliberate ladder inside the selected route of one
fast low-cost tier, one mid-tier workhorse, and one strong tier one step below the vendor's newest
flagship, the strong tier at a pinned reasoning effort in both runs when it is a reasoning model -
temperature is then dropped as a swept knob for the whole walkthrough and two prompt styles form
the baseline's second axis instead, per the sdk-execution reference.
Never auto-select the flagship itself, and say why in one line when presenting the plan:
a first run is for seeing the workflow and the cost-accuracy tradeoff quickly, so it stays faster
and cheaper by searching down the ladder, and the flagship remains the ready next rung for a later
run if the task proves hard enough to need it. When the user's own agent already calls the
flagship, that choice is preserved exactly - it is the baseline being measured - and the ladder
adds the tiers below it; never remove or swap the user's model, and give the same one-line
explanation before the approval so the cheaper added tiers read as deliberate, not as a downgrade.

Frame the enhanced run the same honest way in the plan and in the report: a deliberately small
enhancement for a first look - a few added knobs plus swept values refined from the baseline's own
top rows - and say in one line that this is a small slice of what Traigent can drive, not its full
capability. The deeper layers - richer task-specific spaces and the recommendation and insight
system - come after this run, so the small scope reads as a deliberate first taste rather than the
product's limit.

The baseline needs only the user's own provider credential. It runs locally as an explicit grid, so
it produces a first real result before any Traigent account exists - deliberately the shortest path
from "nothing set up" to "a number I can see". Say plainly that this first measurement is the
local half of the SDK: a fixed grid over a small space, not Traigent choosing what to test. It is
free of Traigent, not free of spend - the provider calls are real money and stay inside the same
combined approval and the same running total as everything else.

Only after that first result is on screen, ask for the Traigent key. The order is the point: the
user has already seen the tool work before being asked to create an account. Tell them the key needs
full access rather than the read-only default, because a read-only key still spends on the run and
then records nothing. Once it is in place, upload the baseline that already ran instead of paying to
repeat it, then run the enhanced search connected so the portal holds both. Report each run with its
own link, name which is which, and never present one link as though it covered both. If the user has
already completed portal registration and still has the key created there, skip the create-account and
generate-key ask - have them paste that key into `.env`, never into chat, and upload the baseline as
above. Registering is not the same as holding a key: the key is created on the API-key page and is
shown once, so a user who registered but did not save it creates a fresh full-access one - from the
portal's top-bar key control, or `https://portal.traigent.ai/management/api-keys` - rather than
hunting for the original. Ask which
state they are in rather than assuming, because getting the
second email and registering are separate acts and many people stop after reading the email. For a
user who is not registered but holds an access code still inside its 10 days, walk the remaining
path in order rather than
naming one destination: open the second Traigent email for the access code, register at
`https://portal.traigent.ai/register` (a clickable link) with that code, then create a full-access
key from the portal's top-bar key control - highlighted on a first visit - and save it as it is
shown; only then come back and paste it. If they have not started
at all, they begin at the Traigent site, and the registration page will refuse them until a code
exists. `references/run-safety.md` holds the four states in full.

Do not run an offline baseline and then pay to repeat it merely to populate the portal. Do not ask
the user to choose trial counts or knobs; select them from the inspected agent and include their
calls in the combined approval.
Every knob must change real behavior, native booleans must stay booleans, and the enhanced space
must be materially larger than its trial cap so Traigent is choosing what to test rather than
replaying the same tiny grid.

Once the enhanced space is final - after the placeholder swept values are refined around the
baseline's winner and before the connected search runs - serialize it in the shape documented in
`references/run-safety.md`, from the space object the search actually receives rather than from a
transcription, and list under `wired` only the controls the agent call really consumes. Delete any
earlier copy before that search starts and save `traigent-runs/config-space.json` only once the
search has returned trials, so the document can never outlive or misdescribe the search it claims -
a search that raises or completes nothing leaves no file. Re-write it whenever the space changes.

If provider, Traigent backend, or portal connectivity is unavailable, stop with the concrete
failure and one recommended recovery. Never fall back automatically to mock or synthetic results,
and never present offline checks as a completed optimization. Resume the connected path after the
failure is resolved.

Do not fabricate configurations to hit a row count. A preserved one-row user baseline is an honest
one-row before and stays unchanged. A Traigent-generated walkthrough must not proceed with a one-
row baseline; generate enough real controls for the six-configuration default.

After the baseline, check whether the dataset and evaluator can distinguish configurations. If
the baseline is perfect or nearly perfect and has no informative failures, stop before the search
and explain the likely ceiling effect. Recommend adding realistic boundary, failure, and harder
cases, then revalidate. Continue only if the user accepts that the run is a workflow
demonstration and may have no measurable room to improve.

One exception pivots that decision: when the objectives include cost, saturated accuracy caps
only the accuracy axis, not the run. An equal-accuracy configuration at materially lower cost is
a legitimate, reportable win - the accuracy-versus-cost Pareto choice - so if cost has headroom,
run the search rather than stopping before it, and report the cheapest configuration that holds
the accuracy, plainly stating that the models are capable and the gain is on cost, not accuracy.
Treat the saturation itself as a prompt to question the measurement in parallel - whether the
dataset is too easy, too small, or too narrow, or the evaluator too lenient - and recommend
hardening or widening whichever is weak; the cost win and this rethink are complementary, not
alternatives. When the dataset is `🛠️` generated, add that synthetic data can be easier than
production data, so real, harder cases are still needed to reveal any accuracy headroom.

Do not require a third optimization pass. Recommend another iteration only after the first result
reveals a specific, worthwhile hypothesis.

### 8. Verify and report

Before saying the run succeeded, verify:

- Trials executed and no silent mock response leaked into the real run.
- Real provider cost is positive or explicitly reported as untracked.
- The user's existing baseline was preserved exactly, or the Traigent-generated baseline produced
  six distinct rows including its initial configuration. If the approved plan explicitly reduced
  that default, the executed count matches the disclosed reduction and still includes the initial
  configuration.
- The enhanced run added real controls and produced 10-13 trials by default, matched an explicitly
  approved and disclosed reduced target, or has a concrete SDK stop reason or failure explanation.
- The optimized result has a best configuration and non-degenerate measures.
- No trial silently truncated.
- Portal persistence completed or a precise degraded/failed state is reported.
- The pre-paid portal-tracking probe passed, and connected tracking never silently fell back to
  local-only during the run; any such degradation halted further paid work rather than surfacing
  only at the end.
- Any portal link is present before claiming the result is visible there.

Report:

- Best small-sweep configuration versus best enhanced configuration on the tuning set.
- Holdout result separately, when a valid holdout exists.
- Cost, trial count, failures, stop reason, and direct portal links.
- Which components were `✅` real and which were `🛠️` walkthrough substitutes.
- The readiness transition: the recorded opening score and band, the closing score and band, and
  which caps cleared and which remain.
- When the enhanced run does not beat the baseline, name the likely cause and show it beside the
  number - an uninformative search space, a dataset ceiling, an over-strict evaluator, controls the
  search never varied, generated data with no headroom, or a base model not capable enough for a
  genuinely hard task where a stronger model or higher reasoning effort is the lever (rule-out order
  and full list in `references/run-safety.md`) - never a bare flat delta. Only after ruling those out
  is a low number the honest difficulty ceiling, reported plainly, not a broken agent. And when the
  reference itself is misleading (ambiguous, wrong, or degenerate), say the question is misleading -
  do not blame the model or reasoning-effort level for failing to match it. A flat result on
  demonstration data shows the workflow ran honestly, not that the production workload cannot improve.

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

Close the loop on the readiness score the run opened with: re-run `scripts/readiness.py` on the
post-repair, post-creation evidence and show the recorded opening score beside the closing one,
naming the caps that cleared and the caps that remain. Pass
`--config-space traigent-runs/config-space.json` to that closing run whenever the enhanced space
was emitted; without it the agent pillar scores from absent evidence and the transition understates
the run's own work. Any gain earned by a `🛠️` substitute is
walkthrough setup and is never presented as real-world readiness. Restate what was weak, what
Traigent filled in, and what that costs in the real world - a dataset of a dozen generated
examples measures the workflow, not the product, however good the number looks. The opening score
and the closing recap are the same conversation: the user should leave knowing which gap to close
first and why it matters, not just what the run produced.

Two local, free reads make that concrete rather than generic, and both come from the completed runs
without another call. The per-example audit names specific examples that no configuration ever got
right, and the optimization insights name which control actually moved the result. Report those by
example and by knob; see `references/sdk-execution.md` for what the installed SDK exposes. Say
plainly that this is what the SDK alone can see.

Then, and only as what comes next rather than what was withheld, name what Traigent adds on top of a
connected run: it scores every example from the run to show which are informative, which are
redundant, and which look mislabelled, and it audits the evaluator itself. Describe those as signals
and curation advice, not as numbers - do not promise a numeric dataset-quality score, and never
imply the platform can grade a dataset that has not been run. Say plainly that this layer is
run-scoped and shows its full power only once the enhanced run has finished - and that what it can
honestly recommend grows with the readiness score: over real components it advises about the
product, over walkthrough substitutes it can only describe the walkthrough. That ties the small
first run to the next one: readier components and a finished enhanced run are what unlock stronger
recommendations.

Artifact-2 template B (DEEPER-INSIGHTS) is the post-optimization-run form of that layer, never a
pre-run one: once the enhanced run has finished, surface the run-scoped analysis per question - name
the examples that were informative, the ones that were redundant, and the ones that look mislabelled,
and pair each with one line of curation advice (keep, drop, relabel, or add a harder sibling).
Describe those as signals and curation advice, not as numbers - do not promise a numeric
dataset-quality score, and never imply the platform can grade a dataset that has not been run. Carry
no numeric pre-run dataset-quality score into this message; it reads the finished run, not an unrun
dataset.

Close by saying what a further run would be worth, grounded in the two facts already on the table:
the gaps the opening readiness score named, and which of them this run actually closed. Name the
ones still open and what each is now costing - an unlabelled half of the dataset, a single-band
difficulty spread, a substitute component still standing in for a real one - so the motivation is
the user's own measured evidence rather than encouragement. Where a gap is one this walkthrough
cannot close, say that plainly instead of implying a further run would fix it.

Then give the one next action their *starting* state earns, not generic advice. The opening score
already measured which gap is largest, so name the specific move and what it would buy:

- Generated or mostly generated data - collect or export a real sample of the same task and re-run.
  This is the gap that ceilings the score no matter how good everything else is, so it is first
  whenever it applies.
- Real inputs with model-written answers - have a person review a sample of the answer key. Until
  then the accuracy number measures agreement with a model, not correctness.
- Rows without expected outputs, or placeholder answers - label a slice rather than the whole set;
  the power bands mean the first few dozen scoreable rows buy most of the resolution.
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
- Result claims match the provenance and holdout evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
