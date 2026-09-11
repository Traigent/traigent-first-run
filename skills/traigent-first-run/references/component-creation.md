# Component Creation

Use this reference after the initial project inspection. Inventory Agent, Dataset, and Evaluation
before creating any of them.

## Contents

1. Evidence and provenance
2. The one ask, and the path that answers it
3. Dependency matrix
4. Agent creation
5. Reading the agent for the opening score
6. Compatibility contract
7. Readiness transitions

## Evidence and provenance

Classify each component as:

- `real` - project/customer material that exists independently of the walkthrough.
- `limited` - real material is technically usable for a walkthrough, but concrete evidence shows
  it cannot yet support a credible optimization claim.
- `demo` - material invented to demonstrate the workflow.
- `missing` - no usable component found.
- `invalid` - material exists but fails compatibility or validation.

Wrapping a real function with `@traigent.optimize` does not make it synthetic. Converting a real
dataset to JSONL does not make it synthetic. Replacing the logic, labels, examples, or grading
policy with invented material does.

Record in `traigent-runs/run-plan.md`:

- Source path or stable identifier, provenance classification, any generated wrapper/copy,
  validation evidence, and the unresolved real-world gap.

Resolve `limited` and `invalid` candidates before using the matrix. For `limited`, recommend
repairing a working copy and revalidating it; if the user explicitly continues unchanged, preserve
it as the real anchor in the matching `real` row but keep its readiness state `❗`. For `invalid`,
repair it successfully or treat it as missing and create a clearly labeled substitute. A
broken evaluator or incompatible dataset is not safe to continue unchanged.

## The one ask, and the path that answers it

SKILL.md owns when the single question is asked. This section owns its contents, wording, and
the handling of a supplied path.

### The gap-question contract

Whatever the inventory did not find - agent, dataset, evaluation method, one of them or all three -
or found and could not read out of, which the opening gate in section 1 of SKILL.md defers here for the same reason -
the user hears it once, in one question, riding on the board above rather than arriving as its own
turn, and before anything is built. Never one question per component. Fold any quality advisory
into the same decision. That question carries five things:

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
5. **What they want optimized**, in one line, where this run cannot already tell. The SDK optimizes
   for their chosen objective. Read it off their evaluator where the evaluator answers it - a
   scorer comparing an answer to an expected one is optimizing correctness and needs no question -
   and ask only where it does not. Where they name nothing, proceed on accuracy and cost **and say that in those
   words**, so a default nobody chose is not mistaken for a choice somebody made.
   `references/evaluation-and-dataset.md` owns what the answer becomes.
Then stop and wait, and ask nothing else here; what this run writes is shown at the pre-spend
approval in section 6, the other checkpoint. The question closes the message: the board and the
cost sit above it, and no summary of it sits above them.
A path given here names material that was in the project all along, so re-run the opening gate over it and
read that as the opening score; the record waits for this answer in any gap run, for the reason the
zero-anchor gate below already gives for its own.
When nothing anchors task intent at all this is not a second question - the zero-anchor gate below
asks one and carries these five things on it. The answer covers absence and shortfall, never a
defect; broken
material keeps every gate section 4 already puts on it. The wording and supplied-path checks below own each outcome.

When a dataset below this run's **28** has an asking cap, its top-up rides on that same question
and never as a second one.
State the bound before the answer. Agreeing changes what the dataset is, never what it earns:
generated rows retain their provenance, so say before they answer that accepting lowers the ceiling.
The shortfall procedure below owns how each size is put, what that sentence says and where the
offer ends; the dataset reference owns the split behind the total, how the rows are drawn and the
ceiling that follows.

### When nothing anchors task intent

When the read-only inventory finds no agent *that performs an identifiable task*, and no dataset,
evaluation, product documentation, tests, fixtures, or other component that anchors task intent,
follow this exact order:

Judge that by what the component does, not by whether the file exists. An agent that returns a
constant, echoes its input, or is a fixture or placeholder counts as **missing** for anchoring
intent, however importable it is, under Evidence and provenance above.

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
   five things "The gap-question contract" above requires - including the `I have it` answer and its
   path - on this same question, so it stays one and not two.
3. Ask exactly one task-intent question: **"What should the walkthrough agent do?"** Offer at
   most three short choices, each put as the job itself - "pull the total and the date out of a
   receipt" - never as a category name like extraction or classification. Write every choice in
   the customer's own words. Avoid unexplained category vocabulary: metric, time range, grouping, entity, intent, schema, or
   canonical form; where their material has no word for a thing, say the thing plainly. Then
   recommend a structured, deterministically scoreable task, and in that same sentence name what
   in THEIR material makes it the one to pick - "it is what your logs already show, and it grades
   deterministically". This question is the last thing in the message. Example for a project
   holding log lines:

   > **A.** Turn a plain-English question about your singers database into a SQL query
   > *(recommended - it is what your logs already show, and it grades deterministically)*

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

### Wording the offer

Resolve the discovered agent's execution boundary before composing this ask. If the real agent is
not Python, keep Agent `❗` unless a thin Python adapter calls the unchanged real behavior and can
be evaluated safely. Fold any adapter/substitute choice into this same ask, keeping the selected
agent and task anchored. A generated Python walkthrough agent is a substitute; it does not mean
the non-Python production agent was optimized. Subprocess, HTTP, and raw provider calls are not
intercepted automatically by Traigent mock mode. Source inspection alone does not establish that
an agent runs; say what was actually inspected or executed.

Say it in their words, naming only what this run looked for and did not find - and name the pieces
themselves rather than the situation: "here is what is lacking: dataset, agent, evaluation method"
is a sentence a customer can act on, where "the inventory is incomplete" is not.

