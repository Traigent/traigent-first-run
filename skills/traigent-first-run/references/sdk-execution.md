# SDK Execution

Use this reference after component creation and before writing the run wrapper.

## Contents

1. Capability discovery
2. Automatic run bounds
3. Walkthrough model ladder
4. Decorator contract
5. Small baseline sweep
6. Reading the result for insight
7. Carrying the local baseline into the portal
8. Broader optimization
9. Result checks

## Capability discovery

Inspect the installed SDK instead of assuming a release-specific signature:

```bash
python - <<'PY'
import inspect
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

print(getattr(traigent, "__version__", "unknown"))
print(inspect.signature(traigent.optimize))
print(inspect.signature(EvaluationOptions))
print(inspect.signature(traigent.Dataset.from_jsonl))
print(inspect.signature(ObjectiveDefinition))
print(inspect.signature(ObjectiveSchema.from_objectives))
PY
```

After decorating the function, inspect `agent.optimize_sync` the same way. If the installed
signatures or public dataset loader do not support the usage below, adapt from the installed
public API. Do not invent arguments or reproduce SDK internals.

Start that inspection at these public locations instead of searching the whole package. Treat the
map as navigation, not fixed signatures: confirm each on the installed version, never hardcode a
signature you have not inspected, and treat an absent name as unavailable rather than assumed.

| Need | Import from |
| --- | --- |
| `optimize` decorator, `EvaluationOptions`, `InjectionOptions` | `traigent.api.decorators` |
| `get_config()` - read the trial's chosen values inside the agent body | `traigent` (`traigent.get_config`) |
| `ObjectiveDefinition`, `ObjectiveSchema` | `traigent.core.objectives` |
| Primary-only or cost-aware candidate selection | `traigent.ParetoFrontCalculator` |
| Dataset loader and example fields (`.input_data` / `.expected_output` / `.metadata`) | `traigent.Dataset` (`Dataset.from_jsonl`) |
| `optimize_sync(...)` and its result object | the decorated function (`agent.optimize_sync`) |

Read outcomes from attributes on the result object rather than parsing the printed table; inspect
it once and reuse the names: `cloud_url` (direct portal link), `best_config`, `best_score`,
`total_cost`, `trials`, `failed_trials`, `stop_reason`, `run_label`. Confirm the exact names on the
installed version and treat any that are absent as not available. For the scorer argument contract,
use the installed public `metric_functions` shape shown under "Decorator contract" below rather than
inferring aliases or positional fallbacks from SDK internals.

The installed SDK owns:

- In-run enforcement, at trial granularity, of the per-optimization cost limit it is given.
- Graceful partial results when an optimization timeout occurs.
- Retries for transient Traigent-backend requests.
- Provider-error classification and stop reasons.

The first-run wrapper must not duplicate those behaviors. Preserve any retry behavior already
present in the user's agent, and do not set `TRAIGENT_VENDOR_MAX_RETRIES` or LiteLLM `num_retries`
for generated walkthrough code. The single exception is the one the ledger below cannot do without:
the door pins the provider client's own `max_retries` to `0`, because retries taken beneath it are
billed without being counted. It is stated with what it trades where it is written, and
`references/run-safety.md` owns the rule it is the exception to. That rule binds what is GENERATED,
and the caller the door exists for is the other one: this guide preserves the user's agent and judge
and imports them after the door, so a `num_retries` already in their code, or a process-wide
`litellm.num_retries`, arrives at the door and multiplies the provider requests one call places.
The door reads both spellings and reserves for them rather than pretending they are absent. If the
preserved agent already has bounded provider retries, include their possible extra calls in the
automatic runtime/spend estimate without asking the user to choose the count.

## Automatic run bounds

Do not ask the user for retry counts or timeout values. Before the paid live probe, estimate
runtime conservatively from dataset size, planned trials, and calls per example. After the
approved probe, replace that estimate with observed latency:

```text
expected seconds =
    rows * trials * calls per example * observed upper latency / effective concurrency

SDK phase timeout = expected seconds * a reasonable completion margin
```

Use a positive floor so setup overhead does not make a small run fail immediately. The coding
assistant selects the exact internal values and places them in the current process; the user does
not fill them in. If the observed estimate becomes materially longer than the approved estimate,
offer a smaller representative run or state the additional approximate time and cost.

Do not bound the enhanced optimization with a mid-run wall-clock cap. Pass
`timeout=OPTIMIZATION_TIMEOUT_SECONDS` where that value is `None` by default, so a legitimately
progressing search is never cut off partway and forced to report a partial result - and so a large
run is not truncated wholesale by a fixed clock. Its real bounds are the trial cap, the total cost
ceiling, and the per-model-request timeout below: a stuck provider call is caught by the request
timeout; the ceiling bounds the execution allowance. Keep a first run from taking too long by sizing it up
front, not by cutting it: if the runtime estimate is too high, reduce the run before starting - a
smaller representative tuning slice for either phase, or a lower enhanced trial cap; the baseline
grid is never reduced, because a grid that does not run its whole space has ranked nothing - and
disclose the revised estimate; a large *preserved* baseline (never shrink a user-owned one) then runs to
completion under the cost ceiling rather than being truncated. The estimate above still drives the
up-front time/cost disclosure and the baseline phase timeout. That timeout is
`TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS`, the fourth process variable beside the three cost
figures, and it has no default: the contract below reads it through `positive_number(...)`, and a
baseline process launched without it stops at import. Size it from the formula above with the
baseline's own figures - its trial count, the tuning rows, calls per example and the observed upper
latency give the expected seconds, times the completion margin, never below the floor. Set
`TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS` only for the rare case that genuinely needs a hard
wall-clock stop.

Keep an individual model-request timeout so one stuck provider call cannot hang the walkthrough.
Reuse the real agent's existing value when present. Generated LiteLLM walkthrough code may use a
reasonable internal fallback such as 120 seconds, adjusted automatically after the live probe.
This is not a new retry policy.

Use one total walkthrough ceiling, `$5.00` by default. Every paid process is launched with that
total and with what earlier phases already debited, and the decorator contract below turns the pair
into two things: the per-optimization limit the SDK enforces for that phase, and the gate every
provider call the wrapper places itself has to pass. `references/run-safety.md` owns what the total
covers, how it is approved, and how the figures are carried between processes.

## Walkthrough model ladder

This section applies only when the assistant prepares a missing baseline. Select its models from
the provider route the user already has in hand: one fast low-cost tier, one mid-tier workhorse,
and one strong tier one step below the vendor's newest flagship. Do not select the flagship
itself. Omitting it bounds generated-walkthrough cost and latency; do not imply it has no value.
State that in the plan and price any flagship comparison separately. Every selected model runs in
the baseline grid and must fit the approved time and cost envelope.

Both generated spaces use the same three models and both have an exact size. State them exactly,
never as "roughly" or "about"; the asserts beside the spaces below enforce both:

- baseline: **3 models × 2 prompt styles × 2 thinking shapes = 12 configurations**, run as 12
  trials so `grid` enumerates every one of them and nothing is left to trial order.
- enhanced: **3 models × 3 binary behaviour knobs = 24 configurations**, half of it reachable
  within the 12-trial cap, which is the 12 reachable configurations the readiness scorer pays
  full marks for.

Say on the approval card, plainly: **the baseline runs 12 paid trials, one for every configuration
in its space**. For the generated walkthrough, all enhanced controls are already fixed; for a
customer-owned space, the two baseline axes provide evidence about which of its existing controls
to carry. State the baseline as a count, never as a change from whatever this guide did before: a
first-run customer has no run of ours to compare against, and our release history is not a fact
about their spend. The user approves the count itself before it is spent.

Temperature has one task-selected value in both spaces and is never swept. Use `0` only when the
task and evaluator demand one reproducible output - exact mathematics, executable checks, strict
schemas, or case-sensitive matching. Otherwise choose one supported nonzero value that permits
normal wording or creative variation without violating the evaluator. Do that before either paid
run, then record the value and reason on the baseline approval card. This is an assistant decision,
not another question or a fourth paid knob.
Keeping the selected value fixed across both phases preserves the 12- and 24-configuration sizes
and keeps their comparison attributable. A user-owned baseline instead keeps its temperature
behavior exactly, including an unset provider default.

The three behaviour knobs are **prompt style**, **thinking shape** (direct or chain-of-thought),
and **reflect**, two values each. They shape behaviour rather than sampling, and each intervenes at
a different moment - how the task is framed, during the answer, and after it - so none is another
spelling of its neighbour. Three knobs are enough to make the managed run choose among more
configurations than it can execute without turning a first taste into the full-power workflow.

The synthesized walkthrough dataset contains the tuning rows and, in their own file, the held-out
rows no search ever evaluates; `references/evaluation-and-dataset.md` owns both counts, the band
composition, and when they are reserved. The baseline's two non-model axes are `prompt_style` and `thinking_shape` because the enhanced
space carries both: a baseline that ranks a lever the enhanced run will not use has measured nothing
usable, which is what temperature became once it was pinned. Every baseline value is kept, so the
baseline is a strict subset and the enhanced run never gets a model the baseline did not measure, so
a measured difference cannot be explained by quietly upgrading the model. The coding assistant
fixes every generated value before either run; the user is never asked to pick values or edit the
wrapper. The assistant adds the disclosed
controls; Traigent performs managed selection under the declared objectives, including cost only
when its evidence supports comparison. Keep those actors separate in the report.

### The knob catalog - nine documented controls, seven eligible direct parameters

The three slots above are the default fill for a generated single-call classification or extraction
walkthrough - a selection, not the list. Pick the three that fit the customer's agent from this
catalog, keeping the different-moments test, and name the ones left out on the approval card. The
catalog is assistant-side choice, not a menu the first-run customer has to design; the approval
card shows the selected three and why they fit.

| Knob | Values | Choose it when |
|---|---|---|
| `model` | 3 ladder rungs | always - it is the ladder, not a slot |
| `prompt_style` | `plain`, `structured` | default slot; the task's framing is unexamined |
| `thinking_shape` | `direct`, `chain_of_thought` | default slot; answers need derivation, not recall |
| `reflect` | off, on | default slot; answers are nearly right and need one revision |
| `few_shot_count` | two counts within 0-10 | the task has a house format worked examples would teach |
| `retrieval_k` - not eligible | two counts within 1-5 | retrieved context is the lever, in a space contained enough to trace it |
| `context_format` | two layouts | retrieved or structured context is pasted in raw |
| `tool_policy` - not eligible | two policies | tool behavior is the lever, in a space contained enough to trace it |
| `temperature` | the customer's own values | only when preserving a customer-owned sweep - see below |

This first run includes only direct request parameters: values this finalized wrapper passes to
its single model request and whose distinct values produce distinct dicts for every selected model
and tuning input. Source inspection does not
prove the customer's original agent varies. Retrieval, tool, repair, and multi-call controls - `retrieval_k`
and `tool_policy` above, task decomposition, self-consistency - are indirect even when
changing one also changes
an outer request dict; they require separately contained tracing and are excluded from this paid space.

For an assistant-prepared walkthrough, temperature is one task-selected fixed value, not a search
slot. When the customer already sweeps it, preserve **their** values rather than inventing a new
range or pinning underneath them. Do not add a temperature sweep to generated material merely to
manufacture breadth.

`batch_size` and `max_tokens` are deliberately absent: both move throughput and cost without changing
what the answer says, and a knob that cannot change the answer is not a quality lever.

### Judging a space before you send it

Readiness scores the agent pillar on one number: how many distinct configurations the space holds,
against how many the run has budget to try. That number is the honest part - whether four wide
knobs beat ten narrow ones is what the run is *for*, and nothing can rank it from a JSON file.

Three things it cannot count, and you can. Check each before emitting the document; none of them
lowers the score by itself, and each makes the score describe a search that is not there.

- **Values too close together are not two values.** `temperature: [0.1, 0.115]` is one setting
  written twice, and a run that spends two trials on it learns nothing from the second. The scorer
  collapses the numeric ones it has a range for - the card then says "2 distinct configurations
  (4 declared)" - but it has no range for an unfamiliar knob, so `chunk_size: [500, 505]` counts as
  two and the space it reports is bigger than the space that exists.
- **Two knobs naming one dimension are one knob.** `prompt_style` and `prompt_policy` are the same
  lever spelled twice, and the scorer only knows the spellings it has been told about. Two aliases
  it does not know multiply the space by the size of a dimension the agent has only one of.
- **A knob the agent never reads is not a lever.** Only names in `wired` are counted, and that list
  is your claim rather than a measurement. A name in it the call path ignores adds configurations
  that differ in nothing.

So say what you left out and why on the approval card, in the customer's terms, and let their own
judgement of their agent settle it. That is the check this guide actually has - the customer knows
whether two of their knobs are the same knob, and the scorer never will.

### Say what is being tried, once the enhanced run is under way

When enhanced optimization starts, name its direct paid parameters and their effect on the answer:

- **model** - Tries the same task on a cheaper, a mid-range, and a stronger model.
- **prompt_style** - Changes how the request is worded, from bare task to spelled-out instructions.
- **thinking_shape** - Lets the model work through the problem before answering instead of
  answering straight away.
- **reflect** - Has the model look back at its own answer and fix it before returning it.
- **few_shot_count** - Shows the model worked examples of the task first.
- **context_format** - Changes how the supplied material is laid out for the model to read.
- **temperature** - Changes how much the model varies its wording between runs.

Say nothing else here. No percentages, no reported gains, no references, no "research shows". A
customer waiting on a run wants to know what is being tried, not to be handed reading - and a number
quoted here reads as a promise about their task, which none of it is.

