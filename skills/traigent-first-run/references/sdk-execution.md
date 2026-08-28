# SDK Execution

Use this reference after component creation and before writing the run wrapper.

## Contents

1. Capability discovery
2. Automatic run bounds
3. Walkthrough model ladder
4. Decorator contract
5. Small baseline sweep
6. Broader optimization
7. Result checks

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
| Dataset loader and example fields (`.input_data` / `.expected_output` / `.metadata`) | `traigent.Dataset` (`Dataset.from_jsonl`) |
| `optimize_sync(...)` and its result object | the decorated function (`agent.optimize_sync`) |
| Knob recommendations - `recommend_configuration_space(agent_type)`, agent_type `rag` or `code_gen` | `traigent.config_generator.recommendations` |

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
timeout and total spend by the ceiling. Keep a first run from taking too long by sizing it up
front, not by cutting it: if the runtime estimate is too high, reduce the run before starting - a
smaller representative tuning slice, fewer trials, or a smaller model set - and disclose the
revised estimate; a large *preserved* baseline (never shrink a user-owned one) then runs to
completion under the cost ceiling rather than being truncated. The estimate above still drives the
up-front time/cost disclosure and the baseline phase timeout (`timeout=BASELINE_TIMEOUT_SECONDS`, a
small fixed grid). Set `TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS` only for the rare case that
genuinely needs a hard wall-clock stop.

Keep an individual model-request timeout so one stuck provider call cannot hang the walkthrough.
Reuse the real agent's existing value when present. Generated LiteLLM walkthrough code may use a
reasonable internal fallback such as 120 seconds, adjusted automatically after the live probe.
This is not a new retry policy.

Use one total walkthrough ceiling, `$5.00` by default. Every paid process is launched with that
total and with what earlier phases already spent, and the decorator contract below turns the pair
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
  within the 12-trial cap and, with `model`, at the four varying knobs the readiness scorer pays
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

**`self_check` is gone, and `reflect` is the one that stayed.** They were one knob under two names:
both appended "look at your answer again and fix it", differing only in what the model was told to
look at, and no customer-facing sentence tells those apart without becoming two sentences that mean
the same thing. `reflect` is the usual name for the technique.

The synthesized walkthrough dataset contains 18 tuning rows: 3 easy, 5 medium, 5 hard, and 5 very
hard, plus the ten held-out rows reserved at creation time in their own file, which no search
ever evaluates. The baseline's two non-model axes are `prompt_style` and `thinking_shape` because the enhanced
space carries both: a baseline that ranks a lever the enhanced run will not use has measured nothing
usable, which is what temperature became once it was pinned. Every baseline value is kept, so the
baseline is a strict subset and the enhanced run never gets a model the baseline did not measure, so
a measured difference cannot be explained by quietly upgrading the model. The coding assistant
fixes every generated value before either run; the user is never asked to pick values or edit the
wrapper. The assistant adds the disclosed
controls; Traigent performs managed, cost-aware selection among them. Keep those actors separate
in the report.

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
| `retrieval_k` | two counts within 1-5 | not part of this first-run paid space; retrieval is indirect and needs separately contained tracing |
| `context_format` | two layouts | retrieved or structured context is pasted in raw |
| `tool_policy` | two policies | not part of this first-run paid space; tool behavior is indirect and needs separately contained tracing |
| `temperature` | the customer's own values | only when preserving a customer-owned sweep - see below |

This first run includes only direct request parameters: values this finalized wrapper passes to
its single model request and whose distinct values produce distinct dicts for every selected model
and tuning input. Source inspection does not
prove the customer's original agent varies. Retrieval, tool, repair, and multi-call controls -
including task decomposition and self-consistency - are indirect even when changing one also changes
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
row count in the enhanced space and add only direct request parameters the probe establishes for
every selected model and tuning input. Indirect, retrieval, tool, repair, and multi-call controls
stay outside this paid space. Adding a cheaper or stronger model changes the experiment
and attribution, so do it only as a separately disclosed and approved model comparison. Preserve an
existing flagship and its calling convention exactly; never replace or augment it silently.

For the generated ladder, use one model family when the selected route can supply all three model
choices. One family keeps the result readable - "the mid tier held the strong tier's accuracy at a
fraction of the cost" is a sentence the user can act on - keeps a single company receiving the
user's prompts, and keeps one bill. If the chosen vendor does not expose at least three usable
model choices, ask the user to add a second vendor only for the missing model(s), and name that
extra provider in the approval. When using OpenRouter, one key reaches every family; still prefer
one family by default, and borrow a missing model from a second family only when the chosen family
lacks it, naming that extra provider in the approval.

These three model slots are roles, not hardcoded ids: pick concrete model ids from what the
selected route lists at run time, then verify each id is live and cost-tracked before scaling, as
`run-safety.md` already requires.

## Decorator contract

Use one production-compatible function for baseline and optimization:

```python
import atexit
import contextvars
import json
import math
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

RUN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RUN_DIR.parent
APPROVED_FIGURE_NAMES = (
    "TRAIGENT_FIRST_RUN_COST_CEILING_USD",
    "TRAIGENT_FIRST_RUN_COST_SPENT_USD",
    "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD",
)
# Read before dotenv: a stale .env cannot opt into connected work. Baseline is
# the fail-safe default.
FIRST_RUN_PHASE = os.environ.get(
    "TRAIGENT_FIRST_RUN_PHASE", "baseline"
).strip().casefold()
# The three approved figures, read here for the same reason and taken from this
# dict below rather than from the environment again. `load_dotenv` fills an
# ABSENT process variable from the file, so figures left in `.env` would have
# supplied the ceiling, the running total and the per-call rate - and the
# refusal below, which exists so a phase launched without an approval cannot
# start, would have found them present and passed. Measured against an
# otherwise empty environment and a `.env` naming all three: the block ran to
# completion on the file's ceiling and wrote it into TRAIGENT_RUN_COST_LIMIT.
APPROVED_FIGURES = {name: os.environ.get(name) for name in APPROVED_FIGURE_NAMES}
load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ.pop("TRAIGENT_FIRST_RUN_PHASE", None)
for _approved_name in APPROVED_FIGURE_NAMES:
    # Popped like the phase flag, so a child process inherits neither an
    # approval nor a running total it was not launched with.
    os.environ.pop(_approved_name, None)
if FIRST_RUN_PHASE not in {"baseline", "connected"}:
    raise SystemExit("TRAIGENT_FIRST_RUN_PHASE must be 'baseline' or 'connected'")
def inherited(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# Both phases are paid, and a canned response costs nothing and proves nothing.
# The SDK honours an inherited mock flag outside production, so neither phase
# may start under one.
if inherited("TRAIGENT_MOCK_LLM"):
    raise SystemExit(
        "TRAIGENT_MOCK_LLM is set. Both measurements would run on canned "
        "responses, so every score would describe the mock and not the agent. "
        "Unset it before a paid phase; this run will not unset it for you."
    )
if FIRST_RUN_PHASE == "baseline":
    if inherited("TRAIGENT_REQUIRE_CLOUD"):
        raise SystemExit(
            "TRAIGENT_REQUIRE_CLOUD requires a backend session, but the baseline "
            "is deliberately local. Stop before paid work, disclose this conflict "
            "on the baseline approval card, and only after approval launch a new "
            "baseline process with TRAIGENT_REQUIRE_CLOUD=0 in its environment. "
            "Do not merely unset it: .env could restore the true value."
        )
    # Backend-offline is process-local: a stored CLI credential can survive
    # removing the environment key, so this is what keeps the baseline local.
    os.environ["TRAIGENT_OFFLINE_MODE"] = "true"
    os.environ.pop("TRAIGENT_API_KEY", None)
else:
    # Both spellings: the SDK reads either as offline, and either resolves this
    # run to local-only BEFORE a session is attempted - so the flag below is
    # never consulted and the run completes locally with the guard apparently on.
    for offline_name in ("TRAIGENT_OFFLINE", "TRAIGENT_OFFLINE_MODE"):
        if inherited(offline_name):
            raise SystemExit(
                f"{offline_name} is set, which resolves this run to local-only "
                "before a backend session is attempted and so silently defeats "
                "TRAIGENT_REQUIRE_CLOUD: this phase would spend on a local "
                "search and report it as the managed one. Unset it deliberately "
                "to run connected, or stop at the local baseline. This run will "
                "not unset it for you - where data may go is a choice to make."
            )
    # Managed search or nothing. Without this the SDK degrades a connected run
    # whose backend session cannot be created - absent, wrong, or unscoped key,
    # backend unreachable - to a local sweep, and returns a result that reads
    # like the managed one the user approved paying for.
    os.environ["TRAIGENT_REQUIRE_CLOUD"] = "1"


def approved_usd(name: str) -> float:
    """One figure out of the approval, in USD. No default, ever.

    A default here would be a number nobody approved. Absent one of these, the
    SDK's own per-optimization default governs instead - built fresh per call,
    so every phase would get the whole of it and none of them would know what
    the earlier phases already spent. Read out of the pre-dotenv capture above,
    which is what makes "never in .env" a refusal rather than a request.
    """
    raw = (APPROVED_FIGURES.get(name) or "").strip()
    if not raw:
        raise SystemExit(
            f"{name} is not set, and this phase spends real money. Supply the "
            "approved figures in this process's environment - never in .env, "
            "which outlives the approval that set them - and start it again."
        )
    try:
        value = float(raw)
    except ValueError:
        # Caught rather than left to surface: every other way this figure can
        # be wrong stops with a sentence naming the remedy, and a bare
        # ValueError on a comma decimal would be the one that does not.
        raise SystemExit(
            f"{name} is {raw!r}, which is not a number of USD. Write it plainly "
            "as 5.00 - a decimal comma, a currency symbol, or a thousands "
            "separator is not read as a figure here."
        ) from None
    if not math.isfinite(value) or value < 0:
        raise SystemExit(f"{name} must be a finite, non-negative number of USD")
    return value


# The total the user approved, and the single running total at the moment this
# process starts - the tracked-or-deducted spend of every earlier paid phase,
# `0` only while nothing has been spent yet. Two figures rather than one
# remaining, so the process says what was approved as well as what is left.
RUN_COST_CEILING_USD = approved_usd("TRAIGENT_FIRST_RUN_COST_CEILING_USD")
RUN_COST_SPENT_USD = approved_usd("TRAIGENT_FIRST_RUN_COST_SPENT_USD")
# What one provider call is deducted for when its route reports no cost.
# Without it an unpriced route makes the ledger below a no-op: every call
# deducts nothing, the remaining never falls, and nothing ever refuses.
UNTRACKED_CALL_COST_USD = approved_usd("TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD")
RUN_COST_REMAINING_USD = RUN_COST_CEILING_USD - RUN_COST_SPENT_USD
if UNTRACKED_CALL_COST_USD <= 0:
    raise SystemExit(
        "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD must be positive: a zero "
        "deduction lets an unpriced route run until something else stops it"
    )
if RUN_COST_REMAINING_USD < UNTRACKED_CALL_COST_USD:
    raise SystemExit(
        f"${RUN_COST_REMAINING_USD:.4f} of the approved "
        f"${RUN_COST_CEILING_USD:.2f} is left, which does not cover one "
        f"provider call at ${UNTRACKED_CALL_COST_USD:.4f}. Take a larger total "
        "back to the user; do not start a phase that cannot finish one call."
    )
# Placed with the other process-scoped SDK settings, before the import, so it is
# already in the environment whenever the SDK builds its enforcer from it. That
# enforcer polices this number per trial for this phase, in place of a default
# that knows nothing about this walkthrough. `repr` rather than a rounded
# format: a remaining that rounds to zero is refused above, not written out as
# a limit no trial can fit under.
os.environ["TRAIGENT_RUN_COST_LIMIT"] = repr(RUN_COST_REMAINING_USD)
# Process-only, and set because the alternative is worse than it looks: without
# it the SDK opens its own handshake whenever its pre-run estimate exceeds the
# limit, and that handshake's third option RAISES the limit to the estimate
# times 1.5 - past the approved total, on one keystroke, in the middle of a run
# the user already approved. It also short-circuits a stored approval token,
# which raises the limit to whatever the token names. Neither can move this
# number now, and the SDK's per-trial admission check is untouched.
#
# It costs two things, and both are named here rather than left to be found,
# because a flag governing spend cannot have an effect nobody wrote down.
#
# The SDK's pre-run check on models it holds no price for downgrades from a
# refusal to a warning. That gap has an owner - `run-safety.md` requires every
# selected model be verified live and cost-tracked before scaling - and a route
# the SDK cannot price still debits the ledger below at the conservative rate.
#
# And the handshake is one branch of a gate that otherwise refuses, so stopping
# the branch stops the gate. `is_cost_preapproved` returns true on this variable
# alone, so `check_and_approve` approves before comparing anything: a phase
# whose whole-phase estimate exceeds the limit is no longer refused cleanly
# before its first trial. Nothing here replaces that with a second estimate -
# one obliged to agree with the SDK's own is the two-caps defect rejected below,
# and a flat conservative rate over a whole phase would refuse runs that fit.
# What bounds the phase instead is the per-trial admission check against the
# remaining, which stops it and reports `stop_reason`; the refusal above, for a
# remaining too small for one call; and the ledger below, for the calls no
# permit sees. So the loss is specific: a phase that does not fit spends up to
# the approved total and stops partway, where it would have refused having spent
# nothing.
#
# Both of those stop AGAINST the total rather than capping it, and the
# difference is money. Admission and the ledger each decide before a call, on a
# flat conservative per-call figure, while nothing here sets `max_tokens` - so a
# strong-tier or judge call can legitimately cost more than the figure it was
# admitted under, and the last call of a phase can carry the running total past
# the approved one. The approved ceiling halts further spending; it is not a
# bound on what the provider bills for a call that has left, and
# `run-safety.md` owns that rule.
os.environ["TRAIGENT_COST_APPROVED"] = "true"
SDK_RESULTS_DIR = RUN_DIR / "sdk-results"
if not os.environ.get("TRAIGENT_RESULTS_FOLDER", "").strip():
    os.environ["TRAIGENT_RESULTS_FOLDER"] = str(SDK_RESULTS_DIR)
# SDK 0.26.0 otherwise stores query/response/expected text in local per-example
# logs. The first-run record needs ids and metrics, not another copy of content.
os.environ["TRAIGENT_LOG_EXAMPLE_CONTENT"] = "false"

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

TUNING_DATASET = str(RUN_DIR / "tuning.jsonl")
# A separate file, not a column in the tuning one: only `eval_dataset=TUNING_DATASET`
# below reaches the search, so a reserved row cannot be scored during selection.
HOLDOUT_DATASET = str(RUN_DIR / "holdout.jsonl")
BASELINE_RESULTS = str(RUN_DIR / "baseline-results.json")
OPTIMIZED_RESULTS = str(RUN_DIR / "optimized-results.json")
CONFIG_SPACE_DOCUMENT = str(RUN_DIR / "config-space.json")
SELECTED_CURRENT_MODEL = os.environ["TRAIGENT_FIRST_RUN_CURRENT_MODEL"]
SELECTED_ALTERNATIVE_MODEL = os.environ["TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL"]
SELECTED_STRONG_MODEL = os.environ["TRAIGENT_FIRST_RUN_STRONG_MODEL"]
# Set only when the strong tier is a reasoning model; blank means no reasoning kwargs.
STRONG_REASONING_EFFORT = (
    os.environ.get("TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT", "").strip() or None
)
SELECTED_CURRENT_PROVIDER = os.environ["TRAIGENT_FIRST_RUN_CURRENT_PROVIDER"].casefold()
# Every name litellm will authenticate a route on, any one of which is enough.
# The same inventory `preflight.py` opens the run with, name for name on every
# route a variable settles - Bedrock is the one it does not, and its reason is
# below - because a gate that admits a credential in front of a run that
# refuses it stops a customer on a call that would have succeeded. Neither copy
# is the authority and neither is checked against the other alone: the suite
# reads the names out of the installed client's own resolution code, so a route
# whose second name is in nobody's documentation - `OR_API_KEY`, `CO_API_KEY`,
# `PALM_API_KEY` - is still a name a customer's key can be sitting in.
PROVIDER_KEY_NAMES = {
    "openrouter": ("OPENROUTER_API_KEY", "OR_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "PALM_API_KEY"),
    "mistral": ("MISTRAL_API_KEY", "MISTRAL_AZURE_API_KEY"),
    "cohere": ("COHERE_API_KEY", "CO_API_KEY"),
    "huggingface": ("HF_TOKEN", "HUGGINGFACE_API_KEY"),
    # Empty because no environment name settles it: Bedrock signs through the
    # AWS credential chain, so a shared profile, an SSO session, or an instance
    # role authenticates with no `AWS_*` variable set at all. Refusing on their
    # absence would stop a run whose calls would have gone through, so this
    # route is declared and left to fail, if it fails, on its own first call.
    "bedrock": (),
}
# One route, two literals. litellm sends `command-r` to `cohere_chat` and
# `command` to `cohere`, through one branch written `== "cohere_chat" or ==
# "cohere"` that reads the same two names for both - so which spelling an
# assistant derives depends on the model it read, not on the credential.
ROUTE_ALIASES = {"cohere_chat": "cohere"}

# Select this literal from the inspected task and evaluator before either paid
# run. Zero belongs only to deterministic/exact work; otherwise use one
# supported nonzero value that permits the expected variation. Keep it fixed across both phases so
# it does not become a fourth paid knob or confound their comparison.
WALKTHROUGH_TEMPERATURE = 0.0