> I found your agent's source. Searching outward from it, I did not find any set of examples to
> score it on, or anything that says what a right answer looks like - they may well exist somewhere
> I did not look. I can write both from the agent itself: examples that exercise what it actually
> does, and a grading method to match. Examples I write are weaker evidence than examples out of
> your product: the score carries the generated-data ceiling because of it, so this run can show the
> workflow working and cannot tell you how your product performs.
>
> Shall I go ahead? Or reply `I have it` with a path - `agent: <path>`, `dataset: <path>`,
> `evaluation: <path>` - and I will use yours.

Never say the material does not exist: it may live outside the inspected project directory.
Say what was not found and offer `I have it` with a path.

### What the ask offers, and the opening that says what they are choosing between

The gap-question contract owns the choices. Adapt the opening sentence to the anchor discovered;
do not offer the user a choice between starting states the inventory already settled.

Name the anchor and what comes off it. `math_calc` that takes a question and returns a number is a
grader and a set of arithmetic examples; a retrieval agent over a docs folder is questions its own
corpus answers. Recorded request/response logs are a dataset source, not only an artifact to find -
a project with no dataset often has the material for one, and saying so is the difference between
"I will write examples" and "I will build them from your own traffic". The selected agent's name is
the last anchor to fall: an agent that echoes its input anchors nothing, and that case is the
matrix's all-missing row, which asks what the walkthrough should do rather than guessing it.

Match the cost sentence to how much is derived: one generated component around real material and
a trio built from task intent support different claims. Keep the answers last, the cost to one
sentence, and the search to one clause. Explain the generated demonstration accurately without
overselling the alternative of waiting for real material.

### When the gap is a shortfall

Same question, same message, different sentence. What is short here is rows to compare on rather
than a component, so name the count the score actually used, say where the offer stops, and say what
accepting it costs:

> Your dataset is here and I can run on it - 9 rows scored, so a difference between configurations
> can come down to one lucky row. I can add generated examples up to 28 rows in total, the size this
> walkthrough builds. That gives the search more to separate on, and it also makes most of the set
> model-written, which lowers the ceiling on what the result may claim. Continue on the nine, add the
> rest, or reply `I have it` with a path if there are rows I did not find.

The dataset reference owns the split and provenance arithmetic behind this offer.

Match the sentence to which ceiling the card actually raised rather than to a row count of your own.
The wiring-check ceiling is the harder finding, and its sentence is the one above; the
small-comparison-set ceiling is the softer, and its offer is put as a closer fit to real-world
variety rather than a must-have, with continuing as is named first. The total goes in the sentence
either way, as it does above. When the card stops asking there is nothing to offer, and a ceiling
left standing over it is not a request. None of this applies while the card is blocked on an empty
tuning split: the rows are there, the split is what is wrong, and more rows answer nothing.

### When a component is present but unusable

The section above is for material this run could not find. This one is for material it found and
cannot use: an evaluator that scores every answer the same, an agent that echoes its input instead
of attempting the task, a schema that does not parse. Name the user's own file where you say this,
by the path the inventory recorded; the shapes below are the situation, not the filenames. What the distinction changes is what a build YIELDS, not how many answers the ask carries. Material
that exists can be mended, so some of the customer's own work can survive into the result - and how
much survives is a fact this run established when it read the files, not a question for them.

**So the answers stay two here as well, for the same reason they stay two above.** Mending what
survives and writing what does not is one action: the assistant opens their file either way, keeps
whatever holds up, and supplies the rest. Splitting that into "repair" and "write a stand-in" offers
a choice of method for identical work, and when nothing survives - an echo stub has no call path to
mend, a scorer returning one number has no rubric to keep - the two produce the same artifact, in
the same place, described in the same words. That is the situation-not-an-action mistake the section above
refuses by name, and a reader who cannot find the difference is right that there is none.

This is why `references/evaluation-and-dataset.md` offers three for a *material limitation* and this
section offers two, and the two documents agree rather than disagree. A limited component still
executes, so continuing on the customer's own material is an available action and earns its own
route. An unusable one cannot be continued on at all - that is what makes it unusable - so the third
route has nothing to be. The count follows from what the run can actually do with their files, never
from a house style, and a route offered where the action does not exist is the ask asserting a
choice the project cannot honour.

What that sounds like, when the agent and the evaluator are both unusable and the dataset is real:

> Your dataset is real and I can run on it. The agent here echoes its input back rather than
> attempting what your rows describe, and the evaluator it would be graded by returns the same
> score for every answer, so nothing can be graded yet. Two ways forward:
>
> A. **I build both (recommended).** In a reversible copy under `traigent-runs/`, leaving yours
> untouched, and re-validate, then carry on. Neither file has anything to mend - no call path in
> one, no rubric in the other - so what I write is a generated stand-in: not a repair
> of yours, a substitute for it. The run then measures my stand-ins against your 30 rows and your
> task, so it shows the workflow end to end and cannot tell you how your own code performs.
> B. Pause, and I will give you the exact checks a corrected version has to pass. Fix them and the
> same first run measures your code instead of my stand-ins.
>
> Either way this first run is a bounded one - a small sample and a capped number of trials, priced
> before it starts. It is a taste of the workflow, not a full search.
>
> Or reply `I have it` with a path - `agent: <path>`, `dataset: <path>`, `evaluation: <path>` - and
> I will use yours instead. I keep the agent I selected unless you point me elsewhere.

Keep that closing structure literal when this branch applies: render the two lettered routes as
`A.` and `B.`, then the unnumbered `I have it` line last. Do **not** compress them into a
"Shall I go ahead?" yes/no question. A yes/no form hides the pause route, and putting `I have it`
inside the choices turns a path into a third decision. No customer-facing sentence follows the
standing path line.

