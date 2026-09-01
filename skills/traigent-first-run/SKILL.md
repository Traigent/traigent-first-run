---
name: traigent-first-run
description: Guide a professional first Traigent optimization for non-executing comparison evaluators, such as classification, extraction, short-answer QA, and query or code text compared rather than run. Use when a user asks to try Traigent, get started with Traigent, run a first optimization, optimize an agent for the first time, set up Traigent, or opens the Traigent/traigent-first-run repository. Inspect what already exists, preserve real components, diagnose limitations with concrete evidence, offer repair and revalidation before spending, create only the missing pieces as one coherent system, distinguish demonstration substitutes from production readiness, preserve the user's baseline or generate a credible small sweep, run one broader bounded optimization, and report what the result does and does not prove.
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

Use [`scripts/preflight.py`](scripts/preflight.py) for the free static preflight. Use
[`scripts/readiness.py`](scripts/readiness.py) as a mandatory gate, never only when it seems
useful: score all three pillars at the start of every guided run before any Agent, Dataset, or
Evaluation component creation or repair,
again as a required step of local validation, again after each repair or creation, and once more
after the run, to measure the space it searched. Use
[`scripts/calibrate_evaluator.py`](scripts/calibrate_evaluator.py) for the separate,
explicit evaluator-execution gate. Supply lifecycle-permitted evidence from the current run;
an absent or deferred input scores its pillar from absent evidence and is never a reason to skip
the score. A config-space file found before this run's enhanced search is historical context, not
current-run readiness evidence: no invocation in this run scores it, and no number derived from
scoring one is reported. Only after task intent is anchored, copy
[`assets/run-plan.md`](assets/run-plan.md) into `traigent-runs/run-plan.md` and fill it from
discovered evidence. Record the opening result there - overall score, band, and binding caps - and
never overwrite the recorded opening score. Record each later run as that template's gate result.
Keep it concise and internal; do not ask the user to complete or review it.
Beside it, append every event `references/run-safety.md` names to `traigent-runs/run-log.jsonl`,
in the shape that reference gives them; load it before the first line is written rather than at
its own stage, and rename the log beside any record this run retires.
Keep its stage-status block current from the moment the record exists: at every stage boundary and
before every stop-and-wait, mark each stage done, in progress, or skipped with the reason; the
next stage is always the first neither marked done nor skipped. A session finding
`traigent-runs/run-plan.md` with a matching target and agent - target plus the recorded task answer
when the agent line is `none discovered` - begins resume validation rather than automatically
restarting: read it top to bottom and treat its status and results as resume hints. Independently
verify the target and agent, rerun the cheap read-only/free gates required by the next action,
including execution-evaluator scope and call-path checks, and verify a paid artifact before quoting
it.
After that verification, continue through free work at the first stage neither marked done nor
skipped. The record may avoid repeating paid work, never waive a safety precondition.
Recorded scores, spend, completed paid results, and the opening score stand; recorded approvals do
not. Open with where the run stands, not the opening message. Before a new or restarted provider,
private-data, connected Traigent, or other approval-gated external call, re-ground in the latest
user approval in the current conversation and confirm it covers the remaining recipients/data,
scope, runtime, and ceiling. If absent, revoked, or insufficient, re-render that remaining-scope
card and obtain explicit approval; the record alone grants no authority. Before that call, compute
the current comparison invariants and compare them byte-for-byte with the pre-baseline invariants
recorded after free validation; never rewrite the recorded invariants. They are the objective,
agent/call behavior, exact tuning and held-out rows, evaluator, and baseline model/value set. The
enhanced space is deliberately excluded because it must add controls; before a connected call,
verify separately that it retains every recorded baseline model/value and that its only additions
exactly match the freshly rendered and approved enhanced card. If the invariants are incomplete or
differ, do not resume this run: rename the old record to the next unused
`traigent-runs/run-plan-historical-<YYYYMMDDTHHMMSSZ>.md` (never overwrite), keep its spend and results
historical or baseline-only, copy a fresh template to canonical `traigent-runs/run-plan.md`, start
at stage 1 with a new opening score, and never rerun paid work without newly scoped approval.
Observe a live process, but never restart or expand it from the record alone. A record with every
stage done or skipped is finished, not a resume point. The operating contract owns the mismatch
rule.

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
- `references/run-safety.md` selects the credential handoff file and owns every rule about it -
  which file, its mode, when and how it is opened, what may be written. Follow it; decide none of
  it here, and never copy or re-request a value already present.
- Inspect before asking. Preserve existing agent logic, datasets, evaluators, tests, and files.
- After task intent is anchored, put generated artifacts under `traigent-runs/`. If
  `git -C "<project-root>" rev-parse --is-inside-work-tree` succeeds, add `/traigent-runs/` to the
  project-root `.gitignore`; otherwise do not create `.gitignore`. Never overwrite source material.
- Do not put educational or advanced-skill links in the active run. Offer links after the result.
- Keep internal check IDs, SDK internals, and optimization jargon out of user-facing progress.
- Put the one ask last. Card, board and evidence first, then the question - never a marker,
  heading or summary of it above them. The reader acts on it, so it ends the message.
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
| Create an isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run; do not fetch or install packages as part of environment creation. |
| Install dependencies in the isolated environment | Proceed only after task intent is anchored and the available standard-library-only component checks have run, and only in the dedicated first-run environment this run created, for the exact packages and versions declared for the run, as a package-artifact fetch/install with no provider or Traigent calls, private-data transfer, or user/project code execution. Name its absolute path before touching it. Preserve every existing, shared, or dependent environment; do not install into or fall back to one. A user or environment policy that requires install approval still takes precedence. |
| Create or update a minimal `.env` | Proceed only after free checks, and only through `references/run-safety.md`'s ordered handoff, which selects the file. Preserve existing values and comments, append only its missing provider key, and require mode `0600` before opening. Before writing, run that reference's git-tracked-file safety check and its ignore verification; it owns the exact commands and exit-code handling, and stop before secret entry if either check fails. Outside Git, do not create `.gitignore`. Never copy or request a duplicate key. Add or request the Traigent key only after the baseline checkpoint. |
| Repair a working copy after the user chooses repair | Proceed only within the agreed repair scope, then revalidate from the failed gate. |
| Change real labels, expected answers, examples, or rubric policy | Show the exact judgment-dependent change and obtain explicit approval. |
| Execute an evaluator or mock check | Proceed without provider approval only after inspection proves a non-executing evaluator path is local-only or every mock model call is intercepted, with no external side effects. A path that executes or imports candidate output as code, shells out with it, or submits it to a code/SQL engine is outside this first-run guide; what is outside is that path, never the task whose answer is code or SQL: stop before execution and follow `run-safety.md`'s manual-containment route. |
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