Sweep only knobs that are real for every model in the space. When one model ignores a knob the
others honor, the winner comparison is confounded - a configuration can win on a prompt or setting
the other models were never given on equal terms, and no report footnote untangles that; when every
model faces exactly the same variations, the winner is clear and the enhanced run's insight is
accurate. So when the strong tier is a reasoning model, pin its calling convention identically in
both runs - a chosen reasoning effort, no `max_tokens` at all, and no sampling parameters such a
model rejects. Nothing else changes: temperature is fixed to the selected value in every space,
and the three paid behaviour knobs are real for a reasoning model and a sampling model alike, so
both branches run the same 12 and 24.

When the user already owns a baseline, do not apply this ladder. Preserve its exact model set and
configuration count in the enhanced space and add only direct request parameters the probe
establishes for every selected model and tuning input. Indirect, retrieval, tool, repair, and
multi-call controls stay outside this paid space. Adding a cheaper or stronger model changes the
experiment and attribution, so do it only as a separately disclosed and approved model comparison.
Preserve an existing flagship and its calling convention exactly; never replace or augment it
silently.

For the generated ladder, use one model family when the selected route can supply all three model
choices. One family keeps the result readable - "the mid tier held the strong tier's accuracy at a
fraction of the cost" is a sentence the user can act on - keeps a single company receiving the
user's prompts, and keeps one bill. If the chosen vendor does not expose at least three usable
model choices, ask the user to add a second vendor only for the missing model(s), and name that
extra provider in the approval. When using OpenRouter, one key reaches every family; still prefer
one family by default, and borrow a missing model from a second family only when the chosen family
lacks it, naming that extra provider in the approval.

These three model slots are roles, not hardcoded ids: pick concrete model ids from what the
selected route lists at run time, then verify each id is live before scaling. Missing cost follows
`run-safety.md`'s telemetry choice; it is not a reason to replace a working model automatically.

## Decorator contract

**Default: generate the bridge.** Write `traigent-runs/adapter.json` (`assets/adapter.schema.json`)
from mappings the user approved; `scripts/generate_adapter.py suggest` only proposes them. Then
`generate_adapter.py generate --config ... --project-root ...` imports their agent and evaluator
unchanged, and `python traigent-runs/adapter_bridge.py probe` (wiring, no keys) and the baseline
command run under the shared runtime's ledger and offline boundary. Calibrate the evaluator with `--scorer
traigent-runs/adapter_bridge.py:score`. Edit the bundled wrapper only when generation refuses, with every reason printed (another
transport than OpenAI or litellm, an engine-reaching evaluator) or for the connected phase.

Use one production-compatible function for baseline and optimization. Adapt only these sites in
the bundled wrapper, each tagged `# ADAPT:` where it sits; every other line is verbatim. Model ids, the
provider route and the run bounds are not edits to the fence at all: they arrive through the
process variables it reads.

- `WALKTHROUGH_TEMPERATURE` - the one task-selected value.
- `ROUTE_ALIASES` - only for a route spelling litellm reads as one already in the table.
- `BASELINE_IS_USER_OWNED` - `True` only for an inspected customer baseline.
- `INCLUDE_COST_OBJECTIVE` and `OBJECTIVES` - the measured primary criterion and the supported
  cost-comparison mode recorded for this operation.
- `BASELINE_CONFIG`, `BASELINE_SPACE`, `ENHANCED_SPACE` and `WIRED_KNOBS`, always together.
- `build_prompt` and `build_request` - how the customer's agent turns a configuration into one
  request.
- `SCORER_CALLS_PER_ROW`, `JUDGE_MODEL` and the judge's sampling key - what the wired evaluator
  places.
- The `task_score` body - the preserved evaluator's grade of one row.
- The decorator's `metric_functions` key, matching the primary objective; the function's signature
  and `holdout_agent_input`, matching the agent's own input contract.
- The returned output or measures - preserve existing observations through baseline, search,
  and held-out scoring, as described below.

The runnable wrapper is bundled at `assets/run_wrapper.py`. Copy it to `traigent-runs/run_wrapper.py` and adapt only the tagged sites listed above; every other line stays verbatim. Do not retype the wrapper. The five short phase fences below run from separate files beside that copy.

After adapting the wrapper and before asking for paid approval, run the local proof with no approved figures or timeout:

```bash
TRAIGENT_FIRST_RUN_PHASE=proof python traigent-runs/run_wrapper.py
```

It prints `PROBE_VERDICTS` and exits after checking the finalized request differences. The proof uses the baseline's backend-offline boundary and a zero-balance call ledger; any provider call is refused. A phase file launched with `proof` stops before its search.



Two gates hold the approved total, and they are different gates because the spending happens two
different ways. Inside `optimize_sync`, the SDK admits a trial only while its own limit allows, and
that limit is now the remaining rather than a default: the wrapper writes
`TRAIGENT_RUN_COST_LIMIT` before importing the SDK, so a phase reaching it stops gracefully and
reports `stop_reason`. Outside it, held-out scoring and an LLM judge call `litellm.completion`
directly, where no permit exists - so the second gate is on `litellm.completion` itself, wrapped
once at setup, and it refuses a call whose worst case the remaining cannot cover. Neither gate is
arithmetic the assistant performs between phases: the first is the SDK's per-trial admission check,
the second a ledger reserved against before each call and settled after it.

**The second gate is a place, not a rule.** The install comment above owns its reach - every caller
that resolves the wrapped attribute when it calls - and that clause is the whole test, so apply it
rather than carrying a list of names that moves with the library. Anything built on the wrapped
attributes is covered even though nothing here mentions it: `litellm.batch_completion` submits
`litellm.completion` to a thread pool of its own, and a configured `Router` calls
`litellm.completion(...)`, so both go through the door. Anything that reaches the provider by its
own path is outside it: `litellm.text_completion` and `litellm.completion_with_retries` do, as do
the spend-capable names that are not chat completions at all - `embedding`, `responses`,
`image_generation` and their kin. So does a module that bound the function with
`from litellm import completion` before setup, and so does a client that is not litellm at all - a
raw provider SDK, an HTTP call, a subprocess. Settle a name by patching a sentinel over
`litellm.completion` and calling it, not by trusting a list. Keep generated calls on the two wrapped
names; where a preserved caller cannot come through the door, declare what the scorer spends:
`check_scorer_calls` compares it against the ledger on every row, so a call the door cannot see
is still noticed.

Resolving the attribute brings a call to the door; it does not by itself make the money right.
litellm's `fallbacks` handling re-enters `litellm.completion` once per attempt - measured at three
ledger entries against two provider requests with one fallback, and four against three with two -
and on a scorer declaring what it places, that surplus entry stops a caller that complied. So the
door counts an INVOCATION once: a re-entry taken while another invocation is in flight is covered
by the reservation that invocation already took, and the two rules together are what "the money
is seen" means here.