Three things that sentence has to carry, because a reader supplies each of them wrongly otherwise.
Name the substitute in WORDS. There is no mark for it, deliberately. Say what the run will
actually read: "your rows" is heard as all of them, and above 100 usable rows the paid run takes a
bounded sample, so name the count this project will really use.
And say that the first run is bounded whichever route they pick - a customer choosing to pause and
fix their own components is buying a better-grounded result, not a bigger one, and letting them
believe otherwise sells the pause on a promise this walkthrough does not make.

How much of the result stays about the customer's product belongs in that first route's sentence,
and it is a property of what SURVIVES the build, never of the copy being reversible. Mending one
broken line in a real scorer keeps their ruler, and the result may read `✅`; writing the call path
an echo stub never had keeps nothing but their rows and their task, and it reads as a substitute. Say which of
the two this is, in the sentence itself. A build that promises "your product" over material this run
wrote is the real-world/walkthrough separation broken in the one place the customer is reading - and a build
offered without saying which one it is asks them to spend on an unlabelled result.

The build route carries the recommendation, and carries it visibly. Two routes with nothing marked
is a menu, and this guide already holds that a menu offered instead of a recommendation is the same
as no recommendation - the same reason the dataset reference marks its repair route. It is also the
rule about silence, applied one section over: state it, so silence never has to be interpreted.
Recommend the build route because pausing is always available and needs no push, while the run
stopping is the outcome the walkthrough exists to avoid - and
because the sentence beside it already says what the result will not be able to claim, so the
recommendation cannot oversell.

That rule tells continuing apart from pausing, and it stops there. When more than one route
continues, it has already done its work and something else has to choose between them: the mark
goes to the route that can produce the result the run is being paid for. A route that continues
into a measurement this same card has already reported as unable to answer the question is not the
one to mark, whatever else recommends it - marking it sells a comparison whose own evidence says it
cannot separate the things being compared, and the customer pays for a number that was never going
to arrive. Leaving the customer's material untouched does not settle it either, and the run that
prompted this is why: both routes wrote only to a working copy, so the property they were sorted on
was one they shared. State the choice as the property rather than as the finding of the day -
whichever finding the card raised, the route that clears it is the one marked, and the route that
leaves it standing is still offered, unmarked. The mark moves; it is never withheld from the set.
Withholding it hands back an unmarked pair in the one state where an invented mark does the most
harm. The rule above is unchanged underneath this one: pausing is never the marked route, and
this only narrows which of the continuing ones is. The baseline spend approval is this same rule at a later stage, and
`references/run-safety.md` applies it there by name rather than stating a second one for a reader
to reconcile with this.

The build route is the way to CONTINUE, and its wording has to make that unmistakable. "I build both
… and re-validate, then carry on" continues; "continue once a valid evaluator is available" is the
pause wearing the build route's letter, and a run that offers it has offered no way forward at all.

No route carries a decision of its own. Choosing a route is the answer; a route that also says
"tell me whether to redraw the split" or "say which you would prefer" has asked a second question
inside the first, and the customer cannot take the route without answering it. A blinded run did
exactly this - a build route that also asked whether to redraw the tuning split - and the ask-ends
rule below did not reach it, because the question was not after the standing line but inside route
A. One ask means one decision in the whole message, not one decision after the last one.

A finding the card does not ask on may explain and may recommend; it may not ask. The card's own
`asks` flag decides which it is, and the rule above already says it: when the card stops asking there
is nothing to offer. The answer-key conversation in `references/evaluation-and-dataset.md` is a
question because its cap asks, not an exception to this - and the run that prompted this sentence
attached its question to `dataset-coarse-resolution`, which does not.

So a limitation that changes what their numbers mean, like a split drawn along the task families, is
named and left named. "This is what your held-out number will measure" is the disclosure; "shall I
change it" is a second ask wearing a disclosure's clothes.

`I have it` is never numbered as a route. It answers a different question - where the material is,
rather than what to do about the material here - and it rides on every ask in this document for that
reason. Every ask also ENDS on it: nothing follows the standing line, not a clarifying question, not
a "while you decide", not the advisory restated as its own query. Anything after it is a second
decision, and one was the whole design - a question that is free to answer is still one the customer
has to notice, weigh and answer before the one that matters. Numbering it turns a standing exit into
one option among three, and the pause beside it into another, which is how a way forward and a way
out become a list of ways to stop.

And nothing ANNOUNCES it above the card either - no marker line, no heading, no one-line summary of
the choice at the top. That way round the customer meets the decision before the material that
justifies it and answers a question the evidence has not argued for yet. The ask goes lowermost:
last on screen, and last read.

One narrowing on what may be OFFERED lives outside this document, and is named here so this one is
not read as the whole rule. Where the run has diagnosed a fault it can repair for nothing and the
customer has already paid for the measurement that fault spoiled, SKILL section 7 withholds routes
this document would otherwise word. That menu only; everywhere else a route this document offers
stays offered, and how any route is worded and ordered stays here.

### When a path arrives

Read it before anything is built. Material the user points at is material this run did not create,
so it is scored rather than trusted, and it enters the matrix below as `real`, `limited`, or
`invalid` on that evidence like any other candidate. A dataset that arrives after the opening-gate
calibration ran also re-derives the calibration cases: they were cut from the rows the run had
then, and cases cut from other rows say nothing about these. SKILL section 4 owns the post-repair
rule this serves.

Three ways it does not resolve. Each lands somewhere, and none of them is a retry loop:

- **The path does not exist.** Say so, quoting the path exactly as given - a mistyped path is the
  common case and it is invisible when the message paraphrases it. Ask once more and name the other
  exit in the same breath. A second miss takes that exit: build the substitute, record the path that
  was offered and missed in `traigent-runs/run-plan.md`, and do not ask a third time.