After creation, keep the three `❗` lines and add three lines under walkthrough setup naming the
substitutes. For mixed states, mark real components `✅`; substitutes stay unmarked under that
heading.

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
environment" names a section the customer was never given.

### 1. Inspect quietly

Unless this run is resuming - which opens with where it stands instead - print
"Opening message" above verbatim before anything else. Then perform safe,
read-only discovery without asking for approval:

- Identify the project language, Python version, dependency system, and every existing virtual
  environment - not the first one found. A tree can hold several, under names no convention
  covers (`env`, `.direnv`, `.tox`, a tool-managed path outside the project), and stage 5 cannot
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

Treat the resolved evaluator method as run-scoped validation state. Resolve it from the currently
selected evaluator, update it whenever that evaluator is created, repaired, or replaced, and pass
the same current `--evaluator-method` value to every paired preflight/readiness invocation. When no
evaluator method exists, omit the flag from both; never let one half infer a different method. When
a file exists but no method can be honestly declared for it without executing it - a syntax error,
or behavior that plainly ignores its input - still omit `--evaluator-method`, but pass its path to
preflight's `--evaluator` for a static syntax check; this reports present-but-unresolved, not absent.

Ground readiness task kind per the evaluation reference.

Declare who wrote the evaluator and the agent on every readiness call, as run-scoped state beside
the method above: `--evaluator-origin` and `--agent-origin`, `brought` for the customer's own and
`generated` for one this run created. Nothing in a scoring function or an agent's source says who
typed it, so this is the only way the score can carry what the card's walkthrough section says,
and it is you rather than the customer who knows - never ask. Omit a flag only where that component
does not exist yet; nothing has an origin before it is there. Update each the moment this run
creates that component, so the re-score after a creation stops claiming the customer's own. Omitting
one is not a neutral choice: it scores a generated component as if it were the customer's, which is
the one thing the real-world/walkthrough separation exists to prevent. The dataset takes no such flag - its
origin is counted per row from declared provenance, and a second declaration beside a count is two
answers to one question.

#### Opening readiness gate

Before any component creation or repair, choose from the recorded inventory. If there is exactly
one compatible Python 3.11-3.13 isolated-environment candidate overall and its resolved path is
inside the user's project root, use its resolved interpreter and report `python-version` as
measured. Otherwise use the host
`python3` as a provisional, no-install bootstrap. Multiple compatible candidates and environments
outside the project wait for stage 5; if the sole candidate fails, record why and fall back to the
host. Stage 5 remains authoritative for the connected run.

Run the bundled static preflight with `--defer-missing-sdk` over whatever dataset was discovered,
omitting `--dataset` when none exists. Then include every safe measurement that can finish now in
the first readiness card. When task intent is anchored and inspection finds a resolved deterministic
evaluator, construct or revalidate its current-run case matrix and semantic-coverage review, then
apply the evaluator-execution scope gate from stage 4. If the verdict is `sufficient` and the
complete path does not execute candidate-generated code or SQL, is local-only, side-effect-free,
standard-library-only, and expected to return in seconds, run fresh credential-stripped calibration now and pass its result to
`scripts/readiness.py --calibration`. This validates an existing component; it does not create or
repair one, needs no provider approval under the action table, and lets the opening card report
what the run can actually establish. Before launching it, tell the user that this local check imports
the inspected evaluator. Pass `--allow-execution` as the assistant's explicit acknowledgement only
after the inspection above; the flag is not safety evidence and bypasses no scope gate. This notice
adds no stop-and-wait. The evaluator-method name and `--kind deterministic` are not safety evidence.
Never reuse a result from an earlier run or a pre-existing artifact.

Otherwise run readiness without `--calibration` and name the concrete deferral: unresolved
semantics, no defensible probe matrix, an uninstalled local dependency, a slow, uncertain, external,
or executing path, or an LLM judge that needs paid approval. Missing calibration is then unmeasured,
not a failed evaluator; the `evaluator-unvalidated` ceiling limits the readiness claim to 45 until
the evaluation method is actually checked. When rows exist, do the row-level sanity check in
`references/evaluation-and-dataset.md` here and pass it as `--row-review`: it is your own read, it
spends nothing, and no generated row competes with it yet. Apply the run-scoped evaluator-method rule above to both
scripts, and apply the run-scoped task-kind rule to readiness only, and the origin rule with it.
**Opening dataset sequencing.** The opening preflight reads a discovered dataset with its default
`input`/`output` fields, before any explicit field mapping; do not pass `--input-field` or
`--expected-field` to that opening call. A request/response log or accepted trace is a **source**
from which rows may later be built, never a `--dataset` argument. If only such sources exist, omit
`--dataset` so the opening card records `dataset-absent` and routes to `get-data`. After that
recorded opening result, map a custom dataset's actual fields and re-score; when deriving rows from
recorded calls, declare the real input separately from the generated candidate output, which is not
an expected-answer key.