A judge is the caller that made this necessary. It runs inside `task_score`, whose
`metric_functions` contract returns a number with no ledger to debit through, and the SDK settles a
trial's cost before applying the metric functions, so a call made inside one is already past that
trial's accounting. The rule for generating a scorer is with `task_score` below.

That is why the ledger counts search trials as well as direct calls: held-out scoring runs last, in
the same process as the connected search, and reading the remaining as it stood at process start
would believe the whole of it still there. The SDK's `ExecutionBudget` is not used: it holds its
state in one Python object, so it cannot reach from the baseline process into the connected one,
and a second cap that must agree with `TRAIGENT_RUN_COST_LIMIT` is one more place to disagree.

The coding assistant selects the process-only values above from the inspected project and
live-probe observation; they are not questions for the user. The generated walkthrough defaults
to twelve baseline configurations and a 12-trial enhanced cap. Preserve those counts when they fit
the approved time, cost, and plan quota; prefer a smaller representative tuning slice over collapsing
the comparison back to one-versus-two configurations. The assistant derives the current provider route from the
existing vendor setup, the current agent call, and the route inventory, then populates the process
variables used below; the user types no route metadata. Call
`require_current_route_credential()` immediately before the approved live probe. A route literal it
does not recognise prints as unverified and does not stop the run: it withholds this one check
rather than refusing the credential, and the route's own first call settles what the table could
not. Report it to the user in those terms, and do not present it as a missing or rejected key. If
the discovered route cannot be populated from the existing vendor and there is no usable fallback
ladder, stop and ask the user to add a vendor or choose a different one. Keep the real current
model and parameter values in `BASELINE_CONFIG`, `BASELINE_SPACE`, and every corresponding
enhanced dimension. Select the alternative and strong models from the same approved provider route,
following the walkthrough model ladder above; set
`TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT` only when the selected strong tier actually supports
a reasoning-effort control, and pin the same value for both runs. A new route or recipient
requires revised data-egress approval. In the generated default, every search
variable must affect the actual agent call for every model in the space. A preserved conditional
dimension receives a `partial` verdict during the local proof before approval. Preserve it unchanged
and stop this first-run path for later/manual approved per-model design. When the strong tier runs as a
reasoning model, temperature is inert for it - which costs the comparison nothing, because
temperature is fixed in both spaces and every swept knob is uniform across the ladder.

The concrete spaces above are the generated classification/extraction walkthrough default, not a
template for every real agent. Its baseline is a credible twelve-point sweep: the three
ladder models by two prompt styles by two thinking shapes, with the remaining controls pinned to
the current behavior. The enhanced space keeps every one of those values, the same three models,
and adds one more real one-call control: reflect. That is exactly 24 configurations, so a 12-trial
managed run has meaningful choices to make while keeping the first taste deliberately small.

When the user already has a baseline or fixed current configuration, preserve that baseline space
and its configuration count exactly; do not expand it to twelve. Replace this example's spaces and
`WIRED_KNOBS` together: the list names every paid enhanced key, including pinned keys. Add direct
request parameters such as context format or few-shot count for observed failures. Retrieval, tools,
repair, and multi-call controls require separately contained tracing outside this first-run paid
space. Do not add no-op fields, recode a customer boolean, or add multi-call composite behavior
merely to raise the portal's trial count.

Missing usage does not invalidate an otherwise usable response. Use public response cost when
present, including a genuine reported `0`; cost and token counts can arrive independently. The
reader prefers explicit `usage.cost` or the provider's response-cost header over LiteLLM's hidden
cost. LiteLLM can turn missing usage into zero token counts and hidden `response_cost=0.0`; that
ambiguous zero stays `None` unless positive token usage corroborates it. An explicit provider zero
needs no token corroboration. A hidden cost computed from usage is available pricing evidence,
not a provider-reported charge: name its source when reporting it.
When cost is absent, keep `None` and the existing conservative debit. Do not recalculate a completed
response with `litellm.completion_cost()`: a missing local price entry can raise after a billable call.
`references/run-safety.md` owns the bounded continuation choice and its disclosure.

Select `INCLUDE_COST_OBJECTIVE` from the approved probe's evidence before constructing the
operation's public `ObjectiveSchema`. Leave it false when trustworthy cost coverage is unavailable;
the SDK then optimizes the customer's primary criterion alone. Set it true only when the SDK's
costs have the expected response provenance and coverage. This is an agent-derived fact, not a
user-facing knob. Once a started comparison is primary-only, keep that mode for its remaining
planned phases; restored costs may be reported, while cost optimization belongs to a future run.
Record each phase's actual objectives in the run plan. Preserve the normal
quality-and-cost path when its cost evidence is sound. The SDK's automatic missing-price approval
remains separate: omitting the cost objective does not waive a native SDK preflight requirement.

The pinned SDK can emit `cost=0.0` and estimated positive token counts when the provider reported
neither. Those fields do not establish vendor telemetry or a free run. Keep any known call-cost subtotal separate from unknown calls and the debit. A known provider cost without token
counts is still useful evidence; enable a cost objective only if the installed public SDK adapter
actually carries that cost into the result. The SDK's public `with_usage` supports cost without
token counts, but validate its output shape with the preserved scorer before adapting a caller;
do not invent SDK metadata fields or replace the customer's output contract.

If cost coverage disappears during an operation, preserve its actual declared objectives and
completed quality observations. Do not mutate objectives while it runs or call its cost-driven
recommendation trustworthy. Read candidates by the primary criterion alone, label the cost
comparison unavailable, and use primary-only objectives for the next already planned operation.
Never repeat a paid baseline merely to restore telemetry or describe the earlier cost-aware search
as a quality-only search. The approval and next-step wording stays in `run-safety.md`.

Do not include `expected` in the agent signature: dataset inputs call the agent, and expected
output belongs only to evaluation.

Keep every dataset path absolute, as `TUNING_DATASET` and `HOLDOUT_DATASET` above already are
(`str(RUN_DIR / "...")`). Never shorten these to a relative path: the SDK resolves a relative one
against the working directory of whichever process opens it, and this run's dataset lives under
`RUN_DIR` while the assistant works from the project root. An absolute path is the same file from
any directory, which is the property that matters when the run, a re-run, and `traigent sync` are
three different processes. Nothing announces a breach: a path resolved against the wrong
directory reads one file or misses one, and neither is a crash.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example reflects the inspected three-argument
contract. Do not infer aliases or positional fallbacks from SDK internals. When grading requires
example metadata or full control of agent execution, use the installed SDK's public custom
evaluator instead.

When that evaluator is an LLM judge - which `references/evaluation-and-dataset.md` prescribes for
summary, explanation, writing, and story tasks - it grades with `call_judge`, and never with
`call_agent`, whose request is built from the trial's own knobs. Reaching `litellm` around it is no
longer a way to spend unseen money, but it still grades on whatever model that request names, and
the truncation check does not run - so route it for those reasons rather than for the ledger's.