def positive_number(name: str, *, default: float | None = None) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        if default is None:
            raise ValueError(f"{name} is required")
        value = default
    else:
        value = float(raw_value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def positive_int(name: str, *, default: int | None = None) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        if default is None:
            raise ValueError(f"{name} is required")
        value = default
    else:
        value = int(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def optional_positive_number(name: str) -> float | None:
    """Return a positive float from the environment, or None when unset - used
    for bounds that are intentionally uncapped by default."""
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None
    value = float(raw_value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


MODEL_REQUEST_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_MODEL_REQUEST_TIMEOUT_SECONDS",
    default=120.0,
)
BASELINE_TIMEOUT_SECONDS = positive_number(
    "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS"
)
# No wall-clock cap on the enhanced optimization by default (None): the search
# runs to its trial cap, bounded by the total cost ceiling and the per-model-
# request timeout above. Set the env var only to add an optional wall-clock limit.
OPTIMIZATION_TIMEOUT_SECONDS = optional_positive_number(
    "TRAIGENT_FIRST_RUN_OPTIMIZATION_TIMEOUT_SECONDS"
)
BASELINE_TRIALS = positive_int(
    "TRAIGENT_FIRST_RUN_BASELINE_TRIALS",
    default=12,
)
ENHANCED_MAX_TRIALS = positive_int(
    "TRAIGENT_FIRST_RUN_ENHANCED_MAX_TRIALS",
    default=12,
)


def require_current_route_credential() -> None:
    route = ROUTE_ALIASES.get(SELECTED_CURRENT_PROVIDER, SELECTED_CURRENT_PROVIDER)
    key_names = PROVIDER_KEY_NAMES.get(route)
    if key_names is None:
        raise RuntimeError(
            f"No first-run credential mapping is declared for the inspected "
            f"provider route {SELECTED_CURRENT_PROVIDER!r}"
        )
    # A placeholder is not a credential: `NAME=# paste your key here` survives
    # `.strip()`, and the gate that opened this run already refuses it.
    if key_names and not any(
        os.environ.get(name, "").strip().partition("#")[0] for name in key_names
    ):
        # One name reads as one name. "none of OPENAI_API_KEY is set" was
        # grammatical nonsense at exactly the moment the reader is stuck.
        missing = (
            f"but {key_names[0]} is not set. Add that credential"
            if len(key_names) == 1
            else f"and none of {', '.join(key_names)} is set. Add any one of them"
        )
        raise RuntimeError(
            f"The current model route {SELECTED_CURRENT_MODEL!r} uses "
            f"{SELECTED_CURRENT_PROVIDER}, {missing} or explicitly approve a "
            "provider-route change; the first run will not switch routes "
            "automatically."
        )

BASELINE_CONFIG = {
    "model": SELECTED_CURRENT_MODEL,
    # One task-selected value in both phases. This worked exact-output example
    # uses zero; replace WALKTHROUGH_TEMPERATURE before a non-deterministic run.
    "temperature": WALKTHROUGH_TEMPERATURE,
    # `prompt_style`'s first value was "direct" until `thinking_shape` arrived
    # and took that word for the thing it actually describes.
    "prompt_style": "plain",
    "thinking_shape": "direct",
    "reflect": "off",
}
BASELINE_SPACE = {
    # The same three ladder models run in both phases, so the enhanced run
    # never gets a model the baseline did not measure.
    "model": [
        BASELINE_CONFIG["model"],
        SELECTED_ALTERNATIVE_MODEL,
        SELECTED_STRONG_MODEL,
    ],
    "temperature": [BASELINE_CONFIG["temperature"]],
    # Two non-model axes, and both must be knobs the enhanced space carries -
    # otherwise the baseline ranks a lever that run will not use. Two rather
    # than one because the selection rule downstream reads the baseline to
    # choose the enhanced knobs, and one ranked lever is almost nothing to
    # read. It costs 12 paid trials instead of 6; the approval card says so.
    "prompt_style": [BASELINE_CONFIG["prompt_style"], "structured"],
    "thinking_shape": [BASELINE_CONFIG["thinking_shape"], "chain_of_thought"],
    "reflect": [BASELINE_CONFIG["reflect"]],
}
ENHANCED_SPACE = {
    "model": BASELINE_SPACE["model"],
    "temperature": BASELINE_SPACE["temperature"],
    # Three behaviour knobs, two values each, keeping every baseline value: the
    # baseline space is a strict subset of this one.
    "prompt_style": BASELINE_SPACE["prompt_style"],
    "thinking_shape": BASELINE_SPACE["thinking_shape"],
    "reflect": ["off", "on"],
}
# Set True only for an inspected customer baseline. It preserves that space and
# stops before approval for separately approved per-model validation.
BASELINE_IS_USER_OWNED = False
# Readiness evidence for `scripts/readiness.py --config-space`. WIRED_KNOBS
# names only the dimensions call_agent below actually consumes - a knob listed
# here that the agent ignores is a false claim about the search space. The
# scorer cannot check that claim, so the assert under `demonstrably_wired`
# below checks it here at load time.
WIRED_KNOBS = [
    "model",
    "temperature",
    "prompt_style",
    "thinking_shape",
    "reflect",
]
def holdout_agent_input(input_data):
    if isinstance(input_data, str):
        return input_data
    if isinstance(input_data, dict) and isinstance(input_data.get("message"), str):
        return input_data["message"]
    raise TypeError(
        "Dataset input does not match the inspected agent(message: str) contract"
    )


# Before approval, locally prove the exact tuning inputs both paid phases use.
# Keep them only in memory; do not write, print, hash, or log their contents.
_tuning_for_probe = traigent.Dataset.from_jsonl(TUNING_DATASET)
PROBE_INPUTS = tuple(
    holdout_agent_input(example.input_data) for example in _tuning_for_probe.examples
)


def configuration_count(space: dict[str, list]) -> int:
    return math.prod(len(values) for values in space.values())


def config_space_document(space: dict[str, list]) -> dict:
    """Serialize the finalized search space as readiness config-space evidence."""
    return {
        "max_trials": ENHANCED_MAX_TRIALS,
        "knobs": {name: list(values) for name, values in space.items()},
        "wired": list(WIRED_KNOBS),
    }


# Every count this walkthrough claims is pinned here, so "24 configurations"
# is a fact the file refuses to contradict rather than a number in a paragraph.
BEHAVIOUR_KNOBS = ["prompt_style", "thinking_shape", "reflect"]
assert set(BASELINE_CONFIG) == set(BASELINE_SPACE), (
    "every baseline config key must be a grid dimension, or exact trial lookup fails"
)
assert len(set(BASELINE_SPACE["model"])) == 3
assert ENHANCED_SPACE["model"] == BASELINE_SPACE["model"]
assert all(
    set(BASELINE_SPACE[knob]) <= set(ENHANCED_SPACE[knob]) for knob in BASELINE_SPACE
), "the baseline must be a subset, or it ranks levers the enhanced run will not use"
# Unconditional, where it used to fire only under a reasoning strong tier: the
# rule got simpler, not stricter, and the branch that gave the enhanced space a
# second size is gone with it.
assert (
    len(BASELINE_SPACE["temperature"]) == 1 and len(ENHANCED_SPACE["temperature"]) == 1
), "temperature is fixed once, never swept - behaviour knobs carry the search"
assert all(len(ENHANCED_SPACE[knob]) == 2 for knob in BEHAVIOUR_KNOBS)
# 3 models × 2 prompt styles × 2 thinking shapes, and 3 models × 3 binary
# behaviour knobs - both holding whether or not the strong tier reasons.
assert configuration_count(BASELINE_SPACE) == 12
assert configuration_count(ENHANCED_SPACE) == 24
# EQUAL, not "at most". The baseline runs `algorithm="grid"`, which enumerates
# the space in order and stops at the trial cap - so a cap below the size is
# not a smaller sweep, it is a sweep that silently drops whichever
# configurations grid happened to order last, and the baseline's job is to rank
# knobs across all of them. Any override of TRAIGENT_FIRST_RUN_BASELINE_TRIALS
# that is not the space size fails here, at load, rather than quietly measuring
# a truncated space.
assert BASELINE_TRIALS == configuration_count(BASELINE_SPACE)
assert 1 <= ENHANCED_MAX_TRIALS < configuration_count(ENHANCED_SPACE)
assert set(WIRED_KNOBS) == set(ENHANCED_SPACE), (
    "wired knobs must cover exactly the paid dimensions, so the local proof "
    "cannot skip a searched key"
)

OBJECTIVES = ObjectiveSchema.from_objectives(
    [
        ObjectiveDefinition(
            name="task_success", orientation="maximize", weight=1.0
        ),
        ObjectiveDefinition(name="cost", orientation="minimize", weight=1.0),
    ]
)


def build_prompt(
    message: str,
    *,
    style: str,
    thinking_shape: str,
    reflect: str,
) -> str:
    """The three supported prompt controls act at different moments.

    Two knobs with one effect are one
    dimension counted twice, which is why `self_check` is not here: it and
    `reflect` were both "look at your answer again", differing only in what the
    model was told to look at, and that is one dimension under two names.

    `style` frames the task. `thinking_shape` acts DURING the answer - derive
    it step by step instead of emitting it. `reflect` acts AFTER - reconsider
    the finished answer and revise it. A replacement knob from the catalog has
    to survive the same distinct-effect test."""
    if style == "plain":
        prompt = message
    elif style == "structured":
        prompt = (
            "Complete the task below. Follow every requested output constraint and return only "
            f"the requested result.\n\nTask:\n{message}"
        )
    else:
        raise ValueError(f"unsupported prompt style: {style}")
    if thinking_shape == "chain_of_thought":
        prompt += (
            "\n\nReason through the task step by step before you answer, then return only the "
            "requested result."
        )
    elif thinking_shape != "direct":
        raise ValueError(f"unsupported thinking shape: {thinking_shape}")
    if reflect == "on":
        prompt += (
            "\n\nAfter reaching an answer, reconsider whether it is actually correct, and "
            "revise it if it is not. Return only the final answer."
        )
    elif reflect != "off":
        raise ValueError(f"unsupported reflect: {reflect}")
    return prompt


def provider_reported_cost(response) -> float | None:
    # `_hidden_params["response_cost"]` FIRST, because it is the field litellm
    # actually populates and the one the SDK's own accounting reads. Measured
    # against the installed client on five of the six routes this package
    # supports - openai, anthropic, gemini, mistral and cohere - the two
    # readings below it return None on every call, so a door that consulted
    # only those was not a ledger at all: it debited the flat unpriced rate
    # every time and became a call counter. Measured end to end, that counter
    # reported a run at its approved ceiling when the true spend was a
    # twentieth of it, and refused a held-out pass that fitted many times over.
    # Normalised once rather than guarded at the first reading alone: the
    # header reading below reaches the same object, and raised on a non-mapping.
    hidden = getattr(response, "_hidden_params", None)
    hidden = hidden if isinstance(hidden, dict) else {}
    reported = hidden.get("response_cost")
    usage = getattr(response, "usage", None)
    if reported is None:
        reported = getattr(usage, "cost", None)
    if reported is None and isinstance(usage, dict):
        reported = usage.get("cost")
    if reported is None:
        headers = hidden.get("additional_headers")
        if isinstance(headers, dict):
            reported = headers.get("llm_provider-x-litellm-response-cost")
    if reported is None:
        return None
    if isinstance(reported, bool):
        raise RuntimeError("The provider returned malformed response-cost metadata")
    try:
        cost = float(reported)
    except (TypeError, ValueError) as error:
        raise RuntimeError("The provider returned malformed response-cost metadata") from error
    if not math.isfinite(cost) or cost < 0:
        raise RuntimeError("The provider returned an invalid per-response cost")
    return cost


def require_nonzero_token_usage(response) -> None:
    """Distinguish a real free-route response from a canned or missing call."""
    usage = getattr(response, "usage", None)

    def usage_field(name: str):
        if isinstance(usage, dict):
            return usage.get(name)
        return getattr(usage, name, None)

    total_tokens = usage_field("total_tokens")
    if total_tokens is None:
        # Some provider adapters expose only the two component counts. They
        # still prove a real call when every reported component is valid and
        # their sum is nonzero.
        components = [
            value
            for value in (
                usage_field("prompt_tokens"),
                usage_field("completion_tokens"),
            )
            if value is not None
        ]
        if components and all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
            for value in components
        ):
            total_tokens = sum(components)
    if (
        isinstance(total_tokens, bool)
        or not isinstance(total_tokens, (int, float))
        or not math.isfinite(total_tokens)
        or total_tokens <= 0
    ):
        raise RuntimeError(
            "The provider response did not report nonzero token usage; "
            "stop before treating this as a real call"
        )


def require_untruncated_completion(response) -> None:
    """A trial the provider cut off is not a measurement, so refuse it.

    The evaluator cannot tell a cut-off answer from a wrong one, so it scores 0
    rather than low and the model it happened to loses to one that had room.
    Raising sends it to the failed-trial count instead. `run-safety.md` owns
    why nothing here sets or predicts a cap.
    """
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason is None and isinstance(choice, dict):
        finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise RuntimeError(
            "The provider truncated this completion (finish_reason='length'). "
            "It is not a measurement and must not be scored: a cut-off answer "
            "scores 0 rather than low and can crown a weaker model. This "
            "wrapper sets no max_tokens, so if your own agent sets one, raise "
            "it and re-run this configuration; otherwise the answer ran into "
            "the model's own output limit, so drop this configuration and "
            "report it as excluded"
        )


def build_request(message: str, config: dict) -> dict:
    """Build the provider request from one configuration. Pure: makes no call.

    Kept separate from `call_agent` so a wired-knob claim can be probed without
    a network or a key: two configurations that differ in a real search
    dimension must produce two different request dicts.
    """
    sampling_kwargs: dict = {"temperature": config["temperature"]}
    if config["model"] == SELECTED_STRONG_MODEL and STRONG_REASONING_EFFORT:
        # Reasoning models reject sampled temperature, so this model swaps the
        # sampling control for an effort setting rather than sending both. No
        # `max_tokens` here or on any other tier - `run-safety.md` owns why,
        # and it is not an oversight to correct.
        sampling_kwargs = {"reasoning_effort": STRONG_REASONING_EFFORT}
    return {
        "model": config["model"],
        "timeout": MODEL_REQUEST_TIMEOUT_SECONDS,
        **sampling_kwargs,
        "messages": [
            {
                "role": "user",
                "content": build_prompt(
                    message,
                    style=config["prompt_style"],
                    thinking_shape=config["thinking_shape"],
                    reflect=config["reflect"],
                ),
            }
        ],
    }


# Spend on trials this wrapper refused. Both guards below raise, so reading the
# cost after them dropped that money out of every total the run reports: a
# truncated trial was billed for every token generated up to the cut, and
# surfaced as $0. It is spend that bought no measurement - report it, never add
# it to the comparison.
REFUSED_TRIAL_COSTS: list[float] = []
# Every provider call this PROCESS places, in the order it placed them - not
# every call this wrapper places, which is a smaller set and was the defect. The
# two searches run under the SDK's enforcement of the limit set above; a
# held-out row and an LLM judge's grading call do not, because they reach
# `litellm.completion` and the orchestrator's permit never sees it. One list
# holds all of them, because they spend the same approved total: after a search
# has spent most of it, held-out scoring has to see what is actually left rather
# than what was left when this process started.
#
# Two things read WINDOWS of this list - the held-out cost slice and
# `check_scorer_calls` - and a window is exact only while one call is placed at
# a time. Nothing this wrapper starts breaks that: the SDK resolves an
# unspecified `parallel_config` to sequential execution, `trial_concurrency`
# and `example_concurrency` and `thread_workers` all 1, and nothing here
# specifies one. Passing
# `parallel_config={"trial_concurrency": N}` to either `optimize_sync` below, or
# to `traigent.configure`, breaks both reads: a neighbour's call lands inside
# the window, and a scorer then stops for a call it did not place. What it no
# longer costs is money: the door below reserves before it places, under a lock
# held across the read and the reservation and never across the provider call,
# so N callers cannot all pass a remaining that funds one. Nor does a reader
# have to opt in to reach concurrency - `batch_completion` is a thread pool of
# its own and is ledgered - which is why the reservation, and not the
# sequential premise, is what the ceiling rests on.
RUN_SPEND_USD: list[float] = []
# The same calls, in the same order, at what the provider actually reported -
# `None` kept as `None`. The ledger above deducts a conservative figure for an
# unpriced call, which is the right number to bound spending by and the wrong
# one to report as measured cost.
RUN_CALL_COSTS: list[float | None] = []
# Provider calls `task_score` places while scoring ONE row: `0` for a
# deterministic evaluator, `1` for an LLM judge that grades every row, higher
# when one row is graded more than once. Select it from the evaluation method
# this run actually wired, before the connected phase starts; the walkthrough's
# own grades deterministically and so declares nothing.
SCORER_CALLS_PER_ROW: int = 0
# Derived, never kept beside it. One agent call per row plus whatever the
# scorer places; two hand-maintained numbers drift, and this is the one that
# would, because nothing reads it until the last paid pass of the run.
CALLS_PER_SCORED_ROW: int = 1 + SCORER_CALLS_PER_ROW
# The judge's own model, fixed for the whole run and never the trial's. `None`
# while the wired evaluator is deterministic, as this walkthrough's is.
JUDGE_MODEL: str | None = None
# The decorated function the paid phases run. `optimize_sync` binds this run's
# own config object to it, and the SDK's session manager stamps THAT object the
# moment backend tracking fails - measured: the same `id()` on both, and the
# stamp readable from inside the door on the very next call. Assigned beside
# the decorator rather than looked up by name, so a preserved agent under its
# own name is read too and the door reads `None` before any run exists.
TRACKED_RUN: object | None = None
# Held across "is there room, and take it" and across nothing else - never
# across a provider call, which is what made a lock look impossible here.
LEDGER_LOCK: threading.Lock = threading.Lock()
# True while a door invocation is in flight, so a re-entry knows it is nested
# and leaves the money to the invocation that reserved for it. A context
# variable rather than a module flag: a new thread starts with a fresh context,
# so `batch_completion`'s pool is unaffected by its neighbours, and a new task
# copies the current one, so an async fallback re-entering the door still sees
# itself as nested.
INSIDE_THE_DOOR: contextvars.ContextVar = contextvars.ContextVar(
    "traigent_first_run_inside_the_door", default=False
)


def run_remaining_usd() -> float:
    """USD left of the approved total, as this process has observed it."""
    return RUN_COST_REMAINING_USD - sum(RUN_SPEND_USD)


def report_run_spend() -> None:
    """Print what THIS process spent, on every ending `atexit` reaches.

    The ledger dies with the process, so a figure nothing emits reaches neither
    the close nor the next phase's `TRAIGENT_FIRST_RUN_COST_SPENT_USD`. It is
    not the SDK's tracked cost and is not interchangeable with it: this carries
    the conservative debit for every call no route priced, and the spend on
    trials the two response checks refused, and that figure carries neither.

    Registered with `atexit` below rather than written after the last call,
    because the phase that most needs this line is the one that did not finish:
    a transient failure raises out of the search, the connected handler exits,
    and a statement below it never runs. It names what it was launched having
    spent as well as what it spent, because without that the line did not add
    up: a process already carrying earlier spend cannot report its own against
    the whole ceiling and call the difference remaining.

    What it does not cover is measured, one subprocess per ending: finishing,
    `sys.exit` with any status, an uncaught exception, `SystemExit` and SIGINT
    each printed it once; SIGTERM, SIGKILL, SIGHUP, SIGQUIT, `os._exit` and
    `os.abort` printed nothing, because none of them runs `atexit` at all - so
    a `kill -9` or an out-of-memory kill on a long paid phase leaves no figure
    behind. `references/run-safety.md` owns what is carried forward without it.
    """
    spent_here = sum(RUN_SPEND_USD)
    print(
        f"this process placed {len(RUN_SPEND_USD)} provider call(s) and spent "
        f"${spent_here:.4f}; with ${RUN_COST_SPENT_USD:.4f} spent before it "
        f"started, ${RUN_COST_SPENT_USD + spent_here:.4f} of the approved "
        f"${RUN_COST_CEILING_USD:.2f} is gone and ${run_remaining_usd():.4f} "
        f"remains; ${sum(REFUSED_TRIAL_COSTS):.4f} of this process's spend "
        "bought no measurement"
    )


def record_call_spend(cost: float | None) -> None:
    """Debit one provider call the door never saw. An unpriced call is not free.

    For a preserved evaluator on another client - the one case the door cannot
    reach - so the ceiling still falls at the conservative rate. A route that
    reports no cost still spent money; debiting `0` there would hold the
    remaining flat across a whole held-out pass and every gate reading it
    would pass.
    """
    RUN_CALL_COSTS.append(cost)
    RUN_SPEND_USD.append(UNTRACKED_CALL_COST_USD if cost is None else cost)


# Every litellm knob that turns one invocation into several provider requests
# is named for what it does: it retries, or it falls back.
# `worst_case_requests` below sizes three of them and can read no others, so a
# request carrying any other is REFUSED rather than priced at one request.
#
# The test is the NAME rather than a list of the knobs known today, because
# such a list is what failed here: `retry_policy` sat outside one, litellm
# honoured it on plain `completion` all the same, and a rate-limited call
# reserved for 1 request placed 6. Measured on the pinned litellm 1.93.0: of
# the 214 entries in its own `all_litellm_params`, eight carry `retry`,
# `retries` or `fallback`; three are the ones priced here; `retry_policy`
# placed 6 requests against a reservation of 1 and `context_window_fallback_dict`
# placed 2 against 1; of the last three, two are read only by the router, and
# `retry_strategy` changes the wait between attempts and not their number -
# refused all the same, because the rule is the name. So the default is
# closed, and a knob a later release adds is refused before it spends rather
# than priced at one after it has.
PRICED_REQUEST_KNOBS: frozenset[str] = frozenset(
    {"num_retries", "max_retries", "fallbacks"}
)
UNPRICED_KNOB_MARKERS: tuple[str, ...] = ("retry", "retries", "fallback")


def worst_case_requests(kwargs: dict) -> int:
    """Billable provider requests one door invocation may leave behind, or a
    refusal when the request carries a knob this cannot size.

    The door cannot watch them happen, so it reads what the request states.
    Measured on the installed litellm against a local server counting what
    arrived, with the pin below applied: nothing set placed 1 request,
    `max_retries` of N and a process-wide `litellm.num_retries` of N each
    placed N+1, and a caller's own `num_retries` of R placed 2R+1 - litellm
    copies it over the client's `max_retries` and runs a retry loop of its own
    above that. F `fallbacks` entries put the request on F+1 legs with the
    client's own retries on each, and the two rules do NOT multiply: a caller's
    own R across those legs placed (1+3R)(F+1), one retry round per leg more
    than the product, so the ordinary `num_retries=2, fallbacks=["backup"]`
    billed 14 requests where that product reserved 10. The extra round is per
    leg and only for a count the CALLER passed: a process-wide N retried the
    whole chain N times instead, and reserving that per leg is over rather
    than under.

    A count is floored at zero, and at ONE wherever litellm reads it as set.
    Unfloored, a negative `num_retries` reserved a NEGATIVE number of requests,
    crediting the ledger and walking the remaining above the approved total;
    floored only to zero it under-reserved, because a negative count still buys
    a round - one over the chain from a process-wide one, one per leg from a
    caller's. It is rounded UP rather than truncated, because litellm hands the
    figure to `tenacity.stop_after_attempt`, which stops at the first attempt
    number that reaches it: a process-wide `1.5` placed 3 requests where
    truncation reserved 2, `2.5` placed 4 against 3, and `4.2` placed 6 against
    5. Whole counts are unmoved by either.

    The pin is what makes any of this countable, and that is its remaining
    merit: an absent `max_retries` is the provider client's own default, which
    moves between releases and cannot be read off the request, while `0` is a
    number this can assert. A caller who wants the resilience sets the count
    itself, and now pays for it here instead of spending it invisibly.
    """
    unpriced = sorted(
        name
        for name in kwargs
        if name not in PRICED_REQUEST_KNOBS
        and any(marker in name for marker in UNPRICED_KNOB_MARKERS)
    )
    if unpriced:
        raise RuntimeError(
            f"a call setting {', '.join(unpriced)} was not placed: this "
            "reservation reads `num_retries`, `max_retries` and `fallbacks` "
            "and prices no other retry or fallback knob - `retry_policy` "
            "alone placed 6 provider requests against a reservation of 1. "
            "Express the resilience with those three alone."
        )

    def rounded_up(count) -> int:
        # An integer is already whole, and `float(10**400)` raises
        # `OverflowError`, so an integer skips the cast. The cast stays for
        # everything else: a count read out of a file arrives as text.
        return count if isinstance(count, int) else math.ceil(float(count))

    asked = kwargs.get("num_retries")
    counted = asked or getattr(litellm, "num_retries", 0) or 0
    library_retries = max(1, rounded_up(counted)) if counted else 0
    client_retries = max(
        0, rounded_up((asked if asked is not None else kwargs["max_retries"]) or 0)
    )
    legs = 1 + len(kwargs.get("fallbacks") or ())
    per_leg = 1 + library_retries + client_retries
    if legs > 1 and asked:
        per_leg += max(1, rounded_up(asked))
    return per_leg * legs


def tracking_stopped() -> str | None:
    """Why this run no longer reaches the portal, or `None` while it does.

    A read of what the SDK already publishes, never a second detector. Its
    session manager flags a mid-run trial rejection or submission failure,
    stamps the run's config `result_source="local_fallback"` with the reason,
    and adds `persistence_reason="rejected"` when the backend rejected rather
    than went missing. Both land before the next trial places a call, which is
    what makes the door able to stop a run that is still spending.

    It reads no `cloud_url`: that exists only on the returned result, so a
    missing one is a between-phases check and cannot be this one.
    """
    config = getattr(TRACKED_RUN, "traigent_config", None)
    if getattr(config, "result_source", None) == "local_fallback":
        return getattr(config, "fallback_reason", None) or "backend tracking failed"
    if getattr(config, "persistence_reason", None) == "rejected":
        return "the backend rejected this run's trials"
    return None


def reserve_call_spend(args: tuple, kwargs: dict) -> int:
    """Commit one invocation's worst case BEFORE it is placed, or refuse it.

    It refuses for the other reason too. A run whose tracking has dropped to
    local-only is buying trials no portal will hold, and this is the one place
    every paid call passes before it is placed - so the halt the connected-run
    rules require is a refusal here, rather than a per-trial hook that one
    blocking `optimize_sync` does not offer.

    Reserving rather than debiting afterwards is the whole of this design's
    third answer at this seam. A debit taken after the call is always one call
    behind, and every hole found here has been money leaving between the check
    and the debit: retries underneath the door, a fallback re-entering it, a
    neighbour reading the same remaining. A reservation closes all three at
    once, because what is committed is what the invocation may cost rather than
    what one attempt of it did.

    Committing before the call is also what closed the concurrency exposure,
    and it rather than the lock is what did it: the window between deciding and
    spending used to contain a whole provider round trip. The lock closes what
    is left of that window by making the read and the reservation one step, and
    it is released before the call rather than held across it.

    Two alternatives lost, and both look better than they measure. Deducting
    `1 + the retry count` on the failure path leaves the success path alone,
    and the success path is where a billed attempt hides behind a retry that
    answered. Counting at litellm's own HTTP hook would have covered retries,
    fallbacks and the non-chat entry points together, and that hook is
    consulted by the OpenAI-family client alone: a counting transport saw the
    request on an `openai/` route and none of the requests on Anthropic,
    Gemini or OpenRouter.

    What it does not buy is stated with it. On the failure path the reservation
    stands, which is exact against every configuration measured above. On the
    success path it settles down to the price litellm reported, and litellm
    reports one price however many attempts it billed for - measured: a
    response returned after four billable requests carries the same
    `_hidden_params` as one returned after one, with no attempt count anywhere
    on it. So an attempt that was billed and then retried into a success is
    outside the settled figure, bounded by this reservation while the call is
    in flight and by nothing afterwards. That gap is the reason the invariant
    above is stated as the pin's reach and not as a property of every caller.
    """
    stopped = tracking_stopped()
    if stopped:
        raise RuntimeError(
            f"backend tracking dropped to local-only during this run "
            f"({stopped}), so nothing further reaches the portal and this call "
            "was not placed. Report the trials that completed and what it cost."
        )
    requests = worst_case_requests(kwargs)
    try:
        needed = requests * UNTRACKED_CALL_COST_USD
    except OverflowError:
        # A count too large to price in floating point is still a count, and
        # the answer to one is the refusal below rather than a traceback out of
        # the arithmetic - clamped, it would name a figure nobody asked for.
        needed = math.inf
    with LEDGER_LOCK:
        remaining = run_remaining_usd()
        if remaining < needed:
            model = kwargs.get("model") or (args[0] if args else "an unnamed model")
            raise RuntimeError(
                f"${remaining:.4f} of the approved ${RUN_COST_CEILING_USD:.2f} "
                f"total is left, which does not cover the {requests} provider "
                f"request(s) this invocation may place, so a call to {model} "
                "was not placed. Report what completed and ask for a larger "
                "total before running anything else."
            )
        RUN_SPEND_USD.append(needed)
        RUN_CALL_COSTS.append(None)
        return len(RUN_SPEND_USD) - 1


def settle_call_spend(slot: int, cost: float | None) -> None:
    """Replace a reservation with what the call is now known to have cost.

    In place, so one invocation is one ledger entry whatever happened beneath
    it - which is what `check_scorer_calls` counts and what the held-out slice
    reads. An unreadable or absent cost keeps the conservative figure, the same
    answer the design gives everywhere else it cannot read a price.
    """
    RUN_SPEND_USD[slot] = UNTRACKED_CALL_COST_USD if cost is None else cost
    RUN_CALL_COSTS[slot] = cost


def ledgered(place):
    """Wrap `litellm.completion` so a caller cannot decline the ledger."""

    def placed(*args, **kwargs):
        # Pin what cannot be counted, then count the rest and reserve it.
        # litellm hands the OpenAI-shaped client a nonzero `max_retries`, so a
        # call retries below this line where nothing can see it; `setdefault`
        # stops that and leaves a caller who asked for retries holding them.
        # The pin alone was claimed to make one wrapped call one billable
        # request, and `worst_case_requests` above records the measurements
        # that refuted it. Nor can the rest be turned off from here:
        # `setdefault("num_retries", 0)` is read as
        # `kwargs.get("num_retries") or litellm.num_retries`, where a literal
        # `0` is falsy - and it DOES suppress the process-wide figure on
        # `acompletion`, which is worse than useless, a safeguard holding on
        # the entry point nothing generates and not on the one every generated
        # line uses.
        #
        # So the invariant is not asserted. What is reserved instead is the
        # worst case the request states, before the call. `run-safety.md`
        # records the pin as one of the two exceptions to preserving a
        # caller's retry behaviour, and what it trades: a transient 429 or 500
        # now reaches the caller instead of being absorbed, paid for and
        # visible rather than silently, and re-running is the user's decision.
        kwargs.setdefault("max_retries", 0)
        if INSIDE_THE_DOOR.get():
            # A re-entry, not a new call - litellm's fallback handling calls
            # back in once per attempt, and the invocation that reserved
            # covered all of them. The paragraph after this fence owns why, and
            # what it concedes: a genuinely separate call placed from INSIDE
            # another one is covered by that invocation's reservation and no
            # more.
            return place(*args, **kwargs)
        slot = reserve_call_spend(args, kwargs)
        outside = INSIDE_THE_DOOR.set(True)
        # Nothing catches below. A call that fails after reaching the provider
        # is billable and brings back no price - litellm surfaces a timeout, a
        # rate limit, a dropped connection and a mid-stream failure as an
        # exception rather than as a degraded response, and an awaited call
        # cancelled in flight raises `CancelledError`, which is not even an
        # `Exception`. The reservation already stands for all of them and for
        # the attempts retried underneath, so the exception propagates as the
        # object the caller would otherwise have caught. Cost metadata that
        # raises out of `provider_reported_cost` lands the same way, with the
        # conservative figure left in place rather than a call spending
        # nothing.
        try:
            response = place(*args, **kwargs)
            settle_call_spend(slot, provider_reported_cost(response))
        finally:
            INSIDE_THE_DOOR.reset(outside)
        return response

    return placed


def ledgered_async(place):
    """The same for `litellm.acompletion`. Generated code awaits neither, but
    an entry point left unwrapped is exactly the outside being removed - and
    this is the one the re-entry check below actually fires on, because
    litellm's `fallbacks` handling routes even a synchronous call back through
    `acompletion`, once per attempt, on a loop it runs in this thread."""

    async def placed(*args, **kwargs):
        kwargs.setdefault("max_retries", 0)  # as above, and for the same reason
        if INSIDE_THE_DOOR.get():
            return await place(*args, **kwargs)
        slot = reserve_call_spend(args, kwargs)
        outside = INSIDE_THE_DOOR.set(True)
        try:
            response = await place(*args, **kwargs)
            settle_call_spend(slot, provider_reported_cost(response))
        finally:
            INSIDE_THE_DOOR.reset(outside)
        return response

    return placed


# The door: one wrap, on the attribute every caller resolves.
#
# The ledger lives on `litellm.completion` itself rather than on a function
# callers are asked to come to, so a hand-written judge that calls it - which is
# what a judge naturally does - is ledgered without knowing this file exists.
# `place_call`, `call_agent` and `call_judge` below are conveniences over it.
# Each wrapper saves what the attribute held and calls through it, which is the
# shape the SDK's own metadata-capture patch uses, so the two compose in either
# order and neither loses the other's work.
#
# It reaches every caller that RESOLVES the attribute when it calls, and no
# others - so import a preserved agent or evaluator module AFTER this line. The
# paragraph after this fence owns what stays outside it and what covers that.
if not getattr(litellm, "_first_run_ledgered", False):
    litellm.completion = ledgered(litellm.completion)
    litellm.acompletion = ledgered_async(litellm.acompletion)
    # Inside this guard rather than beside it: a second execution registered a
    # second handler, measured as two ledger lines out, the second reporting
    # $0.0000 from its own blind namespace.
    atexit.register(report_run_spend)
    # On the module, not in this file's namespace: a second execution of this
    # wrapper in one process would otherwise wrap again and debit every call
    # twice, which overstates spend and refuses a run that fits.
    litellm._first_run_ledgered = True


def refuse_unless_it_fits(calls: int, what: str) -> None:
    """Refuse a fixed run of calls the remaining cannot fund in full.

    For work whose entire output is one number - held-out scoring is the case
    here - a pass that stops halfway is not a smaller result, it is a different
    one under the same name: a mean over whichever rows the money reached. So
    the fit is settled before the first call and nothing is spent when it fails.

    One conservative rate per call, which is what a generated call reserves. A
    preserved caller that configures retries reserves more than that per call,
    so size the approved total with those extra requests in it - the rule above
    the import already requires exactly that of the estimate.
    """
    needed = calls * UNTRACKED_CALL_COST_USD
    remaining = run_remaining_usd()
    if needed > remaining:
        raise RuntimeError(
            f"{what} needs {calls} provider calls, about ${needed:.4f} at the "
            f"approved conservative rate, and ${remaining:.4f} of the approved "
            f"${RUN_COST_CEILING_USD:.2f} is left. Report the phases that did "
            "complete and take a larger total back to the user; do not run "
            "part of this and present its number as the whole."
        )


def place_call(request: dict) -> tuple[str, float | None]:
    """One call, reserved and settled by the door, then checked as a measurement.

    It no longer decides whether money may leave: the refusal and the
    reservation both happen inside the wrapped `litellm.completion` below, for
    this caller and every other one. What is left is what only a caller wanting a
    MEASUREMENT needs - the two checks below turn a canned or truncated
    response into a failed trial rather than a scored one - which is why this
    is still worth calling and no longer worth requiring. Its `what` label went
    with the refusal: the door names the model instead, because it answers to
    callers this file never wrote and holds no label from them.

    The cost is read off the response rather than off the end of the ledger. It
    is a pure read of the same object the settlement read, so the two cannot
    disagree, and it does not depend on what else is in that list.
    """
    response = litellm.completion(**request)
    cost = provider_reported_cost(response)
    try:
        require_nonzero_token_usage(response)
        require_untruncated_completion(response)
    except RuntimeError:
        if cost is not None:
            REFUSED_TRIAL_COSTS.append(cost)
        raise
    return response.choices[0].message.content or "", cost


def call_agent(message: str, config: dict) -> tuple[str, float | None]:
    """One trial's agent call, built from the configuration under test."""
    return place_call(build_request(message, config))


def call_judge(prompt: str) -> tuple[str, float | None]:
    """One grading call, built as the judge's rather than the trial's.

    Separate from `call_agent` rather than a configuration passed to it,
    because the judge is not the agent. Its request carries no swept knob and
    not the trial's model, or the grader moves with the thing it is grading and
    the run measures the pair. That, not the ledger, is now why a judge should
    come through here: the ledger reaches it either way.
    """
    if JUDGE_MODEL is None:
        raise RuntimeError(
            "call_judge was reached with JUDGE_MODEL unset, so there is no "
            "grading model to place this on. Fix the judge's model before the "
            "paid phase; never fall back to the configuration under test"
        )
    return place_call(
        {
            "model": JUDGE_MODEL,
            "timeout": MODEL_REQUEST_TIMEOUT_SECONDS,
            # Drop this key for a judging route that rejects sampling.
            "temperature": 0.0,
            "messages": [{"role": "user", "content": prompt}],
        }
    )


def check_scorer_calls(placed_before: int) -> None:
    """Hold the scorer to the number of provider calls it declared.

    Not a routing check any more - there is nowhere left to route around, so a
    scorer that declares one call and places two is inside the ceiling already
    and the remaining is already right. What it protects is the DECLARATION,
    which is load-bearing on its own: `CALLS_PER_SCORED_ROW` derives from it
    and sizes the held-out refusal, and that refusal is settled BEFORE any of
    the calls it is sizing, so it has nothing of its own to observe. A
    declaration of 1 against a judge placing 2 funds half the pass it refuses
    on. It is also what still notices a caller the door cannot see.

    The count is a delta over `RUN_SPEND_USD`, so it inherits the
    sequential-execution dependency recorded there.
    """
    placed = len(RUN_SPEND_USD) - placed_before
    if placed == SCORER_CALLS_PER_ROW:
        return
    raise RuntimeError(
        f"Scoring one row placed {placed} provider call(s) that the ledger "
        f"saw, and SCORER_CALLS_PER_ROW declares {SCORER_CALLS_PER_ROW} - the "
        "number the held-out refusal is sized from, before any of these calls "
        "happen. More than declared: the scorer places calls it does not "
        "declare - correct the count, or stop placing them. Fewer: a call the "
        "ledger cannot see - place it with call_judge, or debit it with "
        "record_call_spend"
    )


def task_score(prediction, expected, input_data) -> float:
    """The wired scorer, and the check on what scoring one row spends.

    Generate the body below from the preserved evaluator; the paragraph after
    this fence owns how, and where an LLM judge inside it places its call.
    """
    placed_before = len(RUN_SPEND_USD)
    score = ...
    check_scorer_calls(placed_before)
    return score


def require_wiring_probe_inputs(space: dict[str, list]) -> list:
    """Fail closed on an incomplete paid surface or absent proof inputs."""
    missing = set(space) - set(WIRED_KNOBS)
    extra = set(WIRED_KNOBS) - set(space)
    if missing or extra:
        raise RuntimeError(
            "WIRED_KNOBS must name exactly every paid configuration dimension "
            f"(missing={sorted(missing)!r}, extra={sorted(extra)!r}); no provider "
            "call was placed. Update the wrapper and repeat the local proof "
            "before approval."
        )
    for knob, values in space.items():
        if any(
            value == earlier
            for index, value in enumerate(values)
            for earlier in values[:index]
        ):
            raise RuntimeError(
                f"{knob!r} contains duplicate paid values; preserve the source "
                "space and stop before approval rather than paying duplicate "
                "trials. No provider call was placed."
            )
    if not PROBE_INPUTS:
        raise RuntimeError(
            "No tuning input to prove before a provider call; no provider call "
            "was placed. Add real tuning rows and repeat the local proof before approval."
        )
    models = list(space.get("model", []))
    if not models:
        raise RuntimeError(
            "No model to prove before a provider call; no provider call was "
            "placed. Restore the intended model list and repeat the local proof."
        )
    return models


def require_pinned_cloud_space_compatibility(*spaces: dict[str, list]) -> None:
    """Stop before approval on literal bools the pinned cloud session rejects."""
    offending = sorted(
        knob
        for space in spaces
        for knob, values in space.items()
        if any(type(value) is bool for value in values)
    )
    if not offending:
        return
    if BASELINE_IS_USER_OWNED:
        raise RuntimeError(
            f"{offending!r} contain literal bool values the pinned cloud session "
            "rejects. Preserve the customer baseline unchanged; do not offer the "
            "Basic-to-Enhanced approval. Use a separately approved local baseline-only "
            "run or later/manual compatible route. No provider call was placed."
        )
    raise RuntimeError(
        f"The generated space contains literal bool values at {offending!r}, which "
        "the pinned cloud session rejects. Correct the generated space and repeat "
        "the local proof before approval. No provider call was placed."
    )


require_pinned_cloud_space_compatibility(BASELINE_SPACE, ENHANCED_SPACE)


def probe_wiring(space: dict[str, list], base: dict) -> dict[str, str]:
    """Classify each wired knob by what a pure request diff can actually prove.

    A local no-provider proof, repeated before paid phases. It proves only
    **request visibility, per model** - that every distinct value of a swept
    knob produces a distinct dict `build_request` returns, under each model and
    tuning input in the space. It never proves provider *effect*: a provider that silently
    ignores a parameter it accepts produces two different requests and one
    behaviour. Only the run itself can show effect; this only rules out the
    dimension that could not possibly have one.

    It probes every model in the space, not just the base's, because request
    construction branches on the model. It probes every tuning input; each
    swept knob must distinguish every declared value on every one.

    Verdicts:

    - `visible`     - under every model in the space, every distinct value
                      produces a distinct request for every tuning input.
    - `partial`     - it fails that test for some models or inputs. A Cartesian
                      grid would pay duplicates, so use later/manual per-model design.
    - `invisible`   - no model and no probed input ever changes the request.
                      This alone is fatal: it is the no-op that inflates the
                      config-space document with a dimension nothing can move.
                      The probe cannot tell "acts outside request construction"
                      from "the agent ignores it"; this first-run guide refuses
                      both rather than accepting a prose waiver.
    - `not-searched`- fewer than two distinct values, so it claims no dimension.
    """
    models = require_wiring_probe_inputs(space)
    verdicts: dict[str, str] = {}
    for knob in WIRED_KNOBS:
        values = space.get(knob, [])
        if len(values) < 2:
            verdicts[knob] = "not-searched"
            continue
        moved = set()
        any_distinct_requests = False
        for model in models:
            model_base = {**base, "model": model}
            distinguishes_every_input = True
            for message in PROBE_INPUTS:
                requests = [
                    build_request(message, {**model_base, knob: value})
                    for value in values
                ]
                distinguishes_values = all(
                    request != other
                    for index, request in enumerate(requests)
                    for other in requests[index + 1 :]
                )
                any_distinct_requests = any_distinct_requests or distinguishes_values
                distinguishes_every_input = (
                    distinguishes_every_input and distinguishes_values
                )
            if distinguishes_every_input:
                moved.add(model)
        if len(moved) == len(models):
            verdicts[knob] = "visible"
        elif any_distinct_requests:
            verdicts[knob] = "partial"
        else:
            verdicts[knob] = "invisible"
    return verdicts


PROBE_VERDICTS = probe_wiring(ENHANCED_SPACE, BASELINE_CONFIG)
UNPROVEN_WIRED_KNOBS = {
    knob: verdict
    for knob, verdict in PROBE_VERDICTS.items()
    if verdict not in {"visible", "not-searched"}
}
if UNPROVEN_WIRED_KNOBS:
    if BASELINE_IS_USER_OWNED:
        raise RuntimeError(
            f"{UNPROVEN_WIRED_KNOBS} are conditional or unproven in a preserved "
            "baseline. Preserve it: do not alter tuning rows or remove its "
            "dimension. Stop before approval for later approved per-model "
            "validation. No provider call was placed."
        )
    raise RuntimeError(
        f"{UNPROVEN_WIRED_KNOBS} are not visible for every model in the paid "
        "space. A generated first-run Cartesian grid may use only dimensions "
        "every model receives; revise the generated space or defer it to later "
        "contained validation. No provider call was placed."
    )


def request_fingerprint() -> tuple:
    """Canonical in-memory proof of the exact finalized request surface."""
    def freeze(value):
        if isinstance(value, dict):
            return tuple(sorted((repr(key), freeze(item)) for key, item in value.items()))
        if isinstance(value, (list, tuple)):
            return tuple(freeze(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted(freeze(item) for item in value))
        return (type(value).__qualname__, repr(value))

    def configurations(space):
        result = [dict()]
        for knob in sorted(space):
            result = [
                {**config, knob: value}
                for config in result
                for value in space[knob]
            ]
        return result

    return (
        freeze(BASELINE_CONFIG),
        freeze(BASELINE_SPACE),
        freeze(ENHANCED_SPACE),
        freeze(PROBE_INPUTS),
        tuple(
            (message, freeze(config), freeze(build_request(message, config)))
            for space in (BASELINE_SPACE, ENHANCED_SPACE)
            for config in configurations(space)
            for message in PROBE_INPUTS
        ),
    )


REQUEST_FINGERPRINT = request_fingerprint()


def assert_wiring_still_proven() -> None:
    """Re-prove this fresh process's finalized request surface before its paid phase."""
    require_wiring_probe_inputs(BASELINE_SPACE)
    require_wiring_probe_inputs(ENHANCED_SPACE)
    require_pinned_cloud_space_compatibility(BASELINE_SPACE, ENHANCED_SPACE)
    current = probe_wiring(ENHANCED_SPACE, BASELINE_CONFIG)
    if current != PROBE_VERDICTS or request_fingerprint() != REQUEST_FINGERPRINT:
        raise RuntimeError(
            "The builder, inputs, or spaces changed after this process's local "
            "proof; no provider call was placed. Re-run it over the final spaces."
        )
    unproven = {
        knob: verdict
        for knob, verdict in current.items()
        if verdict not in {"visible", "not-searched"}
    }
    if unproven:
        raise RuntimeError(
            f"{unproven} are not visible for every model; no provider call was placed."
        )


@traigent.optimize(
    objectives=OBJECTIVES,
    configuration_space=ENHANCED_SPACE,
    evaluation=EvaluationOptions(
        eval_dataset=TUNING_DATASET,
        metric_functions={"task_success": task_score},
    ),
)
def agent(message: str) -> str:
    config = traigent.get_config()
    output, _cost = call_agent(message, config)
    return output


TRACKED_RUN = agent
```

Two gates hold the approved total, and they are different gates because the spending happens two
different ways. Inside `optimize_sync`, the SDK admits a trial only while its own limit allows, and
that limit is now the remaining rather than a default: the wrapper writes
`TRAIGENT_RUN_COST_LIMIT` before importing the SDK, so a phase reaching it stops gracefully and
reports `stop_reason`. Outside it, held-out scoring and an LLM judge call `litellm.completion`
directly, where no permit exists - so the second gate is on `litellm.completion` itself, wrapped
once at setup, and it refuses a call whose worst case the remaining cannot cover. Neither gate is
arithmetic the assistant performs between phases: the first is the SDK's per-trial admission check,
and the second reads a ledger that same wrapper reserves against before each call and settles after
it.

**The second gate is a place, not a rule, and that is the whole of this design.** Two earlier
versions asked callers to come to a function - first because a judge had bypassed the ledger
outright, then because a judge had routed the call it declared and made another one directly, which
a count of *routed* calls could not tell from compliance. Each asked the caller again and added a
way to notice when it did not comply, and each left the next caller a way out. Putting the debit on
the module attribute removes the outside instead: a hand-written judge that calls
`litellm.completion`, which is what a judge naturally does, is ledgered without being asked to be.

State its edge exactly, because an overstated safeguard is worse than a named gap. It reaches every
caller that RESOLVES `litellm.completion` or `litellm.acompletion` at call time, and no others -
and that clause is the whole test, so apply it rather than carrying a list of names that moves with
the library. Anything built on the wrapped attributes is covered even though nothing here mentions
it: `litellm.batch_completion` submits `litellm.completion` to a thread pool of its own, and a
configured `Router` calls `litellm.completion(...)`, so both go through the door. Anything that
reaches the provider by its own path is outside it: `litellm.text_completion` and
`litellm.completion_with_retries` do, as do the spend-capable names that are not chat completions at
all - `embedding`, `responses`, `image_generation` and their kin. So does a module that bound the
function with `from litellm import completion` before setup, and so does a client that is not
litellm at all - a raw provider SDK, an HTTP call, a subprocess. Settle a name by patching a
sentinel over `litellm.completion` and calling it, not by trusting a list. So import a preserved
agent or evaluator module after the wrapper installs the door, keep generated calls on the two
wrapped names, and where neither can be arranged, declare what the scorer spends:
`check_scorer_calls` compares that declaration against
the ledger on every row, which is what still notices a call the door cannot see.

Resolving the attribute is what brings a call to the door; it is not on its own what makes the
money right, and treating the two as one sentence cost a run. litellm's own `fallbacks` handling
re-enters `litellm.completion` once per attempt, so every attempt resolved the wrapped name and the
invocation above them did too - measured at three ledger entries against two provider requests with
one fallback, and four against three with two. On a scorer declaring what it places, that surplus
entry is a stop on a caller that complied. So the door counts an INVOCATION once: a re-entry taken
while another invocation is in flight is part of it, covered by the reservation that invocation
already took, and the two rules together are what "the money is seen" means here.

A judge is the caller that made this necessary rather than merely tidy. It runs inside `task_score`,
whose `metric_functions` contract passes a prediction, an expectation and an input and returns a
number - no ledger, nothing to debit through. The SDK cannot close that from its side either: it
settles a trial's cost before it applies the metric functions, so a call made inside one is already
past that trial's accounting. The rule for generating a scorer is with the rest of `task_score`
below.

That is why the ledger counts search trials as well as direct calls. Held-out scoring runs last, in
the same process as the connected search, on the run's recommended and often priciest
configuration; if it read the remaining as it stood when the process started, it would believe the
whole of it was still there after the search had spent most of it. The SDK's `ExecutionBudget` is
the SDK's own way to share one cap across calls, and it is not used here: it holds its state in one
Python object, so it cannot reach from the baseline process into the connected one, and a second
cap that has to agree with `TRAIGENT_RUN_COST_LIMIT` is one more place for them to disagree.

The process-only values above are selected by the coding assistant from the inspected project and
live-probe observation; they are not questions for the user. The generated walkthrough defaults
to twelve baseline rows and a 12-trial enhanced cap. Preserve those counts when they fit the approved
time, cost, and plan quota; prefer a smaller representative tuning slice over collapsing the
comparison back to one-versus-two rows. The assistant derives the current provider route from the
existing vendor setup, the current agent call, and the route inventory, then populates the process
variables used below; the user does not type route metadata into the run. Call
`require_current_route_credential()` immediately before the approved live probe. If the discovered
route cannot be populated from the existing vendor and there is no usable fallback ladder, stop and
ask the user to add a vendor or choose a different one. Keep the real current model and parameter
values in `BASELINE_CONFIG`, `BASELINE_SPACE`, and every corresponding enhanced dimension. Select
the alternative and strong models from the same approved provider route when generating the
walkthrough, following the walkthrough model ladder above; set
`TRAIGENT_FIRST_RUN_STRONG_REASONING_EFFORT` only when the selected strong tier actually supports
a reasoning-effort control, and pin the same value for both runs. A new route or recipient
requires revised data-egress approval. In the generated default, every search
variable must affect the actual agent call for every model in the space. A preserved conditional
dimension receives a `partial` verdict during the local proof before approval. Preserve it unchanged
and stop this first-run path for later/manual approved per-model design. When the strong tier runs as a
reasoning model, temperature is inert for it - which costs the comparison nothing, because
temperature is fixed in both spaces and every swept knob is uniform across the ladder.

The concrete spaces above are the generated classification/extraction walkthrough default, not a
template to force onto every real agent. Its baseline is a credible twelve-point sweep: the three
ladder models by two prompt styles by two thinking shapes, with the remaining controls pinned to
the current behavior. The enhanced space keeps every one of those values, the same three models,
and adds one more real one-call control: reflect. That is exactly 24 configurations, so a 12-trial
managed run has meaningful choices to make while keeping the first taste deliberately small.

When the user already has a baseline or fixed current configuration, preserve that baseline space
and its row count exactly; do not expand it to twelve. Replace this example's spaces and `WIRED_KNOBS`
together: the list names every paid enhanced key, including pinned keys. Add direct request parameters
such as context format or few-shot count for observed failures. Retrieval, tools, repair, and multi-call
controls require separately contained tracing outside this first-run paid space. Do not add no-op fields,
recode a customer boolean, or add multi-call composite behavior merely to increase the portal row count.

Require nonzero token usage for every provider call; cost metadata alone does not prove the model
ran. Use public response cost when present. Reported `0` is valid with nonzero usage. The
fallback above reads OpenRouter's provider-reported response-cost header as surfaced by LiteLLM.
When cost is absent but nonzero usage proves a real call, return `None`, report `not measured`, and
deduct the approved estimate. Do not call
`litellm.completion_cost()` here: a real OpenRouter response can be billable and valid even when a
local model-price lookup fails. If neither public usage nor a provider-reported cost is available,
stop before baseline/search instead of scaling an untracked path.

Do not include `expected` in the agent signature. Dataset inputs call the agent; expected output
belongs only to evaluation.

Keep every dataset path absolute, as `TUNING_DATASET` and `HOLDOUT_DATASET` above already are
(`str(RUN_DIR / "...")`). Never shorten these to a relative path: the SDK resolves a relative one
against the working directory of whichever process opens it, and this run's dataset lives under
`RUN_DIR` while the assistant works from the project root. An absolute path is the same file from
any directory, which is the property that matters when the run, a re-run, and `traigent sync` are
three different processes. Nothing announces a breach of this rule: a relative path that resolves
against the wrong directory reads one file or misses one, and neither is a crash.

Generate `task_score` as an adapter around the preserved evaluator using the installed SDK's
documented public `metric_functions` contract; the example reflects the inspected three-argument
contract. Do not infer aliases or positional fallbacks from SDK internals. When grading requires
example metadata or full control of agent execution, use the installed SDK's public custom
evaluator instead.

When that evaluator is an LLM judge - which `references/evaluation-and-dataset.md` prescribes for
summary, explanation, writing, and story tasks - it grades with `call_judge`, and never with
`call_agent`, whose request is built from the trial's own knobs. Reaching `litellm` around it is no
longer a way to spend unseen money, but it still grades on whatever model that request names, and
the two response checks do not run - so route it for those reasons rather than for the ledger's.

Then set `SCORER_CALLS_PER_ROW` to the number of provider calls grading one row places. That number
is the run's claim about its own evaluator, and the one thing here nothing else can derive: it sizes
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

## Small baseline sweep

For the generated walkthrough, run the credible small space as one local fixed grid containing its
initial configuration. Start a fresh process with `TRAIGENT_FIRST_RUN_PHASE=baseline` (the
fail-safe default) and the three approved cost figures `references/run-safety.md` names, all
supplied by the process and never by `.env`. The contract forces backend-offline
before import: removing `TRAIGENT_API_KEY` does not suppress a stored CLI login. Provider calls stay
real. The setting dies with the baseline process; never export it, because the connected
process requires it absent and refuses it if inherited.

```python
assert FIRST_RUN_PHASE == "baseline", "baseline must run in the local phase"
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
```

Pass `algorithm="grid"` explicitly for this baseline sweep. **This applies to the local baseline
only; the connected search under "Broader optimization" must stay on `auto`.** The two runs are
deliberately different, and that difference is the comparison the first run exists to show.

The reason to pin the baseline is that `auto` means different things depending on whether a key is
present. With no Traigent key it does not fail and does not run managed search: it falls back to a
local `random` sweep and reports `fallback_reason=no_api_key`, so a run that looks like Traigent's
managed search is really random sampling. Locally the SDK registers exactly two searches, `grid` and
`random`; the managed family is cloud side and is not registered locally. At baseline size the
difference is visible - the same twelve-point space returns the first grid cell every time under
`grid`, and a different winner between runs under the fallback. A first result the user can
reproduce in front of someone else is worth more than one they cannot, so state which algorithm
actually ran rather than implying the managed one did.

Grid also cannot enumerate a continuous parameter, so every baseline knob stays an explicit list of
values. If a preserved user space is large enough that its trial cap could not reach most of it,
grid would only ever cover the corner it starts from; use `random` there instead, and say which
one ran and why.

Do not supply a separate `default_config`; on local proposal paths it can consume a trial slot and
truncate the grid. Normally verify all twelve distinct points executed and that `BASELINE_CONFIG`
appears in the returned trials. If the baseline approval explicitly reduced that default, verify
the returned count matches the disclosed plan and still contains `BASELINE_CONFIG`. For an
existing user-owned baseline, replace the generated example's configuration, spaces, wired list,
trial count, and algorithm with the preserved values and behavior exactly. A
real one-row fixed configuration remains one row; never manufacture variants around it.

The baseline process prints its ledger on the way out, whether it finished or died on any ending
`atexit` reaches, because `report_run_spend` is registered with it rather than written after the
last call; an ending that reaches no handler prints nothing - SIGTERM, SIGKILL, SIGHUP, SIGQUIT,
`os._exit` and `os.abort`, measured - and `references/run-safety.md` owns what to carry forward
when the line is missing. The figure
to carry forward is the one that line names as gone - what this process spent plus what it was
launched having spent - already carrying the conservative deduction for any call its route did not
price. That total is what the connected process is launched with as
`TRAIGENT_FIRST_RUN_COST_SPENT_USD`, so the number the baseline actually produced is the number the
next phase is bounded by. Do not assemble it by hand from the SDK's tracked cost: that is a smaller,
different quantity, and the gap is exactly the spend the ledger exists to catch. Do not start the
search if it cannot fit the remaining total ceiling.

Read cost as a number only when the SDK reports one. An absent cost is `not measured`, while an
explicit provider-reported zero with nonzero token usage is a genuine free-route result. Never turn
absence into `$0.00`.

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
baseline with one row must wait for the enhanced result or report insight unavailable.
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
get wrong. What the baseline result decides is which knobs a customer's own space keeps, not which
values this one sweeps.

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
- **Write after trials are confirmed.** A search that returns having executed nothing did not search
  the space either, so the document is persisted after `optimized_results.trials` is checked rather
  than merely after the call returns.

A run that legitimately stops earlier, raises, or completes no trial therefore emits no document at
all, and the closing score honestly reports the agent pillar as not yet measured. Re-write the
document whenever the space changes. Its shape is documented in `references/run-safety.md`, and the
finished file is passed to the closing readiness score with `--config-space`.

After the account/key handoff, start a fresh process with
`TRAIGENT_FIRST_RUN_PHASE=connected` and the same three approved cost figures, this time carrying
the baseline's spend, all supplied by the process and never by `.env`. It loads the
updated `.env`; the earlier process cannot see that edit. Run the zero-LLM portal probe, then one
connected search with the same function, tuning dataset, and evaluator:

```python
assert FIRST_RUN_PHASE == "connected", "optimization must run in the connected phase"
assert os.environ.get("TRAIGENT_API_KEY", "").strip(), "Traigent key is not active"
os.environ["TRAIGENT_EXPERIMENT_NAME"] = "first-run Traigent optimization"
# Frozen from the space this call receives; persisted only once this search has
# returned trials of its own.
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
Path(CONFIG_SPACE_DOCUMENT).write_text(config_space_evidence)
# Here rather than beside the closing checks: held-out scoring is the next
# paid pass, and a run that reached no portal must not buy it.
tracking_loss = tracking_stopped() or (
    None if optimized_results.cloud_url is not None else "no portal link came back"
)
if tracking_loss:
    raise SystemExit(
        f"The connected search did not reach the portal ({tracking_loss}); no "
        f"further paid work runs. Report the trials in {OPTIMIZED_RESULTS}, the "
        "spend this process printed, and the baseline still standing."
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

`TRAIGENT_REQUIRE_CLOUD=1`, set for this phase in the wrapper above, is why that check is a
backstop rather than the only defence. Without it `auto` does not fail when the managed brain is
unreachable: it falls back to a local sweep, returns a result, and leaves the fallback reason for
someone to notice afterwards - after twelve paid trials the user approved as a managed search. With
it, session-creation failure raises before any trial. The flag is set only here: it fails any run
that creates no backend session, which is what the baseline phase is. An inherited true value
therefore stops the baseline before spending instead of being silently removed. Disclose the
conflict on the approval card; only after approval may a fresh baseline process be launched with
`TRAIGENT_REQUIRE_CLOUD=0` in its process environment. Do not merely unset it: because dotenv loads
with `override=False`, a true value in `.env` would be restored and stop the baseline again.

Setting it is necessary and not sufficient, and it has to be both spellings. `TRAIGENT_OFFLINE` and
`TRAIGENT_OFFLINE_MODE` each resolve the run to local-only before a session is ever attempted, so
the enforcement site never runs, and either one produces exactly the run this guards against while
the guard reads as on - worse than not setting it. The wrapper refuses to start the connected phase
under either instead of clearing it: no-egress is a deliberate choice about where the user's data
may go, and unsetting it to satisfy this run would send data out on their behalf.

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
persisted, report the trials that completed, take the spend from the ledger line this process
printed on its way out rather than from the SDK's tracked cost, and say plainly that the search
stopped early rather than presenting a partial frontier as the answer. Neither shape is a
reason to re-run the phase without the flag - that would buy back the exact result this prevents.

Do not enable mock mode in this process. The optimization space must include the current
configuration and every baseline value, plus meaningful added knobs that the function consumes.
`max_trials` is a cap rather than an SDK-enforced minimum, passed straight through as
`max_trials=ENHANCED_MAX_TRIALS`, so returned trials never exceed it - unlike the baseline's
twelve-point space, where "all twelve" already names the whole result. `12` is therefore the ceiling and
not a floor beneath a higher count, which is why everything the user reads states it as a ceiling -
"up to 12 configurations" - rather than as a range. Report the actual count and stop reason. Fewer
than 10 rows requires a concrete backend stop, timeout, cost-limit, or failure explanation rather
than being presented as the intended first-run comparison; that floor is this assistant's own
honesty check on a short run, not a count promised to the user, so it stays out of the user-facing
copy while continuing to govern what may be called the intended comparison.

If an optional optimization timeout was set and `stop_reason == "timeout"` with trials completed,
retain and report the best partial result (the enhanced run is uncapped by default, so this is
defensive handling rather than the normal path).
Offer another bounded pass only when the search was still improving or left a specific worthwhile
hypothesis, and state its additional approximate time and cost. If zero trials completed,
diagnose provider latency, a hung call, or setup failure rather than asking for more time. Do not
describe another invocation as "resume" unless the installed SDK exposes a public resume API.

## Result checks

**Read the frontier by hand, on the metric the run actually declared.** The same function reads the
baseline grid's finished trials and the enhanced search's, so one function serves both. It is
arithmetic over artifacts already in hand and makes no provider call:

```python
def frontier_at_or_above(trials, metric_name, floor):
    """Non-dominated completed trials scoring at or above `floor`, cheapest first.

    `metric_name` is this run's own objective name - the key wired through
    `metric_functions`, which is `"task_success"` in this reference's worked
    example - and never `"accuracy"`, which can sit in the same metrics map
    while being built-in exact match rather than the scorer this run wired.

    `floor` is the incumbent trial's value under this same `metric_name`, so
    both sides of the comparison are the same measurement. Never pass the
    result's `best_score` - under the two-objective schema above it is the
    weighted scalarization of score and cost, not the metric being compared.

    The floor is what keeps the frontier honest. Without it the cheapest
    trial is always on the frontier however badly it scored, and the report
    hands the user a configuration worse than the one they already run.

    Higher-is-better is assumed, which is what this reference's
    `orientation="maximize"` objective declares. For a run whose primary
    metric is one where lower is better - an error rate, declared `minimize` -
    reverse both score comparisons rather than passing the metric through
    unchanged, or the frontier is built out of the worst-scoring trials.
    """
    priced = []
    for trial in trials:
        if getattr(trial.status, "value", trial.status) != "completed":
            continue
        score = trial.metrics.get(metric_name)
        cost = trial.metrics.get("cost")
        # An absent cost is not a zero. A trial the run could not price cannot
        # take part in a cost comparison, and reading it as 0.0 puts every
        # unpriced trial on the frontier.
        if score is None or cost is None:
            continue
        if score >= floor:
            priced.append((cost, score, trial))
    frontier = [
        (cost, score, trial)
        for cost, score, trial in priced
        # Dominated: some other point is no dearer and no lower-scoring, and
        # strictly better on one of the two. Nobody would take this one.
        if not any(
            other_cost <= cost
            and other_score >= score
            and (other_cost < cost or other_score > score)
            for other_cost, other_score, _other in priced
        )
    ]
    return [trial for _cost, _score, trial in sorted(frontier, key=lambda row: row[0])]
```

The incumbent is a point like any other and is reported as one: keeping what you already run is a
choice the frontier is meant to show, not one it hides. The incumbent trial that supplies `floor`
must itself carry a reported, positive cost: a `0.0` produced by unknown model pricing is
indistinguishable in the metrics map from a genuine free route, and `references/run-safety.md`
makes measured cost a precondition for the read.

Do not pass `strategy=` or `strategy_params` to obtain this: the frontier is the function above and
nothing else. The presets are unused here because a strategy can replace the objectives the
decorator declared without raising or warning, and because the cost-floor preset floors on built-in
exact-match accuracy rather than the wired scorer - so the floor silently becomes `0.0` and it
returns the cheapest configuration rather than the cheapest acceptable one. Both move the winner
without moving anything the report shows.

Score the reserved rows with the run's recommended configuration, when SKILL stage 7 says to,
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

Before reporting:

```python
assert baseline_results.trials, "baseline did not execute"
assert optimized_results.trials, "optimization did not execute"
assert baseline_results.best_config is not None, "no baseline winner selected"
assert optimized_results.best_config is not None, "no best configuration selected"
```

Also verify that a user-owned baseline was preserved exactly, or that the generated baseline
returned all twelve intended distinct rows including its initial configuration. For an explicitly
approved reduced plan, verify the disclosed lower count and initial configuration instead. Inspect
failed trials, cost tracking, truncation, declared measures, stop reason, and persistence status
as defined in `run-safety.md`. The baseline portal URL, when exact sync was supported, comes from
the successful sync JSON; otherwise label it local-only. Keep and link every experiment actually
persisted. Portal experiment deletion is never walkthrough teardown and requires a later explicit
user request. Do not apply the best configuration automatically. Export it as a candidate and ask
before any production change.