On a zero-anchor run, keep the preflight JSON on stdout and feed it directly to
`readiness.py --preflight -`; retain the rendered card in the conversation only. Until the answer
anchors intent, do not use `--report`, write evidence under the project, or name a readiness
directory.
Explicitly omit every config-space file found before this run's enhanced search from scoring,
including one left by an earlier guided run: it is historical context, not current-run readiness
evidence. Record its provenance; a timestamp, hash, or non-empty `wired` list does not make it
current. A customer-authored file may guide inspection, never score values or wiring. Every guided
run does this, including a zero-anchor run.

After task intent is anchored, every file a
 scoring writes to reach it - that document, the preflight JSON, any note - goes in
 `traigent-runs/readiness/<YYYYMMDDTHHMMSSZ>/`, a fresh directory per scoring so a later one never
reads an earlier one's. Never delete them, and name that directory to the user beside the card in
 that project-relative form, never expanded to an absolute path: they may want to keep, share, or
 remove it. The canonical `traigent-runs/calibration-cases.json` and
 `traigent-runs/calibration-results.json` are evaluator-validation evidence owned by
 `references/evaluation-and-dataset.md`, not readiness-directory artifacts. When opening
 calibration creates them, name both paths beside the readiness directory before showing the card.
 Two halves, one pass, and
neither is optional where an agent was found. For a selected top-level Python function, include
`--agent-source-root`, `--selected-agent`, and `--selected-agent-callable`; `source_lines` must show values on its
verified selected-call path. Otherwise leave source credit unestablished and use the advisory route. A thin Python adapter is
walkthrough material, not proof that the original agent was optimized. `references/component-creation.md` owns the
exact argv and source-evidence contract.
A name only in a comment, docstring, TODO, or example is not scored; it may guide inspection but
cannot establish a value. Same rule as
`references/component-creation.md`, applied here because this
gate is evaluated before that reference loads. Read the same source for how the agent is built and
answer all four checks the reference names: whether it carries a prompt and worked examples,
whether anything pins down the
shape of its answer, whether it ends and on what, and whether the tools it declares can be reached.
Answer a check you cannot settle as undetermined with the reason, never as a no - a no says the
agent lacks the thing. Build declarations stay visible but unmeasured; an undetermined check
still needs its reason. Never write a range or an
option you did not read: an omitted parameter costs a few points, an invented one makes the card
wrong. Wanting a second option here is the right instinct at the wrong stage - stage 5's enhanced
run is where settings get added, from a materially larger space than the agent has today, so the
honest one-option read costs the user nothing they do not get back. It attests nothing about wiring,
clears no wiring cap, and writes nothing into the user's project.
Every guided run that found an agent does this read - not conditionally, not depending on the
agent's language or on how the card would look without it - and the flag is left off only where the
inventory found no agent at all. Where an agent was found and its settings cannot be read out of it,
name it and say what stopped the read, then offer to be pointed at source that can be read: that
offer changes the opening score, which is what makes it worth asking, and it rides on the one ask in
stage 2 below rather than adding one. Leave `--agent-knobs` off in that case: the flag says what a
read found, and no read completed, so passing an empty one reports a finding about the customer's
agent that nothing established. That case is the source defeating the read, never this document
being refused: a rejected document is yours to correct and send again, and dropping the flag instead
tells the user something about their agent that is true only of your own paperwork.
Proceed with what can be varied if nothing comes back. Never ask
for a config-space file here - the paragraph above omits
every one of those found before this run's search, so it cannot answer this. The ceiling left
standing is read by stage 4's cap routing below, which is unchanged. Pass this same reading to every
later re-score in this run, re-reading the agent only where this run created or repaired it: a
re-score that quietly drops the flag reports the agent pillar falling from what the opening read
established to nothing, and that fall reaches the customer as an honest change in their project.
`references/component-creation.md` owns the shape.
The opening score is not skippable, always reports all three pillars, and is the score this run
reports for the project. Show it before any Agent, Dataset, or Evaluation component is created or
repaired; current-run validation evidence may be prepared first as the gate above requires.

Say that the scoring command reads the project and changes nothing of the customer's. Name the
evidence the guided run wrote before it: its row review when rows exist, and both calibration
artifacts when opening calibration ran. A claim of no writes is refuted by one `ls`.
Show its rendered card verbatim,
then explain its score, band, and cap reasons without internal ids. Describe an existing but
unmeasured component as not yet measured. Presentation detail lives in the glossary:
use its readiness-score presentation.

The score grades measured evidence, not declared existence. Report an uncalibrated real evaluator
and an agent without current-run wiring evidence as not yet measured, never as absent. Do not infer
`wired` from declared `knobs`, copy it from a historical document, or write it merely to clear a
cap. Re-establish wiring on the current agent before the enhanced search as stage 7 requires; the
zero-anchor opening may proceed through the same absent-evidence cap while local setup continues.
Read-only preflight and readiness runs are static local validation; they authorize no project
write.

**Opening invocation contract.** When the opening call supplies measured evidence - its
`--preflight` JSON and any applicable `--agent-knobs` and
`--row-review` documents - do **not** also pass `readiness.py --agent`, `--dataset`, or
`--evaluation`. Those three flags are fallback declarations for material the score was not given;
adding them beside measurements supplies two incompatible accounts of the same project, so
`readiness.py` rejects the invocation. The opening readiness argv therefore contains the measured
inputs plus the run-scoped `--task-kind`, `--evaluator-method`, and component-origin
flags that the rules above establish. Before running it, check the row-review mechanically against its documented
shape: every reviewed row has `id`, normalized `origin`, `verdict`, one-sentence `note`, and the
same explicit `in_run` boolean when membership is settled. Do not rely on a successful exit to
prove an omitted review field was intentionally omitted.

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
2. Say plainly what is lacking, in the customer's own three words - dataset, agent, evaluation
   method - and that the coding assistant will create each after the user chooses the task, and
   that synthetic results demonstrate workflow rather than production performance. Where the
   inventory found request/response logs or accepted traces, say they are built from those: "I
   will create the dataset, the evaluation method and the agent from your logs" is a different
   offer from "I will write them", and the second undersells material they already have. Carry the
   four things "One ask for every gap" below requires - including the `I have it` answer and its
   path - on this same question, so it stays one and not two.
