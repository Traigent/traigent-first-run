# Component Creation

Use this reference after the initial project inspection. Inventory Agent, Dataset, and Evaluation
before creating any of them.

## Contents

1. Evidence and provenance
2. Dependency matrix
3. Agent creation
4. Reading the agent's search space for the opening score
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

## Reading the agent's search space for the opening score

SKILL.md's opening gate asks for this; the shape is here. Write it to a scratch path outside the
user's project and pass it as `scripts/readiness.py --agent-knobs`.

```json
{"source": "agent.py",
 "knobs": {
   "model":       {"values": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
                   "evidence": "agent.py:8 model=model reaches chat.completions.create; agent.py:4 MODELS lists the three ids"},
   "temperature": {"low": 0.0, "high": 1.0,
                   "evidence": "agent.py:9 temperature=temperature reaches the provider call"},
   "style":       {"values": ["direct", "structured"],
                   "evidence": "agent.py:11 STYLES[style] selects the system prompt; agent.py:5 declares both keys"}}}
```

A parameter earns credit only from what its own `evidence` shows: a numeric one needs `low`/`high`
it genuinely accepts, a categorical one needs two or more options that exist. Anything else is
reported with the reason it earned nothing, which is a line the user can read and correct - so a
parameter you are unsure of is worth recording rather than dropping. `seed` and `max_tokens` earn
nothing here, for the reasons the scorer already gives on the card.

A range counts as at least two distinct values and no more; a value list counts as its own length.
The score says "at least N configurations" because nobody has chosen the sweep yet. It is a read of
what is reachable and attests nothing about wiring: it clears no cap, and it never substitutes for
the config-space document the enhanced search emits.

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
creation or repair, the score is re-run after each revalidation, and a rise earned by a `🛠️`
substitute is walkthrough setup, never real-world readiness. A `dataset-absent` cap on the opening
score is what sends the run into the dependency matrix above.

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