`SCORER_CALLS_PER_ROW`, set where the bundled wrapper defines it and nowhere after, is the number of provider
calls grading one row places. That number is the run's claim about its own evaluator, and the one
thing here nothing else can derive: it sizes
the held-out refusal, which is settled before the pass it is sizing places a call, and
`check_scorer_calls` tests it against the ledger on every row scored, in the search as well as the
held-out pass. A deterministic evaluator declares `0` and is held to placing none.

A preserved evaluator that places its own provider calls is the case the adapter cannot route,
because changing it is not on offer. Two shapes, and they need opposite handling - **debit exactly
once**, and which one applies is decided by reading the evaluator's own call path:

- **It resolves `litellm.completion` when it calls** - directly, or through anything that does,
  `batch_completion` and a configured `Router` included. Nothing to do: the door refused and debited
  it already, and adding `record_call_spend(None)` here would charge the approved total twice for
  one call and refuse a run that fits. Declare its calls in `SCORER_CALLS_PER_ROW` and stop there.
- **It uses another client** - a provider SDK, an HTTP call, a subprocess - or holds a
  `from litellm import completion` binding older than the door. Debit it by hand: call
  `record_call_spend(None)` once per call it makes, before returning its score, so the declared
  count still matches and the ceiling still falls at the conservative rate. Disclose on the approval
  that this evaluator's spend is deducted rather than reported, and that it is bounded one call late
  - a hand debit lands after the call, where the door refuses before it.

### Numeric measures beyond the answer

The pinned SDK accepts a decorated function returning `(output, measures)`: an exact two-element
tuple whose second element maps ASCII names such as `tool_call_count` or `tool_use_compliance` to
finite `int`/`float` values, excluding booleans. Preserve observations the real agent already
produces through this channel instead of encoding them in answer text. The SDK passes `output`
alone to `metric_functions` and averages supplied measures over examples into `trial.metrics`.
Evaluator-computed keys win collisions, so supplied measures cannot replace `cost`, `latency`, or
a key also registered in `metric_functions`. A malformed metrics tuple remains raw output; verify
the return shape before using it for evaluation.

When a supplied measure is the chosen objective, use its exact key and direction in
`ObjectiveDefinition`; reporting a measure alone does not make it an optimization objective.
When the evaluator needs the underlying trace, preserve that structured trace in `output` or use
the installed public custom evaluator. The tuple's measures are not an extra argument to the
three-argument scorer. Adapt held-out scoring to use the same measurement source and aggregation
as the two searches; the text-only `task_score` example cannot grade telemetry it never receives.

For an existing multi-agent configuration, `agent_measures={agent_id: [measure_name, ...]}` and
`global_measures=[measure_name, ...]` associate measures with agents or the whole workflow. These
decorator options describe supplied measurements; they do not observe tool calls or compute a
score. Retain the existing agent mapping and verify the emitted names on the installed SDK.
This channel does not enlarge the paid execution or knob scope defined above.

## Small baseline sweep

For the generated walkthrough, run the credible small space as one local fixed grid containing its
initial configuration. Start a fresh process with `TRAIGENT_FIRST_RUN_PHASE=baseline` (the
fail-safe default), the three approved cost figures `references/run-safety.md` names, and
`TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS` sized under "Automatic run bounds", all supplied by
the process and never by `.env`. The contract forces backend-offline
before import: removing `TRAIGENT_API_KEY` does not suppress a stored CLI login. Provider calls stay
real. The setting dies with the baseline process; never export it, because the connected
process requires it absent and refuses it if inherited.

```python
if FIRST_RUN_PHASE != "baseline":
    raise SystemExit("baseline phase file requires TRAIGENT_FIRST_RUN_PHASE=baseline")
transfer_path = Path(BASELINE_TRANSFER_FILE)
try:
    transfer_path.unlink(missing_ok=True)
except OSError:
    raise SystemExit("Baseline did not start: stale baseline-transfer.json could not be removed.") from None
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run standard sweep"
require_current_route_credential()
assert_wiring_still_proven()
baseline_results = agent.optimize_sync(
    algorithm="grid",
    configuration_space=BASELINE_SPACE,
    max_trials=BASELINE_TRIALS,
    timeout=BASELINE_TIMEOUT_SECONDS,
    save_to=BASELINE_RESULTS,
)
assert baseline_results.trials, "baseline did not execute"
assert baseline_results.best_config is not None, "no baseline winner selected"
baseline_transfer = baseline_transfer_payload(
    baseline_results,
    BASELINE_CONFIG,
    config_space_document(BASELINE_SPACE),
    len(PROBE_INPUTS),
    PRIMARY_OBJECTIVE.name,
    OBJECTIVE_SIGNATURE,
)
transfer_path.write_text(
    json.dumps(baseline_transfer, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
```

Pass `algorithm="grid"` explicitly for this baseline sweep. **This applies to the local baseline
only; the connected search under "Broader optimization" must stay on `auto`.** The two runs are
deliberately different, and that difference is the comparison the first run exists to show.

The reason to pin the baseline is that `auto` means different things depending on whether a key is
present. With no Traigent key it does not fail and does not run managed search: it falls back to a
local `random` sweep and reports `fallback_reason=no_api_key`, so a run that looks like Traigent's
managed search is really random sampling. Locally the SDK's registry lists six names, and only
`grid` and `random` sample on their own: the three batch runners wrap a sampling search, `random`
unless another is injected, and `remote` will not construct without an injected client. The managed
family is cloud side and is not registered locally. At baseline size the
difference is visible - the same twelve-point space returns the first grid cell every time under
`grid`, and a different winner between runs under the fallback. A first result the user can
reproduce in front of someone else is worth more than one they cannot, so state which algorithm
actually ran rather than implying the managed one did.

Grid also cannot enumerate a continuous parameter, so every baseline knob stays an explicit list of
values. If a preserved user space is large enough that its trial cap could not reach most of it,
grid would only ever cover the corner it starts from; use `random` there instead, and say which
one ran and why.

Do not supply a separate `default_config`; on local proposal paths it can consume a trial slot and
truncate the grid. Verify all twelve distinct points executed and that `BASELINE_CONFIG`
appears in the returned trials. For an existing user-owned baseline, replace the generated example's configuration, spaces, wired list,
trial count, and algorithm with the preserved values and behavior exactly. A
real single fixed configuration remains one configuration; never manufacture variants around it.

The baseline process prints its ledger on the way out; `report_run_spend` above owns which endings
reach it, and `references/run-safety.md` owns what to carry forward when the line is missing. The
figure to carry forward is the **cumulative debit** - this process's debit plus the earlier phases'
debits, including the conservative reservation for any unpriced call. It is a budget figure, not
measured billing. That total is what the connected process is launched with as
`TRAIGENT_FIRST_RUN_COST_SPENT_USD`, so the number the baseline actually produced is the number the
next phase is bounded by. Do not assemble it by hand from the SDK's tracked cost: that is a smaller,
different quantity, and the gap is exactly the spend the ledger exists to catch. Do not start the
search if it cannot fit the remaining total ceiling. A completed baseline is never re-run for a
better number, and nothing is widened, topped up or raised on the way to the search: SKILL.md's
operating contract owns that rule and the newly scoped approval it takes.