3. Ask exactly one task-intent question: **"What should the walkthrough agent do?"** Offer at
   most three short choices, each put as the job itself - "pull the total and the date out of a
   receipt" - never as a category name like extraction or classification, and recommend a
   structured, deterministically scoreable task. This question is the last thing in the message.
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
Do not show external links. Do not ask the user to solve missing setup pieces - the ask below fills
them and offers to use theirs, which is the opposite of delegating them. Refresh only
changed evidence after creation; retain unresolved `❗` lines and add the new substitutes
instead of replacing the initial board with a green one.

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

Whatever the inventory did not find - agent, dataset, evaluation method, one of them or all three -
or found and could not read out of, which the opening gate above defers here for the same reason -
the user hears it once, in one question, riding on the board above rather than arriving as its own
turn, and before anything is built. Never one question per component: a project with no examples and no
way to grade them has a single gap in it, and asking twice asks the same person to consent to the
same substitution twice. When a quality advisory fires in the same turn, fold it in - a gap and a
weakness are one decision about what this run will measure. That question carries four things:

1. What the inventory did not find, named plainly and all of it at once - what was searched for and
   not seen, never what the project does not have - and, on the same line, what it found too little
   of to compare on. Name the pieces themselves, in the words the customer uses for them: dataset,
   agent, evaluation method.
2. That this run can build each missing piece from what exists. Offer a dataset top-up only when
   its cap has `asks: true`; otherwise name the limitation, but do not offer rows.
3. What that costs, in terms the score already uses: what this run writes stays a substitute, never
   becomes real-world readiness, examples it writes carry the generated-data ceiling and cannot
   present as strong however good the rest is, and no configuration from the result may be promoted.
4. One answer where something is missing: proceed. Where it is only short, keeping what they
   brought is a second. `I have it` with a path is never counted among them.

Then stop and wait, and ask nothing else here; what this run writes is shown at the pre-spend
approval in stage 6, which is the other checkpoint and the last moment changing it is free. It
closes the message: the board and the cost sit above it, and no summary of it sits above them.
A path given here names material that was in the project all along, so re-run the opening gate over it and
read that as the opening score; the record waits for this answer in any gap run, for the reason the
zero-anchor gate above already gives for its own.
When nothing anchors task intent at all this is not a second question - the zero-anchor gate above
asks one and carries these four things on it. The answer covers absence and shortfall, never a
defect; broken
material keeps every gate stage 4 already puts on it. `references/component-creation.md` owns the
wording, what a supplied path is checked for, and where each way of not getting one lands.

When a dataset below this run's **28** has an asking cap, its top-up rides on that same question
and never as a second one: a gap and a shortfall are one decision about what this run will measure.
The offer is bounded and its bound is spoken - an offer to add examples with no number on it reads
as an offer to generate without end. Agreeing changes what the dataset is, never what it earns:
rows this run writes score as the generated rows they are, which on a short dataset is most of it,
so say before they answer that accepting lowers the ceiling.
`references/component-creation.md` owns how each size is put, what that sentence says and where the
offer ends; the dataset reference owns the split behind the total, how the rows are drawn and the
ceiling that follows.

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

1. Define or revalidate the calibration case matrix and thresholds from the task semantics, then record the
   assistant-performed semantic-coverage review in `references/evaluation-and-dataset.md`, grounded
   in the strongest available product evidence. Record its evidence, materially distinct paths,
   mode/threshold rationale, gaps, and `sufficient` or `ambiguous` verdict. Use the outcome-class
   table in `references/run-safety.md` and name each case's classes in `outcome_classes`.

   Resolve any `permutation_question` from inspected evidence; ask before paid work only if the
   competing order semantics remain unresolved.
   If inspection identifies an execution evaluator, do not use a permutation probe to turn a
   parse/runtime result into evidence. The scope stop below ends this first-run guide before any
   evaluator execution.
2. If unresolved product-grading ambiguity would materially change which output is correct or how
   candidate configurations rank, ask exactly one product-grading question, explain the affected
   decision, then stop and wait. Otherwise record that no ambiguity remains and do not add a generic
   review pause. Clarification never authorizes changing real labels, examples, answers, or policy;
   follow `references/evaluation-and-dataset.md` for degenerate-row bounds and gold-repair rules.
3. Run the bundled static preflight with `--defer-missing-sdk` and a single `--dataset` JSONL path
   holding every row of both splits, each carrying its `split` label, so local structure and
   quality problems are checked without importing user modules. That combined file is scoring
   evidence; `references/evaluation-and-dataset.md` owns the files the run writes from it. Omit optional model-pricing checks in this
   standard-library-only pass. It checks canonical `input`/`output` fields by default. For another
   schema, pass explicit `--input-field` and `--expected-field` dot paths selected from the user's
   data and task; do not infer SDK aliases. Apply the run-scoped evaluator-method rule above: if
   the evaluator was created or changed, resolve its method again, then pass that same current
   `--evaluator-method` value to this preflight and the paired readiness invocation in step 5 (or
   omit it from both when no method exists). This heuristic check does not assert SDK compatibility.
4. Before calibration, apply `references/run-safety.md`'s execution-evaluator scope gate. If the
   resolved evaluator call path identifies code/SQL execution, record the `containment` stop and
   end this guide before calibration, environment setup, credentials, provider calls, or paid work.
   Otherwise, run deterministic calibration only after a `sufficient`
   semantic-coverage verdict. Its path must be fully inspected, must not execute
   candidate-generated code or SQL, and must be local-only and
   side-effect-free, and runs in the credential-stripped calibration subprocess. When the opening
   gate already produced that fresh result, reuse it here unless the evaluator, cases, semantic
   evidence, or execution path changed; do not execute the same calibration twice merely because
   the flow reached this step. Run here anything the opening gate truthfully deferred and can now
   establish.