- **The path exists and does not parse.** Not a verdict on their file. Read and re-map it per
  `references/evaluation-and-dataset.md` first, because a fully correct file in an unexpected shape
  produces this exact state. Only when mapping genuinely fails is it a defect rather than a gap:
  classify it `invalid` under "Resolve `limited` and `invalid` candidates" above, which is what keeps
  the later gates on it - nobody consented to being graded by something broken.
- **A path for one of two gaps.** Take it and build the other. The question has already been
  answered: a user who hands over a dataset and says nothing about a grading method has said to
  write the grading method, and asking again is the second question the one ask exists to prevent.

## Dependency matrix

Inspect all three columns first, then follow exactly one row:

| Agent | Dataset | Evaluation | Directed action |
|---|---|---|---|
| real | real | real | Validate compatibility; use all three without replacement. |
| real | real | missing/invalid | Build evaluation from the agent output contract, dataset gold/metadata, and the user's product-success meaning. |
| real | missing/invalid | real | Build a dataset whose inputs exercise the real agent and whose expected outcomes match what the evaluator actually scores. |
| missing/invalid | real | real | Build a thin agent whose signature consumes the dataset input and whose output shape satisfies both the gold contract and evaluator. |
| real | missing/invalid | missing/invalid | Build the dataset from the agent's real inputs and failure modes; build evaluation from the agent plus that dataset. |
| missing/invalid | real | missing/invalid | Build an agent matching the dataset contract; build evaluation from the dataset's expected outcomes and the new agent output. |
| missing/invalid | missing/invalid | real | Build the dataset to exercise scoreable evaluator cases; build the agent to emit the evaluator's required output shape. |
| missing/invalid | missing/invalid | missing/invalid | Ask once what the walkthrough should do, then build one coherent agent/dataset/evaluation trio. |

Never generate components independently and attempt to glue them together afterward.

**Where a row says to build the dataset from the agent, its prompt is a source and not only a
reading.** The two rows above that build a dataset around a real agent send you to its real inputs
and failure modes, and the place a working agent most often already carries real input/expected-
output pairs is the worked examples in its own prompt - pairs its author believed were correct,
written in the product's own vocabulary, for the product's own task. The run has already opened that
file to answer the build checks, so seeding from material the customer actually wrote costs nothing
and is strictly better evidence than inventing rows. Rows seeded that way are still the customer's:
they carry collected provenance where the example is theirs, and the generated ceiling prices only
what this run invented around them.

Two bounds on that. Examples inside prose have no syntactic marker, so recognising them is the
assistant's reading rather than a parse, and a row taken from one is recorded by id like every other
row this run writes or repairs. And where a dataset already exists, this says nothing about whether
the prompt's examples agree with it - a prompt teaching one output shape over a dataset whose
expected answers use another is a real and quiet defect, and it is not settled here.

And build each one to the TASK, never to the artefact it was derived from. The matrix makes the trio
coherent; this is what keeps coherent from becoming circular. An evaluation method built from a
dataset has to score the product's idea of a right answer, so it holds for inputs and expected
outputs this dataset does not contain and separates right from wrong rather than recognising these
particular answers. A dataset built to match an evaluator has to exercise the real task that
evaluator scores, not only the shapes it happens to handle. Say which way the derivation ran, in the
terms `references/run-safety.md` sets out at the close: a ruler drawn around one object measures
nothing else, and the number it gives is optimistic about exactly the material it was drawn around.

## Agent creation

When creating an agent:

1. Prefer a small Python function using the user's selected provider through LiteLLM so mock
   interception and cost accounting are observable.
2. Give it one clear input contract and one clear output contract.
3. Expose at least two meaningful, safe optimization variables. Include the initial values in the
   search space.
4. Keep behavior plausible enough to produce differences, but do not intentionally cripple the
   baseline to manufacture improvement.
5. Put generated code in `traigent-runs/walkthrough_agent.py`.
6. State: "I prepared a temporary agent for this walkthrough." Do not call it a sample agent as if
   it were equivalent to the user's production behavior or imply Traigent created it.

If the user gives no preference, recommend a structured classification or extraction task. It is
easy to score deterministically and demonstrates optimization without paying for an LLM judge. That
is the default for a user with nothing to anchor on, not a list of what this guide supports.
"Classification" and "extraction" are how this document names the shape; they are never how the
customer is offered it. SKILL.md's intent gate owns that wording - the job in their own words, and
a recommendation that names what in their material picked it - and it binds every option written
from this default.

Do not create a story-writing or summarization walkthrough with exact-string grading.

For a non-Python agent, apply the adapter/substitute boundary in "The one ask, and the path that
answers it" above; the choice must already have been disclosed before construction.

## Reading the agent for the opening score

### Opening readiness procedure

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
`generated` for one this run created or relies on in their place - a customer's disclaimer of a
pre-existing file makes it `generated`, however cleanly it reads or calibrates. Decide it yourself,
never ask. Omit a flag only while that component does not exist, and update it the moment this run
creates the component. The dataset takes no such flag: its origin is counted per row from declared
provenance.

