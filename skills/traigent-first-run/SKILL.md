---
name: traigent-first-run
description: Guide a professional first Traigent optimization for comparison evaluators, such as classification, extraction, short-answer QA, and query or code text compared rather than run; an evaluator that runs candidate code or SQL is handled by skipping that one check, never by refusing the run. Use when a user asks to try Traigent, get started with Traigent, run a first optimization, optimize an agent for the first time, set up Traigent, or opens the Traigent/traigent-first-run repository. Inspect what already exists, preserve real components, diagnose limitations with concrete evidence, offer repair and revalidation before spending, create only the missing pieces as one coherent system, distinguish demonstration substitutes from production readiness, preserve the user's baseline or generate a credible small sweep, run one broader bounded optimization, and report what the result does and does not prove.
license: Apache-2.0
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

A stage carrying a **Read next.** dispatch has already chosen for that stage, and the dispatch
governs: open its required section, plus any optional section whose stated condition holds, and
leave the rest of that reference closed until a later dispatch asks for it. The list above is
what a stage with no dispatch falls back to.

Use [`scripts/preflight.py`](scripts/preflight.py) for free static checks and
[`scripts/readiness.py`](scripts/readiness.py) as a mandatory gate: score all three pillars before
component creation or repair, again as a required step of local validation and after changed
components as section 4 directs, and after the run for the space actually searched. Use
[`scripts/calibrate_evaluator.py`](scripts/calibrate_evaluator.py) for eligible execution checks.
An absent or deferred input earns absent evidence; never skip scoring because of it.
A readiness document this run did not itself produce is historical context, not
current-run readiness evidence - a config-space file found before this run's enhanced search,
whoever wrote it, and an agent reading left by an earlier or retired run alike: no invocation in
this run scores one, and no number derived from scoring one is reported. Only after task intent is
anchored, copy
[`assets/run-plan.md`](assets/run-plan.md) into `traigent-runs/run-plan.md` and fill it from
discovered evidence. Record the opening result there - overall score, band, and binding caps - and
never overwrite the recorded opening score. Record each later run as that template's gate result.
Keep the record concise and internal. Load The run log before appending its first required event
beside the record, and retire the two together. Keep stage status current at each boundary and
before every wait. A matching unfinished record starts Recovery's resume validation before free
work continues. The record grants no approval: revalidate comparison invariants and current
conversation authority before external calls; never restart a live process or finished run from it.
Every `<YYYYMMDDTHHMMSSZ>` this guide writes into a name - that rename, section 1's readiness
directory, the run log's `ts` - is UTC when that file or directory is written, never one id minted
per run and reused; the run supplies it because no bundled script reads a clock.

## Operating contract

- Treat this as the user's **first Traigent run**, not as evidence about their expertise.
- The walkthrough runs on a deliberately small set so it finishes in one sitting under the
  approved ceiling, proves the cloud connection, and shows the workflow; it is not a search for
  the best number. Without a newly scoped approval, never re-run a paid phase - baseline or
  search - to improve a number, never add rows from the original data or elsewhere, never widen
  the space, and never raise the trial cap. More or harder rows is the post-run handoff to
  `traigent-dataset-curate`, never a route inside this run; a search that timed out follows
  Recovery in `references/run-safety.md`.
- Never classify or announce the user's expertise level.
- Name the actor truthfully: "I will prepare the walkthrough dataset" for assistant-created
  artifacts, and "Traigent will run the managed search" only for work the service performs.
- The loaded guide source is not automatically the target project. Resolve the user-selected agent's
  root before every write or run; guide-source artifacts never count as its results.
- Before readiness or results, state and record `Target project: <absolute path> · Agent: <absolute
  path>:<function or command>`. A mismatched resumed artifact is historical, never current.
  If none is credible, use `Agent: none discovered` until intent selects or creates one.