5. Re-run `scripts/readiness.py` on the fresh preflight JSON plus any applicable calibration
   result. Omit every config-space file found before this run's enhanced search here just as at the
   opening gate. This score is required even when a low score or cap is expected. Record its gate
   result in `traigent-runs/run-plan.md`. If calibration was deferred for an installed local
   dependency, record the preflight-only result now and re-run the score immediately after that
   calibration.

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
the failed gate. Continuing unchanged is permitted only as an explicitly labelled workflow
demonstration; `references/evaluation-and-dataset.md` owns when that limitation is stated.

For an invalid evaluator, incompatible schema, corrupted required rows, or unverified call path,
do not run paid optimization against it. Offer two routes: build and revalidate a reversible copy
under `traigent-runs/` - mending what survives and writing what does not, which is one action and
not two - or pause for a user-authored fix. Say in that same sentence how much of their material
survives, because that is what decides whether the result reads `✅` or reads as a substitute, and it is a fact this
run already established rather than a choice to hand over. Never treat "continue as is" as
permission to optimize against a broken grading signal. Letter the routes from `A` and mark the
build one recommended; close with the unnumbered `I have it` line, which is never a route and always
last. Nothing follows it, and no route carries a decision of its own.
`references/component-creation.md` owns the wording.

`readiness.py` emits these decisions as closed `action_kind` values and one
`recommended_action`: the lowest-ceiling blocking remedy when a cap blocks, otherwise the
lowest-ceiling asking one, otherwise `proceed`.

Route every active dataset cap to the branch this flow already defines, and present the reason
rather than the condition id, in the user's language - machine vocabulary and condition ids stay
internal. Three kinds, not two. A route asking for a creation or repair blocks the run, and so does
one asking for a first look at material nothing has read - under either, nothing was measured. A
route that only scopes what the result may claim lets the run proceed wherever there is a result to
scope, and divides again: where the scope leaves a person something to settle, put it once in the
home that owns that question and carry the answer to the pre-spend approval in stage 6; where it
leaves nothing to do, the ceiling is advisory and there is no repair to route. Route by the reason,
never by the kind - the agent's own no-varying-knobs condition still reads both ways, and its
paragraph below carries both halves:

- `dataset-absent` - enter the creation dependency matrix, and put both ways out on the one ask:
  point this run at the dataset they already have, or have it derive one from whatever the project
  does hold - the agent, the evaluation method, logs.
- `dataset-shape-unrecognised` - no row matched the shape the score read the file with, which is not
  a verdict on the data: do not enter the creation dependency matrix or call it invalid. Read and
  re-map it per the dataset reference, then re-score; repair, then create, only if mapping fails.
- `dataset-no-expected-outputs` - keep it `limited` and `❗`; recommend repairing a labelled working
  copy, with approval for judgment-dependent labels. Do not use unchanged input-only data with a
  reference-requiring evaluator; disclose a reference-free method's absent independent answer key.
- `dataset-integrity-fail` - treat it as invalid; repair and revalidate a working copy or use a
  labeled substitute.
- `dataset-tune-holdout-overlap` - repair a disjoint split and make no generalization claim yet.
- `dataset-split-by-task-family` - disjoint and drawn in the wrong place: every recurring kind of
  input sits on one side, so the held-out score measures transfer to unseen work rather than the
  task that was tuned. Inferred from a leading form, so ask before repairing - name the two kinds in
  the user's own words and take their answer on the one ask. One task, and the run continues with
  the ceiling standing; two, and redraw the split so each kind appears on both sides. Do not enter
  the creation dependency matrix and do not ask for more data.
- `dataset-fully-synthetic` - apply the walkthrough labeling rules; never claim production readiness.
- `dataset-mostly-synthetic` - apply those rules, name the split out loud, and scope the claim.
- `dataset-undeclared-provenance`, `dataset-mostly-undeclared` - say the assumption and both card
  scores when shown, offer declaring the real source rather than new data, and put that offer at the
  pre-spend approval; meanwhile apply the rules above. The rows may be real and only this run cannot
  tell, so it bounds the claim exactly as a declared-generated corpus does and holds nothing up.
- `dataset-generated-answer-key` - require that a person reviews a sample of the answers before a
  correctness claim; until then the score measures model agreement.
- `dataset-mostly-generated-answer-key` - the same review, on the model-written answers only, and
  say how many of the expected answers they are; the run proceeds meanwhile.
- `dataset-unsound-expected-outputs` - bounded, not stopped: put the flagged rows to the user as one
  approval-gated question and take the answer, per "A `no` is never a silent edit" in
  `references/evaluation-and-dataset.md`.
- `dataset-tuning-split-empty` - the rows are fine and the split is not: no row on the side the
  search compares on can be scored. Repair the split as `dataset-tune-holdout-overlap` above is
  repaired; do not enter the creation dependency matrix and do not ask for more data.
- `dataset-below-measurable-size` - more comparable examples is what lifts this; until then call
  rankings exploratory, not stable comparisons. The run is worth making, so where the card asks,
  carry the top-up on the one ask rather than sending anyone away for data.
- `dataset-coarse-resolution` - more comparable examples is what lifts this too, and the same
  bounded offer carries it wherever the card asks; after paired outputs exist, report paired outcome counts and justified
  uncertainty, calling a small or flat difference directional or inconclusive.

