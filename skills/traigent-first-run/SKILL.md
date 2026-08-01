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
- Name the actor truthfully: "I will prepare the walkthrough dataset" for assistant-created
  artifacts, and "Traigent will run the managed search" only for work the service performs.
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- After task intent is anchored, put generated artifacts under `traigent-runs/` and add that
  directory to the project `.gitignore`. Never overwrite source material.
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
| Create `traigent-runs/` artifacts and add that path to `.gitignore` | Proceed only after inspection and once task intent is anchored; preserve source material and provenance. |
| Create an isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run; do not fetch or install packages as part of environment creation. |
| Install dependencies in the isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run, and for the exact packages and versions declared for the run, as a package-artifact fetch/install with no provider or Traigent calls, private-data transfer, or user/project code execution. Name the environment's absolute path either way. Into an environment this run created, or one holding nothing but this walkthrough's own pinned set, proceed; into one with other dependents, obtain one confirmation first, because that resolution can move a package the user's other work depends on. A user or environment policy that requires install approval still takes precedence. |
| Create or update a minimal `.env` | Proceed only after every applicable free component, capability, and safe mock check has run. Preserve existing values, comments, unrelated keys, and any Traigent key already present. Before the local baseline, append only the missing selected-provider key name with a blank value. Before opening it, require mode `0600` on POSIX, then stop once for that local secret. Add or request the Traigent key only after the baseline checkpoint in stage 7. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate from the failed gate. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves the evaluator path is local-only or every mock model call is intercepted, with no external side effects. |
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
calibration or config-space evidence already present. Pass the same resolved
`--evaluator-method` to both scripts. Every guided run does this, the zero-anchor
walkthrough included, and this opening score is not skippable. It always reports all three
pillars; a project with no dataset, no calibration, and no config-space document still scores -
typically 0 and `NOT READY` - and that capped baseline is the honest opening the closing report is
measured against. Always show that opening score to the user before anything is created or
repaired, so the user knows the state they are starting from.

Show the card the script rendered, in a code block, rather than retyping its numbers into prose or
a table of your own. `render_card` already draws a bar per pillar, already falls back from `█░` to
`#-` when the host cannot encode them, and already decides about colour from the stream and the
environment - so a re-typed table silently discards work the tool did for the reader, and turns a
proportion they can see at a glance back into a number they have to compare. Reformatting also
drops what the card is careful to say: the measured-check count beside a thin pillar, and whether
a ceiling reads `LIMITED TO` or `WOULD LIMIT TO`. Add your narrative around the card - never in
place of it.

The card, specifically - not the durable markdown report, which lists each cap by its internal
condition id and would put exactly the strings the next paragraph keeps out of user-facing lines
back into the conversation. The report is written to disk for the run record; the card is the one
built to be read.

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
   assistant-performed semantic-coverage review described in
   `references/evaluation-and-dataset.md`. Ground it in the strongest available product evidence:
   contracts and documentation, tests and fixtures, labels and examples, accepted outputs,
   rubrics, and failure reports. Record the semantic-coverage reviewer and evidence, materially
   distinct inputs, outcome classes, and rubric/schema branches, the mode and threshold rationale,
   known gaps, and a `sufficient` or `ambiguous` verdict. Review against the outcome-class table in
   `references/run-safety.md` rather than against a sense of having looked, and name the classes
   each case covers in its `outcome_classes`, so the record says what was examined instead of that
   someone examined it.

   When `calibrate_evaluator.py` returns a `permutation_question`, put it to the user before any
   paid run. It reports that the evaluator scores a rearrangement of an expected answer as well as
   the answer itself - which is correct for a task whose order genuinely does not matter, and a
   broken ruler for one where a swapped label/value binding is simply wrong. The six mechanical
   checks cannot decide that and stay green either way; the user can decide it in one line. Do not
   treat it as a failure, and do not skip it because the calibration passed - passing is the case
   it exists for.