- `references/run-safety.md` selects the credential handoff file and owns every rule about it -
  which file, its mode, when and how it is opened, what may be written. Follow it; decide none of
  it here, and never copy or re-request a value already present.
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- After task intent is anchored, put generated artifacts under `traigent-runs/`. If
  `git -C "<project-root>" rev-parse --is-inside-work-tree` succeeds, add `/traigent-runs/` to the
  project-root `.gitignore`; otherwise do not create `.gitignore`. Never overwrite source material.
- Do not put educational or advanced-skill links in the active run. Offer links after the result.
- Keep internal check IDs, SDK internals, and optimization jargon out of user-facing progress.
- Named routes are lettered from `A`, exactly one marked recommended, and answerable by reply.
  No route carries a decision of its own. Keep the question last; a route list is never compressed into yes/no. `I have it` is unnumbered,
  last, and only on material questions. A single action without alternatives is not a route list.
- An ask that follows a result sits below it. Never a marker, heading or summary of it above
  the card, board or evidence. An ask before any result may open the message.
- Open with the five-stage journey in "Opening message" below. At boundaries/long work, use
  `Stage <n>/5 · <name>` and `Done / Now / Next`. Show observed readiness score, rows checked,
  calls/trials, cost, or time; keep finished stages as compact checkmarks. Label estimates; never
  invent progress/ETA.
- Explain a blocked step in plain language and give one recommended recovery. Check the run log
  and name its path when `references/run-safety.md` requires it.
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
| Create an isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run; in a Git worktree, ensure the project-root `.gitignore` excludes `/.venv-traigent/` as the environment procedure directs. Do not fetch or install packages as part of environment creation. |
| Install dependencies in the isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run, and only in the dedicated first-run environment this run created, for the exact packages and versions declared for the run, as a package-artifact fetch/install with no provider or Traigent calls, private-data transfer, or user/project code execution. Name its absolute path before touching it. Preserve every existing, shared, or dependent environment; do not install into or fall back to one. A user or environment policy that requires install approval still takes precedence. |
| Create or update a minimal `.env` | Proceed only after free checks, and only through `references/run-safety.md`'s ordered handoff, which selects the file. Preserve existing values and comments, append only its missing provider key, and set mode `0600` before opening as that handoff directs. Before writing, run that reference's git-tracked-file safety check and its ignore verification; it owns the exact commands and exit-code handling, and stop before secret entry if either check fails. Outside Git, do not create `.gitignore`. Never copy or request a duplicate key. Add or request the Traigent key only after the baseline checkpoint. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate as section 4's post-repair rule states. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves a non-executing evaluator path is local-only or every mock model call is intercepted, with no external side effects. A path that executes or imports candidate output as code, shells out with it, or submits it to a code/SQL engine is one this guide will not run on its own initiative; what is out of scope is that path, never the task whose answer is code or SQL, and never the customer's onboarding: skip that execution, disclose it per `run-safety.md`, and continue. |
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

A substitute the assistant creates carries no mark: the two above answer whether the customer's
own component is real and ready, and a substitute is not an answer to that. List it under
walkthrough setup, named in words.

Never mark synthetic material `✅`, never count it as real-world-ready, and never say "3/3 ready"
when any component is synthetic.

After creation, retain unresolved `❗` lines; list substitutes unmarked under walkthrough setup.
Mixed boards mark only validated real components `✅`. The zero-anchor procedure supplies the
three-gap wording; do not render an additional board merely to explain this convention.

## Opening message

> **Welcome to Traigent Onboarding!**
>
> 1. **Inspect** - preserve your agent, dataset, and evaluator.
> 2. **Readiness** - run free readiness research and explain its score.
> 3. **Baseline** - install the SDK, then measure today's setup with calls, cost, and time.
> 4. **Optimize** - the paid baseline result comes first, your Traigent account after it, then a
>    bounded managed search.
> 5. **Results** - compare the runs, recommend one next step, and hand over the Traigent skills so
>    you can keep going alone.
>
> I will mark each stage with measured numbers when available. Readiness checks the score and
> setup—not agent accuracy or an optimization result. I explain details only if action is needed.
> Baseline evidence decides the next step.

## Guided flow