Evaluator and agent caps route through the rules that already own them: `evaluator-unresolved` (a
connected file with no honestly declarable method) and `evaluator-invalid` route through the
invalid-evaluator paragraph above - inspect, repair, or replace; `evaluator-absent` routes through
the absent-evidence reading in the opening readiness gate and the creation dependency matrix -
create or select. `evaluator-generated` and `agent-generated` route through the walkthrough labeling
rules and nothing else - carry the substitute's provenance into the words as well as the card, and say the
result measures the substitute rather than their product. Neither is a repair: this run created the
component on purpose, the run continues, and what the ceiling refuses is the claim, not the work.
`evaluator-unvalidated` routes through the opening/stage-4 calibration gate above: measure it once
when that gate establishes eligibility, or keep the ceiling and name the concrete deferral. It is
an evidence boundary, not a repair finding.
`evaluator-timeout` is neither a repair to route nor the invalid-evaluator
paragraph: calibration ran and did not finish, which establishes nothing about this evaluator and
does not make it invalid - slow and broken look identical from here. Settle it while gaps are still
being filled, before the baseline spends anything: before calibration starts, say what it does and
how long it may take, and on a timeout ask the one five-option question in
`references/evaluation-and-dataset.md` rather than declaring the evaluator broken or carrying the
wait into a paid run. Bounding what one scoring call costs is one option inside that question, not
the route. Name any avoidable cause of the slowness in the readiness summary and again at the
close if it was not fixed. After any repair or substitute creation, re-run the affected checks, the
applicable calibration, and the score, then record that gate result without overwriting the opening
one.

`agent-no-varying-knobs` blocks when a settings document or a statically checked source read finds
no usable dimension. Mark one setting with a second value or expose a direct request parameter. It
is advisory only with no evidence or source candidates whose references could not be verified.
Before either paid grid, the local request-difference proof—not the opening score—must establish
every selected direct dimension. Report stops/zero trials when that proof cannot do so.

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
2. Resolve and prepare the dedicated first-run environment `.venv-traigent` through
   `references/run-safety.md`, naming its absolute path before touching it. Preserve every existing
   environment. The reference owns creation, recovery, and activation mechanics; never fall back
   to a shared or dependent environment.
3. Install the exact declared dependencies under the narrow authorization above: use the project's
   compatible exact declarations, or otherwise the exact pins in
   `assets/requirements-first-run.txt`. Never use an unversioned `pip install traigent`.
   Keep this unattended step foregrounded, explain the wait, and do not delegate it; the safety
   reference owns the rationale. Then re-run `scripts/preflight.py` in that environment without
   `--defer-missing-sdk`; `sdk-version: PASS` is required before continuing. On `FAIL`, preserve
   that environment, report its path and the concrete failure, and stop. Recreate it only on the
   user's explicit request; nothing else catches a silent or partial install.
4. Verify capabilities and public signatures from the installed SDK. Use its public dataset
   loader/validator, decorator, and evaluation models; use a public no-execution contract validator
   when available, otherwise finish with safe mock plumbing and do not claim exhaustive static
   compatibility. Never recreate SDK binding fallbacks. Use resolved dataset paths for the pinned
   SDK's tracked nested-relative defect.
5. Run calibration deferred solely for a local installed dependency. Then run a fresh-process
   Traigent mock plumbing check only when every model call and external side effect is intercepted;
   exit it and never reuse that process for a real run.
6. After all applicable free checks, create or minimally update `.env` through
   `references/run-safety.md`'s ordered credential handoff, which selects the file: add only a
   genuinely missing selected-provider key, and stop once for only that secret locally. Do not
   request or route the Traigent key before the stage-7 baseline checkpoint.

Before baseline approval, locally prove request differences. For an inspected customer baseline, set
`BASELINE_IS_USER_OWNED = True` and make `WIRED_KNOBS` exactly match its paid enhanced dimensions;
preserve conditional rows/dimensions; stop for approved per-model validation. Re-prove before each
paid phase.

Before baseline approval, explain only its provider recipients using `references/run-safety.md`:
the selected provider receives normal model-call content; OpenRouter and every allowed upstream
inference provider/route may receive it. Connected synchronization waits until after the baseline checkpoint.

### 6. Approve and run the baseline

Scope the run before pricing it. When the dataset carries more than 100 usable rows, select the
bounded first-run subset described in `references/evaluation-and-dataset.md` - 18 rows by default, at
least four from each difficulty band, drawn within each split rather than across it - and estimate
runtime and spend from that subset, not from the full row count.

Select only after scoring the full dataset and before pricing the run. Record the chosen row ids,
report subset and full sizes, and state that the small first-run sample limits the claim.

Do not ask the user to choose cost, retries, or timeout settings during discovery or setup, and do
not repeat a provider choice already resolved in stage 5.

Use the baseline checklist in `references/run-safety.md` for one concise baseline preview and
approval covering the live provider check, any pre-baseline LLM-judge calibration, and the
preserved baseline or generated twelve-row sweep. Say only that a separately previewed managed run may
follow; do not front-load its algorithm, search space, trial arithmetic, portal features, or insights.

When this run filled a gap for the walkthrough, or an active cap asks rather than blocks, that same
approval also carries the pre-spend card in `references/run-safety.md`: what the gap was and how it
was filled, absolute paths to what was written, the easiest and hardest rows, what the evaluation
method counts as correct, and one proceed-or-fix answer. It is content on the approval that already
stops, never a second pause, and approving the spend is not approving the material.

Immediately before the paid baseline, show a short run card with model ids, each varying knob and
its explicit values, one plain-language note per knob, and the total combination count. The
enhanced card waits until after the baseline checkpoint.

Put the baseline estimate, selected row count and ids, and **30-minute completion target** in the
money approval. Preflight's first-run count is only a proposal; it cannot know the selected rows.
This is an estimate, not a hard wall-clock guarantee. Size the baseline before it starts.

When the SDK exposes trustworthy live progress, report only those values; otherwise report only
observable phase milestones. Never invent progress or quietly drop validation. A timeout with
completed trials yields an honest partial result and a stop-or-bounded-continuation choice; zero
trials requires diagnosis.

If the estimate exceeds `$5.00` or 30 minutes, first recommend a smaller representative slice or
trial target while preserving meaningful difficulty coverage; disclose any
reduction from the twelve-row baseline target. Proceed after one explicit
approval and keep it process-only. Follow `references/run-safety.md` for SDK limits and retries.
Maintain its single
running total across every paid phase, stop before the next estimate exceeds the remainder, and
do not layer another retry loop. Launch every paid process with the three approved figures that
reference names, so what the user approved is what the code enforces; a phase missing any one of
them stops before spending rather than falling back to a limit nobody approved.

