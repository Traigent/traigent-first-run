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

The matrix below says what gets built. This is what the user was told before it was, and SKILL.md
owns that it is one question, when it is asked, and what it has to carry. Here is what it sounds
like and what happens to the answer.

Say it in their words, naming only what this run looked for and did not find:

> Your agent is here and it runs. Searching outward from it, I did not find any set of examples to
> score it on, or anything that says what a right answer looks like - they may well exist somewhere
> I did not look. I can write both from the agent itself: examples that exercise what it actually
> does, and a grading method to match. Examples I write are weaker evidence than examples out of
> your product: the score carries the generated-data ceiling because of it, so this run can show the
> workflow working and cannot tell you how your product performs.
>
> Shall I go ahead? Or reply `I have it` with a path - `agent: <path>`, `dataset: <path>`,
> `evaluation: <path>` - and I will use yours.

Never say the material does not exist. This run reads the project directory, and a dataset can be
real, in use, and outside it - a shared mount, a sibling repo, a path configured somewhere this
shell never saw, an environment variable this session did not inherit. "There is none here" asserts
what this run did not check, and a user looking straight at their dataset reads the whole card as
wrong. It is also what makes `I have it` the natural next line rather than a correction: nobody is
being told they were wrong, they are being asked to point. `readiness.py` already speaks this way -
its caps say a dataset was not provided *to this score* - so this is the wording catching up with
the script.

### What the ask offers, and the opening that says what they are choosing between

The offer is one where material is missing - write it - and two where it is only short: keep what
they brought, or add. `I have it` is never among them. It rides on every ask, unnumbered and last,
because it answers where the material is rather than what to do about the material here - and a
document that counts it teaches a reader to number it. Two blinded runs put it in the middle of the
list, and both had read a count that included it.

What varies beyond that is the first sentence, and it is not a further route: whether the run
derives from something or from nothing is a fact this run already established, so offering both
would be asking the user to pick a situation rather than an action.

Name the anchor and what comes off it. `math_calc` that takes a question and returns a number is a
grader and a set of arithmetic examples; a retrieval agent over a docs folder is questions its own
corpus answers. Recorded request/response logs are a dataset source, not only an artifact to find -
a project with no dataset often has the material for one, and saying so is the difference between
"I will write examples" and "I will build them from your own traffic". The selected agent's name is
the last anchor to fall: an agent that echoes its input anchors nothing, and that case is the
matrix's all-missing row, which asks what the walkthrough should do rather than guessing it.

Match the cost sentence to how much is derived. One generated piece around a real agent, real rows
and a real ruler is not the same claim as a trio built from one sentence of intent, and
`readiness.py` already scores them apart. One sentence for both tells the smaller case its result
is worth less than it is, and the larger case that its result is worth more.

Keep the two answers on the last line, the cost to one sentence, and the search to one clause. Three
hedges in front of a choice reads as a compliance gate; one reads as a colleague who has already
done the work. Do not soften that sentence, and do not oversell the other exit either: what the user
is choosing between is a real demonstration on generated material today and a delay of unknown
length. Proceeding is one keystroke, and it is what a user with nothing to point at should do.

### When the gap is a shortfall

Same question, same message, different sentence. What is short here is rows to compare on rather
than a component, so name the count the score actually used, say where the offer stops, and say what
accepting it costs:

> Your dataset is here and I can run on it - 9 rows scored, so a difference between configurations
> can come down to one lucky row. I can add generated examples up to 28 rows in total, the size this
> walkthrough builds. That gives the search more to separate on, and it also makes most of the set
> model-written, which lowers the ceiling on what the result may claim. Continue on the nine, add the
> rest, or reply `I have it` with a path if there are rows I did not find.

Three answers, not two, and the cost sits between the offer and them: a customer who is not told that
a mostly-generated set claims less is being asked to agree to something they cannot weigh. Say it
plainly and once - the dataset reference owns the arithmetic behind it.

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
Name the substitute in WORDS. There is no mark for it, deliberately: a glyph is read for what it
depicts, this one was drawn as tools and read as "repaired" - the one thing it never means - and
renaming it only moved the guess. The words were always required beside it, so they carry it now. Say what the run will actually read: "your rows" is heard as all of them, and above 100
usable rows the paid run takes a bounded sample, so name the count this project will really use.
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
rule about silence, applied one section over: state it, so silence never has to be interpreted. A
blinded run reaching an unmarked pair added "(recommended)" itself, which is what an unstated
default looks like from the outside. Recommend the build route because pausing is always available
and needs no push, while the run stopping is the outcome the walkthrough exists to avoid - and
because the sentence beside it already says what the result will not be able to claim, so the
recommendation cannot oversell.

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

### When a path arrives

Read it before anything is built. Material the user points at is material this run did not create,
so it is scored rather than trusted, and it enters the matrix below as `real`, `limited`, or
`invalid` on that evidence like any other candidate.

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
easy to score deterministically and demonstrates optimization without paying for an LLM judge.

Do not create a story-writing or summarization walkthrough with exact-string grading.

If the real agent is not Python, keep Agent `❗` unless a thin Python adapter calls the unchanged
real behavior and can be evaluated safely. A generated Python walkthrough agent is a substitute; it does
not mean the non-Python production agent was optimized. Warn that subprocess, HTTP, and raw
provider calls are not intercepted automatically by Traigent mock mode.

## Reading the agent for the opening score

SKILL.md's opening gate asks for this; the shape is here. One document, two halves: `knobs` is what
the agent can be told to do differently, and `build` is how it is put together.