2. If unresolved product-grading ambiguity would materially change which output is correct or how
   candidate configurations rank, ask exactly one product-grading question, explain the competing
   interpretations and affected decision, then stop and wait. Otherwise record that no material
   ambiguity remains and proceed without a generic review pause. A clarification does not
   authorize changing real labels, expected answers, examples, or rubric policy; show any exact
   judgment-dependent change and obtain the explicit approval required by the action table.

   A *diagnosed degenerate reference is not ambiguity* and does not qualify for that question.
   Report it, continue on the reliably-scoreable rows, and record the excluded row ids for the
   closing report. Do not offer scoring the full set as an equal option. Stop and ask only when
   the remainder is too small to be a measurement or the degenerate rows are a majority; repairing
   a gold keeps the action table's explicit approval either way. The reasoning, and what each of
   those bounds is protecting, are in `references/evaluation-and-dataset.md`.
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

These branches are the policy, and `readiness.py` now emits the same decision in machine-readable
form so a consumer does not have to re-derive it: every cap carries an `action_kind` from a closed
vocabulary, and the payload carries one `recommended_action` for the run - `proceed` unless a
blocking cap fires, otherwise the remedy of the lowest-ceiling blocking cap. Keep presenting the
reason in the user's language; the vocabulary is for the machines reading the JSON, and belongs in
user-facing lines no more than the condition ids do.

Route every active dataset cap to the branch this flow already defines, and present the reason
rather than the condition id:

- `dataset-absent` - treat Dataset as missing and enter the creation dependency matrix in
  `references/component-creation.md`.
- `dataset-no-expected-outputs` - the rows are `limited` and stay `❗`; recommend repairing a
  labelled working copy. Adding or changing expected outputs is judgment-dependent and needs the
  explicit approval the action table already requires. Do not optimize against the unchanged
  input-only data with a reference-requiring evaluator. A genuinely reference-free rubric or
  pointwise/pairwise judge does not fire this cap; disclose the absent independent answer key
  without claiming there is nothing to score.
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
- `dataset-below-measurable-size` - there are too few comparable examples for a stable comparison.
  The walkthrough can still demonstrate verified phases, but treat any ranking as exploratory.
- `dataset-coarse-resolution` - the comparison set is small. Do not invent a detectable-effect
  threshold from row count alone; after the paired outputs exist, report paired outcome counts and
  justified uncertainty, or call a small/flat difference directional or inconclusive.

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
   that the user may request a direct provider instead. If the current route is clear but its
   credential is absent while a
   different provider credential is present, stop with one clear mismatch: recommend adding the
   current route's key, and offer an explicit route change as the alternative. Never rewrite the
   model identifier or provider prefix merely to match an available key.
2. Reuse an existing compatible isolated environment. Otherwise, create the conventional `.venv`
   with Python 3.11-3.13 without fetching packages. Only when `.venv` already exists but is
   incompatible, preserve it and create `.venv-traigent` as a non-destructive fallback. Treat the
   fallback name as an implementation detail, not a user choice.

   Resolve which environment before touching one, and say which by its **absolute path**. Prefer a
   compatible environment at the project root; ignore environments belonging to another project or
   tool, even when they are the only ones on the machine. Then:

   - **Creating one** - name the full path and proceed. Nothing of the user's is being changed, and
     an approval for a directory this run is about to make is a stop that buys the reader nothing.
   - **Adopting an environment that has other dependents** - name the full path, name what will be
     installed into it, and get one confirmation first. This is the one step here that modifies
     something the user built: a version resolution inside their environment can move a package
     their other work depends on, and that is not reversible by deleting a directory we created.
     Offer creating a separate `.venv-traigent` as the alternative in the same breath, so declining
     costs them nothing.

     Other dependents, not merely "already there" - the risk being confirmed is the one that only
     exists when something else relies on that environment. An environment holding nothing but
     this walkthrough's own pinned set has none, which is what a second run of this guide finds,
     and asking again there would charge a stop for a question already answered.
   - **More than one compatible candidate, or the only candidate sits outside the project root** -
     that is a genuine choice, and it gets the same one-question stop as a choice between agent
     candidates. Recommend one, say why, and list the others by path.

   The point is that the user always knows which directory on their machine is about to change.
   "Reuse an existing compatible environment" is a correct instruction that a reader cannot audit:
   in a tree with three of them it does not say which, and the first one found is not a choice.