After the approved live provider probe, derive internal time bounds from observed latency and the
baseline work. If they no longer fit the approval, offer a smaller run or quote the additional
time/cost; do not ask the user to select implementation timeouts.

### 7. Run the honest comparison

Use the same tuning slice, evaluator, objectives, and agent call path for both measurements:

1. **Baseline** - preserve the user's existing baseline exactly, including its original row count;
   never pad it. Only when it is missing, prepare the credible twelve-configuration fixed sweep in
   `references/run-safety.md`, including the initial configuration.
2. **Enhanced Traigent optimization** - keep every baseline value and model, add only meaningful
   controls the agent consumes, and test up to 12 configurations (`references/sdk-execution.md`
   explains that cap and the shortfall it obliges). Add only direct request parameters the
   pre-approval proof establishes for every selected model and tuning input; any new model is a
   separately disclosed experiment. The reference owns the
   generated-space mechanics that make the
   comparison attributable to the managed search rather than a quiet model upgrade. This is the
   last run, so the controls that carry cost are varied here or not at all - which the shared model
   list above already does for a prepared baseline, and which a user-owned single-model baseline
   reaches through that same separate disclosure, never through another round.

Report each measurement as a **Pareto frontier over accuracy and cost**, never as a single cheaper
answer: a frontier carries the same score for less money and a higher score for the same money, and
asserts neither. It costs nothing - it is arithmetic over trials already paid for. Never show a
frontier point that scored below the configuration the user is already running.
`references/run-safety.md` owns what a frontier may claim and the wording of its two outcomes;
`references/sdk-execution.md` owns the read itself.

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
- If any component is a substitute, put the provenance limitation before the numbers.
- State what ran: a local fixed grid, not Traigent choosing the trials.
- Show the best configuration, the primary tuning metric by its actual name, cost, latency, and
  executed and failed trial counts. Report cost or latency as `not measured` when the provider or
  SDK does not supply it.
- Show this grid's own accuracy-cost frontier beside the winner, read from the trials it just
  paid for. A fixed grid is a small frontier, and it is still the user's own measured evidence
  rather than a note about whether the two happen to trade off.
- Explain each baseline knob in one plain-language note.
- State that no generalization or production-improvement claim exists yet and that this phase
  created no portal experiment.
- Do not disclose the held-out score before stage 8.

This checkpoint is a valid place to stop, and saying so without saying what stopping costs is not
a neutral presentation. A baseline-only run has measured one fixed grid on the user's own machine:
they have not seen Traigent choose a trial, have no portal experiment or link, no recommendation
across both runs, and no held-out score - the four things stages 4 and 5 exist to show. Name those
when the baseline leaves headroom, and recommend continuing. If the user stops anyway, preserve the
local result and report the run as baseline-only, not as a completed Traigent optimization.

Now check whether the dataset and evaluator distinguish configurations. If not, stop before the search
and recommend the evidenced repair before any connected preview. If the baseline is nearly perfect with no
informative failures, report little or no measured quality or cost headroom and recommend harder realistic
cases; a ceiling effect remains a hypothesis. That finding does not itself block a healthy customer who
explicitly wants one verified portal/enhanced comparison: offer the connected step as an optional,
no-lift-possible verification run, never as an expected gain. If they decline it, preserve and report the
baseline-only result. An accuracy-only search with walkthrough material requires a workflow-demonstration
label. A cost objective may proceed at equal accuracy only when materially lower cost remains
possible; report any gain as cost and still flag weak evidence.

Preview the connected step with the final reply-ready line and approval rules in
`references/run-safety.md`. Its explicit approval remains required before its key, probe, sync, or calls.

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
handoff and have the user enter credentials locally, never in chat. It is the same file the
baseline used, and that reference performs the handoff again there for `TRAIGENT_API_KEY=`; follow
it for which address each account state gets, and the two 10-day windows: the access code, then
portal access.

Once the key is present, run the zero-LLM portal probe. Then feature-detect a public exact sync id
and follow `references/sdk-execution.md` for its capability-gated exact-session sync. Without a
supported id, keep the baseline local; never inspect private storage or use `--all`. Run the
enhanced optimization connected, require its own verified portal link, and report a direct link for
every persisted run without implying it covers a local-only baseline.

Once the enhanced search returns, select the configuration this run recommends on the **tuning**
scores across both paid measurements - never on the held-out rows, which arbitrate nothing - and
score only that one against the ten held-out rows;
`references/evaluation-and-dataset.md` owns the rest.

Do not run an offline baseline and then pay to repeat it merely to populate the portal. Do not ask
the user to choose trial counts or knobs; select them from the inspected agent and include their
calls in the connected-stage approval.
Every knob must change real behavior. Preserve customer values exactly. Generated `reflect` uses
`off`/`on` because the pinned cloud session rejects bools; never recode a customer boolean. Before
baseline approval, refuse a final space the pinned SDK rejects and stop. The enhanced space must be materially larger than its trial cap so Traigent is choosing what to test rather than
replaying the same tiny grid - and no larger than that cap can explore: aim at four to six varying
knobs, never a customer's whole declared set. `references/run-safety.md` owns that arithmetic and
the baseline evidence that picks which.

Before the enhanced search, prove final wrapper/spaces in its fresh process. Re-prove after a change;
historical `wired` is never proof. Follow that reference's freeze/remove/persist lifecycle.
Save
`traigent-runs/config-space.json` only after this search returns nonzero trials, from the exact
space it received, and use only that current-run document for the closing `--config-space` score.

If provider, Traigent backend, or portal connectivity is unavailable, stop with the concrete
failure and one recommended recovery. Never fall back automatically to mock or synthetic results,
and never present offline checks as a completed optimization. Resume the connected path after the
failure is resolved.

Do not fabricate configurations to hit a row count. A preserved one-row user baseline is an honest
one-row before and stays unchanged. An assistant-prepared walkthrough must not proceed with a one-
row baseline; generate enough real controls for the twelve-configuration default.