Before any component creation or repair, choose from the recorded inventory. If there is exactly
one compatible Python 3.11-3.13 isolated-environment candidate overall and its resolved path is
inside the user's project root, use its resolved interpreter and report `python-version` as
measured. Otherwise resolve an already installed supported interpreter using
[`run-safety.md` § Finding a supported interpreter](run-safety.md#finding-a-supported-interpreter)
as a provisional, no-install bootstrap. Multiple compatible candidates and environments outside
the project wait for section 5; if the sole candidate fails, record why and use that same lookup.
Run bootstrap preflight and readiness with `-I -S`, excluding user-site packages and `PYTHONPATH`.
Name its executable and version; its SDK availability is unmeasured, not evidence that the run
environment is ready. An opening SDK finding from either interpreter never replaces section 5's
required post-install check in the dedicated environment, which remains authoritative for the run.

Run the bundled static preflight with `--defer-missing-sdk` over whatever dataset was discovered,
omitting `--dataset` when none exists. Then include every safe measurement that can finish now in
the first readiness card. When rows carry expected answers, do the row-level sanity check in
`references/evaluation-and-dataset.md` here and pass it as `--row-review` on every opening scoring
call, even when calibration is deferred: it is a free read and no generated row competes with it yet. Read the graded rows, or five brought ones where no split
is settled; it is yours, not the user's. When `existing-traigent-use` reports a declaration, or a Traigent key is
already configured, say so in the readiness turn: Traigent was set up in this project before this
run started, so this may not be a first run, and this run still charges for its own baseline and
search. Never read that as a blocker or a reason to stop - the evidence cannot tell an install apart
from a finished optimization, and the decision is theirs at the section 6 approval, which already
stops. When task intent is anchored and inspection finds a resolved deterministic
evaluator, construct or revalidate its current-run case matrix and semantic-coverage review, then
apply the evaluator-execution scope gate from section 4. If the verdict is `sufficient` and the
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
the evaluation method is actually checked, and the card's recommended action names that outstanding
calibration rather than reading `proceed`. Where the deferral is the evaluator-execution scope gate
rather than a step this run could take, pass `--calibration-scope-refused` so the card discloses the
unmade check instead of asking for the calibration the gate forbids; it moves no number, and it is
the only route where preflight finds no engine. `calibrate_evaluator.py` refuses such an
evaluator itself, naming the file and line, and `references/run-safety.md` records why no
in-process route replaces it. Apply the run-scoped evaluator-method rule above to both
scripts, and apply the run-scoped task-kind rule to readiness only here - narrower than its
destination rule in `references/evaluation-and-dataset.md`, because this gate's calibration takes no
seam flags and so establishes nothing about delivery for section 4 to reuse - and the origin rule with
it.
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
including one left by an earlier guided run, which SKILL.md's historical-document rule already
excludes. Record its provenance; a timestamp, hash, or non-empty `wired` list does not make it
current. A customer-authored file may guide inspection, never score values or wiring. Every
guided run does this, including a zero-anchor run.

After task intent is anchored, place each scoring's evidence document, preflight JSON, and notes
in one fresh readiness directory. Use `traigent-runs/readiness/<YYYYMMDDTHHMMSSZ>/` under the
name-stamp definition in SKILL.md. Never delete these directories or let a later scoring read an
earlier one's evidence. Name the directory beside the card in project-relative form, never an
absolute path. The canonical `traigent-runs/calibration-cases.json` and
`traigent-runs/calibration-results.json` are evaluator-validation evidence owned by
`references/evaluation-and-dataset.md`; name both paths before the card when opening calibration
creates them. Read both the agent's knobs and build when an agent was found.
For a selected top-level Python function, include
`--agent-source-root`, `--selected-agent`, and `--selected-agent-callable`; `source_lines` must show values on its
verified selected-call path. Otherwise leave source credit unestablished and use the advisory route. A thin Python adapter is
walkthrough material, not proof that the original agent was optimized.
Use the executable source-evidence rules below; comments and declarations do not establish values. Read the same source for how the agent is built and
answer all four checks below: whether it carries a prompt and worked examples,
whether anything pins down the
shape of its answer, whether it ends and on what, and whether the tools it declares can be reached.
Answer a check you cannot settle as undetermined with the reason, never as a no - a no says the
agent lacks the thing. Build declarations stay visible but unmeasured; an undetermined check
still needs its reason. Never write a range or an option you did not read; section 7 adds settings.
It attests nothing about wiring, clears no wiring cap, and writes nothing into the user's project.
Every guided run that found an agent does this read - not conditionally, not depending on the
agent's language or on how the card would look without it - and the flag is left off only where the
inventory found no agent at all. Where an agent was found and its settings cannot be read out of it,
name it and say what stopped the read, then offer to be pointed at source that can be read. That
offer changes the opening score and rides on the one ask in SKILL.md section 2 rather than adding one. Leave `--agent-knobs` off in that case: the flag says what a
read found: passing an empty one reports a finding about the customer's agent that nothing established. A document `readiness.py` rejects is yours to correct and send
again, never a reason to drop the flag. Proceed with what can be varied if nothing comes back. Never ask
for a config-space file here; this gate withholds them. The ceiling left
standing is routed through Quality diagnosis and repair choice in the dataset reference. Pass this same reading to every
later re-score of this record, as section 4's post-repair rule states.
The opening score is not skippable, always reports all three pillars, and is the score this run
reports for the project. Show it before any Agent, Dataset, or Evaluation component is created or
repaired; current-run validation evidence may be prepared first as the gate above requires.

Say that the scoring command reads the project and changes nothing of the customer's. Name the
evidence the guided run wrote before it: its row review when rows exist, and both calibration
artifacts when opening calibration ran.
Show its rendered card verbatim,
then explain its score, band, and cap reasons without internal ids. Describe an existing but
unmeasured component as not yet measured. Presentation detail lives in the glossary:
use its readiness-score presentation.

The score grades measured evidence, not declared existence. Report an uncalibrated real evaluator
and an agent without current-run wiring evidence as not yet measured, never as absent. Do not infer
`wired` from declared `knobs`, copy it from a historical document, or write it merely to clear a
cap. Re-establish wiring on the current agent before the enhanced search as section 7 requires; the
zero-anchor opening may proceed through the same absent-evidence cap while local setup continues.
Read-only preflight and readiness runs are static local validation; they authorize no project
write.

**Opening invocation contract.** When the opening call supplies measured evidence - its
`--preflight` JSON and any applicable `--agent-knobs` and
`--row-review` documents - do **not** also pass `readiness.py --agent`, `--dataset`, or
`--evaluation`. Those three flags are fallback declarations for material the score was not given;
adding them beside measurements supplies two incompatible accounts of the same project, so
`readiness.py` rejects the invocation. The opening readiness argv therefore contains the measured
inputs plus the run-scoped `--task-kind`, `--evaluator-method`, and component-origin flags the
rules above establish. Before running it, check the row-review mechanically against its shape:
every row has a preflight-read `id`, normalized `origin`, `verdict`, one-sentence `note`, and the
same explicit `in_run` boolean, on the split, when membership is settled. Do not rely on a
successful exit to prove an omitted field was intentionally omitted.

### Source evidence for the opening score

SKILL.md's opening gate asks for this; the shape is here. One document, two halves: `knobs` is what
the agent can be told to do differently, and `build` is how it is put together.

A name appearing only in a comment, docstring, TODO, or example is not a knob the opening score can
use. Record one only where executable code reads it, passes it onward, or selects behaviour from it.
A customer comment or settings file may guide inspection, but never supplies `values`, a range, or
wiring evidence. If the source uses the parameter but does not enumerate alternatives, record its
evidence without `values` or `low`/`high`; verify the real build path before adding those alternatives
to the enhanced space. A stub whose comment lists the settings a real call *would* take is describing
an agent that does not exist yet, and recording those names reports a search space this project does
not have - the same false readiness a historical config-space file produces. Pass it as
`scripts/readiness.py --agent-knobs`; The opening readiness procedure above states where it is written, how far one
reading travels, and where it stops. Each scoring gets its own directory there because a read is
evidence about the source at the moment it was taken.

```json
{"source": "agent.py",
 "knobs": {
   "model":       {"values": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
                   "source_lines": [4, 8],
                   "evidence": "The selected agent's model alternatives reach its local call path."},
   "temperature": {"low": 0.0, "high": 1.0,
                   "source_lines": [5, 9],
                   "evidence": "The selected agent's temperature alternatives reach its local call path."},
   "style":       {"values": ["direct", "structured"],
                   "source_lines": [6, 12],
                   "evidence": "The selected agent's style alternatives reach its local call path."}},
 "build": {
   "prompt": {"present": true, "few_shot": 0, "source_lines": [6, 9],
              "evidence": "agent.py:6 STYLES holds the instruction text and carries no worked examples; :9 passes one into the call"},
   "output-contract": {"present": false, "source_lines": [9],
                       "evidence": "agent.py:9 returns the provider reply unread, so nothing pins the answer's shape"},
   "control-flow": {"loop": false, "bounded": true, "source_lines": [8, 9],
                    "evidence": "agent.py:8-9 is one straight-line return with no loop"},
   "tools": {"used": false, "declared": [], "unreachable": [],
             "source_lines": [8, 9],
             "evidence": "agent.py:8-9 declares and reaches no tools"}}}
```

Each settled build check carries `source_lines` on the same terms as a parameter, and a check
answered `"determined": false` carries none - a read that could not settle the question has no line
to point at, so a coordinate beside one is refused rather than ignored. The list records where the
read looked. On its own it establishes nothing about what the read found: a line number is in range
or it is not, which cannot tell a citation somebody verified from one they picked.

So two of the four checks are settled against the source, and two are only located. The difference
is on the card, in the sentence beside each check, because it is the difference between "a check ran
and found no contradiction" and "nothing here looked at this".

**`control-flow` is read from the source, in one direction.** A `for`, `async for` or `while` in the
selected callable's own body proves it loops, so `"loop": false` beside one is refused. The absence
of those proves nothing, and `"loop"` is not a question about node types - it is whether the agent
ends, and on what. An agent that never ends need hold no loop of its own: it can call a helper that
spins, recurse, or hand the work to a comprehension, a generator, `map` or `itertools`. Record
`"loop": true` for any of those. It is accepted without a matching node, and it is the honest answer.

**`bounded` is read the same way, and refused only where the tree proves it.** Two conditions
together: the loop test is one the tree settles as true (`while True:`, `while 1:`, `while 2 > 1:`)
**and** nothing in its body leaves it. Such a loop cannot end by its condition and has no way out,
so `"bounded": true` beside one is refused; the card would otherwise print "a stop condition to
point at" over an agent with none.

**A statement leaves the `while` only if nothing between it and the `while` captures it.** That one
sentence is the rule, rather than a list of keywords, and it is what tells you how an unusual shape
will be read. A `break` is captured by any nearer loop: in `while True:` over `for c in q: break`
the `break` ends the `for`, the `while` starts it again, and that agent never ends. A `raise` is
captured by an enclosing `try` whose `except` handles it, so a loop whose only `raise` lands in its
own handler is left exactly where it was. An `assert` is `raise AssertionError` written shorter and
is read on exactly those terms, both when it leaves and when an `except AssertionError:` catches it.
A `return` is captured only by a function definition, and this read never enters one. Where it
cannot tell whether an exception escapes - a class it does not resolve, a handler written as an
attribute - it refuses nothing.

One shape is refused although the loop really does leave: a `while True:` whose only way out is
`sys.exit()` or `os._exit()`. Seeing that means resolving a name to the function it calls, and
nothing here does. The refusal is a limit of this read rather than a finding about your agent, so
record that check `"determined": false` with a `reason` naming the call - a statement about what
this read could settle, not about what your agent does.

Everything else is accepted, because the ordinary way a `while` ends is its condition becoming
false. **A counter or a flag is a bound and you should record it as one**: `while n > 0` with `n`
decrementing, and `while not done` with the flag set inside, are both `"bounded": true`, and neither
is refused - this is the "loop with a bound can be recorded" case that the control-flow definition
below already names. A `while True` carrying an exit that the rule above counts is accepted for the
same reason, because whether that exit is reached is not a question this read can answer. A `for` is
never refused on this ground at all: it is bounded by its iterable.

**`tools` is credited only where the selected callable reaches the name.** A name in `declared` that
appears nowhere in the selected agent's file - not as an identifier, an attribute, or a string - is
not a tool that agent declares, and is refused outright. Presence alone earns nothing beyond
surviving that refusal: credit needs the callable to reach the name, directly or through a
module-level assignment the callable itself names, so a name sitting in a table nothing reads is
declared and unresolved rather than declared and wired. Declare what the call really reaches; a name
listed because it appears somewhere costs the check rather than paying for it.

That walk goes one hop and no further, and it settles the reachability of a NAME rather than what the
thing behind it is. Nothing here decides what makes a call a tool, so a name it does reach is no more
proven to be one than it was before - reachability can only ever lower the credit a declaration
claims, never manufacture it.

**`prompt` and `output-contract` are located only.** Nothing statically decides whether a prompt
carries worked examples, or whether anything pins the shape of an answer. Their `source_lines` say
where you looked and their `evidence` says what you saw; neither settles the finding, and the card
says so rather than letting the four checks read as equally verified.

Write every answer to be true of the agent you selected. A carried-over document is caught when its
coordinates fall outside that source, or when a derivation contradicts it, and not otherwise. Your
`evidence` is prose and nothing reads it: on any of the four checks a sentence describing another
program is reprinted on the customer's card as written, because deciding whether a filename in a
sentence is a misattribution or an ordinary reference to another module of the same project is not
something a reader of prose can do - and refusing such a reference would refuse the truth about
every agent whose prompt or tools live in a second file. What the card prints beside your sentence
instead is the line your `source_lines` actually point at, quoted from the selected agent, so a
reader can weigh the two against each other. Write the sentence so they agree.

Only the control-flow derivations stay inside the selected callable's own body; the tools walk goes
one hop out to module-level assignments, as stated above. Passing any of them is not a finding that
the answer is right. An agent whose loop is in a helper it calls passes both checks with `"loop": true,
"bounded": true` and may still never return. The card says how far each check reached for exactly
this reason; read the source, not the refusal.

**The route this reader follows, and what it costs to step off it.** One agent whose settings it
does follow, the entry that cites it, and the conditions it applies. It is one accepted shape and
not the only one - the paragraph below this one names another - so read it for its parts rather
than for its names. A setting outside every accepted shape is refused for CREDIT, which is not a
finding that the setting does not vary.

```python
from openai import OpenAI

MODELS = ["gpt-4o-mini", "gpt-4o"]

client = OpenAI()


def answer(question, model_choice=0):
    model = MODELS[model_choice]
    reply = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
    )
    return reply.choices[0].message.content
```

and the entry that cites it, inside the document's `knobs` map:

```json
{
  "model": {
    "evidence": "agent.py:3 lists the alternatives, agent.py:9 selects one, and agent.py:11 passes it to the request call.",
    "source_lines": [
      3
    ],
    "values": [
      "gpt-4o-mini",
      "gpt-4o"
    ]
  }
}
```

1. the options are written out as literals in a module-level binding, and 'source_lines' cites that
   line
2. the selected callable chooses among them from something it is given: one of its own parameters, as
   above, or a key it reads from a mapping passed to it
3. that choice is what indexes the module binding
4. the selected value reaches an argument named for the setting, either written into the call or
   through one plain local that nothing else rewrites
5. and where the choice is read from a mapping rather than taken as a parameter, the call has to be a
   provider client's own request; that client can be built at module level or inside the callable,
   either reads

Three limits are worth knowing before you write the citation, because each one is silent in the
code and costs a setting.

**Keep the settings mapping clean, or only its first read survives.** While `config` is only ever
read as `config["x"]` or `config.get("x")` - in the callable that owns it, and in any same-file
helper you hand it to - every setting it holds can be credited, with no limit on how many. The
moment it appears as a bare name anywhere else, logged or serialised or passed to a call this read
does not enter, that callable loses it, and the only setting still followed is whichever is assigned
FIRST in file order. Two one-line repairs: stop passing the mapping around bare, or move the read
you care about to the top of the function.

**A read of a choice table, anywhere in the file, has to be one this reader can see cannot change
the table.** An index, a `.get()`, an `in` comparand, a `for` over it, an f-string interpolation, an
alias nothing later writes to, and an argument to a builtin that only reads it, all keep it. Writing
through the name loses it, and so does handing the table to your own function, wherever in the
module that sits: this reader does not enter your function, so it cannot say what happens in there.
A builtin your file has rebound counts as your own function. `f"{tuple(TABLE)}"` is fine;
`f"{spell_out(TABLE)}"` is not.

**A range has no options to index, so it has its own route:** the setting passed straight to the
request argument named for it, on the provider client's own request, as
`temperature=config["temperature"]`, or, where that name is a parameter of the selected callable
rather than of a helper, `temperature=temperature`. Do not build a mapping whose keys and values
are the same numbers to satisfy the table route. It is worse code and it buys nothing.

A setting outside all of these is still recorded with its options, and the card names it as one this
read could not follow, says which of these rules it fell outside, and prints the followed count as a
floor beside the count those settings would reach if they vary. Neither figure is credit for them.

A parameter's `source_lines` are positive physical lines in relative `source`; that file must be
`--selected-agent` below `--agent-source-root`. `--selected-agent-callable` names the selected
top-level Python function. Without importing code, the scorer accepts only a cited executable
literal binding that is an unconditional module-level statement, has no later binding of that
name, and is consumed by the selected function or one same-file helper whose result contributes
to its return through an intact formal parameter. Local bindings, branches, discarded or uncalled
helpers, metadata, comments, examples, and an unrelated callable cannot lend it credit. This deliberately
narrow static form is an opening observation, not a
claim that every Python agent is unsupported. A valid range/list can improve the opening card,
never prove wrapper wiring or provider effect. Record an unsettled parameter with `evidence` and
no `values` or `low`/`high`; it is worth recording rather than dropping. A knob has no `determined` field.
`seed` and `max_tokens` remain excluded. The pre-approval request-difference probe
alone authorizes a multi-configuration paid grid; the Enhanced config-space record says what ran.

Run the read with all three bound inputs, for example:

```bash
scripts/readiness.py --agent-knobs traigent-runs/readiness/<YYYYMMDDTHHMMSSZ>/agent-knobs.json \
  --agent-source-root "$PROJECT_ROOT" --selected-agent "$PROJECT_ROOT/agent.py" \
  --selected-agent-callable answer_question
```

For a command, method, callable object, or non-Python agent, leave source credit unestablished and
take the advisory route. A safely evaluated thin Python adapter is walkthrough material, not proof
that the original production agent was optimized.

### The build half

The `build` member in that same JSON object answers all four checks, each with
the line you read. Do not split it into a second document: the consumer reads
one object and requires `knobs` at its root.

The source-read card records these answers but leaves all four unmeasured: source
or a reader's description is not proof that a prompt reaches the provider, a
loop ends, an output has one shape, or a named tool is really a tool.

What each is asking, and what it is not. **Prompt** is whether anything the model is told reaches
the call, and how many worked examples ride with it; two is where examples start showing a pattern
rather than illustrating one. **Output contract** is whether the answer's shape is pinned down
anywhere - a parser, a schema, a response format, an instruction naming the format, or the source
itself fixing what comes back (a dict literal, a dataclass, a typed return) - because an answer of
any shape is one an evaluator has to accept whole. That last form is the one readers miss:
`return {"model": model, "config": config, "input": input_text}` records the shape an evaluator reads,
even in a stub that calls no model. Pinned and
performed are separate questions and this one asks only the first, so withholding the check from a
stub answers a question nobody put. **Control flow** is whether the agent ends and on what: no loop
ends trivially, a loop with a bound can be recorded, and a loop with neither is one input costing an
unbounded number of calls. **Tools**
is whether each declared name is reached from the callable, one hop through the module. A partly
reachable list earns only the reachable share of this check. Reading the whole file only ever
REFUTES a name; nothing is credited from it. None of these four is scored on the route a customer
takes: supplying `--agent-knobs` leaves every one of them out of the denominator, so a `false`
answer costs nothing rather than costing this check's weight. Dataset and evaluation are scored in separate
pillars. Memory/context and provider connectivity are not scored here; run safety handles the latter.

None of the four is a judgment about how good the agent is, and none may become one. Whether a
prompt is well written, whether a tool is the right tool, whether the objective is a sensible
objective - those are opinions, and an opinion may lower a score and never raise one, so they are
outside this document. Answer `{"determined": false, "reason": "...", "evidence": "..."}` where the
read genuinely could not settle a check - a prompt assembled at runtime from somewhere this read
cannot reach is the common case - and the check keeps its weight and earns nothing, the same as
an honest no.

Two of the criteria this pillar is asked about are not here, and the card says so rather than
letting four checks imply that six were looked at: whether the dataset and the evaluation method are
wired into the agent. That integration is what the matrix above builds and section 5 verifies against
the installed SDK, so at the opening gate there is nothing in the agent's source to read, and a
score for it would be grading this run's own later work.

## Compatibility contract

Validate all of these before optimization:

- The real agent performs the intended task rather than returning a constant, echo, fixture, or
  placeholder response.
- Every dataset input key binds to an agent parameter or a deliberate scalar adapter.
- Required agent parameters are supplied by every row.
- Agent output is parseable by the evaluator.
- Dataset expected output matches the evaluator's gold contract.
- Per-example side fields reach the evaluator through metadata.
- The baseline configuration is included in the optimization space.
- Every declared optimization variable changes the real agent call or behavior.
- Generated component files import without reaching a provider or backend at module load.
- No generated component overwrites production code or data.

If compatibility fails, mark the affected real component `invalid` and `❗ needs one fix` or keep
it missing. If compatibility passes but the evidence is too small, narrow, or easy to support a
meaningful comparison, mark it `limited` and keep `❗`. A generated adapter is a substitute; it does not
silently convert an invalid real component into `✅`.

## Readiness transitions

Real-world readiness changes to `✅` only when concrete real evidence passes validation without
an unresolved material limitation. After a repair, re-run the relevant validation and calibration
before changing `limited` or `invalid` to `real`.

Walkthrough setup records a substitute once it passes compatibility. Preserve the
corresponding `❗` real-world gap until real material replaces it.

The numeric readiness score follows the same rule. The opening score is computed before any
creation or repair, the score is re-run after each revalidation as the gate on that repair, and a
rise earned by a generated substitute is walkthrough setup, never real-world readiness. A
`dataset-absent` cap on the opening score is what sends the run into the dependency matrix above.

Examples:

- Real agent + generated dataset + generated evaluator:
  - `✅ Agent - existing customer-support answer function validated.`
  - `❗ Dataset - no reviewed real examples connected.`
  - `❗ Evaluation - no product grading policy connected.`
  - Walkthrough setup: `Dataset - 18 varied synthetic cases prepared.`
  - Walkthrough setup: `Evaluation - normalized label scorer calibrated.`
- Generated agent + real dataset/evaluator:
  - Keep Agent `❗`; show the generated adapter/function under walkthrough setup.
  - Dataset and Evaluation may be `✅` after compatibility validation.