3. Install the exact declared dependencies under the narrow authorization above: use the project's
   compatible exact declarations, or otherwise the exact pins in
   `assets/requirements-first-run.txt`. Never use an unversioned `pip install traigent`.

   This is the slowest unattended step and it overlaps nothing, so say what is happening rather
   than going quiet, and do not present the wait as though work were proceeding beside it. Do not
   move it earlier and do not delegate it to a sub-agent. `references/run-safety.md` records why
   both are deliberate.
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
   append only the missing selected-provider key name to the existing file. Leave the new entry
   blank; never replace existing values, comments, unrelated keys, blank alternate-provider
   entries, or a Traigent key already present. Create a new file with a restrictive umask and mode
   `0600` on POSIX; correct any other existing mode before opening it. Stop once and ask the user
   to enter only the selected-provider secret locally, never in chat. Do not request a Traigent
   key, route an account state, or send the user to an account/key destination here. The local
   baseline needs no Traigent account; that handoff belongs after its checkpoint in stage 7.

With OpenRouter, OpenRouter is the gateway and an automatically selected upstream inference
provider may also receive the prompts, examples, and outputs. Name OpenRouter and every allowed
upstream provider or route in the later approval, disclose whether fallback routing is enabled,
and pin allowed routes and disable fallbacks when the user requires an exact recipient set.

Explain the documented data path, and label it as a contract rather than a packet audit:

- According to the documented SDK/service contract, prompts, examples, and outputs are not sent
  to Traigent by the optimization service. This walkthrough does not independently inspect
  network packets; if observed runtime behavior contradicts that contract, stop and report it.
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
statement about the user's dataset and a score taken on our sample would report this run's sample-size
limit as though it were a property of their data. It comes *before* the approval below, because an
estimate priced on 4,812 rows and then run on 18 asks the user to approve a run that never happens -
and a decision made on a number that large may simply be no.

Record the chosen row ids, report the subset size beside the full row count, and state that the
small first-run sample limits what the comparison can establish. A first run shows the workflow; it
does not exhaust the dataset.

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup.
Prepare one concise combined approval immediately before paid work containing:

- What will run: the smallest live provider-credential check, any required LLM-judge calibration,
  the preserved baseline or a generated six-row sweep, one broader bounded optimization, and
  baseline winner versus enhanced winner validation comparison.
- Tuning/validation sizes, validation visibility, trial limit, and approximate total calls.
- The primary metric, each objective's direction and weight, the fixed baseline space, the added
  enhanced controls, how Traigent chooses trials, and the rule used to recommend a final
  configuration when accuracy, cost, or latency trade off.
- For an assistant-prepared baseline, the three-tier generated model ladder and why it omits the
  vendor's newest flagship. For a user-owned baseline, list its exact preserved models and state
  that the enhanced run adds no model unless that separate comparison is disclosed and approved.
- Approximate runtime and estimated spend.
- A `$5.00` total walkthrough ceiling by default.
- Any call path whose cost is untracked; describe the ceiling as a stop target rather than a
  provider-billing guarantee in that case.
- What leaves the machine and every service or route that may receive it. For OpenRouter, name
  OpenRouter plus every allowed upstream inference provider/route and disclose fallback behavior.

Put the runtime estimate and the default **30-minute completion target** in the same approval as the
money ceiling. This is an estimate and an up-front sizing target, not a hard wall-clock guarantee.
The default synchronous enhanced run may expose neither an interruptible checkpoint nor live
partial results, so never promise a pause at minute 30. Size the run to fit before it starts.