Announce only the five stages above, as `Stage N/5`. The numbered sections below are
this guide's structure, not those stages: never show their numbers or their titles.
`Done / Now / Next` names those five stages - a `Next` reading "isolated SDK
environment" names a section the customer was never given. This guide's own prose says
`section N` for a section below and `Stage N/5` for a stage; the map between them:

- `Stage 1/5 · Inspect` - section 1.
- `Stage 2/5 · Readiness` - sections 2 to 4: the board, the one ask, creation, local validation.
- `Stage 3/5 · Baseline` - sections 5 and 6, and section 7 until the baseline returns.
- `Stage 4/5 · Optimize` - section 7 from the local baseline checkpoint.
- `Stage 5/5 · Results` - section 8.

### 1. Inspect quietly

Unless this run is resuming - which opens with where it stands instead - print
"Opening message" above verbatim before anything else. Then perform safe,
read-only discovery without asking for approval:

- Identify the checkout root of this guide's clone, or its installed package directory.
  If it is nested inside the target project, exclude that whole tree from discovery and scoring,
  and say so. Its
  fixtures, scripts, credentials examples, and past results are not customer components. Do not
  move or delete the directory automatically.
- Identify the project language, Python version, dependency system, and every existing virtual
  environment - not the first one found. A tree can hold several, under names no convention
  covers (`env`, `.direnv`, `.tox`, a tool-managed path outside the project), and section 5 cannot
  choose between candidates it was never told about.
- Record the chosen target project's absolute root and the selected agent's absolute path plus
  callable or command. When an old artifact names another target or agent, preserve it as
  historical context but exclude it from this run's score and report.
- Find LLM/model call sites and the smallest scoreable agent function, and infer its input/output
  contract and the product behavior being attempted. Finish this before the search below.
- Then find datasets, fixtures, golden files, accepted traces, request/response logs,
  tests, rubrics, scorers, evaluators, and outcome checks, searching outward from that agent. What it does, the contract just inferred,
  and the files its own call sites and tests reach are what tell its examples and its grading method
  apart from the first plausible ones in the tree - and a project holding two agents usually holds
  material belonging to each. Either of those two may be taken up first; what is load-bearing is
  that both follow the agent.
- Validate the apparent quality of real Dataset and Evaluation candidates, not only their
  existence. Record concrete evidence for Agent, Dataset, and Evaluation. Do not guess.

Ask which agent to use when multiple credible candidates remain. With exactly one, name its path
inside the one ask below instead of halting for it separately; that reply accepts `agent:`. Where
the ask does not fire, the pre-spend approval names the agent before any charge. Once selected,
including a dummy or walkthrough agent, never ask again. Whether the evaluation method grades it
is settled by the compatibility contract in `references/component-creation.md`.

Carry the resolved evaluator method, task kind, and component origins as consistent run-scoped
state into every applicable scoring gate. The opening procedure owns the exact flags and evidence
requirements; re-resolve declarations whenever their component changes.

#### Opening readiness gate

Before any component creation or repair, run the opening readiness procedure below over the
current inventory. It selects a no-install interpreter, runs static preflight, reviews available
rows, calibrates an eligible local evaluator, and scores all three pillars from current-run
evidence. Preserve the opening score before creating substitutes. An existing but unmeasured
component is not absent, and historical readings or config spaces earn no current-run credit.
On a zero-anchor run, keep evidence on stdout and the card in the conversation until the task
answer permits writes. Otherwise name the fresh project-relative readiness directory and any row
review or calibration artifacts before showing the card. Render the card verbatim, then explain
its score, band, and reasons in the user's language using the glossary's presentation rules.
The scoring command reads the project; name the evidence this run wrote before it.