Read cost as measured only when its provenance and coverage are established. An SDK number alone
does not establish that. An absent cost is `not measured`; an explicit provider-reported zero is
valid even without token counts. Never turn absence into `$0.00`.

## Reading the result for insight

Two post-run reads cost nothing, need no key, and turn a flat "it improved by N points" into
something the user can act on. Confirm both on the installed version before relying on them, and
treat an absent name as unavailable rather than assumed.

- A per-example audit on the result object flags examples that no configuration ever scored
  correctly, and can carry a suggested answer where several unrelated models agreed on the same
  non-gold output. Those flags are the fastest route to a mislabelled reference: when every
  configuration fails one example, suspect the expectation before the agent.
- An optimization-insights helper summarizes which controls actually moved the score and which did
  not. A knob that never changed the outcome is worth reporting - it tells the user where not to
  spend effort next time.

Comparison reads need two completed configurations. The generated grid qualifies; a preserved
baseline with one configuration must wait for the enhanced result or report insight unavailable.
Neither read is meaningful under mock mode: identical canned responses describe the mock, not the
dataset.

Do not call the result's `analyze()` method. It requires a separate plugin that this run does not
install and raises `ImportError` without it, so calling it turns a finished run into a crash at the
reporting step.

## Carrying the local baseline into the portal

A baseline that ran without a Traigent key is logged locally. Upload it without another provider
call only when the installed public result exposes an exact sync id:

```bash
SESSION_ID="<copy baseline_results.sync_session_id>"
TRAIGENT_FIRST_RUN_RESULTS_DIR="/absolute/path/to/project/traigent-runs/sdk-results"
TRAIGENT_RESULTS_FOLDER="$TRAIGENT_FIRST_RUN_RESULTS_DIR" traigent sync "$SESSION_ID" --dry-run --json
TRAIGENT_RESULTS_FOLDER="$TRAIGENT_FIRST_RUN_RESULTS_DIR" traigent sync "$SESSION_ID" --json
```

`TRAIGENT_RESULTS_FOLDER` is not optional here. The id is relative to the store that holds the
record, `traigent sync` is a separate process that resolves its store from its own environment, and
the run above set that variable inside the Python process only. Without it the CLI looks in its
default root and rejects an id that is on disk. Replace the placeholder with the resolved absolute
path to this project's `traigent-runs/sdk-results`; do not reuse the Python-only `RUN_DIR` name in
the shell.

Never use `--all`: it pushes every optimization ever logged on the machine, not this walkthrough's
baseline. Always inspect the dry-run before anything leaves the machine. Parse the real command's
JSON and use its `cloud_url` as the baseline portal link; syncing does not mutate the earlier
`baseline_results.cloud_url`.

Use `baseline_results.sync_session_id` only after feature-detecting that public attribute and a
non-empty value. If unavailable, leave the baseline local and report it from the saved local
results - do not inspect private storage or substitute `--all`, whatever the reason: any gap here is
tracked upstream and the fix belongs there.

An empty value is a normal answer, not a failure. The field carries a live id when the local store
holds the authoritative copy of the run - this walkthrough's baseline, run with no Traigent key -
and is empty when the backend tracked the run end to end, because then there is nothing to upload
and `cloud_url` already names it. Read the field itself, never a `metadata` mirror of it, and do not
carry it across a reload: it names a record in one machine's store, and a result loaded from disk
may have come from another.

## Broader optimization

The enhanced space carries no pre-baseline placeholder to replace. Every value in it is fixed
before either run, because the three behaviour knobs are binary and temperature was selected once - there is
no swept range to re-centre on the baseline's winner, and so no between-runs edit for anything to
get wrong. A baseline observation can suggest a later experiment; the space-construction rules in
`references/run-safety.md` preserve the customer's existing dimensions and values in this comparison.

The config-space document is serialized from the space this call receives, so it records what the
search actually got - but nothing is on disk while the search runs.
Three steps in order give the file one meaning and no other, *this is the space the search that just
completed received*:

- **Serialize before the call.** The bytes are frozen from the same `ENHANCED_SPACE` object the call
  is about to receive, so no later edit to the space can drift into them.
- **Unlink before the call.** Ordering alone only protects a first run. A retry - the space is
  narrowed, or the previous search failed and is resumed - starts with the earlier run's document
  already on disk, and if this search raises, that stale file survives as evidence for a search that
  is no longer the one being reported. Removing it makes the file's existence conditional on *this*
  search, not on any search ever having run.
- **Write after trials and the portal are confirmed.** A search that returns having executed
  nothing did not search the space, and one that lost the portal is not the managed search being
  reported, so the document is persisted after `optimized_results.trials` and the tracking check
  pass rather than merely after the call returns.

A run that legitimately stops earlier, raises, completes no trial, or loses the portal therefore
emits no document at all, and the closing score honestly reports the agent pillar as not yet
measured. Re-write the
document whenever the space changes. Its shape is documented in `references/run-safety.md`, and the
finished file is passed to the closing readiness score with `--config-space`.

After the account/key handoff, start a fresh process with
`TRAIGENT_FIRST_RUN_PHASE=connected` and the same three approved cost figures, this time carrying
the baseline's spend, all supplied by the process and never by `.env`. It loads the
updated `.env`; the earlier process cannot see that edit. Run the zero-LLM portal probe, then one
connected search with the same function, tuning dataset, and evaluator:

```python
if FIRST_RUN_PHASE != "connected":
    raise SystemExit("connected phase file requires TRAIGENT_FIRST_RUN_PHASE=connected")
# Reject an absent or stale baseline record before this process starts a paid search.
baseline_trials, baseline_incumbent = load_baseline_transfer(
    BASELINE_TRANSFER_FILE,
    BASELINE_CONFIG,
    config_space_document(BASELINE_SPACE),
    len(PROBE_INPUTS),
    PRIMARY_OBJECTIVE.name,
    OBJECTIVE_SIGNATURE,
)
assert os.environ.get("TRAIGENT_API_KEY", "").strip(), "Traigent key is not active"
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run Traigent optimization"
# Frozen from the space this call receives; persisted only once this search has
# returned trials of its own and reached the portal.
config_space_evidence = (
    json.dumps(config_space_document(ENHANCED_SPACE), indent=2, sort_keys=True) + "\n"
)
# An earlier run's document describes an earlier search. It must not survive
# this one, whatever this one does.
Path(CONFIG_SPACE_DOCUMENT).unlink(missing_ok=True)
error_path = RUN_DIR / "optimization-error.json"
try:
    # A retry that succeeds must not retain the previous attempt's failure.
    error_path.unlink(missing_ok=True)
except OSError:
    raise SystemExit(
        "Managed optimization did not start: the stale sanitized error artifact could not be removed."
    ) from None
try:
    assert_wiring_still_proven()
    optimized_results = agent.optimize_sync(
        algorithm="auto",
        configuration_space=ENHANCED_SPACE,
        max_trials=ENHANCED_MAX_TRIALS,
        # None, never a number: 600 s here cut a 12-trial search at 7.
        timeout=OPTIMIZATION_TIMEOUT_SECONDS,
        save_to=OPTIMIZED_RESULTS,
    )
except BaseException as exc:
    # pyo3 panic exceptions inherit directly from BaseException. Preserve
    # deliberate process cancellation, but turn SDK/provider failures into a
    # bounded artifact and a non-traceback exit. Never persist str(exc): an SDK
    # error can contain prompts, outputs, endpoints, personal data, or secrets.
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise
    try:
        error_path.write_text(
            json.dumps(
                {
                    "status": "managed-optimization-stopped",
                    "error_type": type(exc).__name__,
                    "detail": "Raw exception omitted; inspect it locally and redact before reporting.",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Suppress both the artifact failure and the original exception. Python
        # otherwise prints the original as chained context, undoing the redaction.
        raise SystemExit(
            "Managed optimization stopped; the sanitized error artifact could not be written."
        ) from None
    raise SystemExit(
        f"Managed optimization stopped ({type(exc).__name__}); see {error_path}"
    ) from None
assert optimized_results.trials, "optimization did not execute"
# Here rather than beside the closing checks: held-out scoring is the next
# paid pass, and a run that reached no portal must not buy it - nor is such a
# run the managed search a config-space document would stand as evidence for.
tracking_loss = tracking_stopped() or (
    None if optimized_results.cloud_url is not None else "no portal link came back"
)
if tracking_loss:
    raise SystemExit(
        f"The connected search did not reach the portal ({tracking_loss}); no "
        f"further paid work runs. Report the trials in {OPTIMIZED_RESULTS}, the "
        "spend this process printed, and the baseline still standing."
    )
Path(CONFIG_SPACE_DOCUMENT).write_text(config_space_evidence)
frontier_trials = frontier_at_or_above(
    [*baseline_trials, *optimized_results.trials],
    PRIMARY_OBJECTIVE.name,
    baseline_incumbent,
    PRIMARY_OBJECTIVE.orientation,
    expected_rows=len(PROBE_INPUTS),
    compare_cost=INCLUDE_COST_OBJECTIVE,
)
```

Keep `algorithm="auto"` here, and never pin `grid` or `random` for the connected search. `auto` is
the managed path: it resolves to a cloud-brain execution intent and lets Traigent pick the method,
which is the entire point of the second run. Explicit `grid` or `random` selects configurations
locally; a valid key may still portal-track that local search, but it does not turn it into managed
configuration selection. The managed methods are reachable through `auto` on a connected run.

The pinning rule is therefore per phase, not global: pin the baseline so it is reproducible, leave
the enhanced run on `auto` so it is actually optimized. If a connected search reports a local
fallback reason, treat that as a failure to investigate rather than a result to present - the run
did not do what the report will claim it did.

`TRAIGENT_REQUIRE_CLOUD=1`, set for this phase in the contract above, is why that check is a
backstop rather than the only defence: with it, session-creation failure raises before any trial.
It is set only here, because it fails any run that creates no backend session, which is what the
baseline is - so an inherited true value stops the baseline before spending instead of being
silently removed, and the guard's own message says how to relaunch after approval. It is necessary
and not sufficient: `TRAIGENT_OFFLINE` and `TRAIGENT_OFFLINE_MODE` each resolve the run to
local-only before a session is ever attempted, so the contract refuses the connected phase under
either instead of clearing it - where the user's data may go is their choice, not this run's.

Because the phase now fails instead of degrading, own the failure. The canonical call above catches
ordinary SDK/provider exceptions and pyo3 panic exceptions, while preserving deliberate
`KeyboardInterrupt`/`SystemExit`. It persists only the exception type and a fixed explanation, then
exits nonzero without a traceback. Never save or display raw `str(exc)`: exception text can contain
prompts, outputs, endpoints, personal data, or credentials. Inspect it locally, sanitize the useful
category, and route that sanitized account through the ordinary honest-report path. If even the
sanitized artifact cannot be written, the nested fallback exits with a fixed message and suppresses
both exception contexts, so the original text still cannot leak through chaining. Before a retry,
the wrapper removes that artifact or stops before spending; a later success can therefore never
leave an earlier `managed-optimization-stopped` record beside it.

Two shapes reach that handler and they cost differently. A session that cannot be created fails
before any provider trial, so nothing was spent and the honest report is "the managed run did not
start", with the sanitized reason and the baseline still standing as the result. A managed run that
loses the brain mid-flight raises after some trials are already paid for: recover what the SDK
persisted, report the trials that completed, take the cumulative budget debit and the separately
reported known call cost from this process's exit report, and say plainly that the search
stopped early rather than presenting a partial frontier as the answer. Neither shape is a
reason to re-run the phase without the flag - that would buy back the exact result this prevents.

Do not enable mock mode in this process. The optimization space must include the current
configuration and every baseline value, plus meaningful added knobs that the function consumes.
`max_trials` is a cap rather than an SDK-enforced minimum, passed straight through as
`max_trials=ENHANCED_MAX_TRIALS`, so returned trials never exceed it - unlike the baseline's
twelve-point space, where "all twelve" already names the whole result. `12` is therefore the ceiling and
not a floor beneath a higher count, which is why everything the user reads states it as a ceiling -
"up to 12 configurations" - rather than as a range. Report the actual count and stop reason. Fewer
than 10 trials requires a concrete backend stop, timeout, cost-limit, or failure explanation rather
than being presented as the intended first-run comparison; that floor is this assistant's own
honesty check on a short run, not a count promised to the user, so it stays out of the user-facing
copy while continuing to govern what may be called the intended comparison.

If an optional optimization timeout was set and `stop_reason == "timeout"`, with or without
completed trials, follow the Recovery rules in `references/run-safety.md`; the enhanced run is
uncapped by default, so this is defensive handling rather than the normal path. Do not
describe another invocation as "resume" unless the installed SDK exposes a public resume API.

## Result checks

**Read candidates through the public SDK, on the metric the run actually declared.** The same
adapter reads baseline and enhanced trials without a provider call. Its default compares the
primary criterion alone. Pass `compare_cost=True` only after establishing complete cost provenance
for the comparison, including the incumbent. The recorded objective mode must also include cost;
recovered telemetry does not reopen cost comparison after primary-only execution. The SDK owns
dominance in both cases:

```python
def frontier_at_or_above(
    trials, metric_name, incumbent, orientation="maximize", *, expected_rows,
    compare_cost=False,
):
    """SDK candidates no worse than the incumbent, with an optional measured-cost axis.

    Use the actual primary metric key and orientation, not built-in exact match
    or best_score (which may combine quality and cost). Unknown costs never
    disqualify primary-only candidates or act as tie-breakers. The caller
    establishes cost provenance before enabling the optional axis.
    """
    if orientation not in ("maximize", "minimize"):
        raise ValueError("orientation must be 'maximize' or 'minimize'")
    if type(expected_rows) is not int or expected_rows <= 0:
        raise ValueError("expected_rows must be the positive tuning row count")
    import math
    from traigent import ParetoFrontCalculator

    def measured_number(value):
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value)
        )

    def complete(trial):
        rows = (getattr(trial, "metadata", None) or {}).get("example_results")
        return (
            getattr(trial.status, "value", trial.status) == "completed"
            and measured_number(trial.metrics.get(metric_name))
            and isinstance(rows, list) and len(rows) == expected_rows
            and all(
                isinstance(row, dict) and row.get("success") is True
                and measured_number((row.get("metrics") or {}).get(metric_name))
                for row in rows
            )
        )

    if not complete(incumbent):
        raise ValueError("The incumbent has no complete tuning measurement; no comparison is valid")
    if compare_cost and not measured_number(incumbent.metrics.get("cost")):
        raise ValueError("The incumbent has no measured cost for a cost comparison")
    floor = incumbent.metrics[metric_name]
    upward = orientation == "maximize"
    eligible = []
    for trial in trials:
        if not complete(trial):
            continue
        score = trial.metrics.get(metric_name)
        cost = trial.metrics.get("cost")
        if compare_cost and not measured_number(cost):
            continue
        meets_floor = score >= floor if upward else score <= floor
        if meets_floor:
            eligible.append(trial)
    names = [metric_name, "cost"] if compare_cost else [metric_name]
    directions = {metric_name: upward, **({"cost": False} if compare_cost else {})}
    frontier = ParetoFrontCalculator(maximize=directions).calculate_pareto_front(
        eligible, names
    )
    if compare_cost:
        frontier = sorted(frontier, key=lambda point: point.objectives["cost"])
    else:
        frontier = sorted(
            frontier, key=lambda point: point.objectives[metric_name], reverse=upward
        )
    return [point.trial for point in frontier]
```

Keep the incumbent visible as the option to retain the current configuration. The quality floor
stays strict in both directions; the public SDK's comparison tolerance (`1e-10` in the pinned SDK)
does not admit a point worse than that floor. Pass original trials, preserving their configurations.
Pass the selected incumbent trial and `expected_rows=len(PROBE_INPUTS)`; missing per-example
evidence does not establish a complete measurement. Inspect the installed result's public fields
if its shape differs from the pinned SDK's `metadata["example_results"]` dictionaries.
For a cost comparison, the incumbent and every compared point need measured cost provenance;
unknown-pricing `0.0` is not a free-route measurement. Without that evidence, compare the primary
criterion alone, report cost comparison unavailable, and make no savings or cheapest-choice claim.
`references/evaluation-and-dataset.md` owns choosing one candidate and handling a quality tie.

Do not pass `strategy=` or `strategy_params` to obtain this: use the public calculator through the
adapter above. The pinned SDK removed its named selection presets, and the decorator raises
`TypeError` for either argument; nothing may silently change the metric or winner this report describes.

When the recorded plan has no independent held-out rows, skip this pass and report no held-out
measurement. Otherwise score the reserved rows with the run's recommended configuration, when SKILL section 7 says to,
against `HOLDOUT_DATASET` through the same loader and the same `task_score` the search used.
`references/evaluation-and-dataset.md` owns which configuration that is - one call of
`evaluate_holdout`, never one per candidate, whatever the rounds returned. The returned
cost joins the single running total exactly as a baseline phase does; `references/run-safety.md`
owns what the approval discloses about those calls. These and a judge's are the walkthrough's only
paid calls that no permit covers, so they are also the ones the two gates above are written for: the
pass refuses to start unless the remaining funds every row and its grading, and the wrapped
`litellm.completion` refuses each call individually once it does not.

```python
def evaluate_holdout(config: dict) -> tuple[float, float | None]:
    scores = []
    holdout = traigent.Dataset.from_jsonl(HOLDOUT_DATASET)
    if not holdout.examples:
        raise ValueError("No independent held-out rows; skip held-out scoring, no call was placed")
    # All of these rows or none of them, decided before the first one is paid
    # for. This is the run's most expensive configuration on rows nothing else
    # scores, and it is the last paid work in the walkthrough - so it is also
    # where an exhausted total is likeliest to arrive.
    refuse_unless_it_fits(
        len(holdout.examples) * CALLS_PER_SCORED_ROW, "held-out scoring"
    )
    assert_wiring_still_proven()
    # Every call this pass places falls between these two marks, a judge's
    # grading calls included. Summing the slice rather than the agent call's own
    # cost is what stops a judged pass from reporting half of what it spent to
    # the running total - and one unpriced call anywhere in it makes the whole
    # figure `not measured` rather than a sum missing a row.
    first_call = len(RUN_CALL_COSTS)
    for example in holdout.examples:
        input_data = example.input_data
        expected = example.expected_output
        output, _agent_cost = call_agent(holdout_agent_input(input_data), config)
        scores.append(task_score(output, expected, input_data))
    costs = RUN_CALL_COSTS[first_call:]
    tracked_cost = None if any(cost is None for cost in costs) else sum(costs)
    return sum(scores) / len(scores), tracked_cost
```

Report the selected baseline configuration and the selected enhanced configuration on the tuning
evidence actually produced in this run. Show the best config, score, cost, latency, stop reason,
and direct portal links for every persisted run. Put the two results side by side, explain the
knob differences, and state what changed in the measured tuning behavior. The baseline, search,
and holdout must use the same selected public evaluation path, using the same installed public
`traigent.Dataset.from_jsonl` loader. This first-run comparison does not establish generalization
or expected production improvement, and the held-out score does not convert it into one: that
split is assistant-visible, non-blind, and too small to settle a difference.
`references/evaluation-and-dataset.md` owns the reservation, the disclosure format, and the
small-sample caveat.

At close, name the copied `traigent-runs/run_wrapper.py` and sanitized
`traigent-runs/baseline-transfer.json` among this run's local artifacts.

Before reporting:

```python
assert baseline_results.trials, "baseline did not execute"
assert optimized_results.trials, "optimization did not execute"
assert baseline_results.best_config is not None, "no baseline winner selected"
assert optimized_results.best_config is not None, "no best configuration selected"
```

Also verify that a user-owned baseline was preserved exactly, or that the generated baseline
returned all twelve intended distinct configurations, its initial one among them. Inspect
failed trials, cost tracking, truncation, declared measures, stop reason, and persistence status
as defined in `run-safety.md`. The baseline portal URL, when exact sync was supported, comes from
the successful sync JSON; otherwise label it local-only. Keep and link every experiment actually
persisted. Portal experiment deletion is never walkthrough teardown and requires a later explicit
user request. Do not apply the best configuration automatically. Export it as a candidate and ask
before any production change.