When the installed SDK exposes trustworthy live progress, status updates may name completed trials,
the current best, tracked spend, and an ETA recalculated from completed work. Otherwise report only
observable phase milestones. If an actual configured timeout returns completed trials, present that
partial result and offer two choices: stop and report the measured subset, or continue with a named
additional time/spend budget. Never invent progress or quietly drop validation to make the target.

If the estimated first run exceeds `$5.00` or the 30-minute completion target, first recommend a smaller
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

The combined approval covers a zero-LLM portal-tracking probe later, but do not request the
Traigent key or run that probe yet. First run the local baseline and show its checkpoint. After the
stage-7 account/key handoff, run the probe before the first connected paid trial with a trivial stub
agent that makes no provider call: confirm the whole connected path in one pass - the portal key is
present and authenticated, is scoped for `experiment.write`, a session is created, the first trial
is accepted, and a `cloud_url` comes back. Paid is not the trigger - reaching the portal is. A local
baseline spends real provider money and has no tracking to lose; a connected trial does. A
present-but-unscoped key (HTTP 403 without
`experiment.write`) and a rejected config (HTTP 400) both otherwise degrade silently to local-only
tracking while paid trials keep running and never reach the portal. If any rung fails, show a
sanitized reason and stable status/request identifier when available, then stop before any connected
paid trial. Remove secrets, prompts, examples, outputs, and personal data from externally supplied
error text before showing or saving it. Treat any degradation to local-only tracking that appears
later in the connected run the same way: halt further paid work at once and report it in the result,
never discovered afterward. The connected-run readiness detail is in
`references/run-safety.md`.

After the approved live provider probe, derive internal request and optimization time bounds from observed
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
   configuration is missing, prepare a credible quick manual-style sweep of six distinct
   configurations: by default, three credible models by two safe temperature values, with
   enhanced-only controls pinned to their ordinary/off values. Those generated models are the
   fast, mid, and strong rungs of the walkthrough ladder, never the vendor's newest flagship.
2. **Enhanced Traigent optimization** - a materially larger space that contains every baseline
   value and adds meaningful controls that the agent actually consumes. Target 10-13 visible
   trials, using 12 as the internal default cap. For the generated walkthrough, keep the model
   list identical to the baseline's, add prompt-policy choices and a native boolean self-check
   control without adding another model call, and refine swept values around the baseline's top
   rows. For a user-owned baseline, preserve every baseline model and row exactly and add
   non-model, task-relevant controls by default. Adding a new model is a separately disclosed
   experiment, not a silent part of optimization. These rules keep a win attributable to the
   added controls and managed search rather than to a quietly upgraded model.

The three-tier ladder applies only when this walkthrough supplies a missing baseline. Keep one fast
low-cost tier, one mid-tier workhorse, and one strong tier one step below the newest flagship; when
the strong tier is a reasoning model, pin its supported calling convention across both generated
spaces. Say why the flagship is omitted: this first run stays faster and cheaper while showing the
cost-quality tradeoff. A user-owned baseline is different evidence - preserve its exact model set,
including a flagship if present, and do not add cheaper tiers without the separate disclosure and
approval above.

Frame the enhanced run the same honest way in the plan and in the report: a deliberately small
enhancement for a first look - a few added knobs plus swept values refined from the baseline's own
top rows - and say in one line that this is a small slice of what Traigent can drive, not its full
capability. The deeper layers - richer task-specific spaces and the recommendation and insight
system - come after this run, so the small scope reads as a deliberate first taste rather than the
product's limit.

The baseline needs only the user's provider credential. Run its explicit fixed grid without a
Traigent key in that process, preserving any existing key on disk, so it produces the shortest
path from "nothing set up" to "a number I can see". Say plainly that this is a **local fixed
grid**, not Traigent choosing which configurations to test. It is local, not free: provider calls
spend from the same approved total.

Immediately after it returns, show a **Local baseline checkpoint** before any Traigent-key or
account request:

- If any component is `🛠️`, put the provenance limitation before the numbers.
- State what ran: a local fixed grid, not Traigent choosing the trials.
- Show the best configuration and tuning score, executed and failed trial counts, and tracked cost
  - or `not measured` when the provider/SDK did not report cost.
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
unrecorded. If the user has
already completed portal registration and still has the key created there, skip the create-account and
generate-key ask - have them paste that key into `.env`, never into chat. Registering is not the
same as holding a key: the key is created on the API-key page and is
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

Once the key is present, run the zero-LLM portal probe. Then feature-detect a public exact sync id
on the completed baseline result. When it exists, dry-run an exact one-session sync, perform the
real sync with machine-readable output, and take the baseline portal link from that sync result.
When the installed SDK exposes no supported exact id, keep the baseline local and say so; never
inspect private storage or use `--all`. Run the enhanced optimization connected and require its
own verified portal link. Report a direct link for every run actually persisted, and never imply
the enhanced link also covers a local-only baseline.

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
one-row before and stays unchanged. An assistant-prepared walkthrough must not proceed with a one-
row baseline; generate enough real controls for the six-configuration default.

After the baseline, check whether the dataset and evaluator can distinguish configurations. If
the baseline is perfect or nearly perfect and has no informative failures, stop before the search
and report the observation: this sample/evaluator shows little or no accuracy headroom. A ceiling
effect is a hypothesis, not an established cause; name other live possibilities and say when the
cause is not established. Recommend realistic boundary, failure, and harder cases, then revalidate.
Continue only if the user accepts that the run is a workflow demonstration and may have no
measurable room to improve.

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
- Real provider calls executed with nonzero usage; cost may be positive, provider-reported zero
  for a genuine free route, or explicitly untracked. Never use cost alone to decide whether a run
  was real.
- The user's existing baseline was preserved exactly, or the assistant-prepared baseline produced
  six distinct rows including its initial configuration. If the approved plan explicitly reduced
  that default, the executed count matches the disclosed reduction and still includes the initial
  configuration.
- The enhanced run added real controls and produced 10-13 trials by default, matched an explicitly
  approved and disclosed reduced target, or has a concrete SDK stop reason or failure explanation.
- The optimized result has a best configuration and non-degenerate measures.
- No trial silently truncated.
- Portal persistence completed or a precise degraded/failed state is reported.
- The pre-connected-run portal-tracking probe passed, and connected tracking never silently fell back to
  local-only during the run; any such degradation halted further paid work rather than surfacing
  only at the end.
- Any portal link is present before claiming the result is visible there.

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
post-repair, post-creation evidence and show the recorded opening score beside the closing one,
naming the caps that cleared and the caps that remain. Pass
`--config-space traigent-runs/config-space.json` to that closing run whenever the enhanced space
was emitted; without it the agent pillar scores from absent evidence and the transition understates
the run's own work. Any gain earned by a `🛠️` substitute is
walkthrough setup and is never presented as real-world readiness. Restate what was weak, what
the assistant prepared for the walkthrough, and what that costs in the real world - a dataset of a dozen generated
examples measures the workflow, not the product, however good the number looks. The opening score
and the closing recap are the same conversation: the user should leave knowing which gap to close
first and why it matters, not just what the run produced.

After a completed run, feature-detect the installed SDK's local per-example audit and optimization
insights. Report only fields actually returned, attribute each finding to that artifact, and name
the evidence behind any inference. If the helper or required evidence is absent, say that no
verified local insight artifact was available and omit specific claims.

Treat connected deeper insights the same way. Surface informative, redundant, or possibly
mislabelled-example signals and curation advice only when a verified run-scoped platform artifact
actually returned them. Never fill the DEEPER-INSIGHTS template from expectation, infer labels
from a flat score, promise a numeric dataset-quality score, or imply the platform graded an unrun
dataset. Over walkthrough substitutes, any returned insight describes only the walkthrough.

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
