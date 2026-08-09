# Component Creation

Use this reference after the initial project inspection. Inventory Agent, Dataset, and Evaluation
before creating any of them.

## Contents

1. Evidence and provenance
2. The one ask, and the path that answers it
3. Dependency matrix
4. Agent creation
5. Compatibility contract
6. Readiness transitions

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
repair it successfully or treat it as missing and create a clearly labeled `🛠️` substitute. A
broken evaluator or incompatible dataset is not safe to continue unchanged.

## The one ask, and the path that answers it

The matrix below says what gets built. This is what the user was told before it was, and SKILL.md
owns that it is one question, when it is asked, and what it has to carry. Here is what it sounds
like and what happens to the answer.

Say it in their words, naming only what this run looked for and did not find:

> Your agent is here and it runs. Searching this project I did not find any set of examples to
> score it on, or anything that says what a right answer looks like - they may well exist somewhere
> I did not look. I can write both from the agent itself - examples that exercise what it actually
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

Keep the two answers on the last line, the cost to one sentence, and the search to one clause. Three
hedges in front of a choice reads as a compliance gate; one reads as a colleague who has already
done the work. Do not soften that sentence, and do not oversell the other exit either: what the user
is choosing between is a real demonstration on generated material today and a delay of unknown
length. Proceeding is one keystroke, and it is what a user with nothing to point at should do.

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
real behavior and can be evaluated safely. A generated Python walkthrough agent is `🛠️`; it does
not mean the non-Python production agent was optimized. Warn that subprocess, HTTP, and raw
provider calls are not intercepted automatically by Traigent mock mode.

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
meaningful comparison, mark it `limited` and keep `❗`. A generated adapter is `🛠️`; it does not
silently convert an invalid real component into `✅`.

## Readiness transitions

Real-world readiness changes to `✅` only when concrete real evidence passes validation without
an unresolved material limitation. After a repair, re-run the relevant validation and calibration
before changing `limited` or `invalid` to `real`.

Walkthrough setup changes to `🛠️` when a generated substitute passes compatibility. Preserve the
corresponding `❗` real-world gap until real material replaces it.

The numeric readiness score follows the same rule. The opening score is computed before any
creation or repair, the score is re-run after each revalidation as the gate on that repair, and a
rise earned by a `🛠️` substitute is walkthrough setup, never real-world readiness. A
`dataset-absent` cap on the opening score is what sends the run into the dependency matrix above.

Examples:

- Real agent + generated dataset + generated evaluator:
  - `✅ Agent - existing customer-support answer function validated.`
  - `❗ Dataset - no reviewed real examples connected.`
  - `❗ Evaluation - no product grading policy connected.`
  - `🛠️ Walkthrough dataset - 18 varied synthetic cases prepared.`
  - `🛠️ Walkthrough evaluation - normalized label scorer calibrated.`
- Generated agent + real dataset/evaluator:
  - Keep Agent `❗`; show the generated adapter/function as `🛠️`.
  - Dataset and Evaluation may be `✅` after compatibility validation.