**Read next.** Required: [`references/component-creation.md` § Reading the agent for the opening score](references/component-creation.md#reading-the-agent-for-the-opening-score).
If a component has to be classified `real`, `limited`, or `invalid`: [`references/component-creation.md` § Evidence and provenance](references/component-creation.md#evidence-and-provenance).
If nothing anchors task intent and the user must choose it: [`references/component-creation.md` § The one ask, and the path that answers it](references/component-creation.md#the-one-ask-and-the-path-that-answers-it).
If a matching run record requires resume validation: [`references/run-safety.md` § Recovery](references/run-safety.md#recovery).
If the first event is about to be appended to the run log: [`references/run-safety.md` § The run log](references/run-safety.md#the-run-log).
If a resolved deterministic evaluator is assessed for opening calibration: [`references/evaluation-and-dataset.md` § Mandatory calibration](references/evaluation-and-dataset.md#mandatory-calibration).
If opening calibration could execute an evaluator: [`references/run-safety.md` § Static and mock validation](references/run-safety.md#static-and-mock-validation).
If rows exist and the row review has to be written: [`references/evaluation-and-dataset.md` § The row-level sanity check](references/evaluation-and-dataset.md#the-row-level-sanity-check).

#### Zero-anchor intent gate

When nothing in the inventory anchors an identifiable task, including a constant-returning,
echoing, or placeholder agent, show the opening card and three real-world gaps. Offer to create a
coherent trio from the available material, carrying the same gap question's choices and limits.
Ask **"What should the walkthrough agent do?"** with at most three short jobs in the customer's
words, recommending one from evidence in their material. Make this the final question and **STOP
and wait for the answer**. Before it, make zero project writes: no run directory, run plan,
`.gitignore` edit, environment, dependency installation, or generated component.
After the answer, create the run record and record the unchanged opening score before the trio.
The gap-question procedure below owns the wording and path alternative.

### 2. Show readiness once

For a zero-anchor project, the intent gate already rendered the initial readiness board; do not
render it again before the user answers. For every other starting state, render the initial
real-world readiness board after inspection. Show the rendered card beside that board, as printed.
State what the coding assistant will create for the walkthrough.
Do not show external links. Do not ask the user to solve missing setup pieces - the ask below fills
them and offers to use theirs, which is the opposite of delegating them. After a creation or
repair, the board changes only as section 4's post-repair rule states.

If real material exists but appears too weak to support a meaningful comparison, show a short
**Quality advisory** immediately below the board:

- Name the affected component and cite measured evidence or specific examples.
- Explain the optimization consequence in one sentence: unreliable ranking, no measurable
  headroom, misleading accuracy, or failure during evaluation.
- Recommend: **"Repair a working copy and re-run validation"**.
- Offer repair now, a clearly labeled workflow demonstration when safe, or pause while the user
  edits it. Where a row-count cap asks, the bounded top-up replaces repair: nothing is broken.

Do not call a component weak merely from intuition. For judgment-based findings such as "all
examples are easy," cite representative rows and the missing challenge/failure modes. For
structural findings, report counts and percentages.

#### One ask for every gap

Put all missing or unread components, quality findings, and eligible shortfalls on one question
below the board, before building anything. Say what was searched for and not found, what this run
can derive, and how substitutes limit the result. Offer bounded top-up only for an asking cap:
up to 28 rows, with its generated-data ceiling disclosed. Offer proceed; where material is only
short, also offer keeping it. Always end with `I have it` and a path as an unnumbered alternative.
Ask what they want optimized only where their evaluator and project do not establish it; if no
objective is named, say the default is accuracy and cost. Then stop and wait. A supplied path
reopens the opening gate before the run record is created. The zero-anchor task question carries
these same terms, never an additional question; defects keep section 4's validation gates.

**Read next.** Required: [`references/component-creation.md` § The one ask, and the path that answers it](references/component-creation.md#the-one-ask-and-the-path-that-answers-it).
If a dataset below this run's 28 puts a top-up on that same ask: [`references/evaluation-and-dataset.md` § Dataset construction](references/evaluation-and-dataset.md#dataset-construction).

### 3. Complete the system

Follow the dependency matrix in `references/component-creation.md`:

- Preserve every real component.
- Build only missing components.
- Derive each created component from all existing anchors, not independently.
- If nothing exists, create the run record and one coherent trio only after the user answers the
  single task-intent question.
- Design compatibility in both directions: dataset inputs fit the agent contract, and agent
  outputs are meaningfully scoreable by the evaluator. Treat this as a design check here; exact
  runtime binding is owned by the installed SDK and is verified in section 5.

**Read next.** Required: [`references/component-creation.md` § Dependency matrix](references/component-creation.md#dependency-matrix).
If this run needs to create a dataset of examples: [`references/evaluation-and-dataset.md` § Dataset construction](references/evaluation-and-dataset.md#dataset-construction).
If this run will create, top up, split, repair, or sample a dataset: [`references/evaluation-and-dataset.md` § Held-out set and claims](references/evaluation-and-dataset.md#held-out-set-and-claims).
If the matrix row directs creating an agent: [`references/component-creation.md` § Agent creation](references/component-creation.md#agent-creation).
If the row directs building an evaluation method: [`references/evaluation-and-dataset.md` § Evaluation selection](references/evaluation-and-dataset.md#evaluation-selection).

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

**Read next.** Required: [`references/evaluation-and-dataset.md` § Mandatory calibration](references/evaluation-and-dataset.md#mandatory-calibration).
If the resolved evaluator call path executes or imports candidate output: [`references/run-safety.md` § Static and mock validation](references/run-safety.md#static-and-mock-validation).
If the evaluator replays the customer's own workflow: [`references/run-safety.md` § A replay that changes the customer's world asks first](references/run-safety.md#a-replay-that-changes-the-customers-world-asks-first).
If calibration reaches its timeout: [`references/evaluation-and-dataset.md` § When calibration runs long](references/evaluation-and-dataset.md#when-calibration-runs-long).
If a check reports that the dataset or evaluator cannot separate configurations: [`references/evaluation-and-dataset.md` § Quality diagnosis and repair choice](references/evaluation-and-dataset.md#quality-diagnosis-and-repair-choice).
If the agent and the evaluator have to be validated against each other before optimization: [`references/component-creation.md` § Compatibility contract](references/component-creation.md#compatibility-contract).
If a repair is to move a component from `limited` or `invalid` to `real`: [`references/component-creation.md` § Readiness transitions](references/component-creation.md#readiness-transitions).
If the dataset carries more than 100 usable rows: [`references/evaluation-and-dataset.md` § First-run subset for a large dataset](references/evaluation-and-dataset.md#first-run-subset-for-a-large-dataset).

Follow the local validation sequence: record task-grounded calibration cases and semantic coverage;
resolve only material grading ambiguity with one question; run deferred-SDK static preflight over
both splits; apply the evaluator-execution scope gate; calibrate eligible inspected paths; then
score readiness from fresh evidence. Reuse a valid opening calibration unless its inputs or path
changed. Keep external or paid calibration behind its stage approval. A skipped execution-evaluator
check records `containment` and its disclosure; it does not end the run. Preflight-only evidence is
recorded now and refreshed after any deferred calibration.
Keep limited real components `❗`, with a repair recommendation or explicitly labeled demonstration.
An invalid evaluator, schema, required row set, or unverified call path cannot support paid work:
repair and revalidate a reversible copy, or pause for a user-authored fix. Say what material survives;
`continue as is` does not override validation. Use the component reference's existing choice wording.

After a repair or a creation, re-run only the checks whose input the repair changed. Two repairs
invalidate an earlier pass and must redo it: an evaluator repair re-runs the degenerate-gold check
in `references/evaluation-and-dataset.md`, and a dataset supplied via `I have it` after the
opening-gate calibration re-derives the calibration cases for the opening-gate re-run that
section 2 owns, whose card is the opening score - that re-run is section 2's, not this rule's.
Then recompute the score over all three pillars, re-reading the agent only where this run created or repaired it, and record that gate
result without overwriting the opening one. Then print exactly one line, `Fixed: <component> -
cleared: <caps> - continuing`; on the board, refresh only changed evidence, retain unresolved `❗`
lines and add the new substitutes under walkthrough setup; show no second card.

Route active caps by their measured reason using the reference's readiness-finding catalog.
Creation, repair, or an unread component must be resolved before spending; an evidence ceiling
limits the claim and proceeds through its existing question or disclosure. Keep condition ids
internal. Generated components remain substitutes; a failed check, an unmade check, and a bounded
sample have different remedies. Before either paid grid, the local request-difference proof must
establish every selected direct dimension; otherwise report the stop and zero trials.

**Read next.** Required: [`references/evaluation-and-dataset.md` § Quality diagnosis and repair choice](references/evaluation-and-dataset.md#quality-diagnosis-and-repair-choice).

### 5. Prepare the environment and finish free checks

After standard-library-only component checks, follow the environment procedure in order: inventory
the selected route and credential presence without values; prepare the dedicated `.venv-traigent`
while preserving existing environments; announce and install the exact pinned stack; require the
installed preflight’s `sdk-version: PASS`; inspect SDK capabilities; finish deferred calibration and isolated
mock plumbing. Then, if genuinely missing, stop once for the selected provider credential through
the ordered local handoff. Route changes require recipient disclosure and approval. The Traigent
key waits for section 7's baseline checkpoint. Installation stays foregrounded and subject to the
authorization table. A verified completed setup from this unfinished run resumes through that
procedure without reinstalling; no free check grants authority for paid calls.

Before baseline approval, locally prove request differences. For an inspected customer baseline, set
`BASELINE_IS_USER_OWNED = True` and make `WIRED_KNOBS` exactly match its paid enhanced dimensions;
preserve conditional rows/dimensions; stop for approved per-model validation. Re-prove before each
paid phase.

Before baseline approval, explain only its provider recipients using `references/run-safety.md`:
the selected provider receives normal model-call content; OpenRouter and every allowed upstream
inference provider/route may receive it. Connected synchronization waits until after the baseline checkpoint.

**Read next.** Required: [`references/run-safety.md` § Environment and privacy](references/run-safety.md#environment-and-privacy).
If SDK mock plumbing is being assessed or run: [`references/run-safety.md` § Deterministic calibration and mock plumbing](references/run-safety.md#deterministic-calibration-and-mock-plumbing).
If a public signature or capability has to be confirmed on the installed SDK: [`references/sdk-execution.md` § Capability discovery](references/sdk-execution.md#capability-discovery).

### 6. Approve and run the baseline

Scope the run before pricing it. Where the dataset carries more than 100 usable rows, section 4
already drew the bounded first-run subset; this stage prices it and never draws it. Estimate runtime
and spend from the rows those questions bring, never from the full row count.

Report subset and full sizes from the ids section 4 recorded, and state that the small first-run
sample limits the claim.

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup, and do
not repeat a provider choice already resolved in section 5.

Use the baseline checklist in `references/run-safety.md` for one concise baseline preview and
approval covering the live provider check, any pre-baseline LLM-judge calibration, and the
preserved baseline or generated twelve-configuration sweep. Say only that a separately previewed managed run may
follow; do not front-load its algorithm, search space, trial arithmetic, portal features, or insights.

**Read next.** Required: [`references/run-safety.md` § Approval and budgets](references/run-safety.md#approval-and-budgets).
If runtime or a trial count has to be estimated: [`references/sdk-execution.md` § Automatic run bounds](references/sdk-execution.md#automatic-run-bounds).
If this walkthrough supplies the baseline's models: [`references/sdk-execution.md` § Walkthrough model ladder](references/sdk-execution.md#walkthrough-model-ladder).

The approval includes any required pre-spend evidence card, current limitations and assumed
provenance, prior Traigent setup notice, exact baseline models and knob values, selected row ids,
time and spend estimates, and the **30-minute completion target**. Present one lettered spend-or-fix
choice when the card calls for it; add no extra pause. If the estimate exceeds `$5.00` or 30 minutes,
recommend a smaller representative slice while preserving the baseline grid. Enforce the approved
figures and shared running total in every paid process; stop before the next call exceeds them.
After the approved provider probe, recheck observed time bounds and re-scope approval if needed.
Report measured progress or phase milestones, never invented progress; preserve paid partial
results through Recovery.

### 7. Run the honest comparison

Preserve the user's baseline exactly; generate the twelve-configuration baseline only when absent.
Use the same tuning rows, evaluator, objectives, and agent call path for both measurements. Retain
every baseline model/value in the enhancement, add only proven meaningful controls, and test up to
12 configurations from a materially larger space. The generated model ladder never expands a
customer-owned baseline without a separately disclosed experiment. This is a deliberately small
enhancement; baseline and search are the only paid passes.
Follow the comparison sequence for the baseline, checkpoint, connected approval, and search.

**Read next.** Required: [`references/run-safety.md` § Baseline and optimization](references/run-safety.md#baseline-and-optimization).
If this walkthrough supplies the baseline's models: [`references/sdk-execution.md` § Walkthrough model ladder](references/sdk-execution.md#walkthrough-model-ladder).

The baseline needs only the user's provider credential. Run the local fixed grid without a
Traigent key in that process, preserving keys on disk. It is provider-paid and uses the shared
approved ceiling. Prepare the wrapper and fixed grid from the execution contract.

**Read next.** Required: [`references/sdk-execution.md` § Small baseline sweep](references/sdk-execution.md#small-baseline-sweep).
If the run wrapper is being written now: [`references/sdk-execution.md` § Decorator contract](references/sdk-execution.md#decorator-contract).

Immediately after it returns, show a **Local baseline checkpoint** with target/agent identity,
substitute limits, measured tuning results, cost/latency, trials/failures, and its objective-cost
frontier. Explain knobs plainly; distinguish the local grid from managed search. Do not disclose
the held-out score before section 8, and make no generalization or production-improvement claim.
If the signal cannot distinguish configurations, recommend the evidenced repair before search.
A nearly perfect baseline may proceed as an optional verification with no expected gain, or stop
with its baseline-only result. Recommend the sound continuing route without promising improvement;
stopping preserves a real result. The comparison sequence owns the full decision and disclosure.

Preview `Stage 4/5 · Optimize`: exact enhanced controls and trial ceiling, recipients, documented
sync limits, measured bounds, and conditional capabilities. Obtain explicit connected-stage
approval before its key, probe, sync, or calls; the lettered routes close the message. The user has
seen provider-backed value before being asked to create an account. Reuse a suitable full-access
Traigent key or follow the account-state and local credential handoff procedure. Once the key is
present, run the zero-LLM portal probe, then capability-gated exact-session baseline sync; without
a supported id, keep the baseline local. Never repay the baseline to create a portal entry.
Re-prove the final wrapper and spaces in the fresh enhanced process, then run connected.

**Read next.** Required: [`references/sdk-execution.md` § Broader optimization](references/sdk-execution.md#broader-optimization).
If the connected run's tracking path has not been proved: [`references/run-safety.md` § Connected-run readiness](references/run-safety.md#connected-run-readiness).
If the local baseline is to appear in the portal: [`references/sdk-execution.md` § Carrying the local baseline into the portal](references/sdk-execution.md#carrying-the-local-baseline-into-the-portal).

Persist `traigent-runs/config-space.json` only after nonzero search trials, from the exact space
used; only that current-run document reaches closing readiness. Stop on provider, backend, or
portal failure with the concrete reason and one recovery; preserve paid work and never replace it
with mock or synthetic results. Do not fabricate configurations to reach a count.
After search, recommend a configuration from tuning scores across both measurements and score
only that one on the held-out rows. A frontier may contain no point worse than the current
baseline under the declared objective direction; its conclusions must match measured evidence.

**Read next.** Required: [`references/evaluation-and-dataset.md` § Held-out set and claims](references/evaluation-and-dataset.md#held-out-set-and-claims).

### 8. Verify and report

Before saying the run succeeded, apply every post-run verification in
`references/run-safety.md`. Also verify that the baseline was preserved exactly or the generated
twelve-configuration default ran in full, its initial configuration among them - the baseline grid
is never reduced, and an approved disclosure does not make it so; the enhanced run used real
controls and either produced at least 10 of its 12 permitted trials, matched an explicitly approved
and disclosed reduced target, or reports a concrete stop/failure reason; and a
best configuration and non-degenerate measures exist. Verify the held-out score belongs to the one
configuration this run recommends, chosen on the tuning scores, and that no other candidate was
scored on those rows. Report truncation and persistence failures, require the portal
probe to have stayed green, and verify each portal link before claiming visibility.

**Read next.** Required: [`references/run-safety.md` § Post-run verification](references/run-safety.md#post-run-verification).
If the search stopped, failed, or returned zero trials: [`references/run-safety.md` § Recovery](references/run-safety.md#recovery).

Report in five layers: outcome, what the evidence establishes, current state and limits, one next
action, then auditable details. Compare baseline and enhanced tuning outcomes, show the selected
configuration's one held-out result, and state sample limits, exclusions by id, measured costs,
failed or incomplete work, and verified artifact/portal links. Name substitutes and their limits
before interpreting them; keep every persisted experiment and label an unsynced baseline local-only.
A flat or negative result leads with its measured delta: separate facts, supported inferences, and
hypotheses, using `cause not established by this run` where appropriate. Generated material cannot
establish production performance or support promotion; later promotion requires separate approval
and validation.
Run the closing readiness gate on current post-run evidence to check the agent space actually
searched. Record and route its findings internally; never display a second readiness number or
compare it to the opening score. Post-run verification owns the evidence checklist, invocation,
no-lift interpretation, and handling of stopped or zero-trial searches.

Feature-detect local audit and connected insight capabilities. Report only fields actually
returned, attribute each claim to its artifact, and otherwise say no verified local artifact was
available. Surface deeper signals only when a verified run-scoped platform artifact actually
returned them. Never fill the DEEPER-INSIGHTS template from expectation, infer labels from a flat
score, promise a numeric dataset-quality score, or imply the platform graded an unrun dataset;
over substitutes, every insight describes only the walkthrough.

**Read next.** Required: [`references/sdk-execution.md` § Result checks](references/sdk-execution.md#result-checks).
If the installed result exposes a per-example audit or an insights helper: [`references/sdk-execution.md` § Reading the result for insight](references/sdk-execution.md#reading-the-result-for-insight).

Close with one recommended next action grounded in the recorded opening caps and this run's
measured limits. A substitute fills a gap provisionally; it does not close it. Explain what that
action would improve and the bound that most limited this walkthrough, without promising what a
larger run would find. Use the continuation handoff for the state-specific recommendation,
reply-ready final block, and optional skills package. Handoff observations are hypotheses to test
at full scale; `continue` never bypasses approval.

**Read next.** Required: [`references/run-safety.md` § Continuation handoff](references/run-safety.md#continuation-handoff).

## Completion criteria

The first run is complete only when the record marks every section done or skipped with its reason,
and the evidence supports these checks:

- The starting state, component provenance, opening score/band/caps, and later gate results are
  recorded; the opening score predates component creation/repair and is the only readiness number
  reported to the user.
- Missing components were built around existing anchors; changed components were revalidated.
  Compatibility passed and evidence-backed quality limits and repair/continue/pause choices were
  explained. No paid work used a component the validation gates refused.
- Calibration has the task-semantic cases, thresholds, outcome-class coverage, and sufficient
  assistant review the validation sequence requires. Material grading ambiguity was resolved
  before execution; otherwise no review-only pause occurred. When the execution scope gate skips
  calibration, the recorded `containment` warning, disclosure, and any connection answer satisfy
  this criterion; that run is allowed to finish.
- Free checks made no provider calls, and each paid stage had explicit approval before its calls.
- Baseline and optimization used the same tuning data, evaluator, and objectives; each reported
  frontier has measured costs, a score claim supported by the paired evidence, and no point worse
  than the current baseline under the declared objective direction.
- The user received a concise truthful result, limitations, one next action, artifacts, and only
  verified portal links. Claims match component provenance and validation evidence; incomplete
  phases and remaining gaps remain visible.