Do not require a third optimization pass. Recommend another iteration only after the first result
reveals a specific, worthwhile hypothesis.

### 8. Verify and report

Before saying the run succeeded, apply every post-run verification in
`references/run-safety.md`. Also verify that the baseline was preserved exactly or the generated
twelve-row default (including its initial configuration) ran, subject only to an approved disclosed
reduction; the enhanced run used real controls and either produced at least 10 of its 12 permitted
trials, matched an explicitly approved and disclosed reduced target, or reports a concrete
stop/failure reason; and a
best configuration and non-degenerate measures exist. Verify the held-out score belongs to the one
configuration this run recommends, chosen on the tuning scores, and that no other candidate was
scored on those rows. Report truncation and persistence failures, require the portal
probe to have stayed green, and verify each portal link before claiming visibility.

Lead with a layered summary whose opening layers are enough for a quick read and whose details are
auditable:

1. **Outcome** - baseline versus enhanced result and whether a recommendation is supported.
2. **What the evidence establishes** - baseline tuning result, enhanced tuning result, and actual
   persisted runs.
3. **Current state and limits** - component provenance, exclusions, uncertainty, incomplete
   phases, and any small-sample held-out gap.
4. **Next action** - one action the recorded opening state earns.
5. **Details** - configurations, objectives, trials, failures, cost, stop reason, artifacts, and
   verified links.

Include:

- Best baseline configuration versus best enhanced configuration on the tuning set.
- Each run's accuracy-cost frontier, in the details layer. One recommendation still leads; a
  frontier put where the recommendation belongs is the menu this stage already refuses.
- The recommended configuration's held-out score and small-sample note, shown here first.
- Cost, the configurations tested out of the space's total, failures, stop reason, and direct
  portal links.
- Which components were `✅` real and which were walkthrough substitutes.
- What this run created or repaired, and what that costs the claim: examples it wrote are weaker
  evidence than examples collected from the product, and an evaluation method it wrote is a
  starting point rather than the product's grading policy - one a person may want to move in
  either direction, so it rewards what their product values.
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

Do not close on a second number. Re-run `scripts/readiness.py` on the post-run evidence for the one
reading nothing earlier could take - the agent pillar, scored from the space the enhanced search
actually received - passing the current run's `--config-space traigent-runs/config-space.json` only
when that search emitted it; otherwise score the agent from absent evidence. The opening and stage-4
scores withhold every config-space document by construction, so this is the run's only measurement
of the space the customer paid to search. Its dataset and evaluation caps rank nothing and settle
nothing about what is still open: a gap this run filled with a substitute reads exactly like one the
customer closed themselves, because on disk the evidence is the same either way. Never show that
score or set it beside the opening one.

Two things read that call. Its agent cap is a finding about the search that just ran: a document
that varies nothing means the paid run compared one configuration, so the card blocks and the close
reports it beside the search's own outcome. And this is the only place anything reads
`traigent-runs/config-space.json`, so a file this run wrote and cannot itself parse is refused here
by name rather than left in the customer's project for them to find. `references/run-safety.md`
owns how that card reads after a stopped, failed, or zero-trial search. Leave the user knowing which
remaining gap to close first.

Feature-detect local audit and connected insight capabilities. Report only fields actually
returned, attribute each claim to its artifact, and otherwise say no verified local artifact was
available. Surface deeper signals only when a verified run-scoped platform artifact actually
returned them. Never fill the DEEPER-INSIGHTS template from expectation, infer labels from a flat
score, promise a numeric dataset-quality score, or imply the platform graded an unrun dataset;
over substitutes, every insight describes only the walkthrough.

Close by saying what a further run would be worth. Name the gaps still open and what each is now
costing; use the user's own measured evidence rather than encouragement. Say what this walkthrough
cannot close. Then give the one next action the **recorded opening state** earns: rank the opening
score's caps and this run's own recorded limits, and name its value. A gap this run filled with a
substitute is not cleared - it is filled provisionally, so it stays on this list and the action is
what closing it properly takes:

- Generated or mostly generated data, or an evaluation method this run wrote - one move that closes
  it and one worth making anyway, in this order. **Best:** collect or export real examples of the
  same task, and build the evaluation method from them and from what their expected results actually
  are. This is the only one of the two that lifts the ceiling. **Otherwise:** keep what this run
  generated and have a person read and approve it - the rows and their expected
  answers, and the generated method too, whose grading logic has to match what the agent is really
  scored on and what its expected result is. Say plainly that this one does not lift the ceiling:
  the score reads where the rows came from, and a person approving generated rows leaves them
  generated. It is still worth doing, and it is not the way out. This is the gap that ceilings the
  score no matter how good everything else is, so it is first whenever it applies.
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

Then the forward half, which is not a gap in anything. The run-scope statement already recorded the
three bounds this walkthrough chose - rows scored, configurations tested, controls varied - so name
whichever bound this run hardest and what lifting it would let the user do: more of the agent's
controls, the whole dataset instead of the slice, a space wider than a first look needs. It is a
clause on the recommendation above, not a second one, and it names an action they can take, never a
result a wider run would find.

A menu offered *instead of* a recommendation is the same as no recommendation; put extras later.

End with the final reply-ready line in `references/run-safety.md`; `continue` never bypasses
approval.

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

- The run record's stage-status block shows every stage done or skipped with its reason.
- The starting state and provenance of all three components are recorded.
- Material quality limitations were explained with evidence and a repair/continue/pause choice.
- Any repaired component was revalidated before its status changed.
- The opening readiness score was computed before any Agent, Dataset, or Evaluation component was
  created or repaired, recorded with its band
  and caps, and is the only readiness number the report gives.
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
- Each reported frontier carried measured costs, a score claim the paired counts support, and no
  point below the floor.
- Baseline and optimization used the same tuning data and evaluator.
- Result claims match the provenance and validation evidence.
- The user received a concise result, limitations, artifacts, and portal links that were
  actually verified.
