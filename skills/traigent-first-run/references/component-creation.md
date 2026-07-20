# Component Creation

Use this reference after the initial project inspection. Inventory Agent, Dataset, and Evaluation
before creating any of them.

## Contents

1. Evidence and provenance
2. Dependency matrix
3. Agent creation
4. Compatibility contract
5. Readiness transitions

## Evidence and provenance

Classify each component as:

- `real` - project/customer material that exists independently of the walkthrough.
- `demo` - material invented to demonstrate the workflow.
- `missing` - no usable component found.
- `invalid` - material exists but fails compatibility or validation.

Wrapping a real function with `@traigent.optimize` does not make it synthetic. Converting a real
dataset to JSONL does not make it synthetic. Replacing the logic, labels, examples, or grading
policy with invented material does.

Record in `traigent-runs/run-plan.md`:

- Source path and stable identifier.
- Provenance classification.
- Any conversion or wrapper created.
- Validation evidence.
- Unresolved real-world gap.

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
6. State: "Traigent generated an agent for this walkthrough." Do not call it a sample agent as if
   it were equivalent to the user's production behavior.

If the user gives no preference, recommend a structured classification or extraction task. It is
easy to score deterministically and demonstrates optimization without paying for an LLM judge.

Do not create a story-writing or summarization walkthrough with exact-string grading.

If the real agent is not Python, keep Agent `❗` unless a thin Python adapter calls the unchanged
real behavior and can be evaluated safely. A generated Python walkthrough agent is `🛠️`; it does
not mean the non-Python production agent was optimized. Warn that subprocess, HTTP, and raw
provider calls are not intercepted automatically by Traigent mock mode.

## Compatibility contract

Validate all of these before optimization:

- Every dataset input key binds to an agent parameter or a deliberate scalar adapter.
- Required agent parameters are supplied by every row.
- Agent output is parseable by the evaluator.
- Dataset expected output matches the evaluator's gold contract.
- Per-example side fields reach the evaluator through metadata.
- The baseline configuration is included in the optimization space.
- Generated component files import without reaching a provider or backend at module load.
- No generated component overwrites production code or data.

If compatibility fails, mark the affected real component `❗ needs one fix` or keep it missing.
A generated adapter is `🛠️`; it does not silently convert an invalid real component into `✅`.

## Readiness transitions

Real-world readiness changes to `✅` only when concrete real evidence passes validation.

Walkthrough setup changes to `🛠️` when a generated substitute passes compatibility. Preserve the
corresponding `❗` real-world gap until real material replaces it.

Examples:

- Real agent + generated dataset + generated evaluator:
  - `✅ Agent - existing customer-support answer function validated.`
  - `❗ Dataset - no reviewed real examples connected.`
  - `❗ Evaluation - no product grading policy connected.`
  - `🛠️ Walkthrough dataset - 24 varied synthetic cases prepared.`
  - `🛠️ Walkthrough evaluation - normalized label scorer calibrated.`
- Generated agent + real dataset/evaluator:
  - Keep Agent `❗`; show the generated adapter/function as `🛠️`.
  - Dataset and Evaluation may be `✅` after compatibility validation.