A name appearing only in a comment, docstring, TODO, or example is not a knob. Record one only where
executable code reads it, passes it onward, or selects behaviour from it. A stub whose comment lists
the settings a real call *would* take is describing an agent that does not exist yet, and recording
those names reports a search space this project does not have - which is the same false readiness a
historical config-space file produces, arriving through the one input that is supposed to be read
fresh from the source. Two blinded runs reasoned this out unaided and wrote the reasoning down; a
third recorded six comment-only names. It is not a judgement call, so it does not stay unstated. Pass
it as `scripts/readiness.py --agent-knobs`; SKILL.md stage 1 states where it is written. Each
scoring gets its own directory there for the same reason this paragraph refuses a found file: a
read is evidence about the source at the moment it was taken, never a document to be reused.

```json
{"source": "agent.py",
 "knobs": {
   "model":       {"values": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
                   "evidence": "agent.py:8 model=model reaches chat.completions.create; agent.py:4 MODELS = [\"gpt-4o-mini\", \"gpt-4o\", \"o3-mini\"]"},
   "temperature": {"low": 0.0, "high": 1.0,
                   "evidence": "agent.py:9 temperature=temperature reaches the provider call"},
   "style":       {"values": ["direct", "structured"],
                   "evidence": "agent.py:11 STYLES[style] selects the system prompt; agent.py:5 STYLES = {\"direct\": ..., \"structured\": ...}"}},
 "build": {
   "prompt": {"present": true, "few_shot": 2,
              "evidence": "agent.py:5-19 SYSTEM carries two worked examples"},
   "output-contract": {"present": true, "evidence": "agent.py:24 json.loads(reply) parses it"},
   "control-flow": {"loop": true, "bounded": true,
                    "evidence": "agent.py:31 for _ in range(MAX_STEPS)"},
   "tools": {"used": true, "declared": ["search", "fetch"], "unreachable": [],
             "evidence": "agent.py:12 TOOLS lists both; both resolve in this module"}}}
```

A parameter earns credit only from what its own `evidence` shows: a numeric one needs `low`/`high`
it genuinely accepts, a categorical one needs two or more options its `evidence` quotes verbatim.
That string is all the scorer reads - it never opens the agent - and it matches whole tokens, so
`gpt-4` declared against evidence reading `["gpt-4o-mini", "gpt-4o"]` earns nothing. Anything else
is reported with the reason it earned nothing, which is a line the user can read and correct - so a
parameter you are unsure of is worth recording rather than dropping. Record it with its `evidence`
and no `values` or `low`/`high`: that is how a knob says "seen in the agent, extent not
established". A knob has no `determined` field - that answer belongs to the four `build` checks
below, and inside `knobs` it is refused - because a parameter establishing no range contributes
nothing a search can vary, which is what recording it without one already says.
`seed` and `max_tokens` earn nothing here, for the reasons the scorer already gives on the card.

The opening read cannot prove that a listed option is wired into the running
agent. Keep a comment-only or manual alternative out of `values`; it is a
candidate to add deliberately in the enhanced configuration space, then verify
on the real build path before treating it as searchable.

A range counts as at least two distinct values and no more; a value list counts as its own length.
The score says "at least N configurations" because nobody has chosen the sweep yet. It is a read of
what is reachable and attests nothing about wiring: it clears no cap, and it never substitutes for
the config-space document the enhanced search emits.

### The build half

The `build` member in that same JSON object answers all four checks, each with
the line you read. Do not split it into a second document: the consumer reads
one object and requires `knobs` at its root.

The opening card records these answers but leaves all four unmeasured. A line
of source or a reader's description cannot prove that a prompt reaches the
provider, every loop ends, every output has one shape, or a named tool is
reachable. A later score may measure one only when it receives verification
evidence for that fact; this opening document is not that proof.

What each is asking, and what it is not. **Prompt** is whether anything the model is told reaches
the call, and how many worked examples ride with it; two is where examples start showing a pattern
rather than illustrating one. **Output contract** is whether the answer's shape is pinned down
anywhere - a parser, a schema, a response format, an instruction naming the format, or the source
itself fixing what comes back (a dict literal, a dataclass, a typed return) - because an answer of
any shape is one an evaluator has to accept whole. That last form is the one readers miss:
`return {"model": model, "config": config, "input": input_text}` pins the shape an evaluator reads,
and earns the check in a stub that calls no model just as it does anywhere else. Pinned and
performed are separate questions and this one asks only the first, so withholding the check from a
stub answers a question nobody put. **Control flow** is whether the agent ends and on what: no loop
ends trivially and earns the check, a loop with a bound you can point at
earns it too, and a loop with neither is one input costing an unbounded number of calls. **Tools**
is whether each declared tool can be found. `"used": false` removes only this wiring check; prompt,
output-contract, control-flow, and config-space checks remain, with dataset/evaluation in separate
pillars. Memory/context and provider connectivity are not scored here; run safety handles the latter.

None of the four is a judgment about how good the agent is, and none may become one. Whether a
prompt is well written, whether a tool is the right tool, whether the objective is a sensible
objective - those are opinions, and an opinion may lower a score and never raise one, so they are
outside this document. Answer `{"determined": false, "reason": "...", "evidence": "..."}` where the
read genuinely could not settle a check - a prompt assembled at runtime from somewhere this read
cannot reach is the common case - and the check leaves the pillar rather than scoring zero against
the agent.

Two of the criteria this pillar is asked about are not here, and the card says so rather than
letting four checks imply that six were looked at: whether the dataset and the evaluation method are
wired into the agent. That integration is what the matrix above builds and stage 5 verifies against
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
